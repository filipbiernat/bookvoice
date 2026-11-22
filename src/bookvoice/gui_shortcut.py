"""Create a Windows desktop shortcut for launching the bookvoice GUI without a console."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def desktop_dir() -> Path:
    """Return the current user's Desktop directory (handling OneDrive redirection on Windows)."""
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY = 0x0010
            rc = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
            if rc == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    for candidate in (Path.home() / "Desktop", Path.home() / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return candidate
    return Path.home()


def _resolve_launch_target() -> tuple[str, str]:
    """Return ``(target_path, arguments)`` for launching the GUI without a console window."""
    scripts_dir = Path(sys.executable).resolve().parent
    gui_exe = scripts_dir / "bookvoice-gui.exe"
    if gui_exe.is_file():
        return str(gui_exe), ""
    on_path = shutil.which("bookvoice-gui")
    if on_path:
        return on_path, ""
    pythonw = scripts_dir / "pythonw.exe"
    target = str(pythonw) if pythonw.is_file() else sys.executable
    return target, "-m bookvoice.gui"


def create_desktop_shortcut(name: str = "bookvoice") -> Path:
    """Create ``<Desktop>/<name>.lnk`` on Windows and return its path."""
    if sys.platform != "win32":
        raise RuntimeError("Desktop shortcut creation is only supported on Windows.")

    target, arguments = _resolve_launch_target()
    shortcut_path = desktop_dir() / f"{name}.lnk"
    workdir = str(Path.home())

    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:BV_SHORTCUT);"
        "$s.TargetPath = $env:BV_TARGET;"
        "if ($env:BV_ARGS) { $s.Arguments = $env:BV_ARGS };"
        "$s.WorkingDirectory = $env:BV_WORKDIR;"
        "$s.Description = 'bookvoice - E-book to Audiobook (MP3 + M4B)';"
        '$s.IconLocation = "$env:SystemRoot\\System32\\imageres.dll,128";'
        "$s.Save()"
    )
    env = {
        **os.environ,
        "BV_SHORTCUT": str(shortcut_path),
        "BV_TARGET": target,
        "BV_ARGS": arguments,
        "BV_WORKDIR": workdir,
    }
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, env=env)
    return shortcut_path
