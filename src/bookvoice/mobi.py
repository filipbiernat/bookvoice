"""Convert MOBI/AZW/AZW3 e-books to EPUB using Calibre's ``ebook-convert``."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

MOBI_EXTENSIONS = frozenset({".mobi", ".azw", ".azw3", ".prc"})

_CALIBRE_FALLBACK_PATHS = (
    Path(r"C:\Program Files\Calibre2\ebook-convert.exe"),
    Path(r"C:\Program Files (x86)\Calibre2\ebook-convert.exe"),
    Path("/Applications/calibre.app/Contents/MacOS/ebook-convert"),
)


class MobiConvertError(RuntimeError):
    """Raised when a MOBI/AZW/AZW3 file cannot be converted to EPUB."""


def is_mobi(path: str | Path) -> bool:
    """Return ``True`` if ``path`` has a Kindle/MOBI extension."""
    return Path(path).suffix.lower() in MOBI_EXTENSIONS


def find_ebook_convert() -> Path:
    """Locate Calibre's ``ebook-convert`` executable or raise ``MobiConvertError``."""
    found = shutil.which("ebook-convert")
    if found is not None:
        return Path(found)
    for candidate in _CALIBRE_FALLBACK_PATHS:
        if candidate.is_file():
            return candidate
    raise MobiConvertError(
        "ebook-convert not found on PATH - install Calibre (https://calibre-ebook.com) "
        "to convert MOBI/AZW/AZW3 files"
    )


def mobi_to_epub(src: str | Path, dst: str | Path | None = None) -> Path:
    """Convert a MOBI/AZW/AZW3 file to EPUB via Calibre's ``ebook-convert``."""
    src_path = Path(src)
    if not src_path.is_file():
        raise MobiConvertError(f"file not found: {src_path}")
    dst_path = Path(dst) if dst is not None else src_path.with_suffix(".epub")
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    exe = find_ebook_convert()
    log.info("Converting %s -> %s via Calibre...", src_path.name, dst_path.name)
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run([str(exe), str(src_path), str(dst_path)], **kwargs)  # type: ignore[call-overload]
    if proc.returncode != 0 or not dst_path.is_file():
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        msg = detail[-1] if detail else f"exit code {proc.returncode}"
        raise MobiConvertError(f"ebook-convert failed: {msg}")
    return dst_path
