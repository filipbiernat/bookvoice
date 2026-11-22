"""Environment diagnostics: check Python, FFmpeg and optional Calibre availability."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass

from . import mobi


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str
    install_hint: str | None = None


def install_hint(tool: str, platform: str | None = None) -> str:
    """Return a platform-appropriate installation command for ``ffmpeg`` or ``calibre``."""
    plat = sys.platform if platform is None else platform
    if tool == "ffmpeg":
        if plat == "win32":
            return "winget install --id Gyan.FFmpeg -e"
        if plat == "darwin":
            return "brew install ffmpeg"
        return "sudo apt install ffmpeg"
    if tool == "calibre":
        if plat == "win32":
            return "winget install --id calibre.calibre -e"
        if plat == "darwin":
            return "brew install --cask calibre"
        return "sudo apt install calibre"
    return f"install {tool}"


def run_checks(platform: str | None = None) -> list[CheckResult]:
    """Check required and optional runtime dependencies."""
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    results = [
        CheckResult(
            name="Python",
            ok=sys.version_info >= (3, 10),
            required=True,
            detail=py_ver,
            install_hint="Install Python 3.10+ from https://www.python.org/downloads/",
        )
    ]

    for binary in ("ffmpeg", "ffprobe"):
        found = shutil.which(binary)
        results.append(
            CheckResult(
                name=binary,
                ok=found is not None,
                required=True,
                detail=found or "not found on PATH",
                install_hint=install_hint("ffmpeg", platform),
            )
        )

    try:
        calibre_exe = mobi.find_ebook_convert()
        results.append(
            CheckResult(
                name="Calibre",
                ok=True,
                required=False,
                detail=f"{calibre_exe} (optional, for MOBI/AZW/AZW3)",
            )
        )
    except mobi.MobiConvertError:
        results.append(
            CheckResult(
                name="Calibre",
                ok=False,
                required=False,
                detail="not found (optional, only needed for MOBI/AZW/AZW3)",
                install_hint=install_hint("calibre", platform),
            )
        )
    return results
