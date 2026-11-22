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
_SECTION_LABELS = {
    "cs": "Oddíl",
    "de": "Abschnitt",
    "en": "Section",
    "es": "Sección",
    "fr": "Section",
    "it": "Sezione",
    "nl": "Sectie",
    "pl": "Część",
    "pt": "Seção",
    "uk": "Розділ",
}
_INTRO_LABELS = {
    "cs": "Úvod",
    "de": "Einleitung",
    "en": "Introduction",
    "es": "Introducción",
    "fr": "Introduction",
    "it": "Introduzione",
    "nl": "Inleiding",
    "pl": "Wprowadzenie",
    "pt": "Introdução",
    "uk": "Вступ",
}


def _section_label(language: str) -> str:
    """Return a localised fallback label for untitled sections."""
    return _SECTION_LABELS.get(language.split("-")[0].lower(), "Section")


def _intro_label(language: str) -> str:
    """Return a localised label for merged untitled front matter."""
    return _INTRO_LABELS.get(language.split("-")[0].lower(), "Introduction")


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
    announce_title: bool = True

    @property
    def spoken_title(self) -> str:
        return spoken_title(self.title) if self.announce_title else ""

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
    """Collects text blocks from (X)HTML, optionally splitting at TOC anchor IDs."""

    def __init__(self, split_ids: Iterable[str] = ()) -> None:
        super().__init__(convert_charrefs=True)
        self._split_ids: set[str] = set(split_ids)
        self.sections: list[tuple[str | None, list[tuple[bool, str]]]] = [(None, [])]
        self._buffer: list[str] = []
        self._heading_depth = 0
        self._skip_depth = 0

    @property
    def blocks(self) -> list[tuple[bool, str]]:
        return self.sections[0][1]

    def _maybe_split(self, attrs: list[tuple[str, str | None]]) -> None:
        if not self._split_ids or self._skip_depth:
            return
        for key, value in attrs:
            if key in ("id", "name") and value and value in self._split_ids:
                self._flush()
                self._split_ids.discard(value)
                self.sections.append((value, []))
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._maybe_split(attrs)
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "br":
            self._buffer.append("\n")
        elif tag in _HEADING_TAGS:
            self._flush()
            self._heading_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (<br/>, <hr/>, <div/>) never open a scope.
        self._maybe_split(attrs)
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
            self.sections[-1][1].append((self._heading_depth > 0, text))


def _blocks_to_chapter(
    blocks: list[tuple[bool, str]],
    heading_pattern: re.Pattern[str] | None = DEFAULT_HEADING_PATTERN,
) -> tuple[str | None, list[str]]:
    title: str | None = None
    paragraphs: list[str] = []
    for is_heading, raw in blocks:
        if is_heading and title is None:
            title = format_heading(raw.split("\n"), heading_pattern) or None
            if title:
                continue
        paragraphs.append(normalize_whitespace(raw))
    return title, paragraphs


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
    return _blocks_to_chapter(extractor.blocks, heading_pattern)


def extract_sections(
    markup: str,
    split_ids: Iterable[str] = (),
    heading_pattern: re.Pattern[str] | None = DEFAULT_HEADING_PATTERN,
) -> list[tuple[str | None, str | None, list[str]]]:
    """Extract ``(anchor_id, title, paragraphs)`` sections from an (X)HTML document."""
    extractor = _BlockExtractor(split_ids)
    extractor.feed(markup)
    extractor.close()
    results: list[tuple[str | None, str | None, list[str]]] = []
    for anchor_id, blocks in extractor.sections:
        title, paragraphs = _blocks_to_chapter(blocks, heading_pattern)
        if title is None and not paragraphs:
            continue
        results.append((anchor_id, title, paragraphs))
    return results


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


def _resolve_with_fragment(base_dir: str, href: str) -> tuple[str, str | None]:
    raw_path, sep, raw_frag = href.partition("#")
    path = _resolve(base_dir, raw_path)
    frag = unquote(raw_frag).strip() if sep else ""
    return path, (frag or None)


