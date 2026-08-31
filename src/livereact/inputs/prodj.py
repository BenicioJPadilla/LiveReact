"""Pro DJ Link input from the XDJ-XZ via the `python-prodj-link` library.

⚠️ UNTESTED ON HARDWARE, and the most uncertain adapter in the project:
  - `python-prodj-link` is git-only (not on PyPI). It is NOT a declared dependency;
    install it into the venv before using hardware mode, e.g.:
        pip install "git+https://github.com/flesniak/python-prodj-link@<pinned-sha>"
    (vendoring / pinning a SHA is recommended — docs/06 §4, docs/10 D5.)
  - The exact library API and field names below MUST be verified against the
    installed version; they are isolated in `_make_prodj()` and `_poll_once()` so
    that's the only place to adjust.

Design (docs/04 §4): we run a virtual CDJ on a free device number (5-7 so it can't
collide with the XZ's internal players), then poll the *master* player's status and
translate it to our Beat/Status messages. Bar is inferred downstream by the
metronome; we only forward measured fields. A "no DJ-Link seen" warning fires if no
device appears within a few seconds (the classic network/firewall failure).
"""

from __future__ import annotations

import logging
import threading

from ..clock import Clock
from ..core.messages import BeatMessage, StatusMessage
from .base import InputSource

log = logging.getLogger(__name__)

NO_DEVICE_WARN_AFTER = 5.0  # seconds


class ProDjLinkError(RuntimeError):
    pass


class ProDjLinkListener(InputSource):
    def __init__(
        self,
        output_queue,
        clock: Clock,
        stop_event: threading.Event,
        interface: str | None = None,
        player_number: int = 5,
        poll_hz: float = 50.0,
    ) -> None:
        self.queue = output_queue
        self.clock = clock
        self.stop_event = stop_event
        self.interface = interface          # explicit NIC override (docs/06 §4)
        self.player_number = player_number
        self.poll_hz = poll_hz
        self._pdj = None
        self._thread: threading.Thread | None = None
        self._last_beat_in_bar: int | None = None
        self._seen_device = False
        self._started_at = 0.0

    @property
    def name(self) -> str:
        return "prodj-link"

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._pdj = self._make_prodj()
        self._started_at = self.clock.monotonic()
        self._thread = threading.Thread(target=self._run, name="prodj-link", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        try:
            if self._pdj is not None and hasattr(self._pdj, "stop"):
                self._pdj.stop()
        except Exception:  # noqa: BLE001
            log.exception("Error stopping ProDj")
        finally:
            self._pdj = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ------------------------------------------------------------------ library glue (VERIFY ON HW)
    def _make_prodj(self):
        """Import and start the library. Isolated so the (uncertain) API lives here."""
        try:
            from prodj.core.prodj import ProDj  # type: ignore
        except ImportError as exc:  # pragma: no cover - lib not installed in dev
            raise ProDjLinkError(
                "python-prodj-link is not installed. Install it (git-only) before "
                "using hardware mode; see this module's docstring."
            ) from exc

        pdj = ProDj()
        # VERIFY: interface override + virtual-CDJ player number against the lib API.
        if self.interface and hasattr(pdj, "set_interface"):
            pdj.set_interface(self.interface)
        pdj.start()
        if hasattr(pdj, "vcdj_set_player_number"):
            pdj.vcdj_set_player_number(self.player_number)
        if hasattr(pdj, "vcdj_enable"):
            pdj.vcdj_enable()
        log.info("ProDj started (player #%d, interface=%s)", self.player_number, self.interface or "auto")
        return pdj

    def _poll_once(self) -> None:
        """Read the master player's status and emit messages. VERIFY field names."""
        pdj = self._pdj
        if pdj is None:
            return
        client_list = getattr(pdj, "cl", None)
        clients = getattr(client_list, "clients", []) if client_list else []
        if clients:
            self._seen_device = True
        master = next((c for c in clients if getattr(c, "master", False)), None)
        if master is None:
            return

        now = self.clock.monotonic()
        bpm = float(getattr(master, "bpm", 0.0) or 0.0)
        beat = int(getattr(master, "beat", 0) or 0)        # 1-4 within the bar
        on_air = getattr(master, "on_air", True)
        playing = getattr(master, "play_state", "playing") in ("playing", "Playing", True)
        loop = bool(getattr(master, "loop", False))
        player = int(getattr(master, "player_number", self.player_number))

        # Emit a beat only when the 1-4 counter changes (the lib pushes status often).
        if beat and beat != self._last_beat_in_bar:
            self._last_beat_in_bar = beat
            self.queue.put(BeatMessage(now, beat, bpm, is_master=True, player=player))
        self.queue.put(StatusMessage(now, on_air=(player,) if on_air else (), master_deck=player,
                                     playing=playing, loop_active=loop))

    # ------------------------------------------------------------------ poll loop
    def _run(self) -> None:
        from ..clock import LoopTimer

        timer = LoopTimer(self.clock, self.poll_hz)
        warned = False
        while not self.stop_event.is_set():
            try:
                self._poll_once()
            except Exception:  # noqa: BLE001 - never let the input thread die
                log.exception("ProDj poll failed")
            if (not self._seen_device and not warned
                    and self.clock.monotonic() - self._started_at > NO_DEVICE_WARN_AFTER):
                warned = True
                log.warning(
                    "No DJ-Link device seen yet. Check: Ethernet to the XDJ-XZ, host NIC on "
                    "169.254.x.y/16, Link enabled on the XZ, and the firewall allows UDP "
                    "50000-50002 (see HARDWARE.md)."
                )
            timer.wait()
