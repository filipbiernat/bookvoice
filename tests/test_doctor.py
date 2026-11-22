from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bookvoice import cli, doctor, mobi


@pytest.mark.parametrize(
    ("platform", "ffmpeg_sub", "calibre_sub"),
    [
        ("win32", "winget install", "calibre.calibre"),
        ("darwin", "brew install ffmpeg", "brew install --cask calibre"),
        ("linux", "apt install ffmpeg", "apt install calibre"),
    ],
)
def test_install_hints(platform: str, ffmpeg_sub: str, calibre_sub: str) -> None:
    assert ffmpeg_sub in doctor.install_hint("ffmpeg", platform)
    assert calibre_sub in doctor.install_hint("calibre", platform)


def test_doctor_all_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(mobi, "find_ebook_convert", lambda: Path("/usr/bin/ebook-convert"))

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[OK]       ffmpeg" in out
    assert "[OK]       ffprobe" in out
    assert "[OK]       Calibre" in out


def test_doctor_optional_calibre_missing_is_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    def no_calibre() -> Path:
        raise mobi.MobiConvertError("missing")

    monkeypatch.setattr(mobi, "find_ebook_convert", no_calibre)

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[OPTIONAL] Calibre" in out
    assert "Install:" in out


def test_doctor_missing_ffmpeg_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(mobi, "find_ebook_convert", lambda: Path("/usr/bin/ebook-convert"))

    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "[MISSING]  ffmpeg" in out
    assert "[MISSING]  ffprobe" in out
    assert "Install:" in out
