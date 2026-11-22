"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, audio, mobi, pipeline, queue, tts
from .epub import Book, Chapter, Cover, EpubError, parse_epub
from .text import DEFAULT_HEADING_PATTERN, parse_selection, safe_filename

log = logging.getLogger("bookvoice")

_IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def _heading_pattern(value: str) -> re.Pattern[str] | None:
    if not value:
        return None
    try:
        pattern = re.compile(value, re.IGNORECASE)
    except re.error as exc:
        raise argparse.ArgumentTypeError(f"invalid regular expression: {exc}") from None
    if pattern.groups < 2:
        raise argparse.ArgumentTypeError("pattern needs two groups: (label)(subtitle)")
    return pattern


def _selection(value: str) -> set[int]:
    try:
        return parse_selection(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    book = argparse.ArgumentParser(add_help=False)
    book.add_argument("epub", type=Path, help="path to the .epub (or .mobi/.azw/.azw3) file")
    book.add_argument(
        "--heading-pattern",
        type=_heading_pattern,
        default=DEFAULT_HEADING_PATTERN,
        metavar="REGEX",
        help="regex with two groups splitting single-line headings into label and subtitle "
        "('' disables)",
    )

    output = argparse.ArgumentParser(add_help=False)
    output.add_argument(
        "-o", "--output", type=Path, help="output directory (default: './<Author> - <Title>')"
    )
    output.add_argument(
        "--only", type=_selection, metavar="LIST", help="chapters to process, e.g. '1,3-5'"
    )
    output.add_argument("--bitrate", default="64k", help="audio bitrate (default: 64k)")
    output.add_argument("--cover", type=Path, help="cover image overriding the one in the book")
    output.add_argument(
        "--keep-work", action="store_true", help="keep intermediate files in '<output>/.work'"
    )

    voice = argparse.ArgumentParser(add_help=False)
    voice.add_argument("--rate", default="+0%", help="speaking rate, e.g. '-10%%' or '+15%%'")

    parser = argparse.ArgumentParser(
        prog="bookvoice",
        description="Convert EPUB, MOBI, AZW and AZW3 e-books into chaptered audiobooks "
        "(MP3 + M4B) using Microsoft Edge neural text-to-speech.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-q", "--quiet", action="store_true", help="only print warnings")
    verbosity.add_argument("-v", "--verbose", action="store_true", help="print debug output")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    info = commands.add_parser(
        "info", parents=[book], help="show book metadata and the chapter list"
    )
    info.set_defaults(handler=cmd_info)

    convert = commands.add_parser(
        "convert",
        parents=[book, output, voice],
        help="synthesise chapters to MP3 and package them as M4B",
        description="Synthesise chapters to MP3 files and package them into an M4B audiobook. "
        "Interrupted runs resume where they stopped.",
    )
    convert.add_argument("--voice", help="Edge TTS voice (default: chosen from book language)")
    convert.add_argument(
        "--chunk-chars", type=_positive_int, default=2500, help="max characters per TTS request"
    )
    convert.add_argument(
        "--parallel", type=_positive_int, default=3, help="concurrent TTS requests (default: 3)"
    )
    convert.add_argument(
        "--no-normalize", action="store_true", help="skip EBU R128 loudness normalisation"
    )
    convert.add_argument("--no-m4b", action="store_true", help="only produce chapter MP3s")
    convert.add_argument(
        "--background",
        action="store_true",
        help="run detached in the background and write logs to '<output>/bookvoice.log'",
    )
    convert.set_defaults(handler=cmd_convert)

    m4b = commands.add_parser(
        "m4b",
        parents=[book, output],
        help="package already synthesised chapter MP3s as M4B",
    )
    m4b.set_defaults(handler=cmd_m4b)

    voices = commands.add_parser("voices", help="list available Edge TTS voices")
    voices.add_argument("locale", nargs="?", help="locale prefix filter, e.g. 'pl' or 'en-GB'")
    voices.set_defaults(handler=cmd_voices)

    sample = commands.add_parser(
        "sample",
        parents=[book, voice],
        help="read a short excerpt with several voices to compare them",
    )
    sample.add_argument(
        "--voice",
        action="append",
        dest="voices",
        metavar="VOICE",
        help="voice to try (repeatable; default: all voices for the book language)",
    )
    sample.add_argument("--chapter", type=int, help="chapter to sample (default: first long one)")
    sample.add_argument(
        "--chars", type=_positive_int, default=900, help="approximate excerpt length"
    )
    sample.add_argument(
        "-o", "--output", type=Path, default=Path("voice-samples"), help="output directory"
    )
    sample.set_defaults(handler=cmd_sample)

    mobi2epub = commands.add_parser(
        "mobi2epub",
        help="convert a MOBI/AZW/AZW3 file to EPUB using Calibre",
    )
    mobi2epub.add_argument("input", type=Path, help="path to the .mobi/.azw/.azw3 file")
    mobi2epub.add_argument(
        "-o", "--output", type=Path, help="output .epub path (default: next to input)"
    )
    mobi2epub.set_defaults(handler=cmd_mobi2epub)

    q_parser = commands.add_parser(
        "queue",
        help="manage and run a persistent conversion queue",
        description="Manage a persistent queue of e-books to convert sequentially. "
        "Books added while a worker is running are picked up automatically.",
    )
    q_parser.add_argument(
        "--queue",
        type=Path,
        default=queue.DEFAULT_QUEUE_PATH,
        metavar="FILE",
        help=f"queue state file (default: {queue.DEFAULT_QUEUE_PATH})",
    )
    q_cmds = q_parser.add_subparsers(dest="queue_command", required=True, metavar="ACTION")

    q_add = q_cmds.add_parser(
        "add",
        parents=[output, voice],
        help="add one or more book files or folders to the queue",
    )
    q_add.add_argument(
        "paths", nargs="+", type=Path, help="e-book file(s) or folder(s) containing an e-book"
    )
    q_add.add_argument("--voice", help="Edge TTS voice (default: chosen from book language)")
    q_add.add_argument(
        "--chunk-chars", type=_positive_int, default=2500, help="max characters per TTS request"
    )
    q_add.add_argument(
        "--parallel", type=_positive_int, default=3, help="concurrent TTS requests (default: 3)"
    )
    q_add.add_argument(
        "--no-normalize", action="store_true", help="skip EBU R128 loudness normalisation"
    )
    q_add.add_argument("--no-m4b", action="store_true", help="only produce chapter MP3s")
    q_add.add_argument(
        "--heading-pattern",
        default=None,
        metavar="REGEX",
        help="custom heading regex ('' disables)",
    )
    q_add.add_argument(
        "--background",
        action="store_true",
        help="start the queue worker in the background if not already running",
    )
    q_add.set_defaults(handler=cmd_queue_add)

    q_list = q_cmds.add_parser("list", help="show queued, running, finished and failed books")
    q_list.set_defaults(handler=cmd_queue_list)

    q_rm = q_cmds.add_parser("remove", help="remove an item from the queue by id")
    q_rm.add_argument("id", type=int, help="item id from 'bookvoice queue list'")
    q_rm.set_defaults(handler=cmd_queue_remove)

    q_clear = q_cmds.add_parser("clear", help="clear finished and failed items (or --all)")
    q_clear.add_argument("--all", action="store_true", help="also clear pending items")
    q_clear.set_defaults(handler=cmd_queue_clear)

    q_retry = q_cmds.add_parser("retry", help="re-queue all failed items as pending")
    q_retry.set_defaults(handler=cmd_queue_retry)

    q_run = q_cmds.add_parser("run", help="convert all pending books in the queue sequentially")
    q_run.add_argument(
        "--background",
        action="store_true",
        help="run the queue worker detached in the background",
    )
    q_run.set_defaults(handler=cmd_queue_run)
    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_book(args: argparse.Namespace) -> Book:
    book = parse_epub(args.epub, args.heading_pattern)
    cover_path: Path | None = getattr(args, "cover", None)
    if cover_path is not None:
        mime = _IMAGE_TYPES.get(cover_path.suffix.lower())
        if mime is None:
            raise ValueError("cover must be a .jpg, .jpeg or .png file")
        book = dataclasses.replace(book, cover=Cover(cover_path.read_bytes(), mime))
    return book


def _output_dir(args: argparse.Namespace, book: Book) -> Path:
    return args.output or pipeline.default_output_dir(book)


async def _check_voice(voice: str) -> None:
    try:
        known = {v["ShortName"] for v in await tts.list_voices()}
    except Exception as exc:  # the voice list is a convenience check only
        log.warning("could not fetch the voice list (%s); continuing", exc)
        return
    if voice not in known:
        raise ValueError(f"unknown voice {voice!r}; see 'bookvoice voices'")


def _excerpt(chapter: Chapter, chars: int) -> str:
    picked, total = [], 0
    for paragraph in chapter.paragraphs:
        picked.append(paragraph)
        total += len(paragraph)
        if total >= chars:
            break
    return "\n".join(picked)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_info(args: argparse.Namespace) -> None:
    book = _load_book(args)
    cover = f"yes ({book.cover.mime})" if book.cover else "no"
    print(f"Title:    {book.title}")
    print(f"Author:   {book.author}")
    print(f"Language: {book.language} (default voice: {tts.default_voice(book.language)})")
    print(f"Cover:    {cover}")
    print(f"Chapters: {len(book.chapters)}, {sum(c.char_count for c in book.chapters):,} chars\n")
    width = len(str(len(book.chapters)))
    print(f"{'#':>{width}}  {'chars':>8}  title")
    for chapter in book.chapters:
        print(f"{chapter.index:>{width}}  {chapter.char_count:>8,}  {chapter.title}")


def _spawn_background(
    argv: Sequence[str], log_dir: Path, log_name: str = "bookvoice.log"
) -> tuple[int, Path]:
    """Re-launch ``bookvoice`` detached, writing logs to ``<log_dir>/<log_name>``."""
    child_args = [arg for arg in argv if arg != "--background"]
    cmd = [sys.executable, "-m", "bookvoice", *child_args]
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_name
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
        "env": env,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(cmd, stdout=log_file, **kwargs)  # type: ignore[call-overload]
    return proc.pid, log_path


def cmd_convert(args: argparse.Namespace) -> None:
    audio.require_ffmpeg()
    book = _load_book(args)
    chapters = book.select(args.only)
    out_dir = _output_dir(args, book)
    if args.background:
        pid, log_path = _spawn_background(args._argv, out_dir)
        print(f"Started in background (PID {pid}).")
        print(f"Output: {out_dir}")
        print(f"Log:    {log_path}")
        return
    opts = pipeline.ConvertOptions(
        voice=args.voice or tts.default_voice(book.language),
        rate=args.rate,
        bitrate=args.bitrate,
        chunk_chars=args.chunk_chars,
        parallel=args.parallel,
        normalize=not args.no_normalize,
        keep_work=args.keep_work,
    )
    log.info("%s - %s: %d chapter(s), voice %s", book.author, book.title, len(chapters), opts.voice)

    async def run() -> None:
        await _check_voice(opts.voice)
        await pipeline.render_chapters(book, chapters, out_dir, opts)

    asyncio.run(run())
    if not args.no_m4b:
        pipeline.build_audiobook(
            book, chapters, out_dir, bitrate=args.bitrate, keep_work=args.keep_work
        )


def cmd_m4b(args: argparse.Namespace) -> None:
    audio.require_ffmpeg()
    book = _load_book(args)
    pipeline.build_audiobook(
        book,
        book.select(args.only),
        _output_dir(args, book),
        bitrate=args.bitrate,
        keep_work=args.keep_work,
    )


def cmd_voices(args: argparse.Namespace) -> None:
    voices = asyncio.run(tts.list_voices(args.locale))
    for v in voices:
        print(f"{v['ShortName']:<40} {v['Gender']:<8} {v['Locale']}")
    if not voices:
        print(f"no voices found for {args.locale!r}", file=sys.stderr)


def cmd_sample(args: argparse.Namespace) -> None:
    book = _load_book(args)
    if args.chapter is not None:
        chapter = book.select([args.chapter])[0]
    else:
        long_ones = [c for c in book.chapters if c.char_count >= 5 * args.chars]
        chapter = long_ones[0] if long_ones else max(book.chapters, key=lambda c: c.char_count)
    text = _excerpt(chapter, args.chars)

    async def run() -> None:
        voices = args.voices or [
            v["ShortName"] for v in await tts.list_voices(book.language.split("-")[0])
        ]
        voices = voices or [tts.default_voice(book.language)]
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "excerpt.txt").write_text(text + "\n", encoding="utf-8")
        log.info(
            "Sampling chapter %d (%d chars) with %d voice(s)", chapter.index, len(text), len(voices)
        )
        for i, voice in enumerate(voices, 1):
            dst = args.output / f"{i:02d}_{safe_filename(voice)}.mp3"
            try:
                await tts.synthesize(text, dst, voice=voice, rate=args.rate, attempts=3)
                log.info("  %s -> %s", voice, dst)
            except (tts.TTSError, ValueError) as exc:
                log.warning("  %s failed: %s", voice, exc)

    asyncio.run(run())


