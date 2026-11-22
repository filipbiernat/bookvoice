from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bookvoice import cli, mobi
from bookvoice.epub import EpubError, parse_epub


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("book.mobi", True),
        ("book.MOBI", True),
        ("book.azw", True),
        ("book.azw3", True),
        ("book.prc", True),
        ("book.epub", False),
        ("book.pdf", False),
    ],
)
def test_is_mobi(name: str, expected: bool) -> None:
    assert mobi.is_mobi(name) is expected


def test_find_ebook_convert_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(mobi, "_CALIBRE_FALLBACK_PATHS", ())
    with pytest.raises(mobi.MobiConvertError, match="ebook-convert not found"):
        mobi.find_ebook_convert()


def test_mobi_to_epub_missing_source(tmp_path: Path) -> None:
    with pytest.raises(mobi.MobiConvertError, match="file not found"):
        mobi.mobi_to_epub(tmp_path / "missing.mobi")


def test_mobi_to_epub_invokes_calibre(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "novel.mobi"
    src.write_bytes(b"fake-mobi")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        Path(cmd[2]).write_bytes(b"fake-epub")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(mobi, "find_ebook_convert", lambda: Path("/usr/bin/ebook-convert"))
    monkeypatch.setattr(subprocess, "run", fake_run)

    dst = mobi.mobi_to_epub(src)
    assert dst == tmp_path / "novel.epub"
    assert dst.is_file()
    assert calls == [[str(Path("/usr/bin/ebook-convert")), str(src), str(dst)]]


def test_mobi_to_epub_reports_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "bad.mobi"
    src.write_bytes(b"corrupt")

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="DRM protected")

    monkeypatch.setattr(mobi, "find_ebook_convert", lambda: Path("ebook-convert"))
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(mobi.MobiConvertError, match="DRM protected"):
        mobi.mobi_to_epub(src)


def test_parse_epub_auto_converts_mobi(
    tmp_path: Path, sample_epub: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "book.mobi"
    src.write_bytes(b"fake-mobi")

    def fake_convert(_src: Path, dst: Path) -> Path:
        shutil.copyfile(sample_epub, dst)
        return dst

    monkeypatch.setattr("bookvoice.epub.mobi_to_epub", fake_convert)

    book = parse_epub(src)
    assert book.title == "Test Book"
    assert book.author == "Jane Doe"
    assert len(book.chapters) == 3


def test_parse_epub_wraps_mobi_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "book.mobi"
    src.write_bytes(b"fake-mobi")

    def fail(_src: Path, _dst: Path) -> Path:
        raise mobi.MobiConvertError("Calibre missing")

    monkeypatch.setattr("bookvoice.epub.mobi_to_epub", fail)

    with pytest.raises(EpubError, match="Calibre missing"):
        parse_epub(src)


def test_cli_mobi2epub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "book.mobi"
    src.write_bytes(b"fake-mobi")
    out = tmp_path / "custom.epub"

    def fake_convert(s: Path, d: Path | None) -> Path:
        assert s == src
        assert d == out
        out.write_bytes(b"epub")
        return out

    monkeypatch.setattr(mobi, "mobi_to_epub", fake_convert)
    assert cli.main(["mobi2epub", str(src), "-o", str(out)]) == 0
