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

The Gear card shows what is plugged in, polled about once a second on a
worker thread (``devices.DeviceWatcher``). Start for a live show stays off
until the light adapter and the DJ board are both found, and turns on (or
off) the moment that changes; demo is never gated, and ``--force-start``
lifts the gate for emergencies. The rig is picked by itself when the
adapter's serial number was used with a rig before (``rig-by-adapter.json``
in ~/LiveReact); the first time, the dialog asks for it once.

Nothing here touches the show engine: the dialog runs, and its QApplication's
nested event loop ends, before any of that is created, and the watcher has
stopped (and freed the DJ Link port) by then. DMX goes out only while the
fixture-test panel opened by "Flash each light" is up.
"""

from __future__ import annotations

import glob
import json
import logging
import os

from PySide6 import QtCore, QtWidgets

from .. import devices
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


class _Found(QtCore.QObject):
    """Carries each scan from the watcher thread to the dialog (queued)."""
    scanned = QtCore.Signal(object)


class LaunchDialog(QtWidgets.QDialog):
    """Rig, mode, options and the gear check. ``result_argv`` is set when
    Start is pressed. ``watch=False`` skips the device watcher (tests feed
    ``set_detection`` instead); ``home`` is where the rig memory lives."""

    def __init__(self, cwd: str | None = None, phone_supported: bool = False, parent=None,
                 force_start: bool = False, watch: bool = True, home: str | None = None) -> None:
        super().__init__(parent)
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.phone_supported = phone_supported
        self.force_start = force_start
        self.home = home
        self.result_argv: list[str] | None = None
        self._record_touched = False
        self._rig_touched = False
        self.detection = devices.Detection()
        self._adapter_serial: str | None = None      # the adapter the rig note is about
        self._rig = None                              # the loaded Rig for the fixture list
        self.setWindowTitle("LiveReact")
        self.setModal(True)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(theme.SP6, theme.SP6, theme.SP6, theme.SP6)
        outer.setSpacing(theme.SP4)

        logo = QtWidgets.QLabel()
        logo.setPixmap(icons.pixmap("logo", theme.ACCENT, 22))
        outer.addLayout(hbox(logo, label("LiveReact", "wordmark"), stretch_at=2))
        outer.addWidget(label("Pick the rig and how to run it, then start the show.", "body2", wrap=True))

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(theme.SP4)
        card = Card("Launch", "show")
        card.body.setSpacing(theme.SP4)

        # --- rig
        self.rig_combo = QtWidgets.QComboBox()
        self.rig_combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.rig_combo.setAccessibleName("Rig")
        for path, text in find_rigs(self.cwd):
            self.rig_combo.addItem(text, path)
        self.rig_combo.addItem("Built-in default rig", _DEFAULT_RIG)
        self.rig_combo.activated.connect(self._rig_picked)
        self.b_browse = QtWidgets.QPushButton("Browse...")
        self.b_browse.setAutoDefault(False)
        self.b_browse.clicked.connect(self._browse)
        self.rig_note = label("", "hint", wrap=True)
        self.rig_note.hide()
        rig_field = _field("Rig", hbox(self.rig_combo, self.b_browse))
        rig_field.addWidget(self.rig_note)
        self.adapter_note = label("", "hint", wrap=True)   # the rig the adapter was used with
        self.adapter_note.hide()
        rig_field.addWidget(self.adapter_note)
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
        self.audio_edit.textChanged.connect(self._audio_changed)
        self._audio_wanted = ""                       # read by the watcher thread
        card.body.addLayout(_field("Audio device", self.audio_edit,
                                   "Optional: a device name or index. Leave blank to auto-detect the XDJ."))
        card.body.addStretch(1)
        cards.addWidget(card, 1)
        cards.addWidget(self._build_gear(), 1)
        outer.addLayout(cards)

        # --- actions
        self.b_quit = QtWidgets.QPushButton("Quit")
        self.b_quit.setAutoDefault(False)
        self.b_quit.clicked.connect(self.reject)
        self.b_start = QtWidgets.QPushButton("Start")
        self.b_start.setObjectName("primary")
        self.b_start.setIcon(icons.icon("show", theme.ON_ACCENT, size=16))
        self.b_start.setDefault(True)
        self.b_start.clicked.connect(self._start)
        self.gate_note = label("", "hint", wrap=True)
        outer.addLayout(hbox(self.gate_note, self.b_quit, self.b_start, spacing=theme.SP2))

        self._prefill(load_last_launch(self.cwd))
        self.rig_combo.currentIndexChanged.connect(self._rig_changed)
        self._rig_changed()
        self._mode_changed()
        self.set_detection(self.detection)
        self.setMinimumWidth(1040)
        self.b_start.setFocus()

        self._watcher = None
        if watch:
            self._found = _Found(self)
            self._found.scanned.connect(self.set_detection)
            self._watcher = devices.DeviceWatcher(self._found.scanned.emit, lambda: self._audio_wanted)
            self._watcher.start()

    def _build_gear(self) -> Card:
        gear = Card("Gear", "dmx")
        gear.body.setSpacing(theme.SP3)
        self.gear_rows = []
        for _ in range(2):                        # light adapter, DJ board
            head = label("", "body2", wrap=True)
            detail = label("", "hint", wrap=True)
            detail.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            v = QtWidgets.QVBoxLayout()
            v.setSpacing(2)
            v.addWidget(head)
            v.addWidget(detail)
            gear.body.addLayout(v)
            self.gear_rows.append((head, detail))
        self.l_fixtures = label("", "hint", wrap=True)
        self.b_flash = QtWidgets.QPushButton("Flash each light")
        self.b_flash.setIcon(icons.icon("flash", theme.TEXT_2, size=16))
        self.b_flash.setAutoDefault(False)
        self.b_flash.clicked.connect(self._flash_lights)
        fx = _field("Lights in this rig", self.l_fixtures,
                    "LiveReact only sends DMX and does not use RDM, so it cannot see the lights "
                    "themselves. Flash each one and watch it light to confirm it is patched.")
        fx.addWidget(self.b_flash, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        gear.body.addLayout(fx)
        gear.body.addStretch(1)
        return gear

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

    def _abs(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(self.cwd, path)

    def _rel(self, path: str) -> str:
        """``path`` relative to the cwd when it is inside it, else as given."""
        rel = os.path.relpath(path, self.cwd)
        return path if rel.startswith(os.pardir) else rel

    def _select_rig(self, path: str) -> bool:
        """Select ``path`` (relative to the cwd or absolute), adding it to the
        list when it exists but is not a rigs/ file. False if it is gone."""
        idx = self.rig_combo.findData(path)
        if idx >= 0:
            self.rig_combo.setCurrentIndex(idx)
            return True
        if not os.path.isfile(self._abs(path)):
            return False
        self.rig_combo.insertItem(self.rig_combo.count() - 1, os.path.basename(path), path)
        self.rig_combo.setCurrentIndex(self.rig_combo.count() - 2)
        return True

    def live_start_allowed(self) -> bool:
        return self.detection.ok or self.force_start

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
        self._update_gate()

    def _audio_changed(self, text: str) -> None:
        self._audio_wanted = text

    def _rig_picked(self, *_args) -> None:
        self._rig_touched = True                  # his pick wins over the adapter's memory
        self.rig_note.hide()

    def _rig_changed(self, *_args) -> None:
        from ..fixtures.rig import load_rig

        path = self.rig()
        try:
            self._rig = load_rig(self._abs(path) if path else None)
            lines = [f"{fx.label}  ·  {fx.type_name}  ·  DMX {fx.address}" for fx in self._rig.fixtures]
            self.l_fixtures.setText("\n".join(lines) or "No fixtures in this rig.")
        except Exception as exc:  # noqa: BLE001 - shown, and the show will say it too
            self._rig = None
            self.l_fixtures.setText(f"Could not read this rig: {exc}")
        self._update_gear()

    # ------------------------------------------------------------------ devices
    def set_detection(self, det: devices.Detection) -> None:
        """Show a scan and re-check the gate (the watcher's queued signal)."""
        self.detection = det
        self._update_gear()
        self._update_gate()
        self._pick_rig_for_adapter()

    def _update_gear(self) -> None:
        for (ok, head, details), (l_head, l_detail) in zip(devices.checklist(self.detection), self.gear_rows):
            l_head.setText(f"{'●' if ok else '○'}  {head}")
            theme.set_css(l_head, f"color:{theme.ACCENT if ok else theme.DANGER_TEXT};")
            l_detail.setText("\n".join(details))
            l_detail.setVisible(bool(details))
        a = self.detection.adapter
        self.b_flash.setEnabled(bool(a and a.output_opens and self._rig and self._rig.fixtures))

    def _update_gate(self) -> None:
        live = self.rb_live.isChecked()
        self.b_start.setEnabled(not live or self.live_start_allowed())
        missing = self.detection.missing()
        phrase = self.detection.missing_phrase()
        if not live:
            text = "Demo needs no gear."
        elif not missing:
            text = "Gear connected. Ready to start."
        elif self.force_start:
            text = f"Emergency start (--force-start): starting without {phrase.rsplit(' ', 1)[0]}."
        else:
            text = (f"Start is off until {phrase} connected. "
                    "Emergencies only: --force-start (README).")
        if live and self.detection.errors:
            text += " Could not check: " + "; ".join(self.detection.errors) + "."
        self.gate_note.setText(text)
        theme.set_css(self.gate_note, "" if not live or not missing else
                      f"color:{theme.WARN if self.force_start else theme.DANGER_TEXT};")

    def _pick_rig_for_adapter(self) -> None:
        """Once per adapter: select the rig last used with its serial, or ask."""
        a = self.detection.adapter
        serial = a.serial if a else None
        if serial == self._adapter_serial:
            return
        self._adapter_serial = serial
        if not serial:
            return
        memory = devices.load_rig_memory(self.home)
        if serial not in memory:
            self._say_rig(f"New light adapter (serial {serial}). Which rig is it for? Pick it above; "
                          "next time it is picked by itself.")
            return
        rig = self._rel(memory[serial]) if memory[serial] else ""
        if self._rig_touched:
            self._say_rig(f"Adapter {serial} was last used with {rig or 'the built-in default rig'}.")
        elif not rig:
            self.rig_combo.setCurrentIndex(self.rig_combo.findData(_DEFAULT_RIG))
            self.rig_note.hide()                  # the last-launch rig is superseded
            self._say_rig(f"Picked the built-in default rig, last used with adapter {serial}.")
        elif self._select_rig(rig):
            self.rig_note.hide()
            self._say_rig(f"Picked {self.rig_combo.currentText()}, last used with adapter {serial}.")
        else:
            self._say_rig(f"The rig last used with adapter {serial}, {rig}, is not there any more. Pick one.")
        log.info("Light adapter %s: %s", serial, self.adapter_note.text())

    def _say_rig(self, text: str) -> None:
        self.adapter_note.setText(text)
        self.adapter_note.show()

    def _flash_lights(self) -> None:
        """The fixture-test panel on the detected adapter, until it is closed."""
        from ..clock import RealClock
        from ..output.enttec import EnttecSerialBackend
        from .fixture_test import show_fixture_test

        a = self.detection.adapter
        if not (a and self._rig):
            return
        log.info("Flash each light: fixture test on %s (%s)", a.device, a.model)
        show_fixture_test(self._rig, EnttecSerialBackend(port=a.device), RealClock(),
                          rig_path=self.rig() or None)

    def _record_clicked(self) -> None:
        self._record_touched = True

    def _browse(self) -> None:
        start = os.path.join(self.cwd, RIGS_DIR)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a rig", start if os.path.isdir(start) else self.cwd, "Rig (*.json)")
        if not path:
            return
        self._select_rig(self._rel(path))
        self._rig_touched = True
        self.rig_note.hide()

    def _start(self) -> None:
        live = self.mode() == MODE_LIVE
        if live and not self.live_start_allowed():
            return                                # Enter while the gate is shut
        self.result_argv = self.argv()
        save_last_launch(self.cwd, self.choice())
        a = self.detection.adapter
        if live and a and a.serial:
            devices.remember_rig(a.serial, self._abs(self.rig()) if self.rig() else "", self.home)
        log.info("Start (%s). Devices:\n%s", self.mode(), devices.describe(self.detection))
        self.accept()

    def done(self, result: int) -> None:
        """Stop the watcher first: the engine binds the DJ Link port next."""
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        super().done(result)


def choose_launch_args(cwd: str | None = None, phone_supported: bool = False,
                       **dialog_kwargs) -> list[str] | None:
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
        dlg = LaunchDialog(cwd, phone_supported=phone_supported, **dialog_kwargs)
        dlg.exec()
        argv = dlg.result_argv
        dlg.deleteLater()
        qt.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    finally:
        qt.setQuitOnLastWindowClosed(quit_on_close)
    return argv


__all__ = ["LaunchDialog", "build_argv", "choose_launch_args", "find_rigs",
           "load_last_launch", "save_last_launch"]
