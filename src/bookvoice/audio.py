"""Thin wrappers around ``ffmpeg``/``ffprobe`` for joining, normalising and packaging audio."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

SAMPLE_RATE = 24000  # Edge TTS outputs 24 kHz mono
_META_SPECIAL = re.compile(r"([=;#\\\n])")


class FFmpegError(RuntimeError):
    """Raised when ffmpeg/ffprobe is missing or fails."""


def require_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise FFmpegError(
            f"{' and '.join(missing)} not found on PATH - install FFmpeg (https://ffmpeg.org)"
        )


def _run(cmd: Sequence[str | Path]) -> str:
    proc = subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise FFmpegError(f"{Path(str(cmd[0])).name} failed: {proc.stderr.strip()}")
    return proc.stdout


def run_ffmpeg(*args: str | Path) -> None:
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args])


def probe_duration(path: Path) -> float:
    """Return the duration of a media file in seconds."""
    out = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]
    )
    return float(out.strip())


def make_silence(path: Path, seconds: float) -> Path:
    """Create (once) an MP3 file containing ``seconds`` of silence."""
    if not path.exists():
        run_ffmpeg(
            "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono", "-t", f"{seconds:g}",
            "-c:a", "libmp3lame", "-b:a", "48k", path,
        )  # fmt: skip
    return path


def write_concat_list(inputs: Sequence[Path], list_path: Path) -> Path:
    """Write an ffmpeg concat-demuxer list file."""
    lines = []
    for path in inputs:
        escaped = path.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'\n")
    list_path.write_text("".join(lines), encoding="utf-8")
    return list_path


def concat_mp3(
    inputs: Sequence[Path], dst: Path, *, bitrate: str, list_path: Path, normalize: bool = True
) -> None:
    """Concatenate MP3 files into one mono MP3, optionally loudness-normalised (EBU R128)."""
    write_concat_list(inputs, list_path)
    filters = ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"] if normalize else []
    run_ffmpeg(
        "-f", "concat", "-safe", "0", "-i", list_path, *filters,
        "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "libmp3lame", "-b:a", bitrate, dst,
    )  # fmt: skip


def _escape_meta(value: str) -> str:
    return _META_SPECIAL.sub(r"\\\1", value)


def ffmetadata(title: str, author: str, chapters: Sequence[tuple[str, float]]) -> str:
    """Render an FFMETADATA1 document with book tags and chapter markers.

    ``chapters`` is a sequence of ``(title, duration_in_seconds)`` pairs.
    """
    lines = [
        ";FFMETADATA1",
        f"title={_escape_meta(title)}",
        f"artist={_escape_meta(author)}",
        f"album_artist={_escape_meta(author)}",
        f"album={_escape_meta(title)}",
        "genre=Audiobook",
    ]
    start = 0.0
    for chapter_title, duration in chapters:
        end = start + duration
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={round(start * 1000)}",
            f"END={round(end * 1000)}",
            f"title={_escape_meta(chapter_title)}",
        ]
        start = end
    return "\n".join(lines) + "\n"


def build_m4b(
    inputs: Sequence[Path],
    chapter_titles: Sequence[str],
    dst: Path,
    *,
    title: str,
    author: str,
    bitrate: str,
    work_dir: Path,
    cover: Path | None = None,
) -> float:
    """Join chapter files into a single M4B audiobook with chapters; return its duration."""
    if len(inputs) != len(chapter_titles):
        raise ValueError("inputs and chapter_titles must have the same length")
    work_dir.mkdir(parents=True, exist_ok=True)
    durations = [probe_duration(p) for p in inputs]
    list_path = write_concat_list(inputs, work_dir / "m4b_concat.txt")
    meta_path = work_dir / "m4b_metadata.txt"
    meta_path.write_text(
        ffmetadata(title, author, list(zip(chapter_titles, durations, strict=True))),
        encoding="utf-8",
    )

    sources: list[str | Path] = ["-f", "concat", "-safe", "0", "-i", list_path, "-i", meta_path]
    streams: list[str | Path] = ["-map", "0:a", "-c:a", "aac", "-b:a", bitrate, "-ac", "1"]
    if cover is not None:
        sources += ["-i", cover]
        streams += ["-map", "2:v", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    tmp = dst.with_name(dst.name + ".part")
    run_ffmpeg(
        *sources, *streams, "-map_metadata", "1", "-map_chapters", "1",
        "-movflags", "+faststart", "-f", "mp4", tmp,
    )  # fmt: skip
    tmp.replace(dst)
    return sum(durations)
