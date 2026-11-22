---
name: bookvoice
description: >-
  Interactive guided workflow for converting EPUB, MOBI, AZW, or AZW3 e-books into
  chaptered audiobooks (MP3 and/or M4B) using the bookvoice CLI, including managing
  a persistent conversion queue. Activate this skill whenever the user wants to
  generate an audiobook from an e-book, queue multiple books, compare TTS voices,
  or convert MOBI to EPUB for audiobook generation.
---

# Audiobook Generation Assistant (`bookvoice`)

Guide the user interactively through converting an e-book into a high-quality
audiobook using `bookvoice`. Converse in the user's language and ask clear,
concise questions with sensible defaults before starting long conversions.

## Prerequisites Check

Before running commands, locate the `bookvoice` executable:
- Check if `bookvoice` is on `PATH`, or in a local `.venv` (e.g. `.venv/Scripts/bookvoice` on Windows or `.venv/bin/bookvoice` on macOS/Linux).
- Verify `ffmpeg` and `ffprobe` are available on `PATH`.
- If the source book is `.mobi`, `.azw`, `.azw3`, or `.prc`, verify Calibre's `ebook-convert` is installed (`bookvoice` invokes it automatically).

## Step-by-Step Workflow

### 1. Identify the Book
- If the user has not provided a file path, ask for the path to the `.epub`, `.mobi`, `.azw`, or `.azw3` file (or offer to search their e-book directory if they give a title).
- If the file is `.mobi` / `.azw` / `.azw3`:
  - Inform the user that `bookvoice` automatically converts Kindle formats to EPUB via Calibre's `ebook-convert`.
  - If they also want to keep a permanent `.epub` copy, run `bookvoice mobi2epub <input> [-o <output.epub>]`.

### 2. Inspect the Book
Run:
```bash
bookvoice info "<book_path>"
```
Summarize the findings for the user:
- **Title & Author**
- **Detected language & default voice**
- **Cover image** (present or missing)
- **Chapters** (count, notable front-matter such as "Section 1" / title page, and total character count)
- **Estimated audio length**: roughly `total_chars / 900` minutes (and synthesis time roughly 5–10x faster than real-time).

### 3. Gather User Preferences
Ask the user to confirm or customize the following options (batch them into one clear set of questions — use an interactive multiple-choice question tool if available):

1. **Output format**:
   - **MP3 per chapter + single chaptered M4B** (recommended default)
   - **MP3 per chapter only** (`--no-m4b`)
2. **Language & voice**:
   - Confirm the detected language and default voice (e.g. `pl-PL-MarekNeural`, `en-US-AndrewNeural`).
   - Offer to list voices for a language (`bookvoice voices <locale>`) or generate short voice comparison clips (`bookvoice sample "<book_path>"`) before converting the whole book.
3. **Chapter scope**:
   - **Full book** (all chapters)
   - **Skip front-matter** (e.g. `--only 2-<N>` if chapter 1 is a copyright/title page)
   - **Pilot / test run first** (e.g. `--only 1-2` or `--only 2-3`)
4. **Execution mode** *(for full books or > 2 chapters — never block the chat with a long-running task)*:
   - **Separate terminal window** *(recommended on desktop)*: opens a new console window showing live chapter progress and stays open on completion; the chat is immediately free.
   - **Silent background (`--background`)**: runs detached with logs in `<output>/bookvoice.log`, returns PID immediately; works on all platforms and headless environments.
   - **Wait in chat**: only for short pilots (e.g. `--only 1-2`).
5. **Audio settings** (present defaults, let user override if desired):
   - **Speaking rate**: `+0%` (normal), or e.g. `-10%`, `+10%`, `+15%` (`--rate`)
   - **Bitrate**: `64k` (good speech quality & compact size), or `96k` / `128k` (`--bitrate`)
   - **Loudness normalisation**: enabled by default (EBU R128), or `--no-normalize`
   - **Output directory**: default `./<Author> - <Title>`, or custom `-o "<dir>"`
   - **Custom cover**: only ask if the EPUB has no embedded cover (`--cover "<image>"`)

### 4. Optional: Voice Sampling
If the user wants to compare voices first:
```bash
bookvoice sample "<book_path>" --chars 900 -o voice-samples
```
(Add `--voice <name>` flags if they specified particular voices.)
Tell the user where the sample `.mp3` files are saved so they can listen and choose their preferred voice before proceeding to Step 5.

### 5. Run the Conversion

Base arguments:
```text
convert "<book_path>" --voice <voice> --rate <rate> --bitrate <bitrate> [--only <selection>] [--no-m4b] [--no-normalize] [-o "<output_dir>"] [--cover "<cover_path>"]
```

Choose the launch mode based on the user's preference (for full books, **always** use fire-and-forget so no persistent background task blocks the chat):

- **Separate terminal window (Windows PowerShell):**
  ```powershell
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:PYTHONIOENCODING='utf-8'; & '<bookvoice_exe>' convert '<book_path>' ..."
  ```
- **Separate terminal window (macOS):**
  ```bash
  osascript -e 'tell application "Terminal" to do script "bookvoice convert \"<book_path>\" ..."'
  ```
- **Silent background (Windows / macOS / Linux):**
  ```bash
  bookvoice convert "<book_path>" ... --background
  ```
  Prints the PID, output directory, and `<output>/bookvoice.log` path, then exits immediately.
- **Short pilot (wait in chat):**
  Run `bookvoice convert ...` directly (on Windows PowerShell, set `$env:PYTHONIOENCODING='utf-8'`).

Remind the user that **interrupted runs resume automatically** — running the exact same command skips already-finished chapters.

### 6. Conversion Queue (Multiple Books / Series)
When the user wants to convert multiple books sequentially or add a book to run after an ongoing conversion:
- Add one or more book files or Calibre folders (automatically picks `.epub`, then `.azw3`/`.mobi`):
  ```bash
  bookvoice queue add "<book_or_folder>" [convert options...] [--background]
  ```
- If a queue worker is already running, newly added books are picked up automatically when the current book finishes.
- If no worker is running yet, pass `--background` to `queue add` (or start `bookvoice queue run` in a separate terminal window / with `--background`).
- Check progress anytime with `bookvoice queue list` (and `~/.bookvoice/queue.log`), retry failures with `bookvoice queue retry`, or clean up finished entries with `bookvoice queue clear`.

### 7. Verify Output
- For short synchronous runs: inspect the output directory, verify the `.m4b` duration and chapter count with `ffprobe`, and report the result.
- For fire-and-forget / queue runs: report the launch details (window / PID, output directory, log path) and end the turn cleanly. When the user later asks for status, run `bookvoice queue list`, check the tail of `<output>/bookvoice.log` (or `~/.bookvoice/queue.log`), or count `.mp3` files in `<output>`.
