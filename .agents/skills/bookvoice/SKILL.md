---
name: bookvoice
description: >-
  Interactive guided workflow for converting EPUB, MOBI, AZW, or AZW3 e-books into
  chaptered audiobooks (MP3 and/or M4B) using the bookvoice CLI. Activate this
  skill whenever the user wants to generate an audiobook from an e-book, compare TTS
  voices, or convert MOBI to EPUB for audiobook generation.
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
4. **Audio settings** (present defaults, let user override if desired):
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
Construct and run the `convert` command based on the user's answers, e.g.:
```bash
bookvoice convert "<book_path>" \
  --voice <voice> \
  --rate <rate> \
  --bitrate <bitrate> \
  [--only <selection>] \
  [--no-m4b] \
  [--no-normalize] \
  [-o "<output_dir>"] \
  [--cover "<cover_path>"]
```

- On Windows PowerShell, set `$env:PYTHONIOENCODING='utf-8'` so non-ASCII chapter titles print cleanly.
- For full books, run the conversion in the background and inform the user of the expected duration and output directory.
- Remind the user that **interrupted runs resume automatically** — running the exact same command skips already-finished chapters.

### 6. Verify Output
Once conversion completes:
- Check the output directory for all expected `.mp3` files and (unless `--no-m4b`) the `.m4b` file.
- Verify the `.m4b` duration and chapter count with `ffprobe` if available.
- Report the output path, file size, chapter count, and total duration to the user.
