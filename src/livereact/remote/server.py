"""Phone console: a tiny web page a phone on the venue Wi-Fi can use to make the
show SAFER, and never more intense.

Why it exists: the laptop sits behind the decks. If something looks wrong from
the floor (a strobe that is too much, a laser near the crowd, a fixture about to
fall), whoever is out there should be able to dark or calm the rig from a phone
without running back to the booth.

The safety invariant is enforced HERE, on the server, because the page is
untrusted (anyone on the Wi-Fi with the token can send any request they like):

  - blackout:          can only be turned ON (releasing it is the laptop's job)
  - master_brightness: can only go DOWN (clamped to [0, current])
  - strobe_cap:        can only go DOWN (clamped to [0, current])
  - laser_enable:      can only be set False (disarm), never armed

A request that would raise anything is refused (403) and changes nothing.
Writes are plain attribute assignments on ManualParams, the same thread-safety
model as the desktop console (ui/console.py) and the metronome's
control_callback: the show engine reads each field once per tick. Each new
value is computed as min(current, requested) at write time, so a race with the
laptop can only ever leave the show dimmer, not brighter.

Stdlib only (http.server on a daemon thread): no new dependencies, nothing that
can stop the show from starting. Opt-in via `--phone [PORT]`.
"""

from __future__ import annotations

import hmac
import json
import logging
import math
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .page import PAGE_HTML

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
TOKEN_HEADER = "X-LiveReact-Key"
# No 0/O, 1/I/L: the token may be read off a laptop screen and typed by hand.
TOKEN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TOKEN_LENGTH = 6
MAX_BODY_BYTES = 2048  # every legal request is a few dozen bytes


def make_token(length: int = TOKEN_LENGTH) -> str:
    """A short random access code, generated fresh at every launch."""
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


class _BadRequest(Exception):
    """Malformed input: answered with 400, never allowed past the handler."""


def _number(value: Any) -> float:
    # bool is an int subclass in Python; `true` is not a brightness.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _BadRequest("value must be a number")
    try:
        v = float(value)
    except OverflowError:  # a huge JSON integer
        raise _BadRequest("value must be a finite number") from None
    if not math.isfinite(v):
        raise _BadRequest("value must be a finite number")
    return v


