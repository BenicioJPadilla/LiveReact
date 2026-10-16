"""Gear detection and the live-show start gate, with fake device lists (no hardware)."""

from __future__ import annotations

import json
import os
import socket
import time
from types import SimpleNamespace

import pytest

from livereact import __main__ as cli
from livereact import devices
from livereact.devices import (
    Detection, DjDevice, DjLinkProbe, describe, find_dj_audio, find_dj_midi,
    find_dmx_adapters, load_rig_memory, parse_djlink_name, remember_rig,
)


def port(device, vid=None, pid=None, serial=None, maker=None, product=None, desc="n/a", location=None):
    return SimpleNamespace(device=device, vid=vid, pid=pid, serial_number=serial, manufacturer=maker,
                           product=product, description=desc, location=location)


ENTTEC = port("/dev/cu.usbserial-EN123456", 0x0403, 0x6001, "EN123456", "ENTTEC", "DMX USB PRO",
              "DMX USB PRO")
MAC_NOISE = [port("/dev/cu.debug-console"), port("/dev/cu.Bluetooth-Incoming-Port")]


# --- the light adapter --------------------------------------------------------

def test_the_enttec_pro_is_found_with_its_model_and_serial():
    [a] = find_dmx_adapters(MAC_NOISE + [ENTTEC])
    assert (a.device, a.model, a.serial) == ("/dev/cu.usbserial-EN123456", "ENTTEC DMX USB PRO", "EN123456")
    assert a.exact and a.output_opens
    assert "0403:6001" in a.matched


def test_no_adapter_on_a_mac_with_only_its_own_ports():
    assert find_dmx_adapters(MAC_NOISE) == []
    assert find_dmx_adapters([]) == []


def test_cu_and_tty_nodes_of_one_adapter_are_one_adapter():
    tty = port("/dev/tty.usbserial-EN123456", 0x0403, 0x6001, "EN123456", "ENTTEC", "DMX USB PRO")
    [a] = find_dmx_adapters([tty, ENTTEC])
    assert a.device.startswith("/dev/cu.")        # the node the output opens (tty blocks)


def test_an_unnamed_ftdi_cable_counts_since_the_output_would_open_it():
    """Lenient: a clone or re-flashed adapter that reports only FTDI ids."""
    [a] = find_dmx_adapters([port("COM4", 0x0403, 0x6015, "A50285BI", "FTDI", "FT230X Basic UART")])
    assert not a.exact and a.output_opens
    assert "does not say Enttec" in a.model and a.serial == "A50285BI"


def test_a_dmx_device_by_name_without_ftdi_ids_counts_with_a_warning():
    [a] = find_dmx_adapters([port("COM7", None, None, None, None, None, "ENTTEC DMX USB PRO (COM7)")])
    assert a.exact and not a.output_opens
    assert "may not open it" in a.matched


def test_the_adapter_listed_first_is_the_one_the_output_opens():
    other = port("/dev/cu.usbserial-AB0001", 0x0403, 0x6001, "AB0001", "FTDI", "FT232R USB UART")
    adapters = find_dmx_adapters([port("COM9", None, None, None, None, None, "DMX thing"), other, ENTTEC])
    from livereact.output.enttec import select_enttec_port

    assert adapters[0].device == select_enttec_port([other, ENTTEC])
    assert len(adapters) == 3


# --- the DJ board ----------------------------------------------------------------

XDJ_AUDIO = {"name": "XDJ-XZ", "max_input_channels": 8}
MAC_AUDIO = [{"name": "MacBook Pro Microphone", "max_input_channels": 1},
             {"name": "MacBook Pro Speakers", "max_input_channels": 0}]


def test_the_xdj_audio_device_is_found():
    [d] = find_dj_audio(MAC_AUDIO + [XDJ_AUDIO])
    assert d.name == "XDJ-XZ" and d.exact and not d.note


def test_a_renamed_or_other_pioneer_board_still_counts_with_a_note():
    found = find_dj_audio([{"name": "Pioneer DJ XDJ-RX3 Audio", "max_input_channels": 4},
                           {"name": "DDJ-FLX10", "max_input_channels": 4},
                           {"name": "AlphaTheta OMNIS-DUO", "max_input_channels": 2}])
    assert [d.name for d in found] == ["Pioneer DJ XDJ-RX3 Audio", "DDJ-FLX10", "AlphaTheta OMNIS-DUO"]
    assert "6" in found[0].note                    # an XDJ, but fewer inputs than the auto-detect wants
    assert "type its name" in found[1].note


