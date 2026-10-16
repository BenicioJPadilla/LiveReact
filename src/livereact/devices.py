"""Is the gear plugged in? Device detection for the live-show start gate.

The launch dialog polls this about once a second (on a worker thread, before
any show thread exists), and ``--hardware`` checks it once before starting.
A live show starts only when both are found:

- the light adapter: an Enttec DMX USB Pro, by its FTDI USB VID (the same test
  ``output.enttec.select_enttec_port`` uses to open it), with its model and
  serial number. The Enttec is the only DMX output the code has.
- the DJ board: the XDJ-XZ's USB audio device or USB-MIDI port (by name), or
  its Pro DJ Link keepalives on the network. Any one of them counts.

Matching is lenient on purpose. Refusing to start a show whose gear IS
connected is worse than starting one whose gear is not, so a renamed device,
another Pioneer/AlphaTheta model, an FTDI cable that does not name itself, or
the audio device typed in the dialog all count. Each match says what it
matched on, and the dialog and the log show that.

Plain DMX is one-way, so this cannot see the fixtures. The Enttec Pro's widget
API has RDM labels, but LiveReact only sends label 6 (output only) and never
reads from the port, so there is no RDM discovery: the rig's fixtures are
confirmed by eye with the fixture-test blink panel.

Once the show is running none of this is used: a pulled cable is the DMX
writer's hot-plug and the inputs' failsafes, never a stop.
"""

from __future__ import annotations

import json
import logging
import os
import select
import socket
import threading
import time
from dataclasses import dataclass, field

from .inputs.audio import CHANNELS as ENGINE_AUDIO_CHANNELS
from .inputs.midi import find_midi_port
from .inputs.prodj import KEEPALIVE_PORT
from .output.enttec import FTDI_VID, select_enttec_port

log = logging.getLogger(__name__)

# Names a DJ board's USB audio or MIDI device may carry. "xdj" is the exact
# match (what the engine's auto-detect looks for); the rest are lenient.
DJ_EXACT = "xdj"
DJ_NAME_TOKENS = ("xdj", "ddj", "djm", "cdj", "pioneer", "alphatheta", "opus-quad", "omnis")
DMX_NAME_TOKENS = ("enttec", "dmx")
ENGINE_AUDIO_INPUTS = max(ENGINE_AUDIO_CHANNELS)   # the auto-detect needs this many inputs

DJLINK_MAGIC = b"Qspt1WmJOL"     # every Pro DJ Link packet starts with this
DJLINK_FRESH_S = 5.0             # keepalives arrive every ~1.5 s per device

RIG_MEMORY_FILE = "rig-by-adapter.json"


# --------------------------------------------------------------------------- found devices
@dataclass(frozen=True)
class DmxAdapter:
    device: str          # the serial port, e.g. /dev/cu.usbserial-EN123456
    model: str           # e.g. "ENTTEC DMX USB PRO"
    serial: str          # USB serial number ("" when the adapter reports none)
    matched: str         # what it matched on, for the dialog and the log
    exact: bool          # names itself as an Enttec / DMX device
    output_opens: bool   # the DMX output would open it (FTDI VID)


@dataclass(frozen=True)
class DjDevice:
    name: str
    matched: str
    exact: bool          # an XDJ, which the engine's auto-detect picks by itself
    note: str = ""


@dataclass
class Detection:
    adapters: list[DmxAdapter] = field(default_factory=list)
    audio: list[DjDevice] = field(default_factory=list)
    midi: list[DjDevice] = field(default_factory=list)
    djlink: list[str] = field(default_factory=list)   # device names heard recently
    djlink_note: str = ""                             # why DJ Link is not being listened to
    errors: list[str] = field(default_factory=list)

    @property
    def adapter(self) -> DmxAdapter | None:
        """The adapter the DMX output will use (listed first)."""
        return self.adapters[0] if self.adapters else None

    @property
    def light_ok(self) -> bool:
        return bool(self.adapters)

    @property
    def dj_ok(self) -> bool:
        return bool(self.audio or self.midi or self.djlink)

    @property
    def ok(self) -> bool:
        return self.light_ok and self.dj_ok

    def missing(self) -> list[str]:
        return [what for what, ok in (("light adapter", self.light_ok), ("DJ board", self.dj_ok)) if not ok]

    def missing_phrase(self) -> str:
        """'the light adapter and the DJ board are' / 'the DJ board is'."""
        missing = self.missing()
        return f"the {' and the '.join(missing)} {'is' if len(missing) == 1 else 'are'}"