class PhoneConsole:
    """The phone's view of the app: what it may read, and the only writes it
    may make. Holds no network code, so the safety rules are testable alone."""

    # (action name, ManualParams field) for the two "lower only" numbers.
    _LEVELS = {"brightness": "master_brightness", "strobe_cap": "strobe_cap"}

    def __init__(self, app: Any) -> None:
        self.app = app
        self.manual = app.manual
        # action -> wall-clock time it was last applied from a phone, so the
        # page can show "Blackout pressed 40 s ago" to everyone holding it.
        self.used: dict[str, float] = {}
        self._used_lock = threading.Lock()  # handler threads run concurrently

    # ------------------------------------------------------------------ read
    def state(self) -> dict[str, Any]:
        app = self.app
        m = self.manual
        snap = app.show_state.snapshot()
        writer = app.writer
        bpm = snap.bpm if math.isfinite(snap.bpm) else None
        silence = getattr(app.show_engine, "silence", None)
        return {
            "ok": True,
            "bucket": snap.bucket,
            "bpm": round(bpm, 1) if bpm is not None else None,
            "scene": app.phrase_engine.current_scene_name,
            "blackout": bool(m.blackout),
            "auto_blackout": bool(getattr(silence, "active", False)),
            "master_brightness": float(m.master_brightness),
            "strobe_cap": float(m.strobe_cap),
            "laser_enable": bool(m.laser_enable),
            # Same test as the console's DMX dot: a real backend that opened.
            "dmx_open": bool(writer.is_open and writer.backend.name != "null-log"),
            "used": self.used_copy(),
            "server_time": time.time(),
        }

    def used_copy(self) -> dict[str, float]:
        with self._used_lock:
            return dict(self.used)

    # ------------------------------------------------------------------ write
    def apply(self, body: Any, client: str = "?") -> tuple[int, dict[str, Any]]:
        """Apply one phone request. Returns (HTTP status, JSON body).

        Never raises for bad input: anything malformed is a 400, anything that
        would raise intensity is a 403, and neither touches ManualParams."""
        try:
            return self._apply(body, client)
        except _BadRequest as e:
            return 400, {"ok": False, "error": str(e)}

    def _apply(self, body: Any, client: str) -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            raise _BadRequest("body must be a JSON object")
        action = body.get("action")
        m = self.manual

        if action == "blackout":
            value = body.get("value", True)
            if not isinstance(value, bool):
                raise _BadRequest("blackout value must be true")
            if not value:
                return self._refuse(action, client, "The phone can only turn blackout ON. "
                                    "Release it on the laptop (B key or the console button).")
            m.blackout = True
            return self._done(action, client, "blackout ON")

        if action == "lasers":
            value = body.get("value", False)
            if not isinstance(value, bool):
                raise _BadRequest("lasers value must be false")
            if value:
                return self._refuse(action, client, "The phone can only DISARM lasers. "
                                    "Arming is the laptop's job (L key or the console checkbox).")
            m.laser_enable = False
            return self._done(action, client, "lasers disarmed")

        if action in self._LEVELS:
            field = self._LEVELS[action]
            current = float(getattr(m, field))
            if "value" in body:
                requested = _number(body["value"])
            elif "by" in body:
                requested = current + _number(body["by"])
            else:
                raise _BadRequest("give 'value' (0..1) or 'by' (a negative step)")
            if requested > current:
                return self._refuse(action, client, f"The phone can only lower {action.replace('_', ' ')} "
                                    f"(now {current:.0%}, asked for {requested:.0%}).")
            # Re-read at write time: if the laptop moved it since `current`
            # was read, min() keeps whichever is lower. (Without a lock shared
            # with the laptop, a laptop write landing between this read and
            # the assignment can still be overwritten, but only by a value no
            # higher than what the phone saw a moment ago.)
            setattr(m, field, min(float(getattr(m, field)), max(0.0, requested)))
            return self._done(action, client, f"{field} -> {getattr(m, field):.2f}")

        raise _BadRequest(f"unknown action {action!r}")

    def _done(self, action: str, client: str, what: str) -> tuple[int, dict[str, Any]]:
        with self._used_lock:
            self.used[action] = time.time()
        log.info("Phone console (%s): %s", client, what)
        return 200, {"ok": True, "state": self.state()}

    def _refuse(self, action: Any, client: str, why: str) -> tuple[int, dict[str, Any]]:
        log.warning("Phone console (%s): refused %r, it would raise intensity", client, action)
        return 403, {"ok": False, "error": why}


class _Server(ThreadingHTTPServer):
    # Handler threads are daemons and server_close never joins them, so a
    # stalled phone can never hold up App.shutdown().
    daemon_threads = True
    block_on_close = False
    # On Windows SO_REUSEADDR lets a second process silently share a busy
    # port; elsewhere it only lets a relaunch (tools/run_show.sh) re-bind
    # straight away past TIME_WAIT.
    allow_reuse_address = sys.platform != "win32"

    console: PhoneConsole
    token: str

    # Each connection gets a thread, and its headers are read before the token
    # can be checked; cap them so a flood from someone on the Wi-Fi cannot
    # pile up threads on the show laptop. A phone needs one or two at a time.
    MAX_CONNECTIONS = 16

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._slots = threading.BoundedSemaphore(self.MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address) -> None:  # type: ignore[no-untyped-def]
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)  # drop it; the page simply retries
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:  # type: ignore[no-untyped-def]
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "LiveReact"
    sys_version = ""
    # A client that connects and then stalls is dropped instead of pinning a
    # thread for ever.
    timeout = 5.0

    # ------------------------------------------------------------------ routes
    def do_GET(self) -> None:
        self._guarded(self._get)

    def do_POST(self) -> None:
        self._guarded(self._post)

    def _get(self, path: str) -> None:
        if path in ("/", "/index.html"):
            self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send_json(200, self.server.console.state())
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def _post(self, path: str) -> None:
        if path != "/api/action":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            body = self._read_json()
        except _BadRequest as e:
            self._send_json(400, {"ok": False, "error": str(e)})
            return
        status, payload = self.server.console.apply(body, client=self.client_address[0])
        self._send_json(status, payload)

    # ------------------------------------------------------------------ plumbing
    def _guarded(self, route) -> None:
        """Token check first, on every route; then the route. Nothing a client
        sends may escape as an exception (socketserver would survive it, but a
        clean 500 and a log line are easier to read at a gig)."""
        try:
            parts = urlsplit(self.path)
            given = self.headers.get(TOKEN_HEADER) or parse_qs(parts.query).get("k", [""])[0]
            if not self._token_ok(given):
                self._send_json(403, {"ok": False, "error": "missing or wrong access code"})
                return
            route(parts.path)
        except Exception:  # noqa: BLE001 - the server thread must outlive any request
            log.exception("Phone console: request failed")
            try:
                self._send_json(500, {"ok": False, "error": "internal error"})
            except Exception:  # noqa: BLE001 - the client may already be gone
                pass

    def _token_ok(self, given: str) -> bool:
        if not given:
            return False
        # Case-insensitive so a hand-typed code works; constant-time compare.
        return hmac.compare_digest(given.strip().upper().encode("utf-8"),
                                   self.server.token.encode("utf-8"))

    def _read_json(self) -> Any:
        raw_len = self.headers.get("Content-Length")
        try:
            length = int(raw_len) if raw_len is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            raise _BadRequest("Content-Length required")
        if length > MAX_BODY_BYTES:
            raise _BadRequest("body too large")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise _BadRequest("body truncated")

        def no_constants(name: str) -> Any:  # NaN / Infinity are not JSON
            raise _BadRequest(f"{name} is not allowed")

        try:
            return json.loads(raw.decode("utf-8"), parse_constant=no_constants)
        except (UnicodeDecodeError, ValueError, RecursionError) as e:
            raise _BadRequest(f"malformed JSON: {e}") from None

    def _send_json(self, status: int, obj: dict[str, Any]) -> None:
        self._send(status, json.dumps(obj, allow_nan=False).encode("utf-8"), "application/json")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")  # the URL carries the token
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # The default writes every poll to stderr; keep it out of the show log.
        log.debug("Phone console %s: " + format, self.client_address[0], *args)


