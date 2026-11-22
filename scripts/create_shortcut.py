"""Create a Windows desktop shortcut for bookvoice GUI (no console window).

Usage:
    python scripts/create_shortcut.py
"""

from __future__ import annotations

from bookvoice.gui_shortcut import create_desktop_shortcut


def main() -> None:
    path = create_desktop_shortcut()
    print(f"Created shortcut: {path}")


if __name__ == "__main__":
    main()
