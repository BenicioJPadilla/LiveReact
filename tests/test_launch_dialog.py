"""The launch dialog (``--choose``) and its CLI wiring, headless (Qt offscreen)."""

from __future__ import annotations

import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from livereact import __main__ as cli  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6 import QtWidgets

    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def venue(tmp_path, monkeypatch):
    """A cwd like ~/LiveReact: rigs/ with two named rigs and a broken one."""
    rigs = tmp_path / "rigs"
    rigs.mkdir()
    (rigs / "junior_crib.json").write_text(json.dumps({"name": "Junior Crib", "fixtures": []}))
    (rigs / "sophias_thai.json").write_text(json.dumps({"name": "Sophia's Thai", "fixtures": []}))
    (rigs / "broken.json").write_text("{ not json")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _dialog(cwd, phone=False):
    from livereact.ui.launch_dialog import LaunchDialog

    return LaunchDialog(str(cwd), phone_supported=phone)


def _pick(dlg, path):
    idx = dlg.rig_combo.findData(path)
    assert idx >= 0, path
    dlg.rig_combo.setCurrentIndex(idx)


def test_lists_the_rigs_in_the_cwd_with_their_names(qapp, venue):
    dlg = _dialog(venue)
    items = [(dlg.rig_combo.itemText(i), dlg.rig_combo.itemData(i)) for i in range(dlg.rig_combo.count())]
    assert items[:3] == [
        ("broken.json", os.path.join("rigs", "broken.json")),
        ("Junior Crib  ·  junior_crib.json", os.path.join("rigs", "junior_crib.json")),
        ("Sophia's Thai  ·  sophias_thai.json", os.path.join("rigs", "sophias_thai.json")),
    ]
    assert items[-1] == ("Built-in default rig", "")


def test_live_choice_builds_the_hardware_argv(qapp, venue):
    dlg = _dialog(venue)
    _pick(dlg, os.path.join("rigs", "junior_crib.json"))
    assert dlg.rb_live.isChecked() and dlg.cb_record.isChecked()   # the defaults
    assert dlg.cb_phone is None                                     # not offered without --phone
    assert dlg.argv() == ["--hardware", "--visualize", "--record", "--rig", os.path.join("rigs", "junior_crib.json")]
    dlg.audio_edit.setText(" 1 ")
    assert dlg.argv()[-2:] == ["--audio-device", "1"]


def test_demo_choice_builds_the_demo_argv(qapp, venue):
    dlg = _dialog(venue, phone=True)
    _pick(dlg, os.path.join("rigs", "sophias_thai.json"))
    dlg.rb_demo.setChecked(True)
    assert not dlg.cb_record.isChecked()          # record follows the mode until touched
    assert not dlg.audio_edit.isEnabled()
    dlg.audio_edit.setText("XDJ")                 # ignored in demo: no audio input is opened
    dlg.cb_phone.setChecked(True)
    assert dlg.argv() == ["--demo", "--visualize", "--rig", os.path.join("rigs", "sophias_thai.json"), "--phone"]


def test_start_remembers_and_the_next_dialog_prefills(qapp, venue):
    dlg = _dialog(venue, phone=True)
    _pick(dlg, os.path.join("rigs", "sophias_thai.json"))
    dlg.rb_demo.setChecked(True)
    dlg.cb_record.click()                         # record a demo on purpose
    dlg.cb_phone.setChecked(True)
    dlg.b_start.click()
    assert dlg.result() == dlg.DialogCode.Accepted
    saved = json.loads((venue / "last-launch.json").read_text())
    assert saved["mode"] == "demo" and saved["record"] is True

    again = _dialog(venue, phone=True)
    assert again.argv() == dlg.result_argv == [
        "--demo", "--visualize", "--record", "--rig", os.path.join("rigs", "sophias_thai.json"), "--phone"]
    assert again.rig_note.isHidden()


def test_a_remembered_rig_that_is_gone_falls_back(qapp, venue):
    (venue / "last-launch.json").write_text(json.dumps(
        {"mode": "live", "rig": "rigs/old_venue.json", "record": True}))
    dlg = _dialog(venue)
    assert dlg.rig() == os.path.join("rigs", "broken.json")       # the first rig
    assert not dlg.rig_note.isHidden() and "old_venue.json" in dlg.rig_note.text()


def test_a_corrupt_memory_file_is_ignored(qapp, venue):
    (venue / "last-launch.json").write_text("[1, 2")
    assert _dialog(venue).argv()[:3] == ["--hardware", "--visualize", "--record"]