def _toc_entries(
    archive: zipfile.ZipFile,
    opf_dir: str,
    spine: ET.Element | None,
    manifest: dict[str, _ManifestItem],
) -> dict[str, list[tuple[str | None, str]]]:
    """Map document path -> top-level TOC ``(fragment_id, label)`` entries."""
    entries: dict[str, list[tuple[str | None, str]]] = {}
    seen: dict[str, set[str | None]] = {}

    def add(base_dir: str, href: str | None, label: str) -> None:
        path, frag = _resolve_with_fragment(base_dir, href or "")
        if not path or not label:
            return
        bucket = seen.setdefault(path, set())
        if frag not in bucket:
            bucket.add(frag)
            entries.setdefault(path, []).append((frag, label))

    nav = next((i for i in manifest.values() if "nav" in i.properties), None)
    if nav is not None:
        try:
            root = _parse_xml(archive, nav.path)
        except EpubError:
            root = None
        if root is not None:
            toc_nav = next(
                (
                    el
                    for el in root.iterfind(".//{*}nav")
                    if "toc" in (el.get("{http://www.idpf.org/2007/ops}type") or "").split()
                ),
                None,
            )
            links = (
                list(toc_nav.findall("./{*}ol/{*}li/{*}a")) if toc_nav is not None else []
            ) or list(root.iterfind(".//{*}a"))
            for link in links:
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
            points = list(root.findall("./{*}navMap/{*}navPoint")) or list(
                root.iterfind(".//{*}navPoint")
            )
            for point in points:
                content = point.find("{*}content")
                label = _first_text(point, "{*}navLabel/{*}text")
                if content is not None:
                    add(posixpath.dirname(ncx.path), content.get("src"), label)
    return entries


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
        language = _first_text(metadata, "{*}language") or "en"
        section_label = _section_label(language)
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
        toc = _toc_entries(archive, opf_dir, spine, manifest)
        raw_chapters: list[tuple[bool, str | None, list[str]]] = []
        prev_was_toc_chapter = False
        for ref in spine.iterfind("{*}itemref") if spine is not None else ():
            item = manifest.get(ref.get("idref", ""))
            if item is None or item.media_type not in _DOCUMENT_TYPES:
                continue
            try:
                markup = archive.read(item.path).decode("utf-8", errors="replace")
            except KeyError:
                continue
            doc_toc = toc.get(item.path, [])
            frag_labels = {frag: label for frag, label in doc_toc if frag}
            # Split a single XHTML file only when the TOC defines 2+ anchors inside it.
            split_ids = frag_labels.keys() if len(frag_labels) >= 2 else ()
            fallback_label = doc_toc[0][1] if doc_toc else None
            for anchor_id, title, paragraphs in extract_sections(
                markup, split_ids=split_ids, heading_pattern=heading_pattern
            ):
                # Heal mid-chapter file splits (e.g. Calibre 260 KB splits): untitled
                # leading text before the first TOC anchor, or an untitled continuation
                # file without TOC entries, continues the previous chapter.
                if (
                    (split_ids or not doc_toc)
                    and anchor_id is None
                    and title is None
                    and prev_was_toc_chapter
                    and raw_chapters
                ):
                    raw_chapters[-1][2].extend(paragraphs)
                    continue
                resolved_title = (
                    title
                    or (frag_labels.get(anchor_id) if anchor_id else None)
                    or (fallback_label if not split_ids else None)
                )
                raw_chapters.append((resolved_title is not None, resolved_title, list(paragraphs)))
                prev_was_toc_chapter = bool(anchor_id) or bool(doc_toc)

        if not raw_chapters:
            raise EpubError(f"no readable text found in {path}")

        # Merge all leading untitled front-matter sections into one intro chapter
        # whenever the book has at least one titled chapter following them.
        first_titled = next((i for i, (titled, _, _) in enumerate(raw_chapters) if titled), None)
        chapters: list[Chapter] = []
        if first_titled is not None and first_titled > 0:
            front_paragraphs: list[str] = []
            for _, _, paras in raw_chapters[:first_titled]:
                front_paragraphs.extend(paras)
            chapters.append(
                Chapter(
                    1,
                    _intro_label(language),
                    tuple(front_paragraphs),
                    announce_title=False,
                )
            )
            remaining = raw_chapters[first_titled:]
        else:
            remaining = raw_chapters

        for titled, resolved_title, paras in remaining:
            index = len(chapters) + 1
            chapters.append(
                Chapter(
                    index,
                    resolved_title or f"{section_label} {index}",
                    tuple(paras),
                    announce_title=titled,
                )
            )

        authors = [
            normalize_whitespace(el.text or "")
            for el in (metadata.findall("{*}creator") if metadata is not None else [])
        ]
        return Book(
            title=_first_text(metadata, "{*}title") or path.stem,
            author=", ".join(a for a in authors if a) or "Unknown Author",
            language=language,
            chapters=tuple(chapters),
            cover=_find_cover(archive, metadata, manifest),
        )
