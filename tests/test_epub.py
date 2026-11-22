from __future__ import annotations

from pathlib import Path

import pytest

from epub2audiobook.epub import EpubError, extract_document, parse_epub

from .conftest import COVER_BYTES, OPF, write_epub


def test_metadata(sample_epub: Path) -> None:
    book = parse_epub(sample_epub)
    assert book.title == "Test Book"
    assert book.author == "Jane Doe"
    assert book.language == "pl"


def test_cover_from_meta(sample_epub: Path) -> None:
    book = parse_epub(sample_epub)
    assert book.cover is not None
    assert book.cover.data == COVER_BYTES
    assert book.cover.mime == "image/jpeg"
    assert book.cover.extension == ".jpg"


def test_chapters_follow_spine_and_skip_empty_documents(sample_epub: Path) -> None:
    book = parse_epub(sample_epub)
    assert [c.index for c in book.chapters] == [1, 2, 3]
    assert [c.title for c in book.chapters] == [
        "Title Page",  # no heading -> label from the EPUB 3 nav document
        "Prologue - The Storm",  # single-line heading split by the default pattern
        "Chapter 1 - The Orphan",  # <br/> inside the heading
    ]


def test_paragraph_text_is_cleaned(sample_epub: Path) -> None:
    prologue = parse_epub(sample_epub).chapters[1]
    assert prologue.paragraphs == (
        "It was a dark and stormy night.",
        "\u201eQuotes\u201d & entities.",
    )
    assert prologue.spoken_title == "Prologue. The Storm."
    assert prologue.char_count == sum(len(p) for p in prologue.paragraphs)


def test_sub_headings_are_kept_as_paragraphs(sample_epub: Path) -> None:
    chapter = parse_epub(sample_epub).chapters[2]
    assert chapter.paragraphs == ("First line second line.", "A sub-heading", "Nested paragraph.")


def test_heading_pattern_can_be_disabled(sample_epub: Path) -> None:
    book = parse_epub(sample_epub, heading_pattern=None)
    assert book.chapters[1].title == "Prologue The Storm"


def test_ncx_used_when_no_nav(tmp_path: Path, epub_files: dict) -> None:
    epub_files["OEBPS/content.opf"] = OPF.replace(' properties="nav"', "")
    book = parse_epub(write_epub(tmp_path / "b.epub", epub_files))
    assert book.chapters[0].title == "From NCX"


def test_fallback_title_and_metadata(tmp_path: Path, epub_files: dict) -> None:
    opf = OPF.replace(' properties="nav"', "").replace('toc="ncx"', "")
    opf = opf.replace('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', "")
    opf = opf.replace("<dc:title>Test Book</dc:title>", "").replace(
        "<dc:creator>Jane Doe</dc:creator>", ""
    )
    epub_files["OEBPS/content.opf"] = opf
    book = parse_epub(write_epub(tmp_path / "untitled.epub", epub_files))
    assert book.chapters[0].title == "Section 1"
    assert book.title == "untitled"
    assert book.author == "Unknown Author"


def test_select(sample_epub: Path) -> None:
    book = parse_epub(sample_epub)
    assert [c.index for c in book.select({3, 1})] == [1, 3]
    assert len(book.select()) == 3
    with pytest.raises(ValueError, match="no such chapter"):
        book.select({7})


def test_not_a_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.epub"
    bad.write_text("nope")
    with pytest.raises(EpubError, match="cannot open"):
        parse_epub(bad)


def test_missing_container(tmp_path: Path) -> None:
    with pytest.raises(EpubError, match=r"container\.xml"):
        parse_epub(write_epub(tmp_path / "b.epub", {"x.txt": "x"}))


def test_extract_document_without_heading() -> None:
    title, paragraphs = extract_document("<html><body><p>Only text</p></body></html>")
    assert title is None
    assert paragraphs == ["Only text"]
