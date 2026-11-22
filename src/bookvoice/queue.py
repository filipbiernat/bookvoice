"""Persistent conversion queue stored as JSON (default: ``~/.bookvoice/queue.json``)."""

from __future__ import annotations

import ctypes
import dataclasses
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BOOK_EXTENSIONS = (".epub", ".azw3", ".mobi", ".azw", ".prc")
DEFAULT_QUEUE_PATH = Path.home() / ".bookvoice" / "queue.json"


class QueueError(RuntimeError):
    """Raised on invalid queue operations or missing book files."""


def resolve_book_path(path: str | Path) -> Path:
    """Resolve a book file or pick the best e-book inside a directory (preferring ``.epub``)."""
    target = Path(path).expanduser().resolve()
    if target.is_file():
        if target.suffix.lower() not in BOOK_EXTENSIONS:
            raise QueueError(
                f"unsupported book format {target.suffix!r} "
                f"(expected one of {', '.join(BOOK_EXTENSIONS)})"
            )
        return target
    if target.is_dir():
        by_ext: dict[str, list[Path]] = {}
        for entry in sorted(target.iterdir()):
            if entry.is_file() and entry.suffix.lower() in BOOK_EXTENSIONS:
                by_ext.setdefault(entry.suffix.lower(), []).append(entry)
        for ext in BOOK_EXTENSIONS:
            if ext in by_ext:
                return by_ext[ext][0]
        raise QueueError(f"no supported e-book found in directory: {target}")
    raise QueueError(f"path not found: {target}")


@dataclass
class QueueItem:
    id: int
    source: str
    status: str = "pending"  # pending | running | done | failed
    output: str | None = None
    voice: str | None = None
    rate: str = "+0%"
    bitrate: str = "64k"
    only: str | None = None
    chunk_chars: int = 2500
    parallel: int = 3
    no_normalize: bool = False
    no_m4b: bool = False
    cover: str | None = None
    keep_work: bool = False
    heading_pattern: str | None = None
    error: str | None = None
    added_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    finished_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueueItem:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class BookQueue:
    """File-backed conversion queue with atomic saves and worker PID tracking."""

    def __init__(self, path: Path = DEFAULT_QUEUE_PATH) -> None:
        self.path = path.expanduser().resolve()
        self.pid_path = self.path.with_suffix(".pid")

    def _load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"next_id": 1, "items": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QueueError(f"cannot read queue file {self.path}: {exc}") from None
        return {"next_id": int(data.get("next_id", 1)), "items": list(data.get("items", []))}

    def _save_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def items(self) -> list[QueueItem]:
        return [QueueItem.from_dict(raw) for raw in self._load_raw()["items"]]

    def add(self, source: str | Path, **options: Any) -> QueueItem:
        resolved = resolve_book_path(source)
        data = self._load_raw()
        item_id = data["next_id"]
        data["next_id"] = item_id + 1
        item = QueueItem(id=item_id, source=str(resolved), **options)
        data["items"].append(item.to_dict())
        self._save_raw(data)
        return item

    def remove(self, item_id: int) -> QueueItem:
        data = self._load_raw()
        for idx, raw in enumerate(data["items"]):
            if raw.get("id") == item_id:
                removed = QueueItem.from_dict(data["items"].pop(idx))
                self._save_raw(data)
                return removed
        raise QueueError(f"no queue item with id {item_id}")

    def clear(self, *, all_items: bool = False) -> int:
        data = self._load_raw()
        before = len(data["items"])
        if all_items:
            data["items"] = [r for r in data["items"] if r.get("status") == "running"]
        else:
            data["items"] = [r for r in data["items"] if r.get("status") not in ("done", "failed")]
        self._save_raw(data)
        return before - len(data["items"])

    def retry_failed(self) -> int:
        data = self._load_raw()
        count = 0
        for raw in data["items"]:
            if raw.get("status") == "failed":
                raw["status"] = "pending"
                raw["error"] = None
                raw["finished_at"] = None
                count += 1
        if count:
            self._save_raw(data)
        return count

    def next_pending(self) -> QueueItem | None:
        for item in self.items():
            if item.status == "pending":
                return item
        return None

    def update(self, item_id: int, **changes: Any) -> QueueItem:
        data = self._load_raw()
        for raw in data["items"]:
            if raw.get("id") == item_id:
                raw.update(changes)
                self._save_raw(data)
                return QueueItem.from_dict(raw)
        raise QueueError(f"no queue item with id {item_id}")

    def worker_pid(self) -> int | None:
        if not self.pid_path.exists():
            return None
        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        if _pid_alive(pid):
            return pid
        self.pid_path.unlink(missing_ok=True)
        return None

    def recover_stale(self) -> int:
        """Reset items stuck in ``running`` back to ``pending`` when no worker is alive."""
        if self.worker_pid() is not None:
            return 0
        data = self._load_raw()
        recovered = 0
        for raw in data["items"]:
            if raw.get("status") == "running":
                raw["status"] = "pending"
                recovered += 1
        if recovered:
            self._save_raw(data)
        return recovered

    def claim_worker(self) -> None:
        active = self.worker_pid()
        if active is not None and active != os.getpid():
            raise QueueError(f"queue worker is already running (PID {active})")
        self.recover_stale()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")

    def release_worker(self) -> None:
        try:
            if self.pid_path.exists() and self.pid_path.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                self.pid_path.unlink(missing_ok=True)
        except OSError:
            pass


def run_queue(queue: BookQueue, processor: Callable[[QueueItem], None]) -> tuple[int, int]:
    """Process all pending items sequentially (re-checking after each book).

    Returns ``(succeeded, failed)``.
    """
    queue.claim_worker()
    succeeded = 0
    failed = 0
    try:
        while (item := queue.next_pending()) is not None:
            log.info("=== Queue #%d: %s ===", item.id, Path(item.source).name)
            queue.update(item.id, status="running", error=None)
            try:
                processor(item)
            except Exception as exc:
                failed += 1
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                queue.update(item.id, status="failed", error=str(exc), finished_at=now)
                log.error("=== Queue #%d failed: %s ===", item.id, exc)
            else:
                succeeded += 1
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                queue.update(item.id, status="done", error=None, finished_at=now)
                log.info("=== Queue #%d done ===", item.id)
    finally:
        queue.release_worker()
    return succeeded, failed
