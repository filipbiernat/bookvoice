from __future__ import annotations

from pathlib import Path

import pytest

from bookvoice.epub import EpubError, extract_document, parse_epub

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
    assert book.chapters[0].title == "Wprowadzenie"
    assert book.chapters[0].spoken_title == ""
    assert book.title == "untitled"
    assert book.author == "Unknown Author"

    epub_files["OEBPS/content.opf"] = opf.replace("<dc:language>pl</dc:language>", "")
    en_book = parse_epub(write_epub(tmp_path / "untitled_en.epub", epub_files))
    assert en_book.chapters[0].title == "Introduction"
    assert en_book.chapters[0].spoken_title == ""


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


def test_parse_epub_splits_multi_chapter_xhtml_by_toc_anchors(
    tmp_path: Path, epub_files: dict
) -> None:
    epub_files["OEBPS/text/ch1.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<h2 id="c1">Chapter 1 First</h2><p>Alpha text.</p>'
        "<h3>Internal subheading</h3><p>Still chapter one.</p>"
        '<h2 id="c2">Chapter 2 Second</h2><p>Beta text.</p>'
        "</body></html>"
    )
    epub_files["OEBPS/nav.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="text/title%20page.xhtml">Title Page</a></li>'
        '<li><a href="text/ch2.xhtml#start">Prologue</a></li>'
        '<li><a href="text/ch1.xhtml#c1">Chapter 1 First</a></li>'
        '<li><a href="text/ch1.xhtml#c2">Chapter 2 Second</a></li>'
        "</ol></nav></body></html>"
    )
    book = parse_epub(write_epub(tmp_path / "multi.epub", epub_files))
    assert [c.title for c in book.chapters] == [
        "Title Page",
        "Prologue - The Storm",
        "Chapter 1 - First",
        "Chapter 2 - Second",
    ]
    assert book.chapters[2].paragraphs == (
        "Alpha text.",
        "Internal subheading",
        "Still chapter one.",
    )
    assert book.chapters[3].paragraphs == ("Beta text.",)


def test_parse_epub_heals_mid_chapter_split_before_toc_anchor(
    tmp_path: Path, epub_files: dict
) -> None:
    epub_files["OEBPS/text/ch2.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<h2 id="c1">Chapter 1 Start</h2><p>First half.</p>'
        "</body></html>"
    )
    epub_files["OEBPS/text/ch1.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        "<p>Second half of chapter one.</p>"
        '<h2 id="c2">Chapter 2 Next</h2><p>Chapter two text.</p>'
        '<h2 id="c3">Chapter 3 End</h2><p>Chapter three text.</p>'
        "</body></html>"
    )
    epub_files["OEBPS/nav.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="text/title%20page.xhtml">Title Page</a></li>'
        '<li><a href="text/ch2.xhtml#c1">Chapter 1 Start</a></li>'
        '<li><a href="text/ch1.xhtml#c2">Chapter 2 Next</a></li>'
        '<li><a href="text/ch1.xhtml#c3">Chapter 3 End</a></li>'
        "</ol></nav></body></html>"
    )
    book = parse_epub(write_epub(tmp_path / "healed.epub", epub_files))
    assert [c.title for c in book.chapters] == [
        "Title Page",
        "Chapter 1 - Start",
        "Chapter 2 - Next",
        "Chapter 3 - End",
    ]
    assert book.chapters[1].paragraphs == ("First half.", "Second half of chapter one.")


def test_parse_epub_heals_standalone_untitled_continuation_file(
    tmp_path: Path, epub_files: dict
) -> None:
    epub_files["OEBPS/text/ch2.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<h2 id="c1">Rozdział 1 Początek</h2><p>Pierwsza część.</p>'
        "</body></html>"
    )
    epub_files["OEBPS/text/ch1.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        "<p>Druga część rozdziału pierwszego bez nagłówka.</p>"
        "</body></html>"
    )
    epub_files["OEBPS/nav.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="text/ch2.xhtml#c1">Rozdział 1 Początek</a></li>'
        "</ol></nav></body></html>"
    )
    epub_files["OEBPS/content.opf"] = OPF.replace('toc="ncx"', "").replace(
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', ""
    )
    book = parse_epub(write_epub(tmp_path / "split_single.epub", epub_files))
    assert [c.title for c in book.chapters] == [
        "Wprowadzenie",
        "Rozdział 1 - Początek",
    ]
    assert book.chapters[0].spoken_title == ""
    assert book.chapters[1].paragraphs == (
        "Pierwsza część.",
        "Druga część rozdziału pierwszego bez nagłówka.",
    )


def test_parse_epub_merges_multiple_leading_front_matter_sections(
    tmp_path: Path, epub_files: dict
) -> None:
    epub_files["OEBPS/text/ch2.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        "<p>Dla Wandy</p><p>Motto książki.</p>"
        "</body></html>"
    )
    epub_files["OEBPS/text/ch1.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        "<h2>Rozdział 1 Start</h2><p>Treść rozdziału.</p>"
        "</body></html>"
    )
    epub_files["OEBPS/content.opf"] = (
        OPF.replace(' properties="nav"', "")
        .replace('toc="ncx"', "")
        .replace('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', "")
    )
    book = parse_epub(write_epub(tmp_path / "front_matter.epub", epub_files))
    assert [c.index for c in book.chapters] == [1, 2]
    assert [c.title for c in book.chapters] == ["Wprowadzenie", "Rozdział 1 - Start"]
    assert book.chapters[0].spoken_title == ""
    assert book.chapters[0].paragraphs == ("Jane Doe", "TEST BOOK", "Dla Wandy", "Motto książki.")
    assert book.chapters[1].spoken_title == "Rozdział 1. Start."


def test_parse_epub_keeps_all_untitled_chapters_separate(tmp_path: Path, epub_files: dict) -> None:
    epub_files["OEBPS/text/ch2.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Drugi plik.</p></body></html>'
    )
    epub_files["OEBPS/text/ch1.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Trzeci plik.</p></body></html>'
    )
    epub_files["OEBPS/content.opf"] = (
        OPF.replace(' properties="nav"', "")
        .replace('toc="ncx"', "")
        .replace('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', "")
    )
    book = parse_epub(write_epub(tmp_path / "all_untitled.epub", epub_files))
    assert [c.title for c in book.chapters] == ["Część 1", "Część 2", "Część 3"]
    assert all(c.spoken_title == "" for c in book.chapters)
