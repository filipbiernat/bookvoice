from __future__ import annotations

import pytest

from epub2audiobook.text import (
    DEFAULT_HEADING_PATTERN,
    chunk_paragraphs,
    format_heading,
    normalize_whitespace,
    parse_selection,
    safe_filename,
    split_long_text,
    spoken_title,
)


def test_normalize_whitespace() -> None:
    assert normalize_whitespace("  a\u00a0 b\n\tc ") == "a b c"


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["Rozdział 1 Sierotka"], "Rozdział 1 - Sierotka"),
        (["Prolog Punkty styku"], "Prolog - Punkty styku"),
        (["CHAPTER XII: The End"], "CHAPTER XII - The End"),
        (["Chapter 3"], "Chapter 3"),
        (["Just a title"], "Just a title"),
        (["Chapter 1", " ", "The Orphan "], "Chapter 1 - The Orphan"),
        ([" "], ""),
    ],
)
def test_format_heading(lines: list[str], expected: str) -> None:
    assert format_heading(lines, DEFAULT_HEADING_PATTERN) == expected


def test_spoken_title() -> None:
    assert spoken_title("Chapter 1 - The Orphan") == "Chapter 1. The Orphan."
    assert spoken_title("Who did it?") == "Who did it?"
    assert spoken_title("Ending...") == "Ending."


def test_split_long_text_prefers_sentence_boundaries() -> None:
    text = "One two three. Four five six! Seven eight nine?"
    assert split_long_text(text, 20) == ["One two three.", "Four five six!", "Seven eight nine?"]


def test_split_long_text_falls_back_to_words_and_hard_cuts() -> None:
    assert split_long_text("aaaa bbbb cccc", 9) == ["aaaa bbbb", "cccc"]
    assert split_long_text("abcdefghij", 4) == ["abcd", "efgh", "ij"]


def test_split_long_text_rejects_bad_limit() -> None:
    with pytest.raises(ValueError):
        split_long_text("x", 0)


def test_chunk_paragraphs_respects_limit() -> None:
    paragraphs = ["a" * 40, "b" * 40, "c" * 40, "Sentence one. " * 10]
    chunks = chunk_paragraphs(paragraphs, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert chunks[0] == "a" * 40 + "\n" + "b" * 40
    assert "".join(chunks).replace("\n", "").replace(" ", "") == "".join(paragraphs).replace(
        " ", ""
    )


def test_safe_filename() -> None:
    assert safe_filename('A: "B"/C?*...') == "A BC"
    assert safe_filename("...") == "untitled"
    assert len(safe_filename("x" * 500)) == 120


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("1", {1}), ("1,3-5", {1, 3, 4, 5}), (" 2 , 2-3 ,", {2, 3})],
)
def test_parse_selection(spec: str, expected: set[int]) -> None:
    assert parse_selection(spec) == expected


@pytest.mark.parametrize("spec", ["", "a", "3-1", "1-x", ","])
def test_parse_selection_errors(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_selection(spec)
