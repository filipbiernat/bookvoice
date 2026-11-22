"""Tests for GUI i18n, config persistence, formatting helpers and CLI entry points."""

from __future__ import annotations

from pathlib import Path

from bookvoice import cli, gui, gui_i18n


def test_tr_defaults_and_formatting() -> None:
    assert "bookvoice" in gui_i18n.tr("en", "app_title")
    assert "Konwersja" in gui_i18n.tr("pl", "tab_convert")
    assert gui_i18n.tr("unknown", "tab_convert") == gui_i18n.tr("en", "tab_convert")
    assert "3" in gui_i18n.tr("en", "status_voices_loaded", count=3)


def test_gui_i18n_keys_match_between_en_and_pl() -> None:
    assert set(gui_i18n.STRINGS["en"]) == set(gui_i18n.STRINGS["pl"])


def test_load_and_save_gui_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "gui.json"
    assert gui_i18n.load_gui_config(cfg_path)["language"] == "en"

    gui_i18n.save_gui_config({"language": "pl", "last_book_dir": "C:/Books"}, cfg_path)
    loaded = gui_i18n.load_gui_config(cfg_path)
    assert loaded["language"] == "pl"
    assert loaded["last_book_dir"] == "C:/Books"

    # Invalid language falls back to default
    cfg_path.write_text('{"language": "xx"}', encoding="utf-8")
    assert gui_i18n.load_gui_config(cfg_path)["language"] == "en"


def test_format_selection() -> None:
    assert gui.format_selection([]) == ""
    assert gui.format_selection([3]) == "3"
    assert gui.format_selection([1, 2, 3, 5, 7, 8, 9]) == "1-3,5,7-9"
    assert gui.format_selection([5, 4, 2, 1, 2]) == "1-2,4-5"


def test_estimate_duration_text() -> None:
    assert gui.estimate_duration_text(900) == "1m 00s"
    assert gui.estimate_duration_text(54000) == "1h 00m"


def test_cli_gui_subcommand_parses() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["gui"])
    assert args.command == "gui"
    assert args.book is None
    assert args.create_shortcut is False

    args2 = parser.parse_args(["gui", "sample.epub"])
    assert args2.book == Path("sample.epub")

    args3 = parser.parse_args(["gui", "--create-shortcut"])
    assert args3.create_shortcut is True
