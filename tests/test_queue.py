from __future__ import annotations

from pathlib import Path

import pytest

from bookvoice import cli
from bookvoice.queue import BookQueue, QueueError, QueueItem, resolve_book_path, run_queue


def test_resolve_book_path_file_and_dir(tmp_path: Path) -> None:
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")
    mobi = tmp_path / "book.mobi"
    mobi.write_bytes(b"mobi")

    assert resolve_book_path(mobi) == mobi.resolve()
    # Directory prefers .epub over .mobi
    assert resolve_book_path(tmp_path) == epub.resolve()

    epub.unlink()
    assert resolve_book_path(tmp_path) == mobi.resolve()


def test_resolve_book_path_errors(tmp_path: Path) -> None:
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    with pytest.raises(QueueError, match="unsupported book format"):
        resolve_book_path(txt)
    with pytest.raises(QueueError, match="no supported e-book"):
        resolve_book_path(tmp_path)
    with pytest.raises(QueueError, match="path not found"):
        resolve_book_path(tmp_path / "nope")


def test_queue_add_remove_clear_retry(tmp_path: Path) -> None:
    book1 = tmp_path / "a.epub"
    book2 = tmp_path / "b.mobi"
    book1.write_bytes(b"a")
    book2.write_bytes(b"b")
    q = BookQueue(tmp_path / "queue.json")

    i1 = q.add(book1, voice="pl-PL-MarekNeural")
    i2 = q.add(book2, no_m4b=True)
    assert [i.id for i in q.items()] == [1, 2]
    assert i1.voice == "pl-PL-MarekNeural"
    assert i2.no_m4b is True

    q.update(i1.id, status="failed", error="boom")
    assert q.retry_failed() == 1
    assert q.items()[0].status == "pending"

    q.update(i1.id, status="done")
    assert q.clear() == 1
    assert [i.id for i in q.items()] == [2]

    q.remove(2)
    assert q.items() == []
    with pytest.raises(QueueError, match="no queue item"):
        q.remove(99)


def test_run_queue_picks_up_dynamically_added_items_and_isolates_errors(tmp_path: Path) -> None:
    b1 = tmp_path / "1.epub"
    b2 = tmp_path / "2.epub"
    b3 = tmp_path / "3.epub"
    for b in (b1, b2, b3):
        b.write_bytes(b"x")

    q = BookQueue(tmp_path / "queue.json")
    q.add(b1)
    q.add(b2)
    seen: list[str] = []

    def process(item: QueueItem) -> None:
        seen.append(Path(item.source).name)
        if item.id == 1:
            q.add(b3)  # added while worker is already running
        if item.id == 2:
            raise RuntimeError("network error")

    ok, err = run_queue(q, process)
    assert (ok, err) == (2, 1)
    assert seen == ["1.epub", "2.epub", "3.epub"]
    statuses = {i.id: i.status for i in q.items()}
    assert statuses == {1: "done", 2: "failed", 3: "done"}
    assert q.worker_pid() is None


def test_cli_queue_workflow(
    sample_epub: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    qfile = tmp_path / "q.json"
    out_dir = tmp_path / "audiobooks"

    assert (
        cli.main(["queue", "--queue", str(qfile), "add", str(sample_epub), "-o", str(out_dir)]) == 0
    )
    assert "Queued #1" in capsys.readouterr().out

    assert cli.main(["queue", "--queue", str(qfile), "list"]) == 0
    out = capsys.readouterr().out
    assert "book.epub" in out
    assert "pending" in out

    assert cli.main(["queue", "--queue", str(qfile), "remove", "1"]) == 0
    assert "Removed #1" in capsys.readouterr().out


def test_run_queue_recovers_stale_running_item(tmp_path: Path) -> None:
    book = tmp_path / "interrupted.epub"
    book.write_bytes(b"x")
    q = BookQueue(tmp_path / "queue.json")
    item = q.add(book)
    q.update(item.id, status="running")  # simulates hard kill / server restart

    seen: list[int] = []
    ok, failed = run_queue(q, lambda it: seen.append(it.id))
    assert (ok, failed) == (1, 0)
    assert seen == [item.id]
    assert q.items()[0].status == "done"


def test_recover_stale_resets_running_without_worker(tmp_path: Path) -> None:
    book = tmp_path / "stuck.epub"
    book.write_bytes(b"x")
    q = BookQueue(tmp_path / "queue.json")
    item = q.add(book)
    q.update(item.id, status="running")

    assert q.next_pending() is None
    assert q.recover_stale() == 1
    assert q.next_pending() is not None
    assert q.items()[0].status == "pending"
