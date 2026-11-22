"""ID3 tagging of per-chapter MP3 files."""

from __future__ import annotations

from pathlib import Path

from mutagen.id3 import APIC, ID3, TALB, TCON, TIT2, TPE1, TPE2, TRCK, ID3NoHeaderError

from .epub import Cover


def tag_mp3(
    path: Path,
    *,
    title: str,
    author: str,
    album: str,
    track: int,
    total: int,
    cover: Cover | None = None,
) -> None:
    """Write audiobook-friendly ID3v2.3 tags (and optional cover art) to ``path``."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=author))
    tags.add(TPE2(encoding=3, text=author))
    tags.add(TALB(encoding=3, text=album))
    tags.add(TRCK(encoding=3, text=f"{track}/{total}"))
    tags.add(TCON(encoding=3, text="Audiobook"))
    if cover is not None:
        tags.add(APIC(encoding=3, mime=cover.mime, type=3, desc="Cover", data=cover.data))
    tags.save(path, v2_version=3)