def lan_ipv4_addresses() -> list[str]:
    """Best-effort LAN IPv4 addresses a phone could reach, most likely first.

    The UDP connect trick asks the OS which local address routes to the
    internet (no packet is sent); the hostname lookup adds any others.
    Loopback and link-local (the Pro DJ Link NIC) are left out: a phone on
    the Wi-Fi cannot reach them."""
    found: list[str] = []

    def add(ip: str) -> None:
        if ip and ip not in found and not ip.startswith(("127.", "169.254.", "0.")):
            found.append(ip)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(str(info[4][0]))
    except OSError:
        pass
    return found


class PhoneServer:
    """Owns the listening socket and its daemon thread.

    The constructor binds (raising OSError if the port is busy) so the caller
    can decide to carry on without it; start() serves; stop() never blocks for
    more than `timeout` seconds."""

    def __init__(self, console: PhoneConsole, port: int = DEFAULT_PORT,
                 host: str = "0.0.0.0", token: str | None = None) -> None:
        self.token = token or make_token()
        self._httpd = _Server((host, port), _Handler)
        self._httpd.console = console
        self._httpd.token = self.token
        self.port: int = self._httpd.server_address[1]
        self.urls: list[str] = []
        self._stopped = False
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.25},
            name="phone-console", daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        # Address discovery can block on a slow hostname lookup; keep it off
        # the caller's thread so the show never waits on it.
        threading.Thread(target=self._announce, name="phone-console-url", daemon=True).start()

    def _announce(self) -> None:
        ips = lan_ipv4_addresses()
        if not ips:
            log.warning("Phone console listening on port %d, but no LAN address was found; "
                        "is the laptop on the venue Wi-Fi? Access code: %s", self.port, self.token)
            return
        self.urls = [f"http://{ip}:{self.port}/?k={self.token}" for ip in ips]
        for url in self.urls:
            log.info("Phone console: open %s on a phone on the same Wi-Fi "
                     "(it can only blackout, dim, cap strobe, disarm lasers)", url)

    def stop(self, timeout: float = 2.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._thread.is_alive():
            # shutdown() waits for serve_forever's next poll (<= 0.25 s); run it
            # on a helper so even a wedged loop cannot hang App.shutdown().
            stopper = threading.Thread(target=self._httpd.shutdown, name="phone-console-stop", daemon=True)
            stopper.start()
            stopper.join(timeout)
            if stopper.is_alive():
                log.warning("Phone console did not stop within %.1f s; abandoning it", timeout)
        try:
            self._httpd.server_close()
        except OSError:
            log.exception("Phone console: error closing the socket")
