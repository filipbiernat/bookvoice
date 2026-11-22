# bookvoice

[![CI](https://github.com/filipbiernat/bookvoice/actions/workflows/ci.yml/badge.svg)](https://github.com/filipbiernat/bookvoice/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

Turn EPUB, MOBI, AZW and AZW3 e-books into audiobooks with natural-sounding
neural voices. **bookvoice** reads the book's chapters, synthesises them with
[Microsoft Edge text-to-speech](https://github.com/rany2/edge-tts) and produces:

- one tagged **MP3 per chapter** (title, author, track number, cover art), and
- a single **M4B audiobook** with chapter markers and embedded cover, ready for
  Apple Books, Smart AudioBook Player, BookPlayer, Plex/Audiobookshelf and others.

## Features

- Works with any standard EPUB 2/3 – chapters follow the spine (reading order),
  titles come from headings or the table of contents.
- Supports Kindle formats (`.mobi`, `.azw`, `.azw3`, `.prc`) automatically via
  Calibre's `ebook-convert`, plus a standalone `mobi2epub` command.
- Picks a default voice from the book's language (400+ voices, 100+ languages).
- Smart text chunking at sentence boundaries, natural pauses between parts.
- Parallel synthesis with automatic retries; **interrupted runs resume** where they
  stopped.
- Persistent **conversion queue** (`bookvoice queue`) — add books or Calibre
  folders anytime, even while a worker is already converting another book.
- EBU R128 loudness normalisation for consistent volume.
- Voice comparison mode to pick the voice you like before converting a whole book.
- Includes an AI Agent Skill (`.agents/skills/bookvoice/SKILL.md`) for guided
  interactive audiobook generation.
- No API key needed.

## Requirements

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) (`ffmpeg` and `ffprobe` on `PATH`)
  - Windows: `winget install Gyan.FFmpeg`
  - macOS: `brew install ffmpeg`
  - Debian/Ubuntu: `sudo apt install ffmpeg`
- *(Optional)* [Calibre](https://calibre-ebook.com) (`ebook-convert`) – only needed
  for `.mobi` / `.azw` / `.azw3` input files
- An internet connection (speech is synthesised by Microsoft's online service)

## Installation

```bash
pipx install git+https://github.com/filipbiernat/bookvoice.git
```

or with plain pip:

```bash
pip install git+https://github.com/filipbiernat/bookvoice.git
```

## Usage

All commands accept `.epub` as well as `.mobi`, `.azw`, `.azw3` and `.prc`
(Kindle files are converted to EPUB automatically when Calibre is installed).

```bash
# 1. Inspect the book: metadata, detected chapters and their sizes
bookvoice info book.epub

# 2. (Optional) compare voices on a short excerpt
bookvoice sample book.epub                       # all voices for the book's language
bookvoice sample book.epub --voice pl-PL-MarekNeural --voice pl-PL-ZofiaNeural

# 3. Try a couple of chapters first ...
bookvoice convert book.epub --only 1-2

# 4. ... then convert the whole book (already finished chapters are skipped)
bookvoice convert book.epub --voice pl-PL-MarekNeural --rate +10%

# Works with Kindle files too (or convert standalone with mobi2epub)
bookvoice convert book.mobi
bookvoice mobi2epub book.mobi -o book.epub
```

The result lands in `./<Author> - <Title>/`:

```text
Tom Clancy - Bez skrupułów/
├── 01 - Strona tytułowa.mp3
├── 02 - Prolog - Punkty styku.mp3
├── 03 - Rozdział 1 - Sierotka.mp3
├── ...
└── Tom Clancy - Bez skrupułów.m4b
```

When `--only` is used, the M4B contains just the selected chapters and is named
`... (excerpt).m4b`.

### Commands

| Command     | Description                                                        |
| ----------- | ------------------------------------------------------------------ |
| `info`      | Show book metadata, the default voice and the chapter list.        |
| `convert`   | Synthesise chapters to MP3 and package them as M4B.                |
| `m4b`       | (Re)build the M4B from already synthesised chapter MP3s.           |
| `voices`    | List available voices, e.g. `bookvoice voices pl`.                 |
| `sample`    | Read a short excerpt with several voices to compare them.          |
| `mobi2epub` | Convert a `.mobi`/`.azw`/`.azw3` file to `.epub` via Calibre.      |
| `queue`     | Manage and run a persistent queue (`add`/`list`/`remove`/`clear`/`retry`/`run`). |

### Conversion queue

Convert a whole series unattended — books added while the worker is running are
picked up automatically as soon as the current book finishes:

```bash
# Add files or whole Calibre book folders (prefers .epub, falls back to .azw3/.mobi)
bookvoice queue add "Book 1/" "Book 2.epub" --voice pl-PL-MarekNeural

# Start the worker in the background (or add --background directly to 'queue add')
bookvoice queue run --background

# Inspect status, retry failed books, or clear finished entries
bookvoice queue list
bookvoice queue retry
bookvoice queue clear
```

Queue state is stored in `~/.bookvoice/queue.json` (override with `--queue FILE`).

### Common options

| Option                  | Default                 | Description                                                   |
| ----------------------- | ----------------------- | ------------------------------------------------------------- |
| `-o, --output DIR`      | `./<Author> - <Title>`  | Output directory.                                             |
| `--only LIST`           | all                     | Chapters to process, e.g. `1,3-5` (numbers from `info`).      |
| `--voice NAME`          | by book language        | Voice short name from `voices`.                               |
| `--rate PCT`            | `+0%`                   | Speaking rate, e.g. `-10%`, `+20%`.                           |
| `--bitrate RATE`        | `64k`                   | Audio bitrate of MP3 and M4B.                                 |
| `--cover IMAGE`         | from book               | Override the cover (`.jpg`/`.png`).                           |
| `--parallel N`          | `3`                     | Concurrent TTS requests.                                      |
| `--chunk-chars N`       | `2500`                  | Maximum characters per TTS request.                           |
| `--no-normalize`        | –                       | Skip loudness normalisation.                                  |
| `--no-m4b`              | –                       | Produce chapter MP3s only.                                    |
| `--background`          | –                       | Run detached in the background, logging to `bookvoice.log`.   |
| `--keep-work`           | –                       | Keep intermediate files in `<output>/.work`.                  |
| `--heading-pattern RE`  | built-in                | Regex splitting headings like `Chapter 1 Title` (see below).  |

Run `bookvoice <command> --help` for the full list.

### Chapter titles

Titles are taken from the first heading of each document, falling back to the
table of contents. Single-line headings such as `Chapter 1 The Beginning` or
`Rozdział 1 Sierotka` are split into `Chapter 1 - The Beginning` (file names, M4B
chapters) and read aloud as *"Chapter 1. The Beginning."*. The built-in pattern
understands common English, Polish, German, French, Spanish and Italian chapter
words; pass your own regex with two groups (label, subtitle) via
`--heading-pattern`, or `--heading-pattern ""` to disable splitting.

## How it works

```mermaid
flowchart LR
    M["MOBI / AZW / AZW3"] -.->|Calibre| A[EPUB]
    A -->|spine, TOC, metadata| B[Chapters]
    B -->|sentence-aware chunks| C[Edge TTS]
    C -->|parallel MP3 parts| D[ffmpeg concat + loudnorm]
    D -->|ID3 tags + cover| E[Chapter MP3s]
    E -->|chapter markers| F[M4B]
```

| Module               | Responsibility                                      |
| -------------------- | --------------------------------------------------- |
| `bookvoice.epub`     | EPUB parsing (metadata, cover, chapters, TOC).      |
| `bookvoice.mobi`     | MOBI/AZW/AZW3 -> EPUB conversion via Calibre.       |
| `bookvoice.queue`    | Persistent conversion queue and worker tracking.    |
| `bookvoice.text`     | Text normalisation, chunking, titles, file names.   |
| `bookvoice.tts`      | Edge TTS synthesis with retries and voice listing.  |
| `bookvoice.audio`    | FFmpeg wrappers: concat, silence, M4B packaging.    |
| `bookvoice.tagging`  | ID3 tags for chapter MP3s.                          |
| `bookvoice.pipeline` | Orchestration of the whole conversion.              |
| `bookvoice.cli`      | Command-line interface.                             |

## AI Agent Skill

The repository includes an Agent Skill at
[`.agents/skills/bookvoice/SKILL.md`](.agents/skills/bookvoice/SKILL.md) that
guides you interactively through converting a book — asking about format
(MP3 / M4B), language & voice, voice sampling, chapter selection, speaking rate
and bitrate before starting the conversion.

## Development

```bash
git clone https://github.com/filipbiernat/bookvoice.git
cd bookvoice
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest              # tests run offline against generated EPUB fixtures
ruff check .        # lint
ruff format .       # format
```

## Disclaimer

- Edge TTS uses Microsoft's online speech service through the unofficial
  [`edge-tts`](https://github.com/rany2/edge-tts) library. It is not affiliated with
  or endorsed by Microsoft and may change or stop working at any time.
- Convert only books you have the right to use, e.g. DRM-free books you own, for
  personal use. Do not distribute generated audiobooks of copyrighted works.

## License

[MIT](LICENSE) © Filip Biernat
