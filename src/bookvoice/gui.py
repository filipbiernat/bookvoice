"""Desktop GUI for bookvoice (native tkinter/ttk, zero extra dependencies)."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
import queue as thread_queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Iterable, Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from . import __version__, audio, cli, doctor, gui_shortcut, mobi, pipeline, progress, queue, tts
from .epub import Book, Cover, parse_epub
from .gui_i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_LABELS,
    load_gui_config,
    save_gui_config,
    tr,
)
from .text import DEFAULT_HEADING_PATTERN, parse_selection, safe_filename

_GRAY = "#6b6b6b"
_GREEN = "#1a7f37"
_ORANGE = "#b35900"
_RED = "#c62828"

_IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_RATE_PRESETS = ("-20%", "-15%", "-10%", "-5%", "+0%", "+5%", "+10%", "+15%", "+20%", "+25%")
_BITRATE_PRESETS = ("48k", "64k", "96k", "128k")


def format_selection(indices: Iterable[int]) -> str:
    """Format a set of 1-based chapter numbers into compact range syntax, e.g. ``1-3,5,7-9``."""
    nums = sorted(set(indices))
    if not nums:
        return ""
    ranges: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def estimate_duration_text(total_chars: int) -> str:
    """Estimate spoken audio duration from character count (~900 chars/minute)."""
    minutes = max(1, round(total_chars / 900))
    return progress.format_duration(minutes * 60)


def _open_path(path: Path) -> None:
    if not path.exists():
        return
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _show_in_folder(path: Path) -> None:
    if not path.exists():
        return
    if sys.platform == "win32":
        if path.is_file():
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        _open_path(path if path.is_dir() else path.parent)


class _QueueLogHandler(logging.Handler):
    """Forward ``bookvoice`` log records to the GUI event queue."""

    def __init__(self, event_queue: thread_queue.Queue[tuple[str, Any]]) -> None:
        super().__init__(logging.INFO)
        self._q = event_queue
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):
            self._q.put(("log", self.format(record)))


class ChapterPickerDialog(tk.Toplevel):
    """Modal dialog for picking chapters from an inspected book."""

    def __init__(
        self,
        parent: tk.Misc,
        book: Book,
        selected: set[int] | None,
        lang: str,
    ) -> None:
        super().__init__(parent)
        self._lang = lang
        self._book = book
        self._checked: set[int] = (
            set(selected) if selected is not None else {c.index for c in book.chapters}
        )
        self.result: str | None = None

        self.title(tr(lang, "ch_dialog_title"))
        self.geometry("620x440")
        self.transient(parent)  # type: ignore[arg-type]
        self.grab_set()

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text=tr(lang, "ch_hint"), foreground=_GRAY).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=("chk", "num", "chars", "title"),
            show="headings",
            selectmode="extended",
        )
        self._tree.heading("chk", text="✓")
        self._tree.heading("num", text=tr(lang, "ch_col_num"))
        self._tree.heading("chars", text=tr(lang, "ch_col_chars"))
        self._tree.heading("title", text=tr(lang, "ch_col_title"))
        self._tree.column("chk", width=36, anchor="center", stretch=False)
        self._tree.column("num", width=48, anchor="e", stretch=False)
        self._tree.column("chars", width=84, anchor="e", stretch=False)
        self._tree.column("title", width=400, anchor="w", stretch=True)

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        for ch in book.chapters:
            mark = "☑" if ch.index in self._checked else "☐"
            self._tree.insert(
                "",
                "end",
                iid=str(ch.index),
                values=(mark, ch.index, f"{ch.char_count:,}", ch.title),
            )

        self._tree.bind("<Double-1>", self._toggle_selected)
        self._tree.bind("<space>", self._toggle_selected)

        btns = ttk.Frame(frame)
        btns.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(btns, text=tr(lang, "ch_btn_all"), command=self._select_all).pack(side="left")
        ttk.Button(btns, text=tr(lang, "ch_btn_skip_front"), command=self._skip_first).pack(
            side="left", padx=6
        )
        ttk.Button(btns, text=tr(lang, "ch_btn_none"), command=self._select_none).pack(side="left")
        ttk.Button(btns, text=tr(lang, "ch_btn_cancel"), command=self.destroy).pack(side="right")
        ttk.Button(btns, text=tr(lang, "ch_btn_ok"), command=self._apply).pack(
            side="right", padx=(0, 6)
        )

    def _refresh_marks(self) -> None:
        for ch in self._book.chapters:
            mark = "☑" if ch.index in self._checked else "☐"
            self._tree.set(str(ch.index), "chk", mark)

    def _toggle_selected(self, _event: tk.Event[Any] | None = None) -> None:
        sel = self._tree.selection()
        for iid in sel:
            idx = int(iid)
            if idx in self._checked:
                self._checked.remove(idx)
            else:
                self._checked.add(idx)
        self._refresh_marks()

    def _select_all(self) -> None:
        self._checked = {c.index for c in self._book.chapters}
        self._refresh_marks()

    def _skip_first(self) -> None:
        self._checked = {c.index for c in self._book.chapters if c.index > 1}
        self._refresh_marks()

    def _select_none(self) -> None:
        self._checked.clear()
        self._refresh_marks()

    def _apply(self) -> None:
        all_indices = {c.index for c in self._book.chapters}
        if not self._checked or self._checked == all_indices:
            self.result = ""
        else:
            self.result = format_selection(self._checked)
        self.destroy()


class BookvoiceApp(tk.Tk):
    """Main desktop window for bookvoice."""

    def __init__(self, initial_book: str = "") -> None:
        super().__init__()
        self._cfg = load_gui_config()
        self._lang: str = self._cfg.get("language", DEFAULT_LANGUAGE)
        self._events: thread_queue.Queue[tuple[str, Any]] = thread_queue.Queue()
        self._worker: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_task: asyncio.Task[Any] | None = None
        self._stop_event = threading.Event()
        self._active_tracker: progress.ProgressTracker | None = None
        self._book: Book | None = None
        self._result_m4b: Path | None = None
        self._result_dir: Path | None = None
        self._samples_dir: Path | None = None
        self._voices_cache: list[dict[str, Any]] = []
        self._doctor_results: list[doctor.CheckResult] = []
        self._queue_obj = queue.BookQueue()
        self._last_live_dir: Path | None = None

        self.minsize(780, 620)
        self._setup_style()
        self._setup_vars()
        self._build_ui()
        self._apply_language()
        self._run_doctor_check()
        self._refresh_queue_and_status()

        if initial_book:
            cleaned = initial_book.strip().strip('"')
            if cleaned:
                self.v_book.set(cleaned)
                self.after(150, self._inspect_book)

        self.after(100, self._poll_events)
        self.after(2000, self._periodic_status_refresh)

        self.lift()
        self.focus_force()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _t(self, key: str, **kwargs: Any) -> str:
        return tr(self._lang, key, **kwargs)

    def _is_busy(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        family = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
        base_font = (family, 10)
        bold_font = (family, 10, "bold")
        hint_font = (family, 9)
        big_font = (family, 12, "bold")

        style.configure(".", font=base_font)
        style.configure("Title.TLabel", font=bold_font)
        style.configure("Hint.TLabel", foreground=_GRAY, font=hint_font)
        style.configure("Status.TLabel", font=bold_font)
        style.configure("Big.TButton", font=big_font, padding=(18, 8))
        style.configure("Bold.TRadiobutton", font=bold_font)

    def _setup_vars(self) -> None:
        self.v_lang_label = tk.StringVar(value=LANGUAGE_LABELS.get(self._lang, "English"))
        self.v_book = tk.StringVar()
        self.v_meta = tk.StringVar()
        self.v_format = tk.StringVar(value="mp3_m4b")
        self.v_voice = tk.StringVar()
        self.v_output = tk.StringVar()
        self.v_only = tk.StringVar()
        self.v_rate = tk.StringVar(value="+0%")
        self.v_bitrate = tk.StringVar(value="64k")
        self.v_normalize = tk.BooleanVar(value=True)
        self.v_cover = tk.StringVar()
        self.v_parallel = tk.StringVar(value="3")
        self.v_chunk_chars = tk.StringVar(value="2500")
        self.v_heading_pattern = tk.StringVar()
        self.v_disable_heading = tk.BooleanVar(value=False)
        self.v_keep_work = tk.BooleanVar(value=False)
        self.v_open_after = tk.BooleanVar(value=False)
        self.v_status = tk.StringVar()

        # Queue & Status tab
        self.v_live_book = tk.StringVar()
        self.v_live_meta = tk.StringVar()
        self.v_live_progress = tk.StringVar()
        self.v_worker_badge = tk.StringVar()

        # Tools tab
        self.v_mobi_src = tk.StringVar()
        self.v_mobi_dst = tk.StringVar()
        self.v_mobi_status = tk.StringVar()
        self.v_shortcut_status = tk.StringVar()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=(12, 10))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # Header bar
        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=f"🎧 bookvoice {__version__}", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        lang_box = ttk.Frame(header)
        lang_box.grid(row=0, column=1, sticky="e")
        self.l_lang = ttk.Label(lang_box)
        self.l_lang.pack(side="left", padx=(0, 6))
        self.cb_lang = ttk.Combobox(
            lang_box,
            textvariable=self.v_lang_label,
            values=list(LANGUAGE_LABELS.values()),
            state="readonly",
            width=10,
        )
        self.cb_lang.pack(side="left")
        self.cb_lang.bind("<<ComboboxSelected>>", self._on_language_change)

        # Tabs
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.tab_convert = ttk.Frame(self.notebook, padding=12)
        self.tab_queue = ttk.Frame(self.notebook, padding=12)
        self.tab_tools = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.tab_convert, text="Convert")
        self.notebook.add(self.tab_queue, text="Queue")
        self.notebook.add(self.tab_tools, text="Tools")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_convert_tab()
        self._build_queue_tab()
        self._build_tools_tab()

    def _build_convert_tab(self) -> None:
        f = self.tab_convert
        f.columnconfigure(1, weight=1)
        r = 0

        # Book file
        self.l_book = ttk.Label(f, style="Title.TLabel")
        self.l_book.grid(row=r, column=0, sticky="w", pady=(0, 2))
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.e_book = ttk.Entry(row, textvariable=self.v_book)
        self.e_book.grid(row=0, column=0, sticky="ew", ipady=2)
        self.b_browse_book = ttk.Button(row, command=self._browse_book)
        self.b_browse_book.grid(row=0, column=1, padx=(6, 0))
        self.b_inspect = ttk.Button(row, command=self._inspect_book)
        self.b_inspect.grid(row=0, column=2, padx=(6, 0))
        r += 1

        self.l_book_hint = ttk.Label(f, style="Hint.TLabel")
        self.l_book_hint.grid(row=r, column=1, sticky="w", pady=(0, 6))
        r += 1

        # Book metadata summary card
        self.f_meta = ttk.Frame(f, relief="groove", padding=(10, 6))
        self.f_meta.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.f_meta.columnconfigure(0, weight=1)
        self.l_meta = ttk.Label(self.f_meta, textvariable=self.v_meta, wraplength=700)
        self.l_meta.grid(row=0, column=0, sticky="w")
        r += 1

        # Format
        self.l_format = ttk.Label(f, style="Title.TLabel")
        self.l_format.grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="w", pady=4)
        self.rb_mp3_m4b = ttk.Radiobutton(
            row, value="mp3_m4b", variable=self.v_format, style="Bold.TRadiobutton",
            command=self._on_format_change,
        )
        self.rb_mp3_m4b.pack(side="left", padx=(0, 14))
        self.rb_mp3_only = ttk.Radiobutton(
            row, value="mp3_only", variable=self.v_format, style="Bold.TRadiobutton",
            command=self._on_format_change,
        )
        self.rb_mp3_only.pack(side="left", padx=(0, 14))
        self.rb_m4b_only = ttk.Radiobutton(
            row, value="m4b_only", variable=self.v_format, style="Bold.TRadiobutton",
            command=self._on_format_change,
        )
        self.rb_m4b_only.pack(side="left")
        r += 1

        # Voice & sampling
        self.l_voice = ttk.Label(f, style="Title.TLabel")
        self.l_voice.grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="ew", pady=4)
        row.columnconfigure(0, weight=1)
        default_voices = sorted(set(tts.DEFAULT_VOICES.values()))
        self.cb_voice = ttk.Combobox(row, textvariable=self.v_voice, values=default_voices)
        self.cb_voice.grid(row=0, column=0, sticky="ew")
        self.b_load_voices = ttk.Button(row, command=self._load_voices)
        self.b_load_voices.grid(row=0, column=1, padx=(6, 0))
        self.b_sample = ttk.Button(row, command=self._sample_voices)
        self.b_sample.grid(row=0, column=2, padx=(6, 0))
        r += 1

        # Output folder
        self.l_output = ttk.Label(f, style="Title.TLabel")
        self.l_output.grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="ew", pady=4)
        row.columnconfigure(0, weight=1)
        self.e_output = ttk.Entry(row, textvariable=self.v_output)
        self.e_output.grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="…", width=3, command=self._browse_output).grid(
            row=0, column=1, padx=(6, 0)
        )
        self.l_output_hint = ttk.Label(row, style="Hint.TLabel")
        self.l_output_hint.grid(row=0, column=2, padx=(8, 0))
        r += 1

        # Chapters
        self.l_chapters = ttk.Label(f, style="Title.TLabel")
        self.l_chapters.grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="w", pady=4)
        self.e_only = ttk.Entry(row, textvariable=self.v_only, width=20)
        self.e_only.pack(side="left")
        self.b_pick_chapters = ttk.Button(row, command=self._open_chapter_picker)
        self.b_pick_chapters.pack(side="left", padx=(6, 8))
        self.l_chapters_hint = ttk.Label(row, style="Hint.TLabel")
        self.l_chapters_hint.pack(side="left")
        r += 1

        # Audio row (rate, bitrate, normalize)
        self.l_audio = ttk.Label(f, style="Title.TLabel")
        self.l_audio.grid(row=r, column=0, sticky="w", pady=4)
        row = ttk.Frame(f)
        row.grid(row=r, column=1, sticky="w", pady=4)
        self.l_rate = ttk.Label(row)
        self.l_rate.pack(side="left")
        self.cb_rate = ttk.Combobox(row, textvariable=self.v_rate, values=_RATE_PRESETS, width=7)
        self.cb_rate.pack(side="left", padx=(4, 14))
        self.l_bitrate = ttk.Label(row)
        self.l_bitrate.pack(side="left")
        self.cb_bitrate = ttk.Combobox(
            row, textvariable=self.v_bitrate, values=_BITRATE_PRESETS, width=6, state="readonly"
        )
        self.cb_bitrate.pack(side="left", padx=(4, 14))
        self.chk_normalize = ttk.Checkbutton(row, variable=self.v_normalize)
        self.chk_normalize.pack(side="left")
        r += 1

        # Collapsible More Options (PobierzKlip style)
        self.b_more = ttk.Button(f, command=self._toggle_more)
        self.b_more.grid(row=r, column=0, sticky="w", pady=(6, 0))
        r += 1

        self.f_more = ttk.LabelFrame(f, padding=10)
        self.f_more.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.f_more.columnconfigure(1, weight=1)
        o = self.f_more

        self.l_cover = ttk.Label(o)
        self.l_cover.grid(row=0, column=0, sticky="w", pady=2)
        c_row = ttk.Frame(o)
        c_row.grid(row=0, column=1, sticky="ew", pady=2)
        c_row.columnconfigure(0, weight=1)
        ttk.Entry(c_row, textvariable=self.v_cover).grid(row=0, column=0, sticky="ew")
        ttk.Button(c_row, text="…", width=3, command=self._browse_cover).grid(
            row=0, column=1, padx=(4, 0)
        )
        self.b_clear_cover = ttk.Button(
            c_row, width=3, command=lambda: self.v_cover.set("")
        )
        self.b_clear_cover.grid(row=0, column=2, padx=(4, 0))

        self.l_parallel = ttk.Label(o)
        self.l_parallel.grid(row=1, column=0, sticky="w", pady=2)
        p_row = ttk.Frame(o)
        p_row.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Spinbox(p_row, from_=1, to=10, textvariable=self.v_parallel, width=5).pack(side="left")
        self.l_chunk = ttk.Label(p_row)
        self.l_chunk.pack(side="left", padx=(18, 6))
        ttk.Spinbox(
            p_row, from_=500, to=10000, increment=250, textvariable=self.v_chunk_chars, width=7
        ).pack(side="left")

        self.l_heading = ttk.Label(o)
        self.l_heading.grid(row=2, column=0, sticky="w", pady=2)
        h_row = ttk.Frame(o)
        h_row.grid(row=2, column=1, sticky="ew", pady=2)
        h_row.columnconfigure(0, weight=1)
        self.e_heading = ttk.Entry(h_row, textvariable=self.v_heading_pattern)
        self.e_heading.grid(row=0, column=0, sticky="ew")
        self.chk_disable_heading = ttk.Checkbutton(
            h_row, variable=self.v_disable_heading, command=self._on_disable_heading_toggle
        )
        self.chk_disable_heading.grid(row=0, column=1, padx=(8, 0))

        checks = ttk.Frame(o)
        checks.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.chk_keep_work = ttk.Checkbutton(checks, variable=self.v_keep_work)
        self.chk_keep_work.pack(side="left", padx=(0, 18))
        self.chk_open_after = ttk.Checkbutton(checks, variable=self.v_open_after)
        self.chk_open_after.pack(side="left")

        self.f_more.grid_remove()
        r += 1

        # Action bar
        actions = ttk.Frame(f)
        actions.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(12, 6))
        actions.columnconfigure(0, weight=1)
        self.b_start = ttk.Button(actions, style="Big.TButton", command=self._start_convert)
        self.b_start.grid(row=0, column=0, sticky="ew")
        self.b_add_queue = ttk.Button(actions, command=self._add_current_to_queue)
        self.b_add_queue.grid(row=0, column=1, padx=(8, 0), sticky="ns")
        self.b_stop = ttk.Button(actions, command=self._stop_current, state="disabled")
        self.b_stop.grid(row=0, column=2, padx=(6, 0), sticky="ns")
        self.b_defaults = ttk.Button(actions, command=self._restore_defaults)
        self.b_defaults.grid(row=0, column=3, padx=(6, 0), sticky="ns")
        r += 1

        # Progress bar & status
        self.pbar = ttk.Progressbar(f, mode="determinate", maximum=100.0)
        self.pbar.grid(row=r, column=0, columnspan=2, sticky="ew")
        r += 1

        self.l_status = ttk.Label(
            f, textvariable=self.v_status, style="Status.TLabel", wraplength=740
        )
        self.l_status.grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1

        # Result buttons (hidden until success)
        self.f_result = ttk.Frame(f)
        self.f_result.grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.b_open_m4b = ttk.Button(self.f_result, command=self._open_result_m4b)
        self.b_open_m4b.pack(side="left")
        self.b_show_folder = ttk.Button(self.f_result, command=self._open_result_folder)
        self.b_show_folder.pack(side="left", padx=6)
        self.b_open_samples = ttk.Button(self.f_result, command=self._open_samples_folder)
        self.b_open_samples.pack(side="left")
        self.f_result.grid_remove()
        r += 1

        # Collapsible log
        self.b_log = ttk.Button(f, command=self._toggle_log)
        self.b_log.grid(row=r, column=0, sticky="w", pady=(8, 0))
        r += 1

        self.t_log = ScrolledText(f, height=10, font=("Consolas", 9), state="disabled", wrap="word")
        self.t_log.grid(row=r, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        f.rowconfigure(r, weight=1)
        self.t_log.grid_remove()

    def _build_queue_tab(self) -> None:
        f = self.tab_queue
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        # Live status card
        self.f_live = ttk.LabelFrame(f, padding=10)
        self.f_live.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.f_live.columnconfigure(0, weight=1)

        ttk.Label(self.f_live, textvariable=self.v_live_book, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.b_live_folder = ttk.Button(
            self.f_live, command=self._open_live_folder, state="disabled"
        )
        self.b_live_folder.grid(row=0, column=1, sticky="e")
        ttk.Label(self.f_live, textvariable=self.v_live_meta, style="Hint.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 4)
        )
        self.pbar_live = ttk.Progressbar(self.f_live, mode="determinate", maximum=100.0)
        self.pbar_live.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(self.f_live, textvariable=self.v_live_progress).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )

        # Queue section
        self.f_queue = ttk.LabelFrame(f, padding=10)
        self.f_queue.grid(row=1, column=0, sticky="nsew")
        self.f_queue.columnconfigure(0, weight=1)
        self.f_queue.rowconfigure(1, weight=1)

        top_q = ttk.Frame(self.f_queue)
        top_q.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top_q.columnconfigure(0, weight=1)
        ttk.Label(top_q, textvariable=self.v_worker_badge, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.b_q_refresh = ttk.Button(top_q, command=self._refresh_queue_and_status)
        self.b_q_refresh.grid(row=0, column=1, sticky="e")

        tree_wrap = ttk.Frame(self.f_queue)
        tree_wrap.grid(row=1, column=0, sticky="nsew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        self.q_tree = ttk.Treeview(
            tree_wrap,
            columns=("id", "status", "book", "voice", "format", "error"),
            show="headings",
            selectmode="browse",
        )
        self.q_tree.column("id", width=44, anchor="e", stretch=False)
        self.q_tree.column("status", width=86, anchor="center", stretch=False)
        self.q_tree.column("book", width=220, anchor="w", stretch=True)
        self.q_tree.column("voice", width=155, anchor="w", stretch=False)
        self.q_tree.column("format", width=98, anchor="center", stretch=False)
        self.q_tree.column("error", width=160, anchor="w", stretch=True)

        q_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.q_tree.yview)
        self.q_tree.configure(yscrollcommand=q_scroll.set)
        self.q_tree.grid(row=0, column=0, sticky="nsew")
        q_scroll.grid(row=0, column=1, sticky="ns")

        q_btns = ttk.Frame(self.f_queue)
        q_btns.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.b_q_add_files = ttk.Button(q_btns, command=self._queue_add_files)
        self.b_q_add_files.pack(side="left")
        self.b_q_add_folder = ttk.Button(q_btns, command=self._queue_add_folder)
        self.b_q_add_folder.pack(side="left", padx=(6, 0))
        self.b_q_run = ttk.Button(q_btns, command=self._queue_run_background)
        self.b_q_run.pack(side="left", padx=(12, 0))
        self.b_q_retry = ttk.Button(q_btns, command=self._queue_retry)
        self.b_q_retry.pack(side="left", padx=(6, 0))
        self.b_q_remove = ttk.Button(q_btns, command=self._queue_remove)
        self.b_q_remove.pack(side="right")
        self.b_q_clear = ttk.Button(q_btns, command=self._queue_clear_done)
        self.b_q_clear.pack(side="right", padx=(0, 6))

    def _build_tools_tab(self) -> None:
        f = self.tab_tools
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        # MOBI -> EPUB
        self.f_mobi = ttk.LabelFrame(f, padding=10)
        self.f_mobi.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.f_mobi.columnconfigure(1, weight=1)

        self.l_mobi_src = ttk.Label(self.f_mobi)
        self.l_mobi_src.grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(self.f_mobi, textvariable=self.v_mobi_src).grid(
            row=0, column=1, sticky="ew", padx=6, pady=3
        )
        ttk.Button(self.f_mobi, text="…", width=3, command=self._browse_mobi_src).grid(
            row=0, column=2, pady=3
        )

        self.l_mobi_dst = ttk.Label(self.f_mobi)
        self.l_mobi_dst.grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(self.f_mobi, textvariable=self.v_mobi_dst).grid(
            row=1, column=1, sticky="ew", padx=6, pady=3
        )
        ttk.Button(self.f_mobi, text="…", width=3, command=self._browse_mobi_dst).grid(
            row=1, column=2, pady=3
        )

        m_row = ttk.Frame(self.f_mobi)
        m_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.b_mobi_convert = ttk.Button(m_row, command=self._run_mobi2epub)
        self.b_mobi_convert.pack(side="left")
        self.l_mobi_dst_hint = ttk.Label(m_row, style="Hint.TLabel")
        self.l_mobi_dst_hint.pack(side="left", padx=10)
        self.l_mobi_status = ttk.Label(self.f_mobi, textvariable=self.v_mobi_status)
        self.l_mobi_status.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # Doctor
        self.f_doctor = ttk.LabelFrame(f, padding=10)
        self.f_doctor.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.f_doctor.columnconfigure(0, weight=1)
        self.f_doctor.rowconfigure(0, weight=1)

        self.doc_tree = ttk.Treeview(
            self.f_doctor,
            columns=("status", "tool", "detail", "hint"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        self.doc_tree.column("status", width=95, anchor="center", stretch=False)
        self.doc_tree.column("tool", width=90, anchor="w", stretch=False)
        self.doc_tree.column("detail", width=290, anchor="w", stretch=True)
        self.doc_tree.column("hint", width=220, anchor="w", stretch=True)
        self.doc_tree.grid(row=0, column=0, sticky="nsew")

        d_btns = ttk.Frame(self.f_doctor)
        d_btns.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.b_recheck = ttk.Button(d_btns, command=self._run_doctor_check)
        self.b_recheck.pack(side="left")
        self.b_copy_hint = ttk.Button(d_btns, command=self._copy_doctor_hint)
        self.b_copy_hint.pack(side="left", padx=6)

        # Windows desktop shortcut
        self.f_shortcut = ttk.LabelFrame(f, padding=10)
        self.f_shortcut.grid(row=2, column=0, sticky="ew")
        self.f_shortcut.columnconfigure(0, weight=1)
        self.l_shortcut_desc = ttk.Label(self.f_shortcut, wraplength=700)
        self.l_shortcut_desc.grid(row=0, column=0, sticky="w", pady=(0, 6))
        s_row = ttk.Frame(self.f_shortcut)
        s_row.grid(row=1, column=0, sticky="ew")
        self.b_shortcut = ttk.Button(s_row, command=self._create_shortcut)
        self.b_shortcut.pack(side="left")
        ttk.Label(s_row, textvariable=self.v_shortcut_status, foreground=_GREEN).pack(
            side="left", padx=10
        )

    # ------------------------------------------------------------------
    # Language switching
    # ------------------------------------------------------------------
    def _on_language_change(self, _event: tk.Event[Any] | None = None) -> None:
        chosen_label = self.v_lang_label.get()
        for code, label in LANGUAGE_LABELS.items():
            if label == chosen_label:
                self._lang = code
                self._cfg["language"] = code
                save_gui_config(self._cfg)
                break
        self._apply_language()
        self._refresh_queue_and_status()

    def _apply_language(self) -> None:
        self.title(self._t("app_title"))
        self.l_lang.configure(text=self._t("lang_label"))
        self.notebook.tab(self.tab_convert, text=self._t("tab_convert"))
        self.notebook.tab(self.tab_queue, text=self._t("tab_queue"))
        self.notebook.tab(self.tab_tools, text=self._t("tab_tools"))

        # Convert tab
        self.l_book.configure(text=self._t("book_label"))
        self.b_browse_book.configure(text=self._t("btn_browse_file"))
        self.b_inspect.configure(text=self._t("btn_inspect"))
        self.l_book_hint.configure(text=self._t("book_hint"))
        self._render_book_meta()

        self.l_format.configure(text=self._t("format_label"))
        self.rb_mp3_m4b.configure(text=self._t("fmt_mp3_m4b"))
        self.rb_mp3_only.configure(text=self._t("fmt_mp3_only"))
        self.rb_m4b_only.configure(text=self._t("fmt_m4b_only"))
        self.l_voice.configure(text=self._t("voice_label"))
        self.b_load_voices.configure(text=self._t("btn_load_voices"))
        self.b_sample.configure(text=self._t("btn_sample"))
        self.l_output.configure(text=self._t("output_label"))
        self.l_output_hint.configure(text=self._t("output_hint"))
        self.l_chapters.configure(text=self._t("chapters_label"))
        self.b_pick_chapters.configure(text=self._t("btn_pick_chapters"))
        self.l_chapters_hint.configure(text=self._t("chapters_hint"))
        self.l_audio.configure(text=self._t("audio_label"))
        self.l_rate.configure(text=self._t("rate_label"))
        self.l_bitrate.configure(text=self._t("bitrate_label"))
        self.chk_normalize.configure(text=self._t("chk_normalize"))

        more_open = self.f_more.winfo_ismapped()
        self.b_more.configure(text=self._t("btn_more_open" if more_open else "btn_more_closed"))
        self.f_more.configure(text=self._t("more_frame"))
        self.l_cover.configure(text=self._t("cover_label"))
        self.b_clear_cover.configure(text=self._t("btn_clear"))
        self.l_parallel.configure(text=self._t("parallel_label"))
        self.l_chunk.configure(text=self._t("chunk_label"))
        self.l_heading.configure(text=self._t("heading_label"))
        self.chk_disable_heading.configure(text=self._t("chk_disable_heading"))
        self.chk_keep_work.configure(text=self._t("chk_keep_work"))
        self.chk_open_after.configure(text=self._t("chk_open_after"))

        self._update_start_button_label()
        self.b_add_queue.configure(text=self._t("btn_add_queue"))
        self.b_stop.configure(text=self._t("btn_stop"))
        self.b_defaults.configure(text=self._t("btn_defaults"))
        self.b_open_m4b.configure(text=self._t("btn_open_m4b"))
        self.b_show_folder.configure(text=self._t("btn_show_folder"))
        self.b_open_samples.configure(text=self._t("btn_open_samples"))
        log_open = self.t_log.winfo_ismapped()
        self.b_log.configure(text=self._t("btn_log_open" if log_open else "btn_log_closed"))
        if not self.v_status.get():
            self.v_status.set(self._t("status_ready"))

        # Queue tab
        self.f_live.configure(text=self._t("live_frame"))
        self.b_live_folder.configure(text=self._t("btn_show_folder"))
        self.f_queue.configure(text=self._t("queue_frame"))
        self.b_q_refresh.configure(text=self._t("q_btn_refresh"))
        self.q_tree.heading("id", text=self._t("q_col_id"))
        self.q_tree.heading("status", text=self._t("q_col_status"))
        self.q_tree.heading("book", text=self._t("q_col_book"))
        self.q_tree.heading("voice", text=self._t("q_col_voice"))
        self.q_tree.heading("format", text=self._t("q_col_format"))
        self.q_tree.heading("error", text=self._t("q_col_error"))
        self.b_q_add_files.configure(text=self._t("q_btn_add_files"))
        self.b_q_add_folder.configure(text=self._t("q_btn_add_folder"))
        self.b_q_run.configure(text=self._t("q_btn_run_bg"))
        self.b_q_retry.configure(text=self._t("q_btn_retry"))
        self.b_q_remove.configure(text=self._t("q_btn_remove"))
        self.b_q_clear.configure(text=self._t("q_btn_clear_done"))

        # Tools tab
        self.f_mobi.configure(text=self._t("mobi_frame"))
        self.l_mobi_src.configure(text=self._t("mobi_src_label"))
        self.l_mobi_dst.configure(text=self._t("mobi_dst_label"))
        self.l_mobi_dst_hint.configure(text=self._t("mobi_dst_hint"))
        self.b_mobi_convert.configure(text=self._t("btn_mobi_convert"))
        self.f_doctor.configure(text=self._t("doctor_frame"))
        self.doc_tree.heading("status", text=self._t("doc_col_status"))
        self.doc_tree.heading("tool", text=self._t("doc_col_tool"))
        self.doc_tree.heading("detail", text=self._t("doc_col_detail"))
        self.doc_tree.heading("hint", text=self._t("doc_col_hint"))
        self.b_recheck.configure(text=self._t("btn_recheck"))
        self.b_copy_hint.configure(text=self._t("btn_copy_hint"))
        self.f_shortcut.configure(text=self._t("shortcut_frame"))
        self.l_shortcut_desc.configure(text=self._t("shortcut_desc"))
        self.b_shortcut.configure(text=self._t("btn_shortcut"))

    # ------------------------------------------------------------------
    # Field behaviors
    # ------------------------------------------------------------------
    def _update_start_button_label(self) -> None:
        if self._is_busy():
            self.b_start.configure(text=self._t("btn_working"))
        elif self.v_format.get() == "m4b_only":
            self.b_start.configure(text=self._t("btn_build_m4b"))
        else:
            self.b_start.configure(text=self._t("btn_convert"))

    def _on_format_change(self) -> None:
        is_m4b_only = self.v_format.get() == "m4b_only"
        voice_state = "disabled" if is_m4b_only else "normal"
        self.cb_voice.configure(state=voice_state)
        self.cb_rate.configure(state=voice_state)
        self.chk_normalize.configure(state=voice_state)
        self._update_start_button_label()

    def _on_disable_heading_toggle(self) -> None:
        self.e_heading.configure(state="disabled" if self.v_disable_heading.get() else "normal")

    def _toggle_more(self) -> None:
        if self.f_more.winfo_ismapped():
            self.f_more.grid_remove()
            self.b_more.configure(text=self._t("btn_more_closed"))
        else:
            self.f_more.grid()
            self.b_more.configure(text=self._t("btn_more_open"))

    def _toggle_log(self, show: bool | None = None) -> None:
        visible = self.t_log.winfo_ismapped()
        target = (not visible) if show is None else show
        if target:
            self.t_log.grid()
            self.b_log.configure(text=self._t("btn_log_open"))
        else:
            self.t_log.grid_remove()
            self.b_log.configure(text=self._t("btn_log_closed"))

    def _restore_defaults(self) -> None:
        self.v_format.set("mp3_m4b")
        self.v_output.set("")
        self.v_only.set("")
        self.v_rate.set("+0%")
        self.v_bitrate.set("64k")
        self.v_normalize.set(True)
        self.v_cover.set("")
        self.v_parallel.set("3")
        self.v_chunk_chars.set("2500")
        self.v_heading_pattern.set("")
        self.v_disable_heading.set(False)
        self.v_keep_work.set(False)
        self.v_open_after.set(False)
        if self._book is not None:
            self.v_voice.set(tts.default_voice(self._book.language))
        else:
            self.v_voice.set("")
        self._on_format_change()
        self._on_disable_heading_toggle()
        self.l_status.configure(foreground="")
        self.v_status.set(self._t("status_defaults"))

    def _browse_book(self) -> None:
        initial = self._cfg.get("last_book_dir") or str(Path.home())
        path = filedialog.askopenfilename(
            parent=self,
            title=self._t("dlg_ebook_title"),
            initialdir=initial,
            filetypes=[
                (self._t("dlg_ebook_filter"), "*.epub *.mobi *.azw *.azw3 *.prc"),
                (self._t("dlg_all_filter"), "*.*"),
            ],
        )
        if path:
            p = Path(path)
            self.v_book.set(str(p))
            self._cfg["last_book_dir"] = str(p.parent)
            save_gui_config(self._cfg)
            self._inspect_book()

    def _browse_output(self) -> None:
        initial = self.v_output.get() or self._cfg.get("last_output_dir") or str(Path.home())
        folder = filedialog.askdirectory(
            parent=self, title=self._t("dlg_folder_title"), initialdir=initial
        )
        if folder:
            self.v_output.set(str(Path(folder)))
            self._cfg["last_output_dir"] = str(Path(folder))
            save_gui_config(self._cfg)

    def _browse_cover(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title=self._t("dlg_cover_title"),
            filetypes=[
                (self._t("dlg_cover_filter"), "*.jpg *.jpeg *.png"),
                (self._t("dlg_all_filter"), "*.*"),
            ],
        )
        if path:
            self.v_cover.set(str(Path(path)))

    def _heading_regex(self) -> re.Pattern[str] | None:
        if self.v_disable_heading.get():
            return None
        raw = self.v_heading_pattern.get().strip()
        if not raw:
            return DEFAULT_HEADING_PATTERN
        pat = re.compile(raw, re.IGNORECASE)
        if pat.groups < 2:
            raise ValueError("Heading regex needs two groups: (label)(subtitle)")
        return pat

    def _render_book_meta(self) -> None:
        if self._book is None:
            self.v_meta.set(self._t("meta_empty"))
            return
        book = self._book
        total_chars = sum(c.char_count for c in book.chapters)
        cover_txt = self._t("cover_yes") if book.cover else self._t("cover_no")
        self.v_meta.set(
            self._t(
                "meta_summary",
                author=book.author,
                title=book.title,
                lang=book.language,
                voice=tts.default_voice(book.language),
                cover=cover_txt,
                chapters=len(book.chapters),
                chars=total_chars,
                duration=estimate_duration_text(total_chars),
            )
        )

    # ------------------------------------------------------------------
    # Inspect book & chapter picker
    # ------------------------------------------------------------------
    def _inspect_book(self) -> None:
        raw = self.v_book.get().strip().strip('"')
        if not raw:
            messagebox.showwarning(self._t("warn_title"), self._t("err_no_book"), parent=self)
            return
        path = Path(raw)
        if not path.is_file():
            messagebox.showwarning(self._t("warn_title"), self._t("err_book_missing"), parent=self)
            return
        try:
            pattern = self._heading_regex()
        except (re.error, ValueError) as exc:
            messagebox.showerror(self._t("err_title"), str(exc), parent=self)
            return

        self.v_meta.set(self._t("meta_loading"))
        self.v_status.set(self._t("status_inspecting"))
        self._set_indeterminate(True)

        def work() -> None:
            try:
                book = parse_epub(path, pattern)
                self._events.put(("inspected", book))
            except Exception as exc:
                self._events.put(("inspect_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _open_chapter_picker(self) -> None:
        if self._book is None:
            messagebox.showinfo(
                self._t("warn_title"), self._t("err_no_chapters_loaded"), parent=self
            )
            return
        current: set[int] | None = None
        spec = self.v_only.get().strip()
        if spec:
            try:
                current = parse_selection(spec)
            except ValueError:
                current = None
        dlg = ChapterPickerDialog(self, self._book, current, self._lang)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.v_only.set(dlg.result)

    # ------------------------------------------------------------------
    # Voices & sampling
    # ------------------------------------------------------------------
    def _load_voices(self) -> None:
        locale_prefix: str | None = None
        if self._book is not None:
            locale_prefix = self._book.language.split("-")[0]

        self.b_load_voices.configure(state="disabled")

        def work() -> None:
            try:
                voices = asyncio.run(tts.list_voices(locale_prefix))
                if not voices and locale_prefix:
                    voices = asyncio.run(tts.list_voices(None))
                self._events.put(("voices_loaded", voices))
            except Exception as exc:
                self._events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _sample_voices(self) -> None:
        if self._is_busy():
            return
        raw = self.v_book.get().strip().strip('"')
        if not raw or not Path(raw).is_file():
            messagebox.showwarning(self._t("warn_title"), self._t("err_no_book"), parent=self)
            return
        try:
            pattern = self._heading_regex()
        except (re.error, ValueError) as exc:
            messagebox.showerror(self._t("err_title"), str(exc), parent=self)
            return

        book_path = Path(raw)
        rate = self.v_rate.get().strip() or "+0%"
        chosen_voice = self.v_voice.get().strip()
        samples_dir = (
            Path(self.v_output.get().strip()) / "voice-samples"
            if self.v_output.get().strip()
            else book_path.parent / "voice-samples"
        )

        self._begin_task(indeterminate=True, status=self._t("status_sampling"))

        def work() -> None:
            handler = self._attach_log_handler()
            try:
                book = self._book or parse_epub(book_path, pattern)
                long_ones = [c for c in book.chapters if c.char_count >= 5 * 900]
                chapter = (
                    long_ones[0] if long_ones else max(book.chapters, key=lambda c: c.char_count)
                )
                text = cli._excerpt(chapter, 900)

                async def run() -> int:
                    lang_prefix = book.language.split("-")[0]
                    voices = [v["ShortName"] for v in await tts.list_voices(lang_prefix)]
                    if chosen_voice and chosen_voice not in voices:
                        voices.insert(0, chosen_voice)
                    voices = voices or [tts.default_voice(book.language)]
                    samples_dir.mkdir(parents=True, exist_ok=True)
                    (samples_dir / "excerpt.txt").write_text(text + "\n", encoding="utf-8")
                    saved = 0
                    for idx, voice_name in enumerate(voices, 1):
                        if self._stop_event.is_set():
                            raise asyncio.CancelledError
                        dst = samples_dir / f"{idx:02d}_{safe_filename(voice_name)}.mp3"
                        try:
                            await tts.synthesize(text, dst, voice=voice_name, rate=rate, attempts=3)
                            saved += 1
                            self._events.put(("log", f"  {voice_name} -> {dst.name}"))
                        except (tts.TTSError, ValueError) as exc:
                            self._events.put(("log", f"  {voice_name} failed: {exc}"))
                    return saved

                count = self._run_cancellable(run())
                self._events.put(("samples_done", (count, samples_dir)))
            except asyncio.CancelledError:
                self._events.put(("stopped", None))
            except Exception as exc:
                self._events.put(("error", f"{exc}\n\n{traceback.format_exc()}"))
            finally:
                self._detach_log_handler(handler)

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------
    # Conversion execution
    # ------------------------------------------------------------------
    def _collect_convert_params(self) -> dict[str, Any]:
        raw = self.v_book.get().strip().strip('"')
        if not raw:
            raise ValueError(self._t("err_no_book"))
        book_path = Path(raw)
        if not book_path.is_file():
            raise ValueError(self._t("err_book_missing"))

        only_raw = self.v_only.get().strip()
        only = parse_selection(only_raw) if only_raw else None

        cover_raw = self.v_cover.get().strip().strip('"')
        cover_path = Path(cover_raw) if cover_raw else None
        if cover_path is not None:
            if not cover_path.is_file():
                raise ValueError(f"Cover file not found: {cover_path}")
            if cover_path.suffix.lower() not in _IMAGE_TYPES:
                raise ValueError("Cover must be a .jpg, .jpeg or .png file")

        parallel = int(self.v_parallel.get().strip() or "3")
        chunk_chars = int(self.v_chunk_chars.get().strip() or "2500")
        if parallel <= 0 or chunk_chars <= 0:
            raise ValueError("Parallel and chunk size must be positive integers")

        pattern = self._heading_regex()
        out_raw = self.v_output.get().strip().strip('"')
        out_dir = Path(out_raw) if out_raw else None

        return {
            "book_path": book_path,
            "mode": self.v_format.get(),
            "voice": self.v_voice.get().strip() or None,
            "output": out_dir,
            "only": only,
            "only_raw": only_raw or None,
            "rate": self.v_rate.get().strip() or "+0%",
            "bitrate": self.v_bitrate.get().strip() or "64k",
            "normalize": self.v_normalize.get(),
            "cover": cover_path,
            "parallel": parallel,
            "chunk_chars": chunk_chars,
            "heading_pattern": pattern,
            "heading_raw": (
                ""
                if self.v_disable_heading.get()
                else (self.v_heading_pattern.get().strip() or None)
            ),
            "keep_work": self.v_keep_work.get(),
        }

    def _start_convert(self) -> None:
        if self._is_busy():
            return
        try:
            params = self._collect_convert_params()
        except (ValueError, re.error) as exc:
            messagebox.showwarning(self._t("warn_title"), str(exc), parent=self)
            return

        self._begin_task(
            indeterminate=(params["mode"] == "m4b_only"),
            status=self._t("status_starting"),
        )

        def work() -> None:
            handler = self._attach_log_handler()
            tracker: progress.ProgressTracker | None = None
            try:
                audio.require_ffmpeg()
                book = parse_epub(params["book_path"], params["heading_pattern"])
                if params["cover"] is not None:
                    cov_path: Path = params["cover"]
                    mime = _IMAGE_TYPES[cov_path.suffix.lower()]
                    book = dataclasses.replace(book, cover=Cover(cov_path.read_bytes(), mime))

                chapters = book.select(params["only"])
                out_dir: Path = params["output"] or (
                    params["book_path"].parent / pipeline.default_output_dir(book)
                )

                if params["mode"] == "m4b_only":
                    self._events.put(("status", self._t("status_packaging")))
                    m4b_path = pipeline.build_audiobook(
                        book,
                        chapters,
                        out_dir,
                        bitrate=params["bitrate"],
                        keep_work=params["keep_work"],
                    )
                    self._events.put(("convert_done", (m4b_path, out_dir)))
                    return

                voice_name = params["voice"] or tts.default_voice(book.language)
                opts = pipeline.ConvertOptions(
                    voice=voice_name,
                    rate=params["rate"],
                    bitrate=params["bitrate"],
                    chunk_chars=params["chunk_chars"],
                    parallel=params["parallel"],
                    normalize=params["normalize"],
                    keep_work=params["keep_work"],
                )
                tracker = progress.ProgressTracker(
                    book_title=book.title,
                    book_author=book.author,
                    output_dir=out_dir.resolve(),
                    voice=opts.voice,
                    chapter_total=len(chapters),
                    chars_total=sum(c.char_count + len(c.spoken_title) for c in chapters),
                    quiet=True,
                )
                self._active_tracker = tracker

                async def run_tts() -> None:
                    await cli._check_voice(opts.voice)
                    await pipeline.render_chapters(book, chapters, out_dir, opts, tracker=tracker)

                self._run_cancellable(run_tts())

                m4b_path: Path | None = None
                if params["mode"] == "mp3_m4b":
                    tracker.set_packaging()
                    self._events.put(("packaging", None))
                    m4b_path = pipeline.build_audiobook(
                        book,
                        chapters,
                        out_dir,
                        bitrate=params["bitrate"],
                        keep_work=params["keep_work"],
                    )
                tracker.finish()
                self._events.put(("convert_done", (m4b_path, out_dir)))
            except asyncio.CancelledError:
                if tracker is not None:
                    tracker.finish(failed=True)
                self._events.put(("stopped", None))
            except Exception as exc:
                if tracker is not None:
                    tracker.finish(failed=True)
                self._events.put(("error", f"{exc}\n\n{traceback.format_exc()}"))
            finally:
                self._active_tracker = None
                self._detach_log_handler(handler)

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _run_cancellable(self, coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        task = loop.create_task(coro)
        self._async_task = task
        try:
            return loop.run_until_complete(task)
        finally:
            self._async_task = None
            self._loop = None
            loop.close()

    def _stop_current(self) -> None:
        if not self._is_busy():
            return
        self._stop_event.set()
        self.v_status.set(self._t("status_stopping"))
        self.b_stop.configure(state="disabled")
        loop, task = self._loop, self._async_task
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)

    def _begin_task(self, *, indeterminate: bool, status: str) -> None:
        self._stop_event.clear()
        self._result_m4b = None
        self._result_dir = None
        self._samples_dir = None
        self.f_result.grid_remove()
        self.t_log.configure(state="normal")
        self.t_log.delete("1.0", tk.END)
        self.t_log.configure(state="disabled")
        self.l_status.configure(foreground="")
        self.v_status.set(status)
        self.b_start.configure(state="disabled", text=self._t("btn_working"))
        self.b_sample.configure(state="disabled")
        self.b_stop.configure(state="normal")
        self._set_indeterminate(indeterminate)

    def _end_task(self) -> None:
        self._set_indeterminate(False)
        self.b_start.configure(state="normal")
        self._update_start_button_label()
        self.b_sample.configure(state="normal")
        self.b_stop.configure(state="disabled")

    def _set_indeterminate(self, active: bool) -> None:
        if active:
            self.pbar.configure(mode="indeterminate")
            self.pbar.start(12)
        else:
            self.pbar.stop()
            self.pbar.configure(mode="determinate")

    def _attach_log_handler(self) -> _QueueLogHandler:
        handler = _QueueLogHandler(self._events)
        logger = logging.getLogger("bookvoice")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        return handler

    def _detach_log_handler(self, handler: _QueueLogHandler) -> None:
        logging.getLogger("bookvoice").removeHandler(handler)

    def _append_log(self, line: str) -> None:
        self.t_log.configure(state="normal")
        self.t_log.insert(tk.END, line + "\n")
        self.t_log.see(tk.END)
        self.t_log.configure(state="disabled")

    # ------------------------------------------------------------------
    # Event loop polling
    # ------------------------------------------------------------------
    def _poll_events(self) -> None:
        try:
            for _ in range(200):
                kind, payload = self._events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "status":
                    self.v_status.set(str(payload))
                elif kind == "inspected":
                    self._set_indeterminate(False)
                    self._book = payload
                    self._render_book_meta()
                    if not self.v_voice.get().strip():
                        self.v_voice.set(tts.default_voice(payload.language))
                    self.l_status.configure(foreground="")
                    self.v_status.set(self._t("status_ready"))
                elif kind == "inspect_error":
                    self._set_indeterminate(False)
                    self._book = None
                    self._render_book_meta()
                    self.l_status.configure(foreground=_RED)
                    self.v_status.set(f"❌ {payload}")
                    messagebox.showerror(self._t("err_title"), str(payload), parent=self)
                elif kind == "voices_loaded":
                    self._voices_cache = payload
                    names = [v["ShortName"] for v in payload]
                    self.cb_voice.configure(values=names)
                    self.b_load_voices.configure(state="normal")
                    self.v_status.set(self._t("status_voices_loaded", count=len(names)))
                elif kind == "packaging":
                    self._set_indeterminate(True)
                    self.v_status.set(self._t("status_packaging"))
                elif kind == "convert_done":
                    m4b_path, out_dir = payload
                    self._end_task()
                    self.pbar.configure(value=100.0)
                    self._result_m4b = m4b_path
                    self._result_dir = out_dir
                    name = m4b_path.name if m4b_path else out_dir.name
                    self.l_status.configure(foreground=_GREEN)
                    self.v_status.set(self._t("status_done", name=name, folder=str(out_dir)))
                    self._show_result_buttons(has_m4b=bool(m4b_path), has_samples=False)
                    self.bell()
                    if self.v_open_after.get():
                        _show_in_folder(m4b_path or out_dir)
                    self._refresh_queue_and_status()
                elif kind == "samples_done":
                    count, samples_dir = payload
                    self._end_task()
                    self.pbar.configure(value=100.0)
                    self._samples_dir = samples_dir
                    self.l_status.configure(foreground=_GREEN)
                    self.v_status.set(
                        self._t("status_samples_done", count=count, folder=str(samples_dir))
                    )
                    self._show_result_buttons(has_m4b=False, has_samples=True)
                    self.bell()
                elif kind == "stopped":
                    self._end_task()
                    self.l_status.configure(foreground=_ORANGE)
                    self.v_status.set(self._t("status_stopped"))
                    self._refresh_queue_and_status()
                elif kind == "error":
                    self._end_task()
                    self.b_load_voices.configure(state="normal")
                    msg = str(payload)
                    first_line = msg.splitlines()[0] if msg else "Error"
                    self.l_status.configure(foreground=_RED)
                    self.v_status.set(f"❌ {first_line}")
                    self._append_log(msg)
                    self._toggle_log(True)
                    messagebox.showerror(self._t("err_title"), msg[:1500], parent=self)
                elif kind == "mobi_done":
                    dst = Path(payload)
                    self.b_mobi_convert.configure(state="normal")
                    self.l_mobi_status.configure(foreground=_GREEN)
                    self.v_mobi_status.set(self._t("mobi_done", path=str(dst)))
                    self.bell()
                elif kind == "mobi_error":
                    self.b_mobi_convert.configure(state="normal")
                    self.l_mobi_status.configure(foreground=_RED)
                    self.v_mobi_status.set(f"❌ {payload}")
                    messagebox.showerror(self._t("err_title"), str(payload), parent=self)
        except thread_queue.Empty:
            pass

        # Live progress update for active in-app conversion
        tracker = self._active_tracker
        if tracker is not None and tracker.state.state == "running":
            st = tracker.state
            pct = st.fraction * 100.0
            self.pbar.configure(value=pct)
            elapsed = progress.format_duration(max(0.0, time.time() - st.started_at))
            eta = (
                progress.format_duration(st.eta_seconds)
                if st.eta_seconds is not None
                else "…"
            )
            self.v_status.set(
                self._t(
                    "progress_line",
                    pct=pct,
                    ch=st.chapter_index,
                    ch_total=st.chapter_total,
                    ch_title=st.chapter_title or "…",
                    chunk=st.chunk_done,
                    chunk_total=st.chunk_total,
                    elapsed=elapsed,
                    eta=eta,
                )
            )

        self.after(100, self._poll_events)

    def _show_result_buttons(self, *, has_m4b: bool, has_samples: bool) -> None:
        self.b_open_m4b.pack_forget()
        self.b_show_folder.pack_forget()
        self.b_open_samples.pack_forget()
        if has_m4b:
            self.b_open_m4b.pack(side="left", padx=(0, 6))
        if self._result_dir is not None:
            self.b_show_folder.pack(side="left", padx=(0, 6))
        if has_samples:
            self.b_open_samples.pack(side="left")
        self.f_result.grid()

    def _open_result_m4b(self) -> None:
        if self._result_m4b:
            _open_path(self._result_m4b)

    def _open_result_folder(self) -> None:
        if self._result_m4b and self._result_m4b.exists():
            _show_in_folder(self._result_m4b)
        elif self._result_dir:
            _show_in_folder(self._result_dir)

    def _open_samples_folder(self) -> None:
        if self._samples_dir:
            _open_path(self._samples_dir)

    # ------------------------------------------------------------------
    # Queue & Live Status tab
    # ------------------------------------------------------------------
    def _on_tab_changed(self, _event: tk.Event[Any] | None = None) -> None:
        if self.notebook.select() == str(self.tab_queue):
            self._refresh_queue_and_status()

    def _periodic_status_refresh(self) -> None:
        if self.notebook.select() == str(self.tab_queue):
            self._refresh_queue_and_status()
        self.after(2000, self._periodic_status_refresh)

    def _refresh_queue_and_status(self) -> None:
        # Live status.json
        st = progress.read_status()
        if st is None:
            self.v_live_book.set(self._t("live_none"))
            self.v_live_meta.set("")
            self.v_live_progress.set("")
            self.pbar_live.configure(value=0.0)
            self._last_live_dir = None
            self.b_live_folder.configure(state="disabled")
        else:
            alive = queue._pid_alive(st.pid)
            active = st.state in ("running", "packaging") and alive
            label = st.state
            if st.state in ("running", "packaging") and not alive:
                label = "stopped"
            pct = st.fraction * 100.0
            end_time = time.time() if active else (st.updated_at or time.time())
            elapsed = progress.format_duration(max(0.0, end_time - st.started_at))
            eta = (
                progress.format_duration(st.eta_seconds)
                if st.eta_seconds is not None and st.state == "running" and alive
                else "-"
            )
            self.v_live_book.set(self._t("live_book", author=st.book_author, title=st.book_title))
            self.v_live_meta.set(self._t("live_meta", state=label, voice=st.voice, pid=st.pid))
            self.v_live_progress.set(
                self._t(
                    "live_progress",
                    pct=pct,
                    ch=st.chapter_index,
                    ch_total=st.chapter_total,
                    ch_title=st.chapter_title or "-",
                    chunk=st.chunk_done,
                    chunk_total=st.chunk_total,
                    elapsed=elapsed,
                    eta=eta,
                )
            )
            self.pbar_live.configure(value=pct)
            out = Path(st.output_dir)
            self._last_live_dir = out if out.exists() else None
            self.b_live_folder.configure(state="normal" if self._last_live_dir else "disabled")

        # Persistent queue
        worker = self._queue_obj.worker_pid()
        self.v_worker_badge.set(
            self._t("worker_running", pid=worker) if worker else self._t("worker_idle")
        )
        selected = self.q_tree.selection()
        for iid in self.q_tree.get_children():
            self.q_tree.delete(iid)
        for item in self._queue_obj.items():
            fmt = "MP3" if item.no_m4b else "MP3+M4B"
            self.q_tree.insert(
                "",
                "end",
                iid=str(item.id),
                values=(
                    item.id,
                    item.status,
                    Path(item.source).name,
                    item.voice or "auto",
                    fmt,
                    item.error or "",
                ),
            )
        if selected and selected[0] in self.q_tree.get_children():
            self.q_tree.selection_set(selected[0])

    def _open_live_folder(self) -> None:
        if self._last_live_dir:
            _open_path(self._last_live_dir)

    def _add_current_to_queue(self) -> None:
        try:
            params = self._collect_convert_params()
        except (ValueError, re.error) as exc:
            messagebox.showwarning(self._t("warn_title"), str(exc), parent=self)
            return
        try:
            item = self._queue_obj.add(
                params["book_path"],
                output=str(params["output"].resolve()) if params["output"] else None,
                voice=params["voice"],
                rate=params["rate"],
                bitrate=params["bitrate"],
                only=params["only_raw"],
                chunk_chars=params["chunk_chars"],
                parallel=params["parallel"],
                no_normalize=not params["normalize"],
                no_m4b=params["mode"] == "mp3_only",
                cover=str(params["cover"].resolve()) if params["cover"] else None,
                keep_work=params["keep_work"],
                heading_pattern=params["heading_raw"],
            )
        except queue.QueueError as exc:
            messagebox.showerror(self._t("err_title"), str(exc), parent=self)
            return
        self.l_status.configure(foreground=_GREEN)
        self.v_status.set(self._t("status_queued", id=item.id, name=Path(item.source).name))
        self._refresh_queue_and_status()

    def _queue_add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title=self._t("dlg_ebook_title"),
            initialdir=self._cfg.get("last_book_dir") or str(Path.home()),
            filetypes=[
                (self._t("dlg_ebook_filter"), "*.epub *.mobi *.azw *.azw3 *.prc"),
                (self._t("dlg_all_filter"), "*.*"),
            ],
        )
        if not paths:
            return
        for p in paths:
            try:
                self._queue_obj.add(Path(p))
            except queue.QueueError as exc:
                messagebox.showerror(self._t("err_title"), str(exc), parent=self)
        self._refresh_queue_and_status()

    def _queue_add_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self,
            title=self._t("dlg_folder_title"),
            initialdir=self._cfg.get("last_book_dir") or str(Path.home()),
        )
        if not folder:
            return
        try:
            self._queue_obj.add(Path(folder))
        except queue.QueueError as exc:
            messagebox.showerror(self._t("err_title"), str(exc), parent=self)
        self._refresh_queue_and_status()

    def _queue_run_background(self) -> None:
        active = self._queue_obj.worker_pid()
        if active is not None:
            messagebox.showinfo(
                self._t("warn_title"), self._t("q_already_running", pid=active), parent=self
            )
            return
        self._queue_obj.recover_stale()
        if self._queue_obj.next_pending() is None:
            messagebox.showinfo(self._t("warn_title"), self._t("q_empty"), parent=self)
            return
        try:
            audio.require_ffmpeg()
            pid, log_path = cli._spawn_background(
                ["queue", "--queue", str(self._queue_obj.path), "run"],
                self._queue_obj.path.parent,
                "queue.log",
            )
        except Exception as exc:
            messagebox.showerror(self._t("err_title"), str(exc), parent=self)
            return
        messagebox.showinfo(
            self._t("warn_title"),
            self._t("q_started_bg", pid=pid, log=str(log_path)),
            parent=self,
        )
        self.after(600, self._refresh_queue_and_status)

    def _queue_retry(self) -> None:
        self._queue_obj.recover_stale()
        self._queue_obj.retry_failed()
        self._refresh_queue_and_status()

    def _queue_remove(self) -> None:
        sel = self.q_tree.selection()
        if not sel:
            messagebox.showinfo(self._t("warn_title"), self._t("err_no_selection"), parent=self)
            return
        try:
            self._queue_obj.remove(int(sel[0]))
        except queue.QueueError as exc:
            messagebox.showerror(self._t("err_title"), str(exc), parent=self)
        self._refresh_queue_and_status()

    def _queue_clear_done(self) -> None:
        self._queue_obj.clear(all_items=False)
        self._refresh_queue_and_status()

    # ------------------------------------------------------------------
    # Tools & Doctor tab
    # ------------------------------------------------------------------
    def _browse_mobi_src(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title=self._t("dlg_mobi_title"),
            filetypes=[("Kindle", "*.mobi *.azw *.azw3 *.prc"), (self._t("dlg_all_filter"), "*.*")],
        )
        if path:
            self.v_mobi_src.set(str(Path(path)))

    def _browse_mobi_dst(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title=self._t("dlg_epub_save_title"),
            defaultextension=".epub",
            filetypes=[("EPUB", "*.epub"), (self._t("dlg_all_filter"), "*.*")],
        )
        if path:
            self.v_mobi_dst.set(str(Path(path)))

    def _run_mobi2epub(self) -> None:
        src_raw = self.v_mobi_src.get().strip().strip('"')
        if not src_raw or not Path(src_raw).is_file():
            messagebox.showwarning(self._t("warn_title"), self._t("err_no_book"), parent=self)
            return
        dst_raw = self.v_mobi_dst.get().strip().strip('"')
        src_path = Path(src_raw)
        dst_path = Path(dst_raw) if dst_raw else None

        self.b_mobi_convert.configure(state="disabled")
        self.l_mobi_status.configure(foreground="")
        self.v_mobi_status.set(self._t("status_starting"))

        def work() -> None:
            try:
                out = mobi.mobi_to_epub(src_path, dst_path)
                self._events.put(("mobi_done", out))
            except Exception as exc:
                self._events.put(("mobi_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _run_doctor_check(self) -> None:
        self._doctor_results = doctor.run_checks()
        for iid in self.doc_tree.get_children():
            self.doc_tree.delete(iid)
        for idx, chk in enumerate(self._doctor_results):
            tag = "[OK]" if chk.ok else ("[MISSING]" if chk.required else "[OPTIONAL]")
            self.doc_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(tag, chk.name, chk.detail, chk.install_hint or ""),
            )

    def _copy_doctor_hint(self) -> None:
        sel = self.doc_tree.selection()
        if not sel:
            return
        chk = self._doctor_results[int(sel[0])]
        if not chk.install_hint:
            return
        self.clipboard_clear()
        self.clipboard_append(chk.install_hint)
        messagebox.showinfo(
            self._t("warn_title"),
            self._t("copied_hint", cmd=chk.install_hint),
            parent=self,
        )

    def _create_shortcut(self) -> None:
        if sys.platform != "win32":
            messagebox.showinfo(self._t("warn_title"), self._t("shortcut_non_win"), parent=self)
            return
        try:
            path = gui_shortcut.create_desktop_shortcut()
        except Exception as exc:
            messagebox.showerror(self._t("err_title"), str(exc), parent=self)
            return
        self.v_shortcut_status.set(self._t("shortcut_done", path=str(path)))


def launch(initial_book: str = "") -> int:
    """Start the bookvoice GUI window."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = BookvoiceApp(initial_book=initial_book)
    app.mainloop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``bookvoice-gui`` and ``python -m bookvoice.gui``."""
    args = list(sys.argv[1:] if argv is None else argv)
    initial = " ".join(args).strip()
    return launch(initial_book=initial)


if __name__ == "__main__":
    raise SystemExit(main())
