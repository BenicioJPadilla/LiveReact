"""Phone console (remote/): the token gate, and the invariant that a phone can
only ever make the show safer -- blackout on, dim, strobe cap down, lasers
disarmed -- never the reverse."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

import pytest

from livereact.__main__ import _parse_args
from livereact.app import App, AppConfig
from livereact.remote import PhoneConsole, PhoneServer, make_token
from livereact.remote.server import TOKEN_ALPHABET, TOKEN_HEADER


@pytest.fixture
def app():
    # Demo mode arms the lasers, so "disarm" has something to do.
    return App(AppConfig(demo=True, config_path=None))


@pytest.fixture(scope="module")
def _server():
    # One server for the module (stopping one waits for its poll tick);
    # each test points it at a fresh App below.
    server = PhoneServer(PhoneConsole(App(AppConfig(demo=True, config_path=None))),
                         port=0, host="127.0.0.1")
    server.start()
    yield server
    server.stop()


@pytest.fixture
def served(app, _server):
    _server._httpd.console = PhoneConsole(app)
    return app, _server


def _request(server, path, body=None, token="__right__", raw=None, query_token=None):
    url = f"http://127.0.0.1:{server.port}{path}"
    if query_token is not None:
        url += f"?k={query_token}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if token is not None:
        req.add_header(TOKEN_HEADER, server.token if token == "__right__" else token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _json(server, path, body=None, **kw):
    status, raw = _request(server, path, body, **kw)
    return status, json.loads(raw)


def _snapshot(m):
    return (m.blackout, m.master_brightness, m.strobe_cap, m.laser_enable)


# ---------------------------------------------------------------- token gate

def test_token_is_short_and_unambiguous():
    tok = make_token()
    assert len(tok) == 6 and all(c in TOKEN_ALPHABET for c in tok)
    assert not set("01OIL") & set(TOKEN_ALPHABET)


@pytest.mark.parametrize("path", ["/", "/api/state", "/nope", "/favicon.ico"])
def test_every_get_route_needs_the_token(served, path):
    _, server = served
    assert _request(server, path, token=None)[0] == 403
    assert _request(server, path, token="WRONG1")[0] == 403


def test_action_without_token_changes_nothing(served):
    app, server = served
    before = _snapshot(app.manual)
    status, _ = _json(server, "/api/action", {"action": "blackout"}, token=None)
    assert status == 403
    assert _request(server, "/api/action", {"action": "blackout"}, token="ZZZZZZ")[0] == 403
    assert _snapshot(app.manual) == before


def test_page_served_with_query_token(served):
    _, server = served
    status, body = _request(server, "/", token=None, query_token=server.token.lower())  # typed by hand
    assert status == 200
    assert b"BLACKOUT" in body and b"<script" in body
    assert b"http://" not in body and b"https://" not in body  # no external assets


# ---------------------------------------------------------------- allowed actions

def test_blackout_on(served):
    app, server = served
    status, body = _json(server, "/api/action", {"action": "blackout"})
    assert status == 200 and body["state"]["blackout"] is True
    assert app.manual.blackout is True


def test_dim_to_value_and_by_step(served):
    app, server = served
    assert _json(server, "/api/action", {"action": "brightness", "value": 0.5})[0] == 200
    assert app.manual.master_brightness == 0.5
    assert _json(server, "/api/action", {"action": "brightness", "by": -0.1})[0] == 200
    assert app.manual.master_brightness == pytest.approx(0.4)
    assert _json(server, "/api/action", {"action": "brightness", "value": -3})[0] == 200
    assert app.manual.master_brightness == 0.0  # clamped to [0, current]


def test_strobe_cap_down_and_off(served):
    app, server = served
    assert _json(server, "/api/action", {"action": "strobe_cap", "value": 0.5})[0] == 200
    assert app.manual.strobe_cap == 0.5
    assert _json(server, "/api/action", {"action": "strobe_cap", "value": 0})[0] == 200
    assert app.manual.strobe_cap == 0.0


def test_disarm_lasers(served):
    app, server = served
    assert app.manual.laser_enable is True
    assert _json(server, "/api/action", {"action": "lasers", "value": False})[0] == 200
    assert app.manual.laser_enable is False


def test_used_controls_are_reported(served):
    _, server = served
    _json(server, "/api/action", {"action": "lasers"})
    _, state = _json(server, "/api/state")
    assert set(state["used"]) == {"lasers"}


# ---------------------------------------------------------------- refused: raises intensity

def test_every_raise_is_refused_and_changes_nothing(app):
    console = PhoneConsole(app)
    m = app.manual
    m.blackout, m.master_brightness, m.strobe_cap, m.laser_enable = True, 0.5, 0.3, False
    raises = [
        {"action": "blackout", "value": False},
        {"action": "brightness", "value": 0.6},
        {"action": "brightness", "value": 1.0},
        {"action": "brightness", "by": 0.1},
        {"action": "strobe_cap", "value": 0.31},
        {"action": "strobe_cap", "by": 0.5},
        {"action": "lasers", "value": True},
    ]
    before = _snapshot(m)
    for body in raises:
        status, payload = console.apply(body)
        assert status == 403, body
        assert payload["ok"] is False and payload["error"]
        assert _snapshot(m) == before, body
    assert console.used == {}


def test_raise_refused_over_http(served):
    app, server = served
    app.manual.master_brightness = 0.5
    status, body = _json(server, "/api/action", {"action": "brightness", "value": 0.9})
    assert status == 403 and "lower" in body["error"]
    assert app.manual.master_brightness == 0.5


def test_laptop_raise_after_phone_dim_uses_the_current_value(app):
    console = PhoneConsole(app)
    console.apply({"action": "brightness", "value": 0.3})
    assert app.manual.master_brightness == 0.3
    app.manual.master_brightness = 0.9   # the laptop slider raises it again
    # -10 % is now from the laptop's 0.9, not the phone's stale 0.3...
    assert console.apply({"action": "brightness", "by": -0.1})[0] == 200
    assert app.manual.master_brightness == pytest.approx(0.8)
    # ...and an absolute value between the two is a legal lowering.
    assert console.apply({"action": "brightness", "value": 0.5})[0] == 200
    assert app.manual.master_brightness == 0.5


# ---------------------------------------------------------------- bad input

@pytest.mark.parametrize("raw", [
    b"{not json", b"", b"\xff\xfe", b"[]", b"42", b"null",
    b'{"action": "brightness", "value": NaN}',
    b'{"action": "brightness", "value": 1e999}',
    b'{"action": "brightness", "value": 1' + b"0" * 400 + b"}",
    b'{"action": "brightness", "value": "0.1"}',
    b'{"action": "brightness", "value": true}',
    b'{"action": "brightness"}',
    b'{"action": "blackout", "value": "yes"}',
    b'{"action": "lasers", "value": 0}',
    b'{"action": "release_blackout"}',
    b'{"action": "laser_arm"}',
    b'{"value": 1}',
    b"[" * 1500,
])
def test_malformed_or_unknown_is_400_and_changes_nothing(served, raw):
    app, server = served
    before = _snapshot(app.manual)
    status, body = _json(server, "/api/action", raw=raw)
    assert status == 400 and body["ok"] is False
    assert _snapshot(app.manual) == before
    assert _request(server, "/api/state")[0] == 200  # the server is still up


def test_oversized_body_is_rejected(served):
    _, server = served
    assert _request(server, "/api/action", raw=b"{" + b" " * 5000 + b"}")[0] == 400


def test_bad_content_length_does_not_kill_the_server(served):
    _, server = served
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
        s.sendall(b"POST /api/action HTTP/1.0\r\n" + TOKEN_HEADER.encode() + b": "
                  + server.token.encode() + b"\r\nContent-Length: -5\r\n\r\n")
        assert b" 400 " in s.recv(4096).split(b"\r\n")[0]
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
        s.sendall(b"garbage\r\n\r\n")
        s.recv(4096)
    assert _request(server, "/api/state")[0] == 200


# ---------------------------------------------------------------- state

def test_state_shape(served):
    app, server = served
    status, s = _json(server, "/api/state")
    assert status == 200
    assert set(s) >= {"bucket", "bpm", "scene", "blackout", "master_brightness", "strobe_cap",
                      "laser_enable", "dmx_open", "server_time", "used"}
    assert s["bucket"] == app.show_state.snapshot().bucket
    assert s["scene"] == app.phrase_engine.current_scene_name
    assert s["dmx_open"] is False  # demo: the null-log backend never counts as DMX
    assert abs(s["server_time"] - time.time()) < 5
    assert isinstance(s["master_brightness"], float) and isinstance(s["laser_enable"], bool)


# ---------------------------------------------------------------- App wiring

def test_cli_flag():
    assert _parse_args([]).phone is None
    assert _parse_args(["--phone"]).phone == 8765
    assert _parse_args(["--phone", "9000", "--demo"]).phone == 9000
    with pytest.raises(SystemExit):
        _parse_args(["--phone", "70000"])


def test_app_without_phone_starts_no_server():
    app = App(AppConfig(demo=True, config_path=None, duration=0.01))
    app.start()
    try:
        assert app.phone is None and app.phone_url is None
    finally:
        app.shutdown()


def test_app_serves_and_shuts_down_cleanly():
    app = App(AppConfig(demo=True, config_path=None, phone_port=0))
    app.start()
    try:
        server = app.phone
        assert server is not None
        assert _request(server, "/api/state")[0] == 200
        deadline = time.monotonic() + 10
        while not server.urls and time.monotonic() < deadline:
            time.sleep(0.02)  # discovery runs on its own thread
        if server.urls:  # a CI box may have no LAN address at all
            assert app.phone_url == server.urls[0] and f"?k={server.token}" in app.phone_url
    finally:
        t0 = time.monotonic()
        app.shutdown()
    assert time.monotonic() - t0 < 5
    assert not server._thread.is_alive()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", server.port), timeout=1).close()


def test_busy_port_does_not_stop_the_show():
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen()
    try:
        app = App(AppConfig(demo=True, config_path=None, phone_port=blocker.getsockname()[1]))
        app.start()
        try:
            assert app.phone is None
            assert app.writer.is_alive()
        finally:
            app.shutdown()
    finally:
        blocker.close()


def test_stop_without_start_does_not_hang(app):
    server = PhoneServer(PhoneConsole(app), port=0, host="127.0.0.1")
    t0 = time.monotonic()
    server.stop()
    server.stop()  # idempotent
    assert time.monotonic() - t0 < 1


def test_connection_flood_is_capped_and_recovers(served):
    _, server = served
    # Idle connections that never send a request each hold a handler thread.
    idle = [socket.create_connection(("127.0.0.1", server.port), timeout=5) for _ in range(40)]
    try:
        time.sleep(0.2)
        assert server._httpd._slots._value == 0  # capped, not 40 threads
    finally:
        for s in idle:
            s.close()
    deadline = time.monotonic() + 5
    status = None
    while time.monotonic() < deadline:
        try:
            status = _request(server, "/api/state")[0]
            break
        except OSError:
            time.sleep(0.05)
    assert status == 200
