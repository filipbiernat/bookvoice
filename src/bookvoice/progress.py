"""Live conversion progress, ETA estimation and persistent ``status.json`` reporting."""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from .queue import BookQueue, QueueItem, _pid_alive

DEFAULT_STATUS_PATH = Path.home() / ".bookvoice" / "status.json"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as ``42s``, ``12m 05s`` or ``1h 23m``."""
    total = max(0, round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def render_bar(fraction: float, width: int = 24) -> str:
    """Render an ASCII progress bar such as ``[############------------]``."""
    clamped = max(0.0, min(1.0, fraction))
    filled = round(clamped * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


@dataclass
class ProgressState:
    pid: int
    state: str  # running | packaging | done | failed
    book_title: str
    book_author: str
    output_dir: str
    voice: str
    chapter_index: int = 0
    chapter_total: int = 0
    chapter_title: str = ""
    chunk_done: int = 0
    chunk_total: int = 0
    chars_done: int = 0
    chars_total: int = 0
    started_at: float = 0.0
    updated_at: float = 0.0
    eta_seconds: float | None = None

    @property
    def fraction(self) -> float:
        if self.chars_total <= 0:
            return 1.0 if self.state == "done" else 0.0
        return max(0.0, min(1.0, self.chars_done / self.chars_total))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgressState:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def read_status(path: Path | None = None) -> ProgressState | None:
    """Read the last saved conversion status, or ``None`` if unavailable."""
    resolved = (DEFAULT_STATUS_PATH if path is None else path).expanduser().resolve()
    if not resolved.exists():
        return None
    try:
        return ProgressState.from_dict(json.loads(resolved.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _write_status(path: Path, state: ProgressState) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    except OSError:
        pass  # status reporting must never break conversion


class ProgressTracker:
    """Tracks chapter/chunk progress, computes ETA and updates ``status.json``."""

    def __init__(
        self,
        *,
        book_title: str,
        book_author: str,
        output_dir: Path,
        voice: str,
        chapter_total: int,
        chars_total: int,
        status_path: Path = DEFAULT_STATUS_PATH,
        stream: TextIO | None = None,
        quiet: bool = False,
        clock: Any = time.time,
    ) -> None:
        self.status_path = status_path.expanduser().resolve()
        self._stream = sys.stderr if stream is None else stream
        self._quiet = quiet
        self._clock = clock
        self._is_tty = bool(getattr(self._stream, "isatty", lambda: False)())
        self._has_inline = False
        now = float(self._clock())
        self._session_chars = 0
        self._session_start = now
        self.state = ProgressState(
            pid=os.getpid(),
            state="running",
            book_title=book_title,
            book_author=book_author,
            output_dir=str(output_dir),
            voice=voice,
            chapter_total=chapter_total,
            chars_total=max(0, chars_total),
            started_at=now,
            updated_at=now,
        )
        _write_status(self.status_path, self.state)

    def _compute_eta(self, now: float) -> float | None:
        remaining = max(0, self.state.chars_total - self.state.chars_done)
        if remaining == 0:
            return 0.0
        elapsed = now - self._session_start
        if self._session_chars <= 0 or elapsed <= 0.1:
            return None
        rate = self._session_chars / elapsed
        return remaining / rate if rate > 0 else None

    def _clear_inline(self) -> None:
        if self._is_tty and self._has_inline:
            self._stream.write("\r" + " " * 96 + "\r")
            self._stream.flush()
            self._has_inline = False

    def _render_inline(self) -> None:
        if self._quiet or not self._is_tty:
            return
        pct = self.state.fraction * 100
        eta = (
            f"ETA ~{format_duration(self.state.eta_seconds)}"
            if self.state.eta_seconds is not None
            else "ETA ..."
        )
        line = (
            f"  {render_bar(self.state.fraction, 18)} {pct:5.1f}% | "
            f"ch {self.state.chapter_index}/{self.state.chapter_total} "
            f"({self.state.chunk_done}/{self.state.chunk_total} chunks) | {eta}"
        )
        self._stream.write("\r" + line[:96].ljust(96))
        self._stream.flush()
        self._has_inline = True

    def skip_chapter(self, pos: int, title: str, chars: int) -> None:
        now = float(self._clock())
        self.state.chapter_index = pos
        self.state.chapter_title = title
        self.state.chunk_done = 0
        self.state.chunk_total = 0
        self.state.chars_done = min(self.state.chars_total, self.state.chars_done + max(0, chars))
        self.state.updated_at = now
        self.state.eta_seconds = self._compute_eta(now)
        _write_status(self.status_path, self.state)

    def start_chapter(self, pos: int, title: str, chunk_total: int) -> None:
        self._clear_inline()
        now = float(self._clock())
        self.state.chapter_index = pos
        self.state.chapter_title = title
        self.state.chunk_done = 0
        self.state.chunk_total = chunk_total
        self.state.updated_at = now
        self.state.eta_seconds = self._compute_eta(now)
        _write_status(self.status_path, self.state)
        self._render_inline()

    def advance_chunk(self, chunk_chars: int) -> None:
        now = float(self._clock())
        added = max(0, chunk_chars)
        self.state.chunk_done += 1
        self.state.chars_done = min(self.state.chars_total, self.state.chars_done + added)
        self._session_chars += added
        self.state.updated_at = now
        self.state.eta_seconds = self._compute_eta(now)
        _write_status(self.status_path, self.state)
        self._render_inline()

    def finish_chapter(self) -> None:
        self._clear_inline()

    def set_packaging(self) -> None:
        self._clear_inline()
        now = float(self._clock())
        self.state.state = "packaging"
        self.state.chars_done = self.state.chars_total
        self.state.eta_seconds = 0.0
        self.state.updated_at = now
        _write_status(self.status_path, self.state)

    def finish(self, *, failed: bool = False) -> None:
        self._clear_inline()
        now = float(self._clock())
        self.state.state = "failed" if failed else "done"
        if not failed:
            self.state.chars_done = self.state.chars_total
            self.state.eta_seconds = 0.0
        self.state.updated_at = now
        _write_status(self.status_path, self.state)


def format_status_report(
    state: ProgressState | None,
    queue: BookQueue,
    *,
    now: float | None = None,
) -> str:
    """Format a human-readable dashboard combining live progress and queue state."""
    current_time = time.time() if now is None else now
    lines: list[str] = []

    if state is None:
        lines.append("Current conversion: none")
    else:
        alive = _pid_alive(state.pid)
        active = state.state in ("running", "packaging") and alive
        label = state.state
        if state.state in ("running", "packaging") and not alive:
            label = "stopped (process exited)"
        pct = state.fraction * 100
        end_time = current_time if active else (state.updated_at or current_time)
        elapsed = format_duration(max(0.0, end_time - state.started_at))
        eta = (
            format_duration(state.eta_seconds)
            if state.eta_seconds is not None and state.state == "running" and alive
            else "-"
        )
        lines.append(f"Book:     {state.book_author} - {state.book_title}")
        lines.append(f"Status:   {label} (PID {state.pid}, voice {state.voice})")
        lines.append(f"Progress: {render_bar(state.fraction)} {pct:5.1f}%")
        lines.append(
            f"Chapter:  {state.chapter_index}/{state.chapter_total} - {state.chapter_title} "
            f"({state.chunk_done}/{state.chunk_total} chunks)"
        )
        lines.append(f"Time:     {elapsed} elapsed | ETA: {eta}")
        lines.append(f"Output:   {state.output_dir}")

    items: list[QueueItem] = queue.items()
    worker = queue.worker_pid()
    lines.append("")
    lines.append(
        f"Queue ({queue.path}): worker {'running (PID ' + str(worker) + ')' if worker else 'idle'}"
    )
    if not items:
        lines.append("  (empty)")
    else:
        for item in items:
            extra = f" [{item.error}]" if item.error else ""
            lines.append(f"  #{item.id:<3} {item.status:<8} {Path(item.source).name}{extra}")
    return "\n".join(lines)
