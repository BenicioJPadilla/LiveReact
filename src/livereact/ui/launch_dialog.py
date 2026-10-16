"""The launch dialog: pick the rig and the options before the show starts.

LiveReact ships as a double-click app, so Josh needs a way to choose his rig
without a terminal. ``python -m livereact --choose`` opens this dialog first;
it returns the command-line arguments the choices stand for (always with
``--visualize``), or None when he quits. ``__main__`` then parses those
arguments exactly as if they had been typed, so recording, supervision and
everything else behave the same as a terminal launch.

The last choice is remembered in ``last-launch.json`` in the working
directory (next to ``rigs/``) and prefilled next time. A missing or corrupt
file, or a remembered rig that no longer exists, falls back to the defaults.

Nothing here touches the show engine or DMX output: the dialog runs, and its
QApplication's nested event loop ends, before any of that is created.
"""

from __future__ import annotations

import glob
import json
import logging
import os

from PySide6 import QtCore, QtWidgets

from . import icons, theme
from .widgets import Card, hbox, label

log = logging.getLogger(__name__)

LAST_LAUNCH_FILE = "last-launch.json"
RIGS_DIR = "rigs"

MODE_LIVE = "live"
MODE_DEMO = "demo"
_DEFAULT_RIG = ""        # combo data for "no --rig": the packaged default rig