def test_the_audio_device_typed_in_the_dialog_counts():
    """A board renamed in Audio MIDI Setup: the name he typed is the match."""
    devs = MAC_AUDIO + [{"name": "Booth Mixer", "max_input_channels": 8}]
    assert find_dj_audio(devs) == []
    [d] = find_dj_audio(devs, wanted="booth")
    assert d.name == "Booth Mixer" and "you typed" in d.matched
    assert [d.name for d in find_dj_audio(devs, wanted=" 2 ")] == ["Booth Mixer"]   # by index


def test_output_only_devices_are_not_inputs():
    assert find_dj_audio([{"name": "XDJ-XZ", "max_input_channels": 0}]) == []


def test_the_xdj_midi_ports_are_found():
    found = find_dj_midi(["IAC Driver Bus 1", "XDJ-XZ (1)", "XDJ-XZ (2)"])
    assert [d.name for d in found] == ["XDJ-XZ (1)", "XDJ-XZ (2)"] and all(d.exact for d in found)
    assert find_dj_midi(["IAC Driver Bus 1"]) == []
    [ddj] = find_dj_midi(["DDJ-REV7 MIDI"])
    assert not ddj.exact and ddj.note


def keepalive(name: bytes) -> bytes:
    return devices.DJLINK_MAGIC + b"\x06\x00" + name.ljust(20, b"\x00") + b"\x01\x02" + bytes(20)


def test_djlink_keepalives_name_the_device():
    assert parse_djlink_name(keepalive(b"XDJ-XZ")) == "XDJ-XZ"
    assert parse_djlink_name(keepalive(b"")) == "Pro DJ Link device"
    assert parse_djlink_name(b"not a dj link packet at all, but long") is None
    assert parse_djlink_name(devices.DJLINK_MAGIC + b"\x06") is None      # truncated


def test_the_djlink_probe_hears_a_keepalive_on_its_port():
    probe = DjLinkProbe(port=0)                    # any free port
    probe.open()
    try:
        assert probe.sock is not None, probe.note
        addr = ("127.0.0.1", probe.sock.getsockname()[1])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"junk", addr)
            s.sendto(keepalive(b"XDJ-XZ"), addr)
        probe.wait(0.5)
        assert probe.heard() == ["XDJ-XZ"]
        probe.seen["XDJ-XZ"] = time.monotonic() - devices.DJLINK_FRESH_S - 1
        assert probe.heard() == []                 # stale: unplugged
    finally:
        probe.close()
    assert probe.sock is None


# --- the gate --------------------------------------------------------------------

def adapter():
    return find_dmx_adapters([ENTTEC])[0]


@pytest.mark.parametrize("dmx, audio, midi, link, light_ok, dj_ok", [
    (True, True, True, True, True, True),
    (True, False, False, False, True, False),
    (False, True, False, False, False, True),
    (True, False, True, False, True, True),            # MIDI alone is the board
    (True, False, False, True, True, True),            # DJ Link alone is the board
    (False, False, False, False, False, False),
])
def test_both_the_adapter_and_the_board_must_be_found(dmx, audio, midi, link, light_ok, dj_ok):
    det = Detection(adapters=[adapter()] if dmx else [],
                    audio=[DjDevice("XDJ-XZ", "name", True)] if audio else [],
                    midi=[DjDevice("XDJ-XZ (2)", "name", True)] if midi else [],
                    djlink=["XDJ-XZ"] if link else [])
    assert (det.light_ok, det.dj_ok, det.ok) == (light_ok, dj_ok, light_ok and dj_ok)
    text = describe(det)
    assert ("Light adapter: connected" in text) == light_ok
    assert ("Light adapter: not found, plug in the USB cable" in text) == (not light_ok)
    assert ("DJ board: connected" in text) == dj_ok
    assert ("DJ board: not found" in text) == (not dj_ok)


def test_the_checklist_lists_what_it_matched():
    det = Detection(adapters=[adapter()], midi=find_dj_midi(["XDJ-XZ (2)"]), djlink=["XDJ-XZ"])
    text = describe(det)
    assert "ENTTEC DMX USB PRO, serial EN123456" in text and "matched: USB 0403:6001" in text
    assert "MIDI: XDJ-XZ (2)" in text and "DJ Link: XDJ-XZ" in text


def test_a_failing_probe_is_reported_not_raised(monkeypatch):
    import serial.tools.list_ports as lp

    monkeypatch.setattr(lp, "comports", lambda: (_ for _ in ()).throw(OSError("bus gone")))
    det = devices.scan_usb(refresh_audio=False)
    assert not det.light_ok and any("bus gone" in e for e in det.errors)