def cmd_mobi2epub(args: argparse.Namespace) -> None:
    dst = mobi.mobi_to_epub(args.input, args.output)
    log.info("Converted: %s", dst)


def _convert_queue_item(item: queue.QueueItem) -> None:
    pattern = (
        DEFAULT_HEADING_PATTERN
        if item.heading_pattern is None
        else _heading_pattern(item.heading_pattern)
    )
    only = parse_selection(item.only) if item.only else None
    ns = argparse.Namespace(
        epub=Path(item.source),
        heading_pattern=pattern,
        output=Path(item.output) if item.output else None,
        only=only,
        voice=item.voice,
        rate=item.rate,
        bitrate=item.bitrate,
        chunk_chars=item.chunk_chars,
        parallel=item.parallel,
        no_normalize=item.no_normalize,
        no_m4b=item.no_m4b,
        cover=Path(item.cover) if item.cover else None,
        keep_work=item.keep_work,
        background=False,
    )
    cmd_convert(ns)


def cmd_queue_add(args: argparse.Namespace) -> None:
    q = queue.BookQueue(args.queue)
    only_spec = ",".join(map(str, sorted(args.only))) if args.only else None
    output_str = str(args.output.resolve()) if args.output else None
    cover_str = str(args.cover.resolve()) if args.cover else None
    if args.heading_pattern is not None:
        _heading_pattern(args.heading_pattern)
    for path in args.paths:
        item = q.add(
            path,
            output=output_str,
            voice=args.voice,
            rate=args.rate,
            bitrate=args.bitrate,
            only=only_spec,
            chunk_chars=args.chunk_chars,
            parallel=args.parallel,
            no_normalize=args.no_normalize,
            no_m4b=args.no_m4b,
            cover=cover_str,
            keep_work=args.keep_work,
            heading_pattern=args.heading_pattern,
        )
        print(f"Queued #{item.id}: {Path(item.source).name}")

    active = q.worker_pid()
    if active is not None:
        print(
            f"Worker is already running (PID {active}) - it will pick up new items automatically."
        )
    elif args.background:
        audio.require_ffmpeg()
        pid, log_path = _spawn_background(
            ["queue", "--queue", str(q.path), "run"], q.path.parent, "queue.log"
        )
        print(f"Started queue worker in background (PID {pid}).")
        print(f"Log: {log_path}")


