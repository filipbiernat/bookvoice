"""EPUB parsing: metadata, cover image and chapters in reading order."""

from __future__ import annotations

import posixpath
import re
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .mobi import MobiConvertError, is_mobi, mobi_to_epub
from .text import DEFAULT_HEADING_PATTERN, format_heading, normalize_whitespace, spoken_title

_CONTAINER_PATH = "META-INF/container.xml"
_DOCUMENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
        "figcaption", "footer", "header", "hr", "li", "ol", "p", "pre", "section",
        "table", "td", "th", "tr", "ul",
    }
)  # fmt: skip
_SKIP_TAGS = frozenset({"head", "script", "style", "svg", "math", "noscript", "template"})
_HAS_WORD = re.compile(r"\w")


class EpubError(Exception):
    """Raised when a file cannot be read as an EPUB book."""


@dataclass(frozen=True)
class Cover:
    data: bytes
    mime: str

    @property
    def extension(self) -> str:
        return ".png" if self.mime == "image/png" else ".jpg"


@dataclass(frozen=True)
class Chapter:
    """A single spine document with readable text. ``index`` is 1-based."""

    index: int
    title: str
    paragraphs: tuple[str, ...]

    @property
    def spoken_title(self) -> str:
        return spoken_title(self.title)

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.paragraphs)


