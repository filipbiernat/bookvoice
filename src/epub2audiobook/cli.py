"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, audio, pipeline, tts
from .epub import Book, Chapter, Cover, EpubError, parse_epub
from .text import DEFAULT_HEADING_PATTERN, parse_selection, safe_filename

log = logging.getLogger("epub2audiobook")

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
    book.add_argument("epub", type=Path, help="path to the .epub file")
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
    output.add_argument("--cover", type=Path, help="cover image overriding the one in the EPUB")
    output.add_argument(
        "--keep-work", action="store_true", help="keep intermediate files in '<output>/.work'"
    )

    voice = argparse.ArgumentParser(add_help=False)
    voice.add_argument("--rate", default="+0%", help="speaking rate, e.g. '-10%%' or '+15%%'")

    parser = argparse.ArgumentParser(
        prog="epub2audiobook",
        description="Convert EPUB e-books into chaptered audiobooks (MP3 + M4B) "
        "using Microsoft Edge neural text-to-speech.",
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
        raise ValueError(f"unknown voice {voice!r}; see 'epub2audiobook voices'")


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


def cmd_convert(args: argparse.Namespace) -> None:
    audio.require_ffmpeg()
    book = _load_book(args)
    chapters = book.select(args.only)
    out_dir = _output_dir(args, book)
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
        audio.FFmpegError,
        tts.TTSError,
        pipeline.MissingChaptersError,
        ValueError,
        OSError,
    ) as exc:
        log.error("error: %s", exc)
        return 1
    return 0