def find_rigs(cwd: str) -> list[tuple[str, str]]:
    """(path relative to ``cwd``, display text) for every rigs/*.json, sorted
    by file name. The display text is the rig's "name" and its file name; a
    file that does not parse still shows (by file name) so it can be picked
    and fail loudly at load time rather than vanish from the list."""
    out = []
    for full in sorted(glob.glob(os.path.join(cwd, RIGS_DIR, "*.json"))):
        fname = os.path.basename(full)
        name = ""
        try:
            with open(full, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                name = data["name"].strip()
        except (OSError, ValueError):
            pass
        text = f"{name}  ·  {fname}" if name else fname
        out.append((os.path.join(RIGS_DIR, fname), text))
    return out


def load_last_launch(cwd: str) -> dict:
    """The remembered choice, or {} when there is none or it is unreadable."""
    try:
        with open(os.path.join(cwd, LAST_LAUNCH_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_last_launch(cwd: str, choice: dict) -> None:
    path = os.path.join(cwd, LAST_LAUNCH_FILE)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(choice, fh, indent=2)
            fh.write("\n")
    except OSError:
        log.warning("Could not remember the launch choice in %s", path, exc_info=True)


def build_argv(mode: str, rig: str | None, record: bool, phone: bool = False,
               audio_device: str = "") -> list[str]:
    """The command line a set of choices stands for. ``--phone`` goes last:
    it may take an optional PORT, so nothing must follow it."""
    argv = ["--hardware" if mode == MODE_LIVE else "--demo", "--visualize"]
    if record:
        argv.append("--record")
    if rig:
        argv += ["--rig", rig]
    audio_device = audio_device.strip()
    if mode == MODE_LIVE and audio_device:
        argv += ["--audio-device", audio_device]
    if phone:
        argv.append("--phone")
    return argv


def _field(title: str, widget: QtWidgets.QWidget | QtWidgets.QLayout,
           hint: str = "") -> QtWidgets.QVBoxLayout:
    v = QtWidgets.QVBoxLayout()
    v.setSpacing(theme.SP2 - 2)
    v.addWidget(label(title.upper(), "overline"))
    if isinstance(widget, QtWidgets.QLayout):
        v.addLayout(widget)
    else:
        v.addWidget(widget)
    if hint:
        v.addWidget(label(hint, "hint", wrap=True))
    return v


def _two_lines(w: QtWidgets.QWidget) -> None:
    """Room for a title + description option. The console's layouts stretch
    these; a compact dialog sizes them to the stylesheet's one-line minimum,
    which (being a stylesheet value) also overrides setMinimumHeight."""
    theme.set_css(w, "min-height: 40px;")


class LaunchDialog(QtWidgets.QDialog):
    """Rig, mode and options. ``result_argv`` is set when Start is pressed."""

    def __init__(self, cwd: str | None = None, phone_supported: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.phone_supported = phone_supported
        self.result_argv: list[str] | None = None
        self._record_touched = False
        self.setWindowTitle("LiveReact")
        self.setModal(True)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(theme.SP6, theme.SP6, theme.SP6, theme.SP6)
        outer.setSpacing(theme.SP4)

        logo = QtWidgets.QLabel()
        logo.setPixmap(icons.pixmap("logo", theme.ACCENT, 22))
        outer.addLayout(hbox(logo, label("LiveReact", "wordmark"), stretch_at=2))
        outer.addWidget(label("Pick the rig and how to run it, then start the show.", "body2", wrap=True))

        card = Card("Launch", "show")
        card.body.setSpacing(theme.SP4)

        # --- rig
        self.rig_combo = QtWidgets.QComboBox()
        self.rig_combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.rig_combo.setAccessibleName("Rig")
        for path, text in find_rigs(self.cwd):
            self.rig_combo.addItem(text, path)
        self.rig_combo.addItem("Built-in default rig", _DEFAULT_RIG)
        self.b_browse = QtWidgets.QPushButton("Browse...")
        self.b_browse.setAutoDefault(False)
        self.b_browse.clicked.connect(self._browse)
        self.rig_note = label("", "hint", wrap=True)
        self.rig_note.hide()
        rig_field = _field("Rig", hbox(self.rig_combo, self.b_browse))
        rig_field.addWidget(self.rig_note)
        card.body.addLayout(rig_field)

        # --- mode
        self.rb_live = QtWidgets.QRadioButton("Live show\nhardware: Enttec DMX, Pro DJ Link, XDJ audio and MIDI")
        self.rb_demo = QtWidgets.QRadioButton("Demo\nno hardware: synthetic music, nothing is sent to the lights")
        mode_box = QtWidgets.QVBoxLayout()
        mode_box.setSpacing(theme.SP2)
        for rb in (self.rb_live, self.rb_demo):
            rb.setObjectName("option")
            _two_lines(rb)
            mode_box.addWidget(rb)
        self.rb_live.setChecked(True)
        self.rb_live.toggled.connect(self._mode_changed)
        card.body.addLayout(_field("Mode", mode_box))

        # --- options
        self.cb_record = QtWidgets.QCheckBox("Record this session\nlogs, show state and notes into recordings/")
        self.cb_record.setChecked(True)
        _two_lines(self.cb_record)
        self.cb_record.clicked.connect(self._record_clicked)
        options = QtWidgets.QVBoxLayout()
        options.setSpacing(theme.SP2)
        options.addWidget(self.cb_record)
        self.cb_phone: QtWidgets.QCheckBox | None = None
        if phone_supported:
            self.cb_phone = QtWidgets.QCheckBox("Phone console\ncontrol the show from a phone on the same Wi-Fi")
            _two_lines(self.cb_phone)
            options.addWidget(self.cb_phone)
        card.body.addLayout(_field("Options", options))

        # --- audio device
        self.audio_edit = QtWidgets.QLineEdit()
        self.audio_edit.setPlaceholderText("Auto-detect the XDJ")
        self.audio_edit.setAccessibleName("Audio device")
        card.body.addLayout(_field("Audio device", self.audio_edit,
                                   "Optional: a device name or index. Leave blank to auto-detect the XDJ."))
        outer.addWidget(card)

        # --- actions
        self.b_quit = QtWidgets.QPushButton("Quit")
        self.b_quit.setAutoDefault(False)
        self.b_quit.clicked.connect(self.reject)
        self.b_start = QtWidgets.QPushButton("Start")
        self.b_start.setObjectName("primary")
        self.b_start.setIcon(icons.icon("show", theme.ON_ACCENT, size=16))
        self.b_start.setDefault(True)
        self.b_start.clicked.connect(self._start)
        outer.addLayout(hbox(self.b_quit, self.b_start, spacing=theme.SP2, stretch_at=0))

        self._prefill(load_last_launch(self.cwd))
        self._mode_changed()
        self.setMinimumWidth(560)
        self.b_start.setFocus()

    # ------------------------------------------------------------------ state
    def mode(self) -> str:
        return MODE_LIVE if self.rb_live.isChecked() else MODE_DEMO

    def rig(self) -> str | None:
        return self.rig_combo.currentData() or None

    def argv(self) -> list[str]:
        return build_argv(self.mode(), self.rig(), self.cb_record.isChecked(),
                          bool(self.cb_phone and self.cb_phone.isChecked()),
                          self.audio_edit.text())

    def choice(self) -> dict:
        return {"mode": self.mode(), "rig": self.rig(), "record": self.cb_record.isChecked(),
                "phone": bool(self.cb_phone and self.cb_phone.isChecked()),
                "audio_device": self.audio_edit.text().strip()}

    def _select_rig(self, path: str) -> bool:
        """Select ``path`` (relative to the cwd or absolute), adding it to the
        list when it exists but is not a rigs/ file. False if it is gone."""
        idx = self.rig_combo.findData(path)
        if idx >= 0:
            self.rig_combo.setCurrentIndex(idx)
            return True
        full = path if os.path.isabs(path) else os.path.join(self.cwd, path)
        if not os.path.isfile(full):
            return False
        self.rig_combo.insertItem(self.rig_combo.count() - 1, os.path.basename(path), path)
        self.rig_combo.setCurrentIndex(self.rig_combo.count() - 2)
        return True

    def _prefill(self, last: dict) -> None:
        if last.get("mode") == MODE_DEMO:
            self.rb_demo.setChecked(True)
        rig = last.get("rig")
        if isinstance(rig, str) and rig and not self._select_rig(rig):
            self.rig_note.setText(f"The last rig, {rig}, is not there any more. Pick another one.")
            self.rig_note.show()
        elif "rig" in last and not rig:
            self.rig_combo.setCurrentIndex(self.rig_combo.findData(_DEFAULT_RIG))
        if isinstance(last.get("record"), bool):
            self.cb_record.setChecked(last["record"])
        if self.cb_phone is not None and isinstance(last.get("phone"), bool):
            self.cb_phone.setChecked(last["phone"])
        if isinstance(last.get("audio_device"), str):
            self.audio_edit.setText(last["audio_device"])

    # ------------------------------------------------------------------ slots
    def _mode_changed(self, *_args) -> None:
        live = self.rb_live.isChecked()
        self.audio_edit.setEnabled(live)
        if not self._record_touched and self.sender() is self.rb_live:
            self.cb_record.setChecked(live)       # on for a live show unless he chose otherwise

    def _record_clicked(self) -> None:
        self._record_touched = True

    def _browse(self) -> None:
        start = os.path.join(self.cwd, RIGS_DIR)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a rig", start if os.path.isdir(start) else self.cwd, "Rig (*.json)")
        if not path:
            return
        rel = os.path.relpath(path, self.cwd)
        if not rel.startswith(os.pardir):
            path = rel
        self._select_rig(path)
        self.rig_note.hide()

    def _start(self) -> None:
        self.result_argv = self.argv()
        save_last_launch(self.cwd, self.choice())
        self.accept()


def choose_launch_args(cwd: str | None = None, phone_supported: bool = False) -> list[str] | None:
    """Show the dialog (blocking) and return the chosen argv, or None on Quit.

    Reuses the running QApplication or creates one; it is left in place for
    the console to reuse (a second QApplication is not allowed, and a fresh
    one would lose the registered fonts). Closing the dialog must not quit
    the application, so last-window-closed quitting is off while it runs."""
    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply_theme(qt)
    quit_on_close = qt.quitOnLastWindowClosed()
    qt.setQuitOnLastWindowClosed(False)
    try:
        dlg = LaunchDialog(cwd, phone_supported=phone_supported)
        dlg.exec()
        argv = dlg.result_argv
        dlg.deleteLater()
        qt.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    finally:
        qt.setQuitOnLastWindowClosed(quit_on_close)
    return argv


__all__ = ["LaunchDialog", "build_argv", "choose_launch_args", "find_rigs",
           "load_last_launch", "save_last_launch"]