@dataclass(frozen=True)
class Book:
    title: str
    author: str
    language: str
    chapters: tuple[Chapter, ...]
    cover: Cover | None = None

    def select(self, indices: Iterable[int] | None = None) -> list[Chapter]:
        """Return chapters with the given indices (all chapters when ``None``)."""
        if indices is None:
            return list(self.chapters)
        wanted = set(indices)
        unknown = wanted - {c.index for c in self.chapters}
        if unknown:
            raise ValueError(
                f"no such chapter(s): {', '.join(map(str, sorted(unknown)))} "
                f"(valid: 1-{len(self.chapters)})"
            )
        return [c for c in self.chapters if c.index in wanted]


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------
class _BlockExtractor(HTMLParser):
    """Collects text blocks from (X)HTML, flagging the ones inside headings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[bool, str]] = []
        self._buffer: list[str] = []
        self._heading_depth = 0
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "br":
            self._buffer.append("\n")
        elif tag in _HEADING_TAGS:
            self._flush()
            self._heading_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # Self-closing tags (<br/>, <hr/>, <div/>) never open a scope.
        if tag == "br":
            self._buffer.append("\n")
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _HEADING_TAGS:
            self._flush()
            self._heading_depth = max(0, self._heading_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = "".join(self._buffer)
        self._buffer.clear()
        if _HAS_WORD.search(text):
            self.blocks.append((self._heading_depth > 0, text))


def extract_document(
    markup: str, heading_pattern: re.Pattern[str] | None = DEFAULT_HEADING_PATTERN
) -> tuple[str | None, list[str]]:
    """Return ``(title, paragraphs)`` of an (X)HTML document.

    The first heading becomes the title; everything else (including later
    sub-headings) is returned as paragraphs in document order.
    """
    extractor = _BlockExtractor()
    extractor.feed(markup)
    extractor.close()
    title: str | None = None
    paragraphs: list[str] = []
    for is_heading, raw in extractor.blocks:
        if is_heading and title is None:
            title = format_heading(raw.split("\n"), heading_pattern) or None
            if title:
                continue
        paragraphs.append(normalize_whitespace(raw))
    return title, paragraphs


# ---------------------------------------------------------------------------
# EPUB package parsing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _ManifestItem:
    id: str
    path: str
    media_type: str
    properties: frozenset[str]


def _resolve(base_dir: str, href: str) -> str:
    href = unquote(href.split("#", 1)[0])
    return posixpath.normpath(posixpath.join(base_dir, href)) if href else ""


def _parse_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        raise EpubError(f"missing file inside EPUB: {name}") from None
    except ET.ParseError as exc:
        raise EpubError(f"malformed XML in {name}: {exc}") from None


def _first_text(parent: ET.Element | None, path: str) -> str:
    if parent is None:
        return ""
    for element in parent.findall(path):
        text = normalize_whitespace("".join(element.itertext()))
        if text:
            return text
    return ""


def _find_cover(
    archive: zipfile.ZipFile, metadata: ET.Element | None, manifest: dict[str, _ManifestItem]
) -> Cover | None:
    images = [item for item in manifest.values() if item.media_type.startswith("image/")]
    candidates = [item for item in images if "cover-image" in item.properties]
    if metadata is not None:
        for meta in metadata.findall("{*}meta"):
            if meta.get("name") == "cover" and meta.get("content") in manifest:
                candidates.append(manifest[meta.get("content", "")])
    candidates += [i for i in images if "cover" in i.id.lower() or "cover" in i.path.lower()]
    for item in candidates:
        if item.media_type.startswith("image/"):
            try:
                return Cover(archive.read(item.path), item.media_type)
            except KeyError:
                continue
    return None


def _toc_labels(
    archive: zipfile.ZipFile,
    opf_dir: str,
    spine: ET.Element | None,
    manifest: dict[str, _ManifestItem],
) -> dict[str, str]:
    """Map document path -> first table-of-contents label pointing at it."""
    labels: dict[str, str] = {}

    def add(base_dir: str, href: str | None, label: str) -> None:
        path = _resolve(base_dir, href or "")
        if path and label:
            labels.setdefault(path, label)

    nav = next((i for i in manifest.values() if "nav" in i.properties), None)
    if nav is not None:
        try:
            root = _parse_xml(archive, nav.path)
        except EpubError:
            root = None
        if root is not None:
            for link in root.iterfind(".//{*}a"):
                label = normalize_whitespace("".join(link.itertext()))
                add(posixpath.dirname(nav.path), link.get("href"), label)

    ncx_id = spine.get("toc") if spine is not None else None
    ncx = manifest.get(ncx_id or "") or next(
        (i for i in manifest.values() if i.media_type == "application/x-dtbncx+xml"), None
    )
    if ncx is not None:
        try:
            root = _parse_xml(archive, ncx.path)
        except EpubError:
            root = None
        if root is not None:
            for point in root.iterfind(".//{*}navPoint"):
                content = point.find("{*}content")
                label = _first_text(point, "{*}navLabel/{*}text")
                if content is not None:
                    add(posixpath.dirname(ncx.path), content.get("src"), label)
    return labels


def parse_epub(
    path: str | Path, heading_pattern: re.Pattern[str] | None = DEFAULT_HEADING_PATTERN
) -> Book:
    """Read metadata, cover and readable chapters (in spine order) from an EPUB or MOBI file.

    Kindle formats (``.mobi``, ``.azw``, ``.azw3``, ``.prc``) are automatically
    converted to a temporary EPUB via Calibre's ``ebook-convert``.
    """
    path = Path(path)
    if is_mobi(path):
        with tempfile.TemporaryDirectory(prefix="bookvoice_") as tmp:
            try:
                converted = mobi_to_epub(path, Path(tmp) / f"{path.stem}.epub")
            except MobiConvertError as exc:
                raise EpubError(str(exc)) from exc
            return parse_epub(converted, heading_pattern)

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise EpubError(f"cannot open {path}: {exc}") from None

    with archive:
        container = _parse_xml(archive, _CONTAINER_PATH)
        rootfile = container.find(".//{*}rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            raise EpubError("container.xml does not reference a package document")
        opf_path = rootfile.get("full-path", "")
        opf_dir = posixpath.dirname(opf_path)
        package = _parse_xml(archive, opf_path)

        metadata = package.find("{*}metadata")
        manifest: dict[str, _ManifestItem] = {}
        for item in package.iterfind("{*}manifest/{*}item"):
            item_id, href = item.get("id"), item.get("href")
            if item_id and href:
                manifest[item_id] = _ManifestItem(
                    id=item_id,
                    path=_resolve(opf_dir, href),
                    media_type=item.get("media-type", ""),
                    properties=frozenset(item.get("properties", "").split()),
                )

        spine = package.find("{*}spine")
        toc = _toc_labels(archive, opf_dir, spine, manifest)
        chapters: list[Chapter] = []
        for ref in spine.iterfind("{*}itemref") if spine is not None else ():
            item = manifest.get(ref.get("idref", ""))
            if item is None or item.media_type not in _DOCUMENT_TYPES:
                continue
            try:
                markup = archive.read(item.path).decode("utf-8", errors="replace")
            except KeyError:
                continue
            title, paragraphs = extract_document(markup, heading_pattern)
            if title is None and not paragraphs:
                continue  # e.g. a cover page containing only an image
            index = len(chapters) + 1
            title = title or toc.get(item.path) or f"Section {index}"
            chapters.append(Chapter(index, title, tuple(paragraphs)))

        if not chapters:
            raise EpubError(f"no readable text found in {path}")

        authors = [
            normalize_whitespace(el.text or "")
            for el in (metadata.findall("{*}creator") if metadata is not None else [])
        ]
        return Book(
            title=_first_text(metadata, "{*}title") or path.stem,
            author=", ".join(a for a in authors if a) or "Unknown Author",
            language=_first_text(metadata, "{*}language") or "en",
            chapters=tuple(chapters),
            cover=_find_cover(archive, metadata, manifest),
        )