def cmd_queue_list(args: argparse.Namespace) -> None:
    q = queue.BookQueue(args.queue)
    active = q.worker_pid()
    status_line = f"running (PID {active})" if active else "idle"
    print(f"Queue:  {q.path}")
    print(f"Worker: {status_line}\n")
    items = q.items()
    if not items:
        print("(empty)")
        return
    print(f"{'#':>3}  {'status':<8}  book")
    for item in items:
        extra = f"  [{item.error}]" if item.error else ""
        print(f"{item.id:>3}  {item.status:<8}  {Path(item.source).name}{extra}")


def cmd_queue_remove(args: argparse.Namespace) -> None:
    removed = queue.BookQueue(args.queue).remove(args.id)
    print(f"Removed #{removed.id}: {Path(removed.source).name}")


def cmd_queue_clear(args: argparse.Namespace) -> None:
    count = queue.BookQueue(args.queue).clear(all_items=args.all)
    print(f"Cleared {count} item(s).")


def cmd_queue_retry(args: argparse.Namespace) -> None:
    count = queue.BookQueue(args.queue).retry_failed()
    print(f"Re-queued {count} failed item(s).")


def cmd_queue_run(args: argparse.Namespace) -> None:
    audio.require_ffmpeg()
    q = queue.BookQueue(args.queue)
    if args.background:
        active = q.worker_pid()
        if active is not None:
            raise queue.QueueError(f"queue worker is already running (PID {active})")
        pid, log_path = _spawn_background(args._argv, q.path.parent, "queue.log")
        print(f"Started queue worker in background (PID {pid}).")
        print(f"Log: {log_path}")
        return
    if q.next_pending() is None:
        log.info("Queue is empty (no pending items).")
        return
    ok, failed = queue.run_queue(q, _convert_queue_item)
    log.info("Queue finished: %d done, %d failed.", ok, failed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    args._argv = raw_argv
    level = logging.WARNING if args.quiet else logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")
    if not args.verbose:
        logging.getLogger("asyncio").setLevel(logging.WARNING)
    try:
        args.handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted - run the same command again to resume.", file=sys.stderr)
        return 130
    except (
        EpubError,
        mobi.MobiConvertError,
        queue.QueueError,
        audio.FFmpegError,
        tts.TTSError,
        pipeline.MissingChaptersError,
        ValueError,
        OSError,
    ) as exc:
        log.error("error: %s", exc)
        return 1
    return 0