def test_a_rig_path_with_spaces_stays_one_argument(qapp, venue):
    other = venue / "My Rigs"
    other.mkdir()
    rig = other / "back room.json"
    rig.write_text(json.dumps({"name": "Back room"}))
    dlg = _dialog(venue)
    assert dlg._select_rig(str(rig))
    argv = dlg.argv()
    assert argv[argv.index("--rig") + 1] == str(rig)
    assert cli._parse_args(argv).rig == str(rig)


def test_quit_returns_none_and_leaves_qt_usable(qapp, venue, monkeypatch):
    from PySide6 import QtCore, QtWidgets
    from livereact.ui import launch_dialog

    def press_quit(self):
        QtCore.QTimer.singleShot(0, self.b_quit.click)
        return QtWidgets.QDialog.exec(self)

    monkeypatch.setattr(launch_dialog.LaunchDialog, "exec", press_quit)
    assert launch_dialog.choose_launch_args(str(venue)) is None
    assert not (venue / "last-launch.json").exists()
    assert qapp.quitOnLastWindowClosed()          # restored for the console
    # the console's own event loop still runs (and stops) normally afterwards
    QtCore.QTimer.singleShot(0, qapp.quit)
    assert qapp.exec() == 0


def test_start_via_enter_returns_the_argv(qapp, venue, monkeypatch):
    from PySide6 import QtCore, QtTest, QtWidgets
    from livereact.ui import launch_dialog

    def press_enter(self):
        QtCore.QTimer.singleShot(0, lambda: QtTest.QTest.keyClick(self.audio_edit, QtCore.Qt.Key.Key_Return))
        return QtWidgets.QDialog.exec(self)

    monkeypatch.setattr(launch_dialog.LaunchDialog, "exec", press_enter)
    argv = launch_dialog.choose_launch_args(str(venue))
    assert argv is not None and argv[:2] == ["--hardware", "--visualize"]


# --- the --choose CLI flag ------------------------------------------------------

def test_choose_runs_the_chosen_args(venue, monkeypatch):
    from livereact.ui import launch_dialog

    seen = {}

    def fake(cwd, phone_supported=False):
        seen["cwd"] = cwd
        return ["--demo", "--duration", "0.3", "--record", "--session-dir", "rec"]

    monkeypatch.setattr(launch_dialog, "choose_launch_args", fake)
    assert cli.main(["--choose", "--log-level", "WARNING"]) == 0
    assert seen["cwd"] == os.getcwd()
    assert (venue / "rec" / "session.log").exists()     # the chosen --record took effect


def test_choose_quit_exits_0_without_starting(venue, monkeypatch):
    from livereact import app as app_mod
    from livereact.ui import launch_dialog

    monkeypatch.setattr(launch_dialog, "choose_launch_args", lambda *a, **k: None)
    monkeypatch.setattr(app_mod.App, "__init__", lambda *a, **k: pytest.fail("App was built"))
    monkeypatch.setattr(cli, "App", app_mod.App)
    assert cli.main(["--choose", "--record"]) == 0
    assert not (venue / "recordings").exists()


def test_choose_is_skipped_for_an_engine_child(monkeypatch):
    """The supervisor's child (``--engine-child``, defined on another branch)
    never shows the dialog, even if --choose reached its command line."""
    from livereact.ui import launch_dialog

    monkeypatch.setattr(launch_dialog, "choose_launch_args", lambda *a, **k: pytest.fail("dialog shown"))
    ns = cli._build_parser().parse_args(["--choose", "--demo", "--duration", "0.1"])
    ns.engine_child = True
    monkeypatch.setattr(cli, "_parse_args", lambda argv: ns)
    assert cli.main(["--choose", "--demo", "--duration", "0.1", "--engine-child"]) == 0


def test_choose_without_pyside6_exits_1(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "livereact.ui.launch_dialog", None)   # import -> ImportError
    assert cli.main(["--choose"]) == 1
    assert "PySide6" in capsys.readouterr().err


def test_passthrough_keeps_only_the_options_the_dialog_does_not_choose():
    argv = ["--choose", "--rig", "rigs/a b.json", "--log-file", "x.log", "--phone", "8080",
            "--demo", "--audio-device=1", "--rate", "30", "--phone"]
    assert cli._passthrough(argv) == ["--log-file", "x.log", "--rate", "30"]
