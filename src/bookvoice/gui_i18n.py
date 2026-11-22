"""Internationalisation (EN / PL) and user preferences for the bookvoice GUI."""
# ruff: noqa: RUF001

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_GUI_CONFIG_PATH = Path.home() / ".bookvoice" / "gui.json"
SUPPORTED_LANGUAGES = ("en", "pl")
DEFAULT_LANGUAGE = "en"

LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "pl": "Polski",
}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "bookvoice – E-book to Audiobook",
        "lang_label": "Language:",
        # Tabs
        "tab_convert": "📖 Convert",
        "tab_queue": "📚 Queue & Status",
        "tab_tools": "🛠 Tools & Doctor",
        # Convert tab - book section
        "book_label": "📖 E-book file:",
        "btn_browse_file": "📂 File…",
        "btn_inspect": "🔍 Inspect",
        "book_hint": "EPUB, MOBI, AZW, AZW3 or PRC (Kindle formats require Calibre)",
        "meta_empty": "Select an e-book file to inspect its title, author, language and chapters.",
        "meta_loading": "Inspecting e-book…",
        "meta_summary": (
            "{author} — {title}\n"
            "Language: {lang} (default voice: {voice})  •  Cover: {cover}  •  "
            "Chapters: {chapters} ({chars:,} chars, ~{duration})"
        ),
        "cover_yes": "yes",
        "cover_no": "no",
        # Convert tab - format & voice
        "format_label": "Format:",
        "fmt_mp3_m4b": "MP3 + M4B (audiobook)",
        "fmt_mp3_only": "MP3 per chapter only",
        "fmt_m4b_only": "Rebuild M4B only",
        "voice_label": "Voice:",
        "btn_load_voices": "🔄 Load voices",
        "btn_sample": "🎧 Sample voices",
        "voice_auto_hint": "auto (by book language)",
        "output_label": "Output folder:",
        "output_hint": "leave empty for ./<Author> - <Title>",
        "chapters_label": "Chapters:",
        "btn_pick_chapters": "📋 Pick…",
        "chapters_hint": "e.g. 2-40 or 1,3-5; empty = all",
        "audio_label": "Audio:",
        "rate_label": "Rate:",
        "bitrate_label": "Bitrate:",
        "chk_normalize": "Loudness normalisation (EBU R128)",
        # More options
        "btn_more_closed": "⚙ More options ▸",
        "btn_more_open": "⚙ More options ▾",
        "more_frame": "More options",
        "cover_label": "Custom cover:",
        "btn_clear": "✕",
        "parallel_label": "Parallel TTS requests:",
        "chunk_label": "Max chars per chunk:",
        "heading_label": "Heading regex:",
        "heading_hint": "empty = built-in pattern",
        "chk_disable_heading": "Disable heading splitting",
        "chk_keep_work": "Keep intermediate .work files",
        "chk_open_after": "Open output folder when finished",
        # Actions
        "btn_convert": "▶  CONVERT",
        "btn_build_m4b": "▶  BUILD M4B",
        "btn_working": "⏳  Working…",
        "btn_add_queue": "➕ Add to queue",
        "btn_stop": "⏹ Stop",
        "btn_defaults": "↺ Defaults",
        # Status & result
        "status_ready": "Choose an e-book file and click Convert.",
        "status_starting": "Starting…",
        "status_inspecting": "Reading book metadata…",
        "status_packaging": "Packaging M4B audiobook…",
        "status_sampling": "Generating voice samples…",
        "status_stopping": "Stopping… (already finished chapters are kept for resume)",
        "status_stopped": "⏹ Stopped. Run again with the same settings to resume.",
        "status_done": "✅ Done: {name}  →  {folder}",
        "status_samples_done": "✅ Saved {count} voice sample(s) → {folder}",
        "status_voices_loaded": "Loaded {count} voice(s).",
        "status_queued": "➕ Added to queue (#{id}): {name}",
        "status_defaults": "Restored default settings.",
        "btn_open_m4b": "▶ Open M4B",
        "btn_show_folder": "📁 Open folder",
        "btn_open_samples": "🎧 Open samples folder",
        "btn_log_closed": "📜 Details ▸",
        "btn_log_open": "📜 Details ▾",
        # Progress line
        "progress_line": (
            "{pct:.1f}%  |  ch {ch}/{ch_total}: {ch_title} ({chunk}/{chunk_total})  |  "
            "{elapsed} elapsed  |  ETA {eta}"
        ),
        # Chapter picker dialog
        "ch_dialog_title": "Select chapters",
        "ch_col_num": "#",
        "ch_col_chars": "Chars",
        "ch_col_title": "Title",
        "ch_btn_all": "Select all",
        "ch_btn_skip_front": "Skip #1",
        "ch_btn_none": "Clear",
        "ch_btn_ok": "Apply",
        "ch_btn_cancel": "Cancel",
        "ch_hint": "Double-click or press Space to toggle a chapter (or use multi-select).",
        # Queue tab
        "live_frame": "Live conversion status (status.json)",
        "live_none": "No active or recent conversion.",
        "live_book": "Book: {author} – {title}",
        "live_meta": "Status: {state}  •  Voice: {voice}  •  PID: {pid}",
        "live_progress": (
            "{pct:.1f}%  •  Chapter {ch}/{ch_total}: {ch_title} "
            "({chunk}/{chunk_total} chunks)  •  {elapsed} elapsed  •  ETA: {eta}"
        ),
        "queue_frame": "Persistent conversion queue (~/.bookvoice/queue.json)",
        "worker_running": "Worker: running (PID {pid})",
        "worker_idle": "Worker: idle",
        "q_col_id": "#",
        "q_col_status": "Status",
        "q_col_book": "Book",
        "q_col_voice": "Voice",
        "q_col_format": "Format",
        "q_col_error": "Note / Error",
        "q_btn_add_files": "➕ Add files…",
        "q_btn_add_folder": "📂 Add folder…",
        "q_btn_run_bg": "▶ Run queue (background)",
        "q_btn_retry": "🔁 Retry failed",
        "q_btn_remove": "🗑 Remove",
        "q_btn_clear_done": "🧹 Clear done/failed",
        "q_btn_refresh": "🔄 Refresh",
        "q_started_bg": "Started queue worker in background (PID {pid}). Log: {log}",
        "q_already_running": "Queue worker is already running (PID {pid}).",
        "q_empty": "No pending items in the queue.",
        # Tools tab
        "mobi_frame": "Convert MOBI / AZW / AZW3 → EPUB (via Calibre)",
        "mobi_src_label": "Kindle file:",
        "mobi_dst_label": "Output .epub:",
        "mobi_dst_hint": "empty = next to input file",
        "btn_mobi_convert": "🔄 Convert to EPUB",
        "mobi_done": "✅ Converted: {path}",
        "doctor_frame": "Environment check (bookvoice doctor)",
        "btn_recheck": "🔄 Re-check",
        "btn_copy_hint": "📋 Copy install command",
        "doc_col_status": "Status",
        "doc_col_tool": "Component",
        "doc_col_detail": "Details",
        "doc_col_hint": "Install hint",
        "shortcut_frame": "Windows desktop shortcut",
        "shortcut_desc": (
            "Create a 'bookvoice' shortcut on your desktop (no console window). "
            "You can also drag and drop an e-book file onto the shortcut."
        ),
        "btn_shortcut": "🖥 Create desktop shortcut",
        "shortcut_done": "✅ Shortcut created: {path}",
        "shortcut_non_win": "Desktop shortcut creation is only available on Windows.",
        # Validation & errors
        "err_title": "bookvoice – Error",
        "warn_title": "bookvoice",
        "err_no_book": "Please select an e-book file first.",
        "err_book_missing": "Selected file does not exist.",
        "err_no_chapters_loaded": "Inspect the book first to browse its chapters.",
        "err_no_selection": "Select an item in the queue first.",
        "copied_hint": "Copied to clipboard: {cmd}",
        # File dialogs
        "dlg_ebook_title": "Select an e-book file",
        "dlg_ebook_filter": "E-books",
        "dlg_all_filter": "All files",
        "dlg_folder_title": "Select folder",
        "dlg_cover_title": "Select cover image",
        "dlg_cover_filter": "Images",
        "dlg_mobi_title": "Select MOBI / AZW / AZW3 file",
        "dlg_epub_save_title": "Save EPUB as",
    },
    "pl": {
        "app_title": "bookvoice – E-book na Audiobook",
        "lang_label": "Język:",
        # Tabs
        "tab_convert": "📖 Konwersja",
        "tab_queue": "📚 Kolejka i status",
        "tab_tools": "🛠 Narzędzia i Doctor",
        # Convert tab - book section
        "book_label": "📖 Plik e-booka:",
        "btn_browse_file": "📂 Plik…",
        "btn_inspect": "🔍 Sprawdź",
        "book_hint": "EPUB, MOBI, AZW, AZW3 lub PRC (formaty Kindle wymagają Calibre)",
        "meta_empty": "Wybierz plik e-booka, aby odczytać tytuł, autora, język i listę rozdziałów.",
        "meta_loading": "Wczytuję informacje o książce…",
        "meta_summary": (
            "{author} — {title}\n"
            "Język: {lang} (domyślny głos: {voice})  •  Okładka: {cover}  •  "
            "Rozdziały: {chapters} ({chars:,} znaków, ~{duration})"
        ),
        "cover_yes": "tak",
        "cover_no": "brak",
        # Convert tab - format & voice
        "format_label": "Format:",
        "fmt_mp3_m4b": "MP3 + M4B (audiobook)",
        "fmt_mp3_only": "Tylko MP3 na rozdział",
        "fmt_m4b_only": "Tylko przebuduj M4B",
        "voice_label": "Głos:",
        "btn_load_voices": "🔄 Pobierz głosy",
        "btn_sample": "🎧 Próbki głosów",
        "voice_auto_hint": "auto (wg języka książki)",
        "output_label": "Folder zapisu:",
        "output_hint": "puste = ./<Autor> - <Tytuł>",
        "chapters_label": "Rozdziały:",
        "btn_pick_chapters": "📋 Wybierz…",
        "chapters_hint": "np. 2-40 lub 1,3-5; puste = wszystkie",
        "audio_label": "Audio:",
        "rate_label": "Tempo:",
        "bitrate_label": "Bitrate:",
        "chk_normalize": "Normalizacja głośności (EBU R128)",
        # More options
        "btn_more_closed": "⚙ Więcej opcji ▸",
        "btn_more_open": "⚙ Więcej opcji ▾",
        "more_frame": "Więcej opcji",
        "cover_label": "Własna okładka:",
        "btn_clear": "✕",
        "parallel_label": "Równoległe żądania TTS:",
        "chunk_label": "Maks. znaków w fragmencie:",
        "heading_label": "Regex nagłówków:",
        "heading_hint": "puste = wbudowany wzorzec",
        "chk_disable_heading": "Wyłącz dzielenie nagłówków",
        "chk_keep_work": "Zachowaj pliki robocze (.work)",
        "chk_open_after": "Po zakończeniu otwórz folder z wynikiem",
        # Actions
        "btn_convert": "▶  KONWERTUJ",
        "btn_build_m4b": "▶  ZBUDUJ M4B",
        "btn_working": "⏳  Pracuję…",
        "btn_add_queue": "➕ Do kolejki",
        "btn_stop": "⏹ Zatrzymaj",
        "btn_defaults": "↺ Domyślne",
        # Status & result
        "status_ready": "Wybierz plik e-booka i kliknij Konwertuj.",
        "status_starting": "Zaczynam…",
        "status_inspecting": "Odczytuję metadane książki…",
        "status_packaging": "Pakuję audiobook M4B…",
        "status_sampling": "Generuję próbki głosów…",
        "status_stopping": "Zatrzymuję… (ukończone rozdziały zostaną zachowane do wznowienia)",
        "status_stopped": "⏹ Zatrzymano. Uruchom ponownie z tymi samymi ustawieniami, aby wznowić.",
        "status_done": "✅ Gotowe: {name}  →  {folder}",
        "status_samples_done": "✅ Zapisano {count} próbek głosów → {folder}",
        "status_voices_loaded": "Pobrano {count} głosów.",
        "status_queued": "➕ Dodano do kolejki (#{id}): {name}",
        "status_defaults": "Przywrócono ustawienia domyślne.",
        "btn_open_m4b": "▶ Otwórz M4B",
        "btn_show_folder": "📁 Otwórz folder",
        "btn_open_samples": "🎧 Otwórz folder próbek",
        "btn_log_closed": "📜 Szczegóły ▸",
        "btn_log_open": "📜 Szczegóły ▾",
        # Progress line
        "progress_line": (
            "{pct:.1f}%  |  rozdz. {ch}/{ch_total}: {ch_title} ({chunk}/{chunk_total})  |  "
            "minęło {elapsed}  |  ETA {eta}"
        ),
        # Chapter picker dialog
        "ch_dialog_title": "Wybierz rozdziały",
        "ch_col_num": "#",
        "ch_col_chars": "Znaki",
        "ch_col_title": "Tytuł",
        "ch_btn_all": "Zaznacz wszystkie",
        "ch_btn_skip_front": "Pomiń #1",
        "ch_btn_none": "Wyczyść",
        "ch_btn_ok": "Zastosuj",
        "ch_btn_cancel": "Anuluj",
        "ch_hint": "Kliknij dwukrotnie lub naciśnij Spację, aby przełączyć rozdział.",
        # Queue tab
        "live_frame": "Bieżący status konwersji (status.json)",
        "live_none": "Brak aktywnej lub ostatniej konwersji.",
        "live_book": "Książka: {author} – {title}",
        "live_meta": "Status: {state}  •  Głos: {voice}  •  PID: {pid}",
        "live_progress": (
            "{pct:.1f}%  •  Rozdział {ch}/{ch_total}: {ch_title} "
            "({chunk}/{chunk_total} fragm.)  •  minęło {elapsed}  •  ETA: {eta}"
        ),
        "queue_frame": "Trwała kolejka konwersji (~/.bookvoice/queue.json)",
        "worker_running": "Worker: działa (PID {pid})",
        "worker_idle": "Worker: bezczynny",
        "q_col_id": "#",
        "q_col_status": "Status",
        "q_col_book": "Książka",
        "q_col_voice": "Głos",
        "q_col_format": "Format",
        "q_col_error": "Uwagi / Błąd",
        "q_btn_add_files": "➕ Dodaj pliki…",
        "q_btn_add_folder": "📂 Dodaj folder…",
        "q_btn_run_bg": "▶ Uruchom kolejkę (w tle)",
        "q_btn_retry": "🔁 Ponów błędne",
        "q_btn_remove": "🗑 Usuń",
        "q_btn_clear_done": "🧹 Wyczyść ukończone",
        "q_btn_refresh": "🔄 Odśwież",
        "q_started_bg": "Uruchomiono kolejkę w tle (PID {pid}). Log: {log}",
        "q_already_running": "Worker kolejki już działa (PID {pid}).",
        "q_empty": "Brak oczekujących pozycji w kolejce.",
        # Tools tab
        "mobi_frame": "Konwersja MOBI / AZW / AZW3 → EPUB (przez Calibre)",
        "mobi_src_label": "Plik Kindle:",
        "mobi_dst_label": "Plik .epub:",
        "mobi_dst_hint": "puste = obok pliku źródłowego",
        "btn_mobi_convert": "🔄 Konwertuj do EPUB",
        "mobi_done": "✅ Skonwertowano: {path}",
        "doctor_frame": "Diagnostyka środowiska (bookvoice doctor)",
        "btn_recheck": "🔄 Sprawdź ponownie",
        "btn_copy_hint": "📋 Kopiuj komendę instalacji",
        "doc_col_status": "Status",
        "doc_col_tool": "Komponent",
        "doc_col_detail": "Szczegóły",
        "doc_col_hint": "Instalacja",
        "shortcut_frame": "Skrót na pulpicie Windows",
        "shortcut_desc": (
            "Tworzy skrót „bookvoice” na pulpicie (uruchamiany bez okna konsoli). "
            "Na skrót można też przeciągnąć plik e-booka."
        ),
        "btn_shortcut": "🖥 Utwórz skrót na pulpicie",
        "shortcut_done": "✅ Utworzono skrót: {path}",
        "shortcut_non_win": "Tworzenie skrótu na pulpicie jest dostępne tylko w systemie Windows.",
        # Validation & errors
        "err_title": "bookvoice – Błąd",
        "warn_title": "bookvoice",
        "err_no_book": "Najpierw wybierz plik e-booka.",
        "err_book_missing": "Wybrany plik nie istnieje.",
        "err_no_chapters_loaded": "Najpierw sprawdź książkę, aby wyświetlić listę rozdziałów.",
        "err_no_selection": "Najpierw zaznacz pozycję na liście kolejki.",
        "copied_hint": "Skopiowano do schowka: {cmd}",
        # File dialogs
        "dlg_ebook_title": "Wybierz plik e-booka",
        "dlg_ebook_filter": "E-booki",
        "dlg_all_filter": "Wszystkie pliki",
        "dlg_folder_title": "Wybierz folder",
        "dlg_cover_title": "Wybierz obraz okładki",
        "dlg_cover_filter": "Obrazy",
        "dlg_mobi_title": "Wybierz plik MOBI / AZW / AZW3",
        "dlg_epub_save_title": "Zapisz EPUB jako",
    },
}


