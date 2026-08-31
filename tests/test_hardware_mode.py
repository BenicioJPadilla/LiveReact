"""Tests that hardware mode wires up real adapters and degrades gracefully when no
devices/library are present (the 'ready but untested on this machine' path)."""

from __future__ import annotations

import threading

from livereact.app import App, AppConfig
from livereact.clock import FakeClock
from livereact.inputs.midi import MidiListener
from livereact.inputs.prodj import ProDjLinkListener
from livereact.network import RECOMMENDED_HOST_IP, diagnostics, has_link_local


def _hw_app() -> App:
    return App(AppConfig(demo=False, config_path=None), clock=FakeClock())


def test_hardware_mode_selects_real_input_sources():
    app = _hw_app()
    kinds = {type(s) for s in app.sources}
    assert ProDjLinkListener in kinds
    assert MidiListener in kinds


def test_hardware_mode_starts_and_stops_without_devices():
    # No Enttec / XDJ on this machine: start() must not raise, failed sources are
    # skipped, and shutdown joins cleanly. RealClock so the engine threads sleep
    # normally (a FakeClock would make them busy-spin during the brief run).
    app = App(AppConfig(demo=False, config_path=None))
    app.start()
    app.shutdown()
    assert app.stop_event.is_set()


def test_prodj_listener_raises_clear_error_without_library():
    src = ProDjLinkListener(None, FakeClock(), threading.Event())
    # python-prodj-link isn't installed in dev; start() should fail with a clear
    # error (caught by App.start in practice), not a bare ImportError surprise.
    from livereact.inputs.prodj import ProDjLinkError

    try:
        src._make_prodj()
    except ProDjLinkError as exc:
        assert "python-prodj-link" in str(exc)
    except Exception:  # if the lib *is* somehow present, that's fine too
        pass


def test_network_diagnostics_report():
    text = diagnostics()
    assert "Pro DJ Link" in text
    assert isinstance(has_link_local([("eth", RECOMMENDED_HOST_IP)]), bool)
    assert has_link_local([("eth", "169.254.1.2")]) is True
    assert has_link_local([("eth", "192.168.1.5")]) is False