def _has_token(text: str, tokens) -> bool:
    text = text.lower()
    return any(t in text for t in tokens)


def _attr(p, name: str) -> str:
    return str(getattr(p, name, None) or "").strip()


def _port_text(p) -> str:
    parts = []
    for a in ("manufacturer", "product", "description"):
        v = _attr(p, a)
        if v and v != "n/a" and v not in parts:
            parts.append(v)
    return " ".join(parts)


def find_dmx_adapters(ports) -> list[DmxAdapter]:
    """The DMX adapters among ``serial.tools.list_ports`` entries, the one the
    output will open first. FTDI devices (any PID) count, as the output opens
    any of them; a non-FTDI port only when it names itself Enttec/DMX (found,
    but the output may not drive it). One entry per device: an older pyserial
    on macOS lists both cu.* and tty.* nodes."""
    ports = list(ports)
    chosen = select_enttec_port(ports)
    seen: dict[str, DmxAdapter] = {}
    for p in ports:
        device = getattr(p, "device", "") or ""
        vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
        text = _port_text(p)
        named = _has_token(text, DMX_NAME_TOKENS)
        ftdi = vid == FTDI_VID
        if not (ftdi or named):
            continue
        serial = _attr(p, "serial_number")
        if ftdi and device.upper().startswith("COM") and len(serial) == 9 and serial.endswith("A"):
            serial = serial[:-1]      # Windows' FTDIBUS id adds the port letter: EN123456A
        product, maker = _attr(p, "product"), _attr(p, "manufacturer")
        if named:
            model = " ".join(s for s in (maker, product) if s) or getattr(p, "description", "") or "DMX adapter"
        else:
            model = f"FTDI USB serial device (PID 0x{pid or 0:04x}), its name does not say Enttec"
        ids = f"USB {vid:04x}:{pid or 0:04x}" if vid is not None else "no USB id"
        matched = f"{ids}, {'name ' + repr(text) if named else 'FTDI vendor id'}"
        if not ftdi:
            matched += "; not FTDI, so the DMX output may not open it"
        adapter = DmxAdapter(device, model, serial, matched, named, ftdi)
        key = serial or getattr(p, "location", None) or device.replace("/dev/tty.", "/dev/cu.")
        if key not in seen or device == chosen:
            seen[key] = adapter
    return sorted(seen.values(), key=lambda a: (a.device != chosen, not a.output_opens, a.device))


def _wanted_audio(info: dict, index: int, wanted: str) -> bool:
    wanted = wanted.strip()
    if not wanted:
        return False
    if wanted.isdigit():
        return int(wanted) == index
    return wanted.lower() in str(info.get("name", "")).lower()   # sounddevice's own substring rule


def find_dj_audio(devices, wanted: str = "") -> list[DjDevice]:
    """DJ-board inputs among ``sounddevice.query_devices()``; ``wanted`` is
    the audio device typed in the dialog (--audio-device), which counts too."""
    out = []
    for i, info in enumerate(devices):
        name = str(info.get("name", ""))
        n_in = int(info.get("max_input_channels", 0) or 0)
        if n_in <= 0:
            continue
        typed = _wanted_audio(info, i, wanted)
        if not (typed or _has_token(name, DJ_NAME_TOKENS)):
            continue
        exact = DJ_EXACT in name.lower()
        matched = f"the device you typed ({wanted.strip()!r})" if typed else f"name {name!r}"
        note = ""
        if not exact and not typed:
            note = "not an XDJ: type its name in Audio device so the engine opens it"
        elif exact and n_in < ENGINE_AUDIO_INPUTS and not typed:
            note = f"{n_in} inputs; the auto-detect wants {ENGINE_AUDIO_INPUTS}"
        out.append(DjDevice(name, f"{matched}, {n_in} inputs", exact, note))
    return out


