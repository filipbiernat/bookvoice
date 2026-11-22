from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from bookvoice import cli
from bookvoice.progress import (
    ProgressTracker,
    format_duration,
    format_status_report,
    read_status,
    render_bar,
)
from bookvoice.queue import BookQueue


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0s"), (42, "42s"), (65, "1m 05s"), (3665, "1h 01m")],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_render_bar() -> None:
    assert render_bar(0.0, 10) == "[----------]"
    assert render_bar(0.5, 10) == "[#####-----]"
    assert render_bar(1.5, 10) == "[##########]"


def test_tracker_writes_status_and_computes_eta(tmp_path: Path) -> None:
    status_file = tmp_path / "status.json"
    now = [1000.0]

    tracker = ProgressTracker(
        book_title="Test Book",
        book_author="Jane Doe",
        output_dir=tmp_path / "out",
        voice="pl-PL-MarekNeural",
        chapter_total=3,
        chars_total=1000,
        status_path=status_file,
        stream=io.StringIO(),
        clock=lambda: now[0],
    )
    # Skipped chapter should advance chars_done without faking session speed
    tracker.skip_chapter(1, "Intro", 200)
    assert tracker.state.chars_done == 200
    assert tracker.state.eta_seconds is None

    tracker.start_chapter(2, "Chapter 1", chunk_total=2)
    now[0] = 1010.0  # 10s elapsed for 400 chars -> 40 chars/s -> 400 remaining = 10s ETA
    tracker.advance_chunk(400)
    saved = read_status(status_file)
    assert saved is not None
    assert saved.chars_done == 600
    assert saved.chunk_done == 1
    assert saved.eta_seconds == pytest.approx(10.0)

    tracker.set_packaging()
    assert read_status(status_file).state == "packaging"  # type: ignore[union-attr]
    tracker.finish()
    final = read_status(status_file)
    assert final is not None
    assert final.state == "done"
    assert final.fraction == 1.0


def test_format_status_report_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    status_file = tmp_path / "status.json"
    qfile = tmp_path / "queue.json"
    book = tmp_path / "next.epub"
    book.write_bytes(b"x")
    q = BookQueue(qfile)
    q.add(book)

    tracker = ProgressTracker(
        book_title="Without Remorse",
        book_author="Tom Clancy",
        output_dir=tmp_path / "out",
        voice="pl-PL-MarekNeural",
        chapter_total=40,
        chars_total=1000,
        status_path=status_file,
        stream=io.StringIO(),
    )
    tracker.start_chapter(10, "Chapter 8", chunk_total=4)
    tracker.advance_chunk(500)
    tracker.state.pid = os.getpid()

    report = format_status_report(read_status(status_file), q)
    assert "Tom Clancy - Without Remorse" in report
    assert "50.0%" in report
    assert "10/40 - Chapter 8" in report
    assert "next.epub" in report

    monkeypatch.setattr("bookvoice.progress.DEFAULT_STATUS_PATH", status_file)
    assert cli.main(["status", "--queue", str(qfile)]) == 0
    out = capsys.readouterr().out
    assert "Tom Clancy - Without Remorse" in out
    assert "next.epub" in out
