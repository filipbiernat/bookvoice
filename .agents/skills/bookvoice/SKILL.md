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

## Prerequisites & Assisted Installation

Before running any conversion, check the environment and help the user install anything missing:

1. **Locate `bookvoice`:**
   - Check if `bookvoice` is on `PATH`, or in a local `.venv` (`.venv/Scripts/bookvoice` on Windows, `.venv/bin/bookvoice` on macOS/Linux).
   - If `bookvoice` is **not installed**, ask the user for permission and offer to install it:
     - Preferred: `pipx install git+https://github.com/filipbiernat/bookvoice.git`
     - Fallback: `pip install git+https://github.com/filipbiernat/bookvoice.git` (or `pip install -e .` if inside a cloned repo).
2. **Run environment diagnostics:**
   ```bash
   bookvoice doctor
   ```
   This checks **Python 3.10+**, **FFmpeg** (`ffmpeg` + `ffprobe`, required), and **Calibre** (`ebook-convert`, optional — only required for `.mobi`/`.azw`/`.azw3`/`.prc`).
3. **Handle missing dependencies gracefully:**
   - **If `ffmpeg` / `ffprobe` is `[MISSING]` (required):**
     - Explain briefly why FFmpeg is required (merging audio chunks, loudness normalisation, M4B packaging).
     - Ask the user for confirmation before installing, then run the matching command:
       - Windows: `winget install --id Gyan.FFmpeg -e`
       - macOS: `brew install ffmpeg`
       - Linux (Debian/Ubuntu): `sudo apt update && sudo apt install -y ffmpeg` (or `dnf`/`pacman` for Fedora/Arch)
     - If they prefer manual installation or the package manager fails, share `https://ffmpeg.org/download.html` and pause until installed.
   - **If `Calibre` is `[OPTIONAL]` (not found):**
     - For `.epub` files: do **not** block — just continue normally.
     - For `.mobi`, `.azw`, `.azw3`, or `.prc` files: explain that Calibre's `ebook-convert` is needed to convert Kindle formats to EPUB, ask for confirmation, and offer to install:
       - Windows: `winget install --id calibre.calibre -e`
       - macOS: `brew install --cask calibre`
       - Linux (Debian/Ubuntu): `sudo apt update && sudo apt install -y calibre`
     - Fallback manual link: `https://calibre-ebook.com/download`.
4. **Verify after installation:**
   - On Windows PowerShell, refresh `PATH` in the current session after `winget` installs:
     ```powershell
     $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
     ```
   - Re-run `bookvoice doctor` to confirm all required dependencies report `[OK]` before proceeding.

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
4. **Execution mode** *(for full books or > 2 chapters — give the user live visibility into progress & ETA without blocking the chat unnecessarily)*:
   - **Run in user's own terminal (copy-paste 1-liner, recommended on Windows/desktop)**: prints a live progress bar + ETA updated after every chunk, survives closing the chat, and keeps the chat completely free (`0 tasks running`). Also supports `--background` + `bookvoice status --watch`.
   - **Silent background (`--background`)**: runs detached with logs in `<output>/bookvoice.log` and live state in `~/.bookvoice/status.json`; monitor anytime with `bookvoice status --watch`. *(Note: some Windows agent shells terminate detached child processes via Job Objects when the command exits — if so, provide the ready-to-run command for the user's own terminal instead.)*
   - **Wait in chat / agent background task**: best for short pilots (e.g. `--only 1-2`), or if the user explicitly wants the agent to run and monitor it.
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

### 7. Monitor & Verify Output
- **Live status anytime:** run `bookvoice status` (shows progress bar, `%`, current chapter/chunk, elapsed time, ETA, and the queue). Tell the user they can also run `bookvoice status --watch` in any terminal for a live auto-refreshing dashboard.
- **For short synchronous runs:** inspect the output directory, verify the `.m4b` duration and chapter count with `ffprobe`, and report the result.
- **For detached / user-terminal / queue runs:** report the launch details (command, output directory, `bookvoice status --watch`) and end the turn cleanly.