def find_dj_midi(names) -> list[DjDevice]:
    """DJ-board ports among ``mido.get_input_names()``; the one the show
    listens on (``inputs.midi.find_midi_port``) says so."""
    names = list(names)
    used = find_midi_port(names)
    out = []
    for name in names:
        if _has_token(name, DJ_NAME_TOKENS):
            exact = DJ_EXACT in name.lower()
            note = "" if exact else "not an XDJ: the MIDI map is for the XDJ-XZ"
            if name == used and exact:
                note = "the show listens on this one"
            out.append(DjDevice(name, f"name {name!r}", exact, note))
    return out


def parse_djlink_name(data: bytes) -> str | None:
    """The device name in a Pro DJ Link packet (bytes 0x0c-0x1f), or None
    when ``data`` is not one. A packet with an unreadable name still counts."""
    if len(data) < 0x20 or not data.startswith(DJLINK_MAGIC):
        return None
    name = data[0x0C:0x20].split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return name or "Pro DJ Link device"


class DjLinkProbe:
    """Listens for Pro DJ Link keepalives (UDP 50000) without blocking.
    Shares the port (SO_REUSEADDR/SO_REUSEPORT) and is closed before the
    engine's own listener binds it."""

    def __init__(self, port: int = KEEPALIVE_PORT) -> None:
        self.port = port
        self.sock: socket.socket | None = None
        self.note = ""
        self.seen: dict[str, float] = {}

    def open(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            s.bind(("0.0.0.0", self.port))
            s.setblocking(False)
            self.sock = s
            self.note = ""
        except OSError as exc:
            self.sock = None
            self.note = f"not listening for DJ Link ({exc})"

    def wait(self, timeout: float, stop: threading.Event | None = None) -> None:
        """Take in keepalives for up to ``timeout`` seconds, or until ``stop``
        (checked every 0.1 s, so the dialog's Start is not held up)."""
        end = time.monotonic() + timeout
        while not (stop and stop.is_set()):
            left = min(0.1, end - time.monotonic())
            if left <= 0:
                return
            if self.sock is None:
                time.sleep(left)
                continue
            try:
                ready, _, _ = select.select([self.sock], [], [], left)
            except (OSError, ValueError):
                return
            if ready:
                self._drain()

    def _drain(self) -> None:
        while self.sock is not None:
            try:
                data, _addr = self.sock.recvfrom(2048)
            except OSError:              # BlockingIOError: drained
                return
            name = parse_djlink_name(data)
            if name:
                self.seen[name] = time.monotonic()

    def heard(self) -> list[str]:
        now = time.monotonic()
        return sorted(n for n, t in self.seen.items() if now - t <= DJLINK_FRESH_S)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None


# --------------------------------------------------------------------------- scanning
def _refresh_portaudio(sd) -> None:
    """PortAudio lists devices as they were when it started; restart it so
    a board plugged in after launch shows up (well under 1 ms on macOS)."""
    try:
        sd._terminate()
    except Exception:  # noqa: BLE001 - a private API: worst case the list is stale
        log.debug("Could not refresh the audio device list", exc_info=True)
        return
    for attempt in range(3):      # never leave PortAudio shut down for the engine
        try:
            sd._initialize()
            return
        except Exception:  # noqa: BLE001
            log.warning("PortAudio restart failed (attempt %d)", attempt + 1, exc_info=True)
            time.sleep(0.1)


PROBE_TIMEOUT_S = 4.0


@dataclass
class _Probe:
    thread: threading.Thread | None = None
    box: dict = field(default_factory=dict)     # "value" or "error" once it returns
    last: list = field(default_factory=list)    # the last answer, while it hangs
    started: float = 0.0


_probes: dict[str, _Probe] = {}
_probes_lock = threading.Lock()


def _start_probe(name: str, fn) -> _Probe:
    """Run ``fn`` on its own thread, unless the last run is still going."""
    with _probes_lock:
        st = _probes.setdefault(name, _Probe())
        if st.thread is None or not st.thread.is_alive():
            box: dict = {}

            def run():
                try:
                    box["value"] = fn()
                except Exception as exc:  # noqa: BLE001
                    box["error"] = exc

            st.box, st.started = box, time.monotonic()
            st.thread = threading.Thread(target=run, name=f"probe-{name}", daemon=True)
            st.thread.start()
        return st


def _probe_result(name: str, st: _Probe, deadline: float):
    """(value, error) by ``deadline``. A probe that hangs (a wedged MIDI
    server, CoreAudio stalling) must not freeze the others, so until it
    returns its last answer stands in (lenient: it does not flip to "not
    found") and the error says so."""
    st.thread.join(max(0.0, deadline - time.monotonic()))
    if st.thread.is_alive():
        return st.last, f"{name}: no answer for {time.monotonic() - st.started:.0f} s, still checking"
    if "error" in st.box:
        return [], f"{name}: {st.box['error']}"
    st.last = st.box["value"]
    return st.last, None


def scan_usb(audio_device: str = "", refresh_audio: bool = True, stopped=lambda: False,
             timeout: float = PROBE_TIMEOUT_S) -> Detection:
    """One look at the serial ports, audio devices and MIDI ports, each
    bounded by ``timeout``. Never raises: a probe that fails or hangs says
    so in ``errors``. ``stopped`` is checked before restarting PortAudio:
    once the dialog has closed, a show may be using it, and a restart would
    cut its audio stream."""
    def serial_ports():
        from serial.tools import list_ports

        return find_dmx_adapters(list_ports.comports())

    def audio():
        import sounddevice as sd

        if refresh_audio and not stopped():
            _refresh_portaudio(sd)
        return find_dj_audio(sd.query_devices(), audio_device)

    def midi():
        import mido

        return find_dj_midi(mido.get_input_names())

    probes = [("serial ports", serial_ports, "adapters"), ("audio devices", audio, "audio"),
              ("MIDI ports", midi, "midi")]
    started = [(name, _start_probe(name, fn), attr) for name, fn, attr in probes]   # all at once
    deadline = time.monotonic() + timeout
    det = Detection()
    for name, st, attr in started:
        value, err = _probe_result(name, st, deadline)
        setattr(det, attr, value)
        if err:
            det.errors.append(err)
    return det


class DeviceWatcher(threading.Thread):
    """Scans about every ``period_s`` and hands each Detection to
    ``on_scan`` (from this thread). ``audio_device`` is read each scan, so
    it must be cheap and thread-safe (the dialog passes a plain attribute)."""

    def __init__(self, on_scan, audio_device=lambda: "", period_s: float = 1.0,
                 scan=scan_usb, probe: DjLinkProbe | None = None) -> None:
        super().__init__(name="device-watch", daemon=True)
        self.on_scan = on_scan
        self.audio_device = audio_device
        self.period_s = period_s
        self.scan = scan
        self.probe = probe if probe is not None else DjLinkProbe()
        self.stop_event = threading.Event()

    def run(self) -> None:
        self.probe.open()
        last = None
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                det = self.scan(self.audio_device(), stopped=self.stop_event.is_set)
                det.djlink, det.djlink_note = self.probe.heard(), self.probe.note
                if det != last and not self.stop_event.is_set():   # only what changed
                    log.info("Devices now:\n%s", describe(det))
                    last = det
                    self.on_scan(det)
                self.probe.wait(max(0.05, self.period_s - (time.monotonic() - started)), self.stop_event)
        except Exception:  # noqa: BLE001 - a broken probe must not take the dialog down
            log.exception("Device detection stopped")
        finally:
            self.probe.close()

    def stop(self, timeout: float = 3.0) -> None:
        """Stop and wait. The DJ Link port is freed for the engine even if a
        scan hangs past ``timeout`` (the engine's socket could not share it)."""
        self.stop_event.set()
        if self.is_alive():
            self.join(timeout)
        if self.is_alive():
            log.warning("Device detection did not stop within %.0f s; closing its DJ Link socket", timeout)
        self.probe.close()


def detect_once(audio_device: str = "", djlink_wait_s: float = 3.0) -> Detection:
    """The CLI's check. Listens for DJ Link only when USB found no DJ board."""
    probe = DjLinkProbe()
    if djlink_wait_s > 0:
        probe.open()                  # keepalives heard during the USB scan count too
    try:
        started = time.monotonic()
        det = scan_usb(audio_device, refresh_audio=False)   # fresh process: PortAudio's list is current
        if not det.dj_ok and djlink_wait_s > 0:
            probe.wait(djlink_wait_s - (time.monotonic() - started))
            det.djlink, det.djlink_note = probe.heard(), probe.note
    finally:
        probe.close()
    return det


# --------------------------------------------------------------------------- the gate, in words
def checklist(det: Detection) -> list[tuple[bool, str, list[str]]]:
    """(ok, headline, detail lines) for the light adapter and the DJ board."""
    a = det.adapter
    if a:
        light = (True, "Light adapter: connected" + ("" if a.exact else " (not confirmed as an Enttec)"), [
            f"{a.model}" + (f", serial {a.serial}" if a.serial else ", no serial number"),
            f"{a.device} (matched: {a.matched})"] + [
            f"also: {o.model} on {o.device}" for o in det.adapters[1:]])
    else:
        light = (False, "Light adapter: not found, plug in the USB cable", [])
    dj_lines = [f"USB audio: {d.name}" + (f" ({d.note})" if d.note else "") for d in det.audio]
    dj_lines += [f"MIDI: {d.name}" + (f" ({d.note})" if d.note else "") for d in det.midi]
    dj_lines += [f"DJ Link: {n}" for n in det.djlink]
    if det.dj_ok:
        dj = (True, "DJ board: connected", dj_lines)
    else:
        dj = (False, "DJ board: not found, plug in its USB cable (or Ethernet for DJ Link)",
              ["Plugged in but named differently? Type its audio device name; that counts."]
              + ([det.djlink_note] if det.djlink_note else []))
    return [light, dj]


def describe(det: Detection) -> str:
    """The checklist as plain text, for the CLI and the log."""
    lines = []
    for ok, head, details in checklist(det):
        lines.append(f"  [{'x' if ok else ' '}] {head}")
        lines += [f"        {d}" for d in details]
    lines += [f"  (could not check {e})" for e in det.errors]
    return "\n".join(lines)


# --------------------------------------------------------------------------- rig memory
def data_home() -> str:
    """~/LiveReact (or $LIVEREACT_HOME), where the packaged app keeps its data."""
    return os.environ.get("LIVEREACT_HOME") or os.path.join(os.path.expanduser("~"), "LiveReact")


def load_rig_memory(home: str | None = None) -> dict[str, str]:
    """{adapter serial: absolute rig path}; {} when missing or unreadable."""
    try:
        with open(os.path.join(home or data_home(), RIG_MEMORY_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    rigs = data.get("adapters") if isinstance(data, dict) else None
    return {k: v for k, v in rigs.items() if isinstance(k, str) and isinstance(v, str)} \
        if isinstance(rigs, dict) else {}


def remember_rig(serial: str, rig_path: str, home: str | None = None) -> None:
    """Remember ``rig_path`` ("" = the built-in default rig) for the adapter."""
    if not serial:
        return
    home = home or data_home()
    rigs = load_rig_memory(home)
    rig = os.path.abspath(rig_path) if rig_path else ""
    if rigs.get(serial) == rig:
        return
    rigs[serial] = rig
    path = os.path.join(home, RIG_MEMORY_FILE)
    try:
        os.makedirs(home, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"adapters": rigs}, fh, indent=2)
            fh.write("\n")
    except OSError:
        log.warning("Could not remember the rig for adapter %s in %s", serial, path, exc_info=True)