def tr(lang: str, key: str, **kwargs: Any) -> str:
    """Translate ``key`` into ``lang`` (falling back to English), formatting ``kwargs``."""
    table = STRINGS.get(lang, STRINGS[DEFAULT_LANGUAGE])
    template = table.get(key) or STRINGS[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**kwargs) if kwargs else template


def load_gui_config(path: Path | None = None) -> dict[str, Any]:
    """Load persisted GUI preferences (e.g. chosen language) from ``~/.bookvoice/gui.json``."""
    resolved = (DEFAULT_GUI_CONFIG_PATH if path is None else path).expanduser().resolve()
    if not resolved.exists():
        return {"language": DEFAULT_LANGUAGE}
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"language": DEFAULT_LANGUAGE}
    except (OSError, json.JSONDecodeError):
        return {"language": DEFAULT_LANGUAGE}
    lang = data.get("language")
    if lang not in SUPPORTED_LANGUAGES:
        data["language"] = DEFAULT_LANGUAGE
    return data


def save_gui_config(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomically save GUI preferences to ``~/.bookvoice/gui.json``."""
    resolved = (DEFAULT_GUI_CONFIG_PATH if path is None else path).expanduser().resolve()
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp = resolved.with_name(resolved.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(resolved)
    except OSError:
        pass
