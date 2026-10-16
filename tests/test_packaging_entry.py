"""Pure logic of the macOS .app entry point (packaging/macos/livereact_app.py).
Runs without PyInstaller."""

from __future__ import annotations

import datetime
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "packaging" / "macos" / "livereact_app.py"
_spec = importlib.util.spec_from_file_location("livereact_app", _PATH)
entry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(entry)


def test_parse_launch_args_ignores_comments_and_blank_lines():
    text = """# a comment
       # indented comment

--hardware --visualize   # trailing comment
--rig "rigs/my rig.json"
"""
    assert entry.parse_launch_args(text) == [
        "--hardware", "--visualize", "--rig", "rigs/my rig.json"]


def test_parse_launch_args_default_text_is_the_documented_default():
    assert entry.parse_launch_args(entry.DEFAULT_LAUNCH_ARGS_TEXT) == [
        "--hardware", "--visualize", "--record", "--rig", "rigs/junior_crib.json"]


def test_parse_launch_args_bad_quoting_raises():
    with pytest.raises(ValueError):
        entry.parse_launch_args('--rig "unterminated')


def test_with_rig_replaces_every_spelling():
    assert entry.with_rig(["--hardware", "--rig", "a.json"], "/x/a.json") == [
        "--hardware", "--rig", "/x/a.json"]
    assert entry.with_rig(["--rig=a.json", "--visualize"], "/x/a.json") == [
        "--rig=/x/a.json", "--visualize"]
    assert entry.with_rig(["--ri", "a.json"], "/x/a.json") == ["--rig", "/x/a.json"]
    assert entry.with_rig(["--demo"], "/x/a.json") == ["--demo", "--rig", "/x/a.json"]


NOW = datetime.datetime(2026, 10, 16, 21, 5, 0)


def test_log_file_added_when_nothing_logs_to_a_file():
    assert entry.with_log_file(["--demo", "--visualize"], now=NOW) == [
        "--demo", "--visualize", "--log-file", "logs/app-20261016-210500.log"]


@pytest.mark.parametrize("args", [
    ["--demo", "--log-file", "x.log"],
    ["--demo", "--log-file=x.log"],
    ["--hardware", "--record"],
    ["--demo", "--session-dir", "s"],
])
def test_log_file_not_added_when_already_logging(args):
    assert entry.with_log_file(args, now=NOW) == args


def test_seed_rigs_copies_missing_and_never_overwrites(tmp_path):
    src, dest = tmp_path / "bundled", tmp_path / "data dir" / "rigs"
    src.mkdir()
    (src / "a.json").write_text('{"bundled": "a"}')
    (src / "b.json").write_text('{"bundled": "b"}')
    (src / "notes.txt").write_text("not a rig")
    dest.mkdir(parents=True)
    (dest / "a.json").write_text('{"calibrated": true}')

    assert entry.seed_rigs(src, dest) == (["b.json"], ["a.json"])
    assert (dest / "a.json").read_text() == '{"calibrated": true}'
    assert (dest / "b.json").read_text() == '{"bundled": "b"}'
    assert not (dest / "notes.txt").exists()
    # second launch: nothing to copy; the calibrated a.json is still reported
    assert entry.seed_rigs(src, dest) == ([], ["a.json"])


def test_seed_rigs_missing_source_is_a_no_op(tmp_path):
    assert entry.seed_rigs(tmp_path / "nope", tmp_path / "rigs") == ([], [])


def test_resolve_default_args_first_launch_creates_file(tmp_path):
    (tmp_path / "rigs").mkdir()
    (tmp_path / "rigs" / "junior_crib.json").write_text("{}")
    args, reason = entry.resolve_default_args(tmp_path)
    assert (tmp_path / "launch-args.txt").read_text() == entry.DEFAULT_LAUNCH_ARGS_TEXT
    assert reason is None
    assert args[-2:] == ["--rig", str(tmp_path / "rigs" / "junior_crib.json")]


def test_resolve_default_args_expands_tilde_in_rig(tmp_path, monkeypatch):
    home = tmp_path / "home dir"
    (home / "my rigs").mkdir(parents=True)
    (home / "my rigs" / "club.json").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "launch-args.txt").write_text('--hardware --rig "~/my rigs/club.json"\n')
    args, reason = entry.resolve_default_args(tmp_path)
    assert reason is None
    assert args == ["--hardware", "--rig", str(home / "my rigs" / "club.json")]


def test_resolve_default_args_reads_rig_through_argparse_prefix(tmp_path):
    (tmp_path / "launch-args.txt").write_text("--hardware --ri rigs/gone.json\n")
    args, reason = entry.resolve_default_args(tmp_path)
    assert args == ["--demo", "--visualize"] and "gone.json" in reason


def test_resolve_default_args_missing_rig_falls_back_to_demo(tmp_path):
    (tmp_path / "launch-args.txt").write_text("--hardware --rig rigs/gone.json\n")
    args, reason = entry.resolve_default_args(tmp_path)
    assert args == ["--demo", "--visualize"]
    assert "gone.json" in reason


def test_resolve_default_args_empty_or_invalid_falls_back(tmp_path):
    (tmp_path / "launch-args.txt").write_text("# only comments\n\n")
    assert entry.resolve_default_args(tmp_path)[0] == ["--demo", "--visualize"]

    (tmp_path / "launch-args.txt").write_text("--demo --bogus\n")
    args, reason = entry.resolve_default_args(tmp_path)
    assert args == ["--demo", "--visualize"] and "--bogus" in reason

    (tmp_path / "launch-args.txt").write_text("--help\n")
    args, reason = entry.resolve_default_args(tmp_path)
    assert args == ["--demo", "--visualize"] and "do not parse" in reason


def test_livereact_parser_rejects_unknown_flags_and_help():
    assert entry.parse_livereact_args(["--demo", "--visualize"]).visualize
    with pytest.raises(ValueError, match="--bogus"):
        entry.parse_livereact_args(["--bogus"])
    with pytest.raises(ValueError, match="--help"):
        entry.parse_livereact_args(["--help"])  # exits 0: no show to start


def test_first_launch_defaults_to_the_launch_dialog_when_the_build_has_it(tmp_path):
    import argparse

    la = entry

    def with_choose(args):
        p = argparse.ArgumentParser()
        p.add_argument("--choose", action="store_true")
        p.add_argument("--rig")
        try:
            return p.parse_args(args)
        except SystemExit:
            raise ValueError("unknown option") from None

    args, reason = la.resolve_default_args(tmp_path, parse=with_choose)
    assert args == ["--choose"] and reason is None
    assert (tmp_path / la.LAUNCH_ARGS_FILE).read_text().strip().endswith("--choose")
