"""Pure text helpers: normalisation, chapter titles, chunking and file names."""

from __future__ import annotations

import re
from collections.abc import Iterable

#: Splits single-line headings such as ``"Chapter 1 The Beginning"`` into a
#: label (``"Chapter 1"``) and a subtitle (``"The Beginning"``).
DEFAULT_HEADING_PATTERN = re.compile(
    r"^((?:chapter|part|book|rozdział|część|księga|kapitel|teil|chapitre|partie|"
    r"capítulo|capitolo|parte)\s+(?:\d+|[ivxlcdm]+)\b|prolog(?:ue)?|epilog(?:ue)?)"
    r"[\s.:\-\u2013\u2014]+(\S.*)$",
    re.IGNORECASE,
)

_WHITESPACE = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"[.!?…][\"'”»)\]]*\s")
_FORBIDDEN_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FILENAME_LENGTH = 120


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace (including non-breaking spaces) to single spaces."""
    return _WHITESPACE.sub(" ", text.replace("\u00a0", " ")).strip()


def format_heading(lines: Iterable[str], pattern: re.Pattern[str] | None = None) -> str:
    """Build a display title such as ``"Chapter 1 - The Beginning"`` from heading lines.

    Multi-line headings (``<h1>Chapter 1<br/>The Beginning</h1>``) are joined with
    ``" - "``. Single-line headings are split with ``pattern`` when it matches.
    """
    parts = [p for p in (normalize_whitespace(line) for line in lines) if p]
    if not parts:
        return ""
    if len(parts) > 1:
        return " - ".join(parts)
    title = parts[0]
    if pattern is not None and (match := pattern.match(title)):
        return f"{match.group(1)} - {match.group(2)}"
    return title


def spoken_title(title: str) -> str:
    """Turn a display title into a sentence-like string read aloud by the TTS voice."""
    sentences = []
    for segment in title.split(" - "):
        segment = segment.strip().rstrip(".")
        if segment:
            sentences.append(segment if segment[-1] in "?!…" else segment + ".")
    return " ".join(sentences)


def split_long_text(text: str, limit: int) -> list[str]:
    """Split ``text`` into pieces of at most ``limit`` characters.

    Prefers sentence boundaries, then word boundaries, and only cuts words as a
    last resort.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    pieces = []
    text = text.strip()
    while len(text) > limit:
        window = text[: limit + 1]
        cut = max((m.end() for m in _SENTENCE_END.finditer(window)), default=0)
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        pieces.append(text)
    return pieces


def chunk_paragraphs(paragraphs: Iterable[str], limit: int) -> list[str]:
    """Group paragraphs into newline-separated chunks of at most ``limit`` characters."""
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for piece in split_long_text(paragraph, limit):
            if current and len(current) + 1 + len(piece) > limit:
                chunks.append(current)
                current = ""
            current = f"{current}\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def safe_filename(name: str, fallback: str = "untitled") -> str:
    """Return ``name`` stripped of characters that are invalid in file names."""
    name = _FORBIDDEN_FILENAME_CHARS.sub("", name).replace("...", "").replace("…", "")
    name = normalize_whitespace(name)[:_MAX_FILENAME_LENGTH].strip(" .")
    return name or fallback


def parse_selection(spec: str) -> set[int]:
    """Parse a selection such as ``"1,3-5"`` into ``{1, 3, 4, 5}``."""
    selected: set[int] = set()
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        start, sep, end = item.partition("-")
        try:
            first = int(start)
            last = int(end) if sep else first
        except ValueError:
            raise ValueError(f"invalid chapter selection: {item!r}") from None
        if first < 0 or last < first:
            raise ValueError(f"invalid chapter range: {item!r}")
        selected.update(range(first, last + 1))
    if not selected:
        raise ValueError("chapter selection is empty")
    return selected