def test_the_watcher_reports_each_scan_and_frees_the_port():
    seen = []

    class Probe(DjLinkProbe):
        def open(self):
            self.opened = True

        def close(self):
            self.closed = True

    probe = Probe()
    probe.seen["XDJ-XZ"] = time.monotonic()
    w = devices.DeviceWatcher(seen.append, lambda: "typed", period_s=0.05,
                              scan=lambda wanted, stopped: Detection(adapters=[adapter()] if wanted == "typed" else []),
                              probe=probe)
    w.start()
    deadline = time.monotonic() + 3
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    w.stop()
    assert not w.is_alive() and probe.closed
    assert seen[0].ok and seen[0].djlink == ["XDJ-XZ"]


# --- the rig each adapter was last used with ------------------------------------

def test_the_rig_is_remembered_per_adapter_serial(tmp_path):
    home = tmp_path / "LiveReact"
    assert load_rig_memory(str(home)) == {}
    remember_rig("EN123456", "rigs/junior_crib.json", str(home))
    remember_rig("EN999999", "", str(home))         # the built-in default rig
    remember_rig("", "rigs/x.json", str(home))      # no serial: nothing to key on
    mem = load_rig_memory(str(home))
    assert set(mem) == {"EN123456", "EN999999"} and mem["EN999999"] == ""
    assert os.path.isabs(mem["EN123456"]) and mem["EN123456"].endswith("junior_crib.json")
    (home / devices.RIG_MEMORY_FILE).write_text("{broken")
    assert load_rig_memory(str(home)) == {}


