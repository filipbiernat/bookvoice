"""High-level conversion pipeline: chapters -> TTS chunks -> chapter MP3s -> M4B."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import audio
from .epub import Book, Chapter
from .progress import ProgressTracker
from .tagging import tag_mp3
from .text import chunk_paragraphs, safe_filename
from .tts import synthesize_all

log = logging.getLogger(__name__)

WORK_DIR_NAME = ".work"


@dataclass(frozen=True)
class ConvertOptions:
    voice: str
    rate: str = "+0%"
    bitrate: str = "64k"
    chunk_chars: int = 2500
    parallel: int = 3
    normalize: bool = True
    pause_after_title: float = 1.5
    pause_between_chunks: float = 0.5
    pause_at_end: float = 2.0
    keep_work: bool = False


class MissingChaptersError(RuntimeError):
    """Raised when building an M4B before all chapter MP3s exist."""


def default_output_dir(book: Book) -> Path:
    return Path(safe_filename(f"{book.author} - {book.title}"))


def _index_width(book: Book) -> int:
    return max(2, len(str(len(book.chapters))))


def chapter_filename(book: Book, chapter: Chapter) -> str:
    return f"{chapter.index:0{_index_width(book)}d} - {safe_filename(chapter.title)}.mp3"


def m4b_filename(book: Book, chapters: Sequence[Chapter]) -> str:
    suffix = "" if len(chapters) == len(book.chapters) else " (excerpt)"
    return f"{safe_filename(f'{book.author} - {book.title}')}{suffix}.m4b"


def _write_cover(book: Book, work_dir: Path) -> Path | None:
    if book.cover is None:
        return None
    path = work_dir / f"cover{book.cover.extension}"
    path.write_bytes(book.cover.data)
    return path


async def render_chapter(
    book: Book,
    chapter: Chapter,
    out_dir: Path,
    work_dir: Path,
    opts: ConvertOptions,
    *,
    tracker: ProgressTracker | None = None,
    position: int | None = None,
) -> Path:
    """Synthesise one chapter into a tagged MP3 in ``out_dir`` (skipped if it exists)."""
    dst = out_dir / chapter_filename(book, chapter)
    label = f"[{chapter.index:0{_index_width(book)}d}]"
    pos = chapter.index if position is None else position
    if dst.exists():
        if tracker is not None:
            tracker.skip_chapter(pos, chapter.title, chapter.char_count)
        log.info("%s already done: %s", label, dst.name)
        return dst

    chapter_dir = work_dir / f"chapter_{chapter.index:04d}"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    texts = [chapter.spoken_title, *chunk_paragraphs(chapter.paragraphs, opts.chunk_chars)]
    parts = [chapter_dir / f"{i:04d}.mp3" for i in range(len(texts))]
    log.info("%s %s: %d chars, %d chunks", label, chapter.title, chapter.char_count, len(texts))
    if tracker is not None:
        tracker.start_chapter(pos, chapter.title, len(texts))
    await synthesize_all(
        zip(texts, parts, strict=True),
        voice=opts.voice,
        rate=opts.rate,
        parallel=opts.parallel,
        on_done=(lambda text, _dst: tracker.advance_chunk(len(text))) if tracker else None,
    )
    if tracker is not None:
        tracker.finish_chapter()

    pause_title = audio.make_silence(work_dir / "pause_title.mp3", opts.pause_after_title)
    pause_chunk = audio.make_silence(work_dir / "pause_chunk.mp3", opts.pause_between_chunks)
    pause_end = audio.make_silence(work_dir / "pause_end.mp3", opts.pause_at_end)
    sequence = [parts[0], pause_title]
    for part in parts[1:]:
        sequence += [part, pause_chunk]
    sequence[-1] = pause_end

    tmp = chapter_dir / "chapter.mp3"
    audio.concat_mp3(
        sequence, tmp, bitrate=opts.bitrate, list_path=chapter_dir / "concat.txt",
        normalize=opts.normalize,
    )  # fmt: skip
    tag_mp3(
        tmp,
        title=f"{chapter.index:0{_index_width(book)}d}. {chapter.title}",
        author=book.author,
        album=book.title,
        track=chapter.index,
        total=len(book.chapters),
        cover=book.cover,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(tmp, dst)
    if not opts.keep_work:
        shutil.rmtree(chapter_dir, ignore_errors=True)
    log.info("%s done -> %s", label, dst.name)
    return dst


async def render_chapters(
    book: Book,
    chapters: Sequence[Chapter],
    out_dir: Path,
    opts: ConvertOptions,
    *,
    tracker: ProgressTracker | None = None,
) -> list[Path]:
    """Render chapters one after another (chunks within a chapter run in parallel)."""
    work_dir = out_dir / WORK_DIR_NAME
    work_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        await render_chapter(book, c, out_dir, work_dir, opts, tracker=tracker, position=pos)
        for pos, c in enumerate(chapters, 1)
    ]
    if not opts.keep_work:
        shutil.rmtree(work_dir, ignore_errors=True)
    return paths


def build_audiobook(
    book: Book, chapters: Sequence[Chapter], out_dir: Path, *, bitrate: str, keep_work: bool = False
) -> Path:
    """Package existing chapter MP3s from ``out_dir`` into a single chaptered M4B."""
    files = [out_dir / chapter_filename(book, c) for c in chapters]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise MissingChaptersError(
            f"{len(missing)} chapter file(s) missing in {out_dir} (first: {missing[0]}); "
            "run 'convert' first"
        )
    work_dir = out_dir / WORK_DIR_NAME
    work_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / m4b_filename(book, chapters)
    log.info("Building %s ...", dst.name)
    total = audio.build_m4b(
        files,
        [c.title for c in chapters],
        dst,
        title=book.title,
        author=book.author,
        bitrate=bitrate,
        work_dir=work_dir,
        cover=_write_cover(book, work_dir),
    )
    if not keep_work:
        shutil.rmtree(work_dir, ignore_errors=True)
    hours, rest = divmod(round(total), 3600)
    log.info("Done: %s (%d:%02d:%02d)", dst, hours, rest // 60, rest % 60)
    return dst
