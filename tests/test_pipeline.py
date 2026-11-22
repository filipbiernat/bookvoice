from __future__ import annotations

from pathlib import Path

import pytest

from bookvoice import cli, pipeline, tts
from bookvoice.audio import ffmetadata, write_concat_list
from bookvoice.epub import parse_epub


def test_ffmetadata_chapters_and_escaping() -> None:
    meta = ffmetadata("A=B; #1", "Doe", [("One", 1.5), ("Two\\Three", 2.25)])
    assert meta.startswith(";FFMETADATA1\ntitle=A\\=B\\; \\#1\n")
    assert "START=0\nEND=1500\ntitle=One\n" in meta
    assert "START=1500\nEND=3750\ntitle=Two\\\\Three\n" in meta


def test_write_concat_list_escapes_quotes(tmp_path: Path) -> None:
    lst = write_concat_list([tmp_path / "it's.mp3"], tmp_path / "list.txt")
    assert lst.read_text(encoding="utf-8").strip().endswith("it'\\''s.mp3'")


def test_default_voice() -> None:
    assert tts.default_voice("pl") == "pl-PL-MarekNeural"
    assert tts.default_voice("en-GB") == "en-US-AndrewNeural"
    assert tts.default_voice("xx") == tts.FALLBACK_VOICE


def test_output_names(sample_epub: Path) -> None:
    book = parse_epub(sample_epub)
    assert pipeline.default_output_dir(book) == Path("Jane Doe - Test Book")
    assert pipeline.chapter_filename(book, book.chapters[2]) == "03 - Chapter 1 - The Orphan.mp3"
    assert pipeline.m4b_filename(book, book.chapters) == "Jane Doe - Test Book.m4b"
    assert pipeline.m4b_filename(book, book.chapters[:1]) == "Jane Doe - Test Book (excerpt).m4b"


def test_build_audiobook_requires_chapter_files(sample_epub: Path, tmp_path: Path) -> None:
    book = parse_epub(sample_epub)
    with pytest.raises(pipeline.MissingChaptersError, match="3 chapter file"):
        pipeline.build_audiobook(book, book.chapters, tmp_path, bitrate="64k")


def test_cli_info(sample_epub: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["info", str(sample_epub)]) == 0
    out = capsys.readouterr().out
    assert "Title:    Test Book" in out
    assert "pl-PL-MarekNeural" in out
    assert "Chapter 1 - The Orphan" in out


def test_cli_reports_errors(tmp_path: Path) -> None:
    assert cli.main(["info", str(tmp_path / "missing.epub")]) == 1


def test_cli_rejects_bad_selection(sample_epub: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["convert", str(sample_epub), "--only", "x"])


def test_cli_convert_background(
    sample_epub: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_dir = tmp_path / "out"
    launched: list[tuple[list[str], dict[str, object]]] = []

    class FakePopen:
        pid = 4242

        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            launched.append((cmd, kwargs))

    monkeypatch.setattr("bookvoice.audio.require_ffmpeg", lambda: None)
    monkeypatch.setattr("bookvoice.cli.subprocess.Popen", FakePopen)

    rc = cli.main(["convert", str(sample_epub), "-o", str(out_dir), "--background", "--only", "1"])
    assert rc == 0
    assert len(launched) == 1
    cmd, kwargs = launched[0]
    assert cmd[:3] == [cli.sys.executable, "-m", "bookvoice"]
    assert "--background" not in cmd
    assert "--only" in cmd
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"  # type: ignore[index]
    assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"  # type: ignore[index]
    assert (out_dir / "bookvoice.log").exists()
    out = capsys.readouterr().out
    assert "PID 4242" in out
    assert "bookvoice.log" in out
