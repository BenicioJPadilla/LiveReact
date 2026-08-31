"""Pro DJ Link input from the XDJ-XZ — direct raw-socket listener.

VERIFIED ON HARDWARE (real XDJ-XZ, 2026-08-31): this does **not** use
`python-prodj-link`'s own runtime (`core.prodj.ProDj` / `core.clientlist.ClientList`
/ `core.vcdj.Vcdj`) — only its packet-format definitions (`prodj.network.packets`),
which parse real captured bytes from this unit correctly.

Why: the library's `ClientList` keys its client table by **IP address**. The
XDJ-XZ is an all-in-one box that broadcasts as *three* distinct devices — Deck 1,
Deck 2, and its internal mixer — each with its own MAC address, but all sharing
one physical IP (one Ethernet port). The library folds all three into a single
client record, and each new keepalive stomps that record's `player_number` with
whichever sub-device just spoke (confirmed by raw capture: player_number cycling
1 -> 2 -> 33 every ~2s, `33` + `is_mixer` flag being the unit's internal mixer).
So when a beat packet arrives carrying its own real player_number, the library's
`getClient(player_number)` lookup misses against the stomped record and the
packet is silently dropped — even though it's genuinely on the wire. Also
verified: this unit never broadcasts status packets (port 50002) at all, only
keepalive (50000) and beat (50001), so on_air/master data isn't available from
it; a virtual-CDJ presence announcement isn't needed either (the real device
broadcasts regardless of whether it sees us, and our own vcdj announce failed
outbound with "No route to host" in testing — moot once we stop needing it).

So: we bind our own sockets on the three PDL ports and parse with the library's
`packets` module directly. Single-device assumption: whichever player is
currently sending beat packets is treated as the (de facto) master — there's no
on_air/master broadcast to arbitrate with on this hardware, and a stopped deck
simply stops sending beat packets, so "is a beat stream live" doubles as
"is playing" for this rig.

`python-prodj-link` is git-only (not on PyPI) — install it into the venv before
using hardware mode:
    pip install "git+https://github.com/flesniak/python-prodj-link@<pinned-sha>"
(vendoring / pinning a SHA is recommended — docs/06 §4, docs/10 D5.)
"""

from __future__ import annotations

import logging
import select
import socket
import threading

from ..clock import Clock
from ..core.messages import BeatMessage, StatusMessage
from .base import InputSource

log = logging.getLogger(__name__)

NO_DEVICE_WARN_AFTER = 5.0  # seconds
KEEPALIVE_PORT = 50000
BEAT_PORT = 50001
STATUS_PORT = 50002


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
        self.interface = interface          # reserved: explicit NIC bind (0.0.0.0 works fine so far)
        self.player_number = player_number  # reserved: no vcdj identity needed for passive listening
        self.poll_hz = poll_hz              # unused now (receive is select()-driven, not polled)
        self._packets = None
        self._socks: list[socket.socket] = []
        self._thread: threading.Thread | None = None
        self._last_beat_in_bar: int | None = None
        self._seen_device = False
        self._started_at = 0.0

    @property
    def name(self) -> str:
        return "prodj-link"

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._packets = self._import_packets()
        self._socks = [self._bind(p) for p in (KEEPALIVE_PORT, BEAT_PORT, STATUS_PORT)]
        self._started_at = self.clock.monotonic()
        self._thread = threading.Thread(target=self._run, name="prodj-link", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass
        self._socks = []

    @staticmethod
    def _bind(port: int) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", port))
        return s

    # ------------------------------------------------------------------ library glue (VERIFY ON HW)
    def _import_packets(self):
        """Import the library's packet-format definitions. Isolated so the (git-only)
        dependency lives here — no runtime state machine from the library is used."""
        try:
            from prodj.network import packets  # type: ignore
        except ImportError as exc:  # pragma: no cover - lib not installed in dev
            raise ProDjLinkError(
                "python-prodj-link is not installed. Install it (git-only) before "
                "using hardware mode; see this module's docstring."
            ) from exc
        return packets

    def _make_prodj(self):
        """Back-compat alias for the (pre-rewrite) library-glue entry point that
        tests/tooling reach for to check the "not installed" error path."""
        return self._import_packets()

    # ------------------------------------------------------------------ receive loop
    def _run(self) -> None:
        warned = False
        while not self.stop_event.is_set():
            try:
                ready, _, _ = select.select(self._socks, [], [], 0.2)
            except OSError:
                break  # sockets closed under us during shutdown
            for s in ready:
                try:
                    data, _addr = s.recvfrom(2048)
                except OSError:
                    continue
                self._handle_packet(s, data)
            if (not self._seen_device and not warned
                    and self.clock.monotonic() - self._started_at > NO_DEVICE_WARN_AFTER):
                warned = True
                log.warning(
                    "No DJ-Link device seen yet. Check: Ethernet to the XDJ-XZ, host NIC on "
                    "169.254.x.y/16, Link enabled on the XZ, and the firewall allows UDP "
                    "50000-50002 (see HARDWARE.md)."
                )

    def _handle_packet(self, sock: socket.socket, data: bytes) -> None:
        port = sock.getsockname()[1]
        try:
            if port == BEAT_PORT:
                self._handle_beat(data)
            elif port == KEEPALIVE_PORT:
                self._seen_device = True
            # STATUS_PORT: this hardware never sends it (verified) — nothing
            # downstream depends on it yet, so it's not parsed.
        except Exception:  # noqa: BLE001 - never let the input thread die on one bad packet
            log.exception("Failed to parse Pro DJ Link packet on port %d", port)

    def _handle_beat(self, data: bytes) -> None:
        packet = self._packets.BeatPacket.parse(data)
        if packet.type != "type_beat":
            return
        self._seen_device = True
        now = self.clock.monotonic()
        player = int(packet.player_number)
        # VERIFIED ON HARDWARE: `content.bpm` is the track's fixed analyzed tempo —
        # it does NOT move with the physical tempo slider (confirmed: stayed pinned
        # at 125.00 while the slider sat at +1.55%). `content.pitch` is the slider's
        # live multiplier (1.0 = neutral); the actual live tempo the board displays
        # is bpm * pitch (confirmed: 125.00 * 1.0155 = 126.94, matching the board).
        bpm = float(packet.content.bpm) * float(packet.content.pitch)
        beat = int(packet.content.beat)  # 1-4 within the bar

        if beat and beat != self._last_beat_in_bar:
            self._last_beat_in_bar = beat
            self.queue.put(BeatMessage(now, beat, bpm, is_master=True, player=player))
        # No status broadcast from this hardware (verified) -> infer "playing"
        # from the live beat stream itself; a deck that isn't playing doesn't
        # send beat packets at all.
        self.queue.put(StatusMessage(now, on_air=(player,), master_deck=player,
                                     playing=True, loop_active=False))