def test_data_home_is_livereact_home_or_the_users_livereact(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVEREACT_HOME", str(tmp_path))
    assert devices.data_home() == str(tmp_path)
    monkeypatch.delenv("LIVEREACT_HOME")
    assert devices.data_home().endswith("LiveReact")


# --- the CLI gate ----------------------------------------------------------------

@pytest.fixture
def no_app(monkeypatch):
    """Record the AppConfig instead of starting a show."""
    built = {}
    monkeypatch.delenv(cli.FORCE_NOTE_ENV, raising=False)   # restored after each test

    class FakeApp:
        def __init__(self, config):
            built["config"] = config

        def serve(self):
            pass

    monkeypatch.setattr(cli, "App", FakeApp)
    return built


def _detected(monkeypatch, det):
    calls = []

    def fake(audio_device="", djlink_wait_s=3.0):
        calls.append(audio_device)
        return det

    monkeypatch.setattr(devices, "detect_once", fake)
    return calls


def test_hardware_refuses_to_start_without_the_gear(monkeypatch, tmp_path, capsys, no_app):
    monkeypatch.chdir(tmp_path)
    _detected(monkeypatch, Detection(adapters=[adapter()]))
    assert cli.main(["--hardware", "--record"]) == 2
    err = capsys.readouterr().err
    assert "the DJ board is not connected" in err and "--force-start" in err
    assert "config" not in no_app
    assert not (tmp_path / "recordings").exists()           # nothing left behind


def test_hardware_starts_when_both_are_there(monkeypatch, tmp_path, capsys, no_app):
    monkeypatch.chdir(tmp_path)
    calls = _detected(monkeypatch, Detection(adapters=[adapter()], midi=find_dj_midi(["XDJ-XZ (2)"])))
    assert cli.main(["--hardware", "--audio-device", "XDJ"]) == 0
    assert calls == ["XDJ"]
    assert no_app["config"].force_start_note == ""
    assert "Light adapter: connected" in capsys.readouterr().out


def test_force_start_starts_anyway_with_a_banner(monkeypatch, tmp_path, capsys, no_app):
    monkeypatch.chdir(tmp_path)
    _detected(monkeypatch, Detection())
    assert cli.main(["--hardware", "--force-start"]) == 0
    note = no_app["config"].force_start_note
    assert "light adapter and the DJ board" in note
    assert os.environ[cli.FORCE_NOTE_ENV] == note            # for a supervised engine child
    assert "WARNING" in capsys.readouterr().err


def test_demo_and_the_tools_are_never_gated(monkeypatch, tmp_path, no_app):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(devices, "detect_once", lambda *a, **k: pytest.fail("gated"))
    assert cli.main(["--demo"]) == 0
    assert cli.main([]) == 0                                 # demo is the default
    assert cli.main(["--hardware", "--net-check"]) == 0


def test_an_engine_child_is_never_gated(monkeypatch, tmp_path, no_app):
    """A crash relaunch mid-set (the supervisor's child) must never be held up;
    it shows the banner its parent's forced start passed on."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(devices, "detect_once", lambda *a, **k: pytest.fail("gated"))
    ns = cli._build_parser().parse_args(["--hardware"])
    ns.engine_child = True
    monkeypatch.setattr(cli, "_parse_args", lambda argv: ns)
    assert cli.main(["--hardware"]) == 0
    assert no_app["config"].force_start_note == ""
    monkeypatch.setenv(cli.FORCE_NOTE_ENV, "Forced start: no DJ board at launch. Check the gear.")
    assert cli.main(["--hardware"]) == 0
    assert "no DJ board" in no_app["config"].force_start_note


def test_the_dialogs_start_is_the_gate(monkeypatch, tmp_path, no_app):
    """--choose: Start was only possible with the gear, so no second check."""
    from livereact.ui import launch_dialog

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(devices, "detect_once", lambda *a, **k: pytest.fail("gated twice"))
    monkeypatch.setattr(launch_dialog, "choose_launch_args", lambda *a, **k: ["--hardware"])
    assert cli.main(["--choose"]) == 0


def test_force_start_reaches_the_dialog(monkeypatch, tmp_path, no_app):
    from livereact.ui import launch_dialog

    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake(cwd, phone_supported=False, force_start=False):
        seen["force"] = force_start
        return ["--hardware"]

    monkeypatch.setattr(launch_dialog, "choose_launch_args", fake)
    _detected(monkeypatch, Detection())
    assert cli.main(["--choose", "--force-start"]) == 0
    assert seen["force"] and no_app["config"].force_start_note        # banner after the dialog too


def test_force_start_is_documented_as_for_emergencies():
    help_text = cli._build_parser().format_help()
    assert "--force-start" in help_text and "EMERGENCIES" in help_text


def test_rig_memory_file_is_plain_json(tmp_path):
    remember_rig("EN1", "/abs/rig.json", str(tmp_path))
    assert json.loads((tmp_path / devices.RIG_MEMORY_FILE).read_text()) == {"adapters": {"EN1": "/abs/rig.json"}}


def test_a_hung_scan_still_frees_the_djlink_port_and_never_restarts_portaudio(monkeypatch):
    """After the dialog closes, a show may own the audio and the DJ Link port."""
    import threading

    release = threading.Event()
    refreshed = []
    monkeypatch.setattr(devices, "_refresh_portaudio", lambda sd: refreshed.append(True))

    def hung_scan(wanted, stopped):
        release.wait(5)                          # e.g. a port scan that hangs
        return devices.scan_usb(wanted, stopped=stopped)

    probe = DjLinkProbe(port=0)
    w = devices.DeviceWatcher(lambda det: None, scan=hung_scan, probe=probe)
    w.start()
    time.sleep(0.1)
    w.stop(timeout=0.2)
    assert probe.sock is None                    # freed although the thread is still in the scan
    release.set()
    w.join(3)
    assert refreshed == []


def test_windows_ftdi_ports_lose_the_port_letter_so_the_rig_memory_matches():
    """pyserial on Windows: no product string, serial "EN123456A" from FTDIBUS."""
    [a] = find_dmx_adapters([port("COM3", 0x0403, 0x6001, "EN123456A", "FTDI", None, "USB Serial Port (COM3)")])
    assert a.serial == "EN123456" and a.output_opens and not a.exact
    det = Detection(adapters=[a])
    assert "Light adapter: connected (not confirmed as an Enttec)" in describe(det)


def test_a_hung_probe_does_not_freeze_the_others(monkeypatch):
    import threading

    import mido

    release = threading.Event()
    monkeypatch.setattr(mido, "get_input_names", lambda: release.wait(5) and ["XDJ-XZ (2)"])
    import serial.tools.list_ports as lp

    monkeypatch.setattr(lp, "comports", lambda: [ENTTEC])
    devices._probes.pop("MIDI ports", None)
    det = devices.scan_usb(refresh_audio=False, timeout=0.2)
    assert det.light_ok                                   # serial answered
    assert any("MIDI ports: no answer" in e for e in det.errors)
    det = devices.scan_usb(refresh_audio=False, timeout=0.2)   # still stuck: not a second thread
    assert sum(t.name == "probe-MIDI ports" for t in threading.enumerate()) == 1
    release.set()
    time.sleep(0.2)
    det = devices.scan_usb(refresh_audio=False, timeout=1.0)
    assert [d.name for d in det.midi] == ["XDJ-XZ (2)"] and not any("MIDI" in e for e in det.errors)
    devices._probes.pop("MIDI ports", None)


def test_portaudio_is_never_left_shut_down(monkeypatch):
    calls = []

    class SD:
        def _terminate(self):
            calls.append("t")

        def _initialize(self):
            calls.append("i")
            if calls.count("i") < 2:
                raise OSError("busy")

    monkeypatch.setattr(time, "sleep", lambda s: None)
    devices._refresh_portaudio(SD())
    assert calls == ["t", "i", "i"]
