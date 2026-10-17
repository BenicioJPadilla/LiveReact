"""The phone console's one page: inline HTML/CSS/JS, no external assets (the
venue Wi-Fi may have no internet), dark so it does not light up the booth, and
big touch targets for a thumb in the dark.

The page is a convenience, not a safety layer: every rule it seems to enforce
(buttons greyed out when they would not lower anything) is enforced again on
the server (remote/server.py). Text from the server is only ever set with
textContent, never parsed as HTML.
"""

from __future__ import annotations

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="theme-color" content="#000000">
<title>LiveReact phone</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { margin: 0; padding: 12px; background: #000; color: #ccc;
         font: 17px/1.35 -apple-system, system-ui, sans-serif; }
  #status { font-size: 28px; font-weight: 700; padding: 14px; border-radius: 12px;
            background: #161616; color: #eee; text-align: center; }
  #status.dark { background: #5a0000; color: #fff; }
  #status.lost { background: #4a3a00; color: #fff; }
  #dmx { text-align: center; color: #fc6; font-weight: 700; margin-top: 6px; }
  #scene { text-align: center; color: #888; margin: 6px 0 12px; min-height: 1.3em; }
  .row { display: flex; gap: 10px; margin: 10px 0; }
  .row > * { flex: 1; min-width: 0; }
  .read { background: #111; border-radius: 10px; padding: 8px; text-align: center; }
  .read b { display: block; font-size: 22px; color: #eee; }
  .read small { color: #777; }
  h2 { font-size: 14px; letter-spacing: .08em; text-transform: uppercase; color: #777;
       margin: 18px 0 4px; }
  button { font: inherit; font-weight: 700; color: #eee; background: #222; border: 0;
           border-radius: 12px; min-height: 64px; padding: 10px; width: 100%; }
  button:active { background: #444; }
  button:disabled { color: #555; background: #111; }
  #blackout { min-height: 110px; font-size: 30px; background: #a00000; color: #fff; }
  #blackout:disabled { background: #3a0000; color: #c88; }
  #disarm { background: #4b2a00; }
  #strobeoff { background: #4b2a00; }
  #strobe { text-align: center; font-weight: 700; padding: 8px; border-radius: 10px; margin-top: 6px; }
  #strobe.off { background: #003a1a; color: #8f8; }
  #strobe.on { background: #3a2a00; color: #fc6; }
  #note { color: #f99; text-align: center; min-height: 1.3em; margin: 8px 0; }
  #msg { text-align: center; min-height: 1.3em; color: #fc6; margin: 8px 0; }
  #used { color: #888; font-size: 15px; }
  footer { color: #555; font-size: 13px; margin-top: 18px; text-align: center; }
</style>
</head>
<body>
<div id="status">Connecting...</div>
<div id="dmx"></div>
<div id="strobe"></div>
<div id="scene"></div>

<button id="blackout">BLACKOUT</button>
<div id="note"></div>

<div class="row">
  <div class="read"><b id="r-bright">-</b><small>brightness</small></div>
  <div class="read"><b id="r-strobe">-</b><small>strobe</small></div>
  <div class="read"><b id="r-laser">-</b><small>lasers</small></div>
</div>

<h2>Dim</h2>
<div class="row">
  <button data-act="brightness" data-by="-0.1">-10 %</button>
  <button data-act="brightness" data-value="0.5">50 %</button>
  <button data-act="brightness" data-value="0.25">25 %</button>
</div>

<h2>Strobe</h2>
<div class="row"><button id="strobeoff">STROBE OFF</button></div>
<div class="row">
  <button data-act="strobe_cap" data-value="0.5">Cap 50 %</button>
</div>

<h2>Lasers</h2>
<div class="row"><button id="disarm">DISARM LASERS</button></div>

<div id="msg"></div>
<h2>Used from the phone</h2>
<div id="used">Nothing yet.</div>

<footer>This page can only make the show safer: blackout on, dim, cap or
switch off strobe, disarm lasers. Undoing any of it is done on the laptop.</footer>

<script>
"use strict";
var KEY = new URLSearchParams(location.search).get("k") || "";
var LABELS = { blackout: "Blackout", brightness: "Dim", strobe_cap: "Strobe cap", strobe: "Strobe off",
              lasers: "Disarm lasers" };
var last = null, lastOk = 0, skew = 0;
function $(id) { return document.getElementById(id); }
function pct(x) { return Math.round(x * 100) + " %"; }

function api(path, body) {
  var opts = { headers: { "X-LiveReact-Key": KEY }, cache: "no-store" };
  if (body) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  return fetch(path, opts).then(function (r) {
    return r.json().catch(function () { return { ok: false, error: "HTTP " + r.status }; });
  });
}

function render(s) {
  last = s; lastOk = Date.now();
  skew = Date.now() / 1000 - s.server_time;
  var st = $("status");
  var dark = s.blackout || s.auto_blackout;
  if (s.blackout) st.textContent = "BLACKOUT";
  else if (s.auto_blackout) st.textContent = "DARK (no music)";
  else if (s.freeze) st.textContent = "FROZEN (holding a frame)";
  else st.textContent = String(s.bucket).toUpperCase() + (s.bpm ? " \\u00b7 " + s.bpm.toFixed(0) + " BPM" : "");
  $("dmx").textContent = s.dmx_open ? "" : "DMX not connected (lights are not being driven)";
  st.className = dark ? "dark" : "";
  $("scene").textContent = s.scene || "";
  $("r-bright").textContent = pct(s.master_brightness);
  // A missing strobe_allowed (an older laptop build) reads as "not known
  // to be off", so the banner never claims an off it can't confirm.
  var strobeOff = s.strobe_allowed === false;
  $("r-strobe").textContent = strobeOff ? "OFF" : pct(s.strobe_cap);
  $("strobe").textContent = strobeOff ? "STROBE OFF: no strobe at all, automatic included"
                                      : "Strobe allowed (up to " + pct(s.strobe_cap) + ")";
  $("strobe").className = strobeOff ? "off" : "on";
  $("strobeoff").disabled = strobeOff;
  $("strobeoff").textContent = strobeOff ? "Strobe is off" : "STROBE OFF";
  $("r-laser").textContent = s.laser_enable ? "ARMED" : "off";

  var b = $("blackout");
  b.disabled = s.blackout;
  b.textContent = s.blackout ? "BLACKED OUT" : "BLACKOUT";
  $("note").textContent = s.blackout ? "Release it on the laptop: B key or the console's BLACKOUT button." : "";
  $("disarm").disabled = !s.laser_enable;
  $("disarm").textContent = s.laser_enable ? "DISARM LASERS" : "Lasers disarmed";

  // Grey out the dim / strobe buttons that would not lower anything now.
  // The server refuses those anyway; this just saves a confusing tap.
  var btns = document.querySelectorAll("button[data-act]");
  for (var i = 0; i < btns.length; i++) {
    var el = btns[i], cur = el.dataset.act === "brightness" ? s.master_brightness : s.strobe_cap;
    el.disabled = el.dataset.by !== undefined ? cur <= 0 : parseFloat(el.dataset.value) >= cur;
  }

  var parts = [], now = Date.now() / 1000 - skew;
  for (var k in s.used) {
    var ago = Math.max(0, Math.round(now - s.used[k]));
    parts.push((LABELS[k] || k) + " " + (ago < 90 ? ago + " s" : Math.round(ago / 60) + " min") + " ago");
  }
  $("used").textContent = parts.length ? parts.join(" \\u00b7 ") : "Nothing yet.";
}

function send(body) {
  $("msg").textContent = "...";
  api("/api/action", body).then(function (r) {
    $("msg").textContent = r.ok ? "Done." : (r.error || "Refused.");
    if (r.state) render(r.state);
  }).catch(function () { $("msg").textContent = "No connection to the laptop."; });
}

function poll() {
  api("/api/state").then(function (s) {
    if (s.ok) { render(s); return; }
    lastOk = Date.now();  // the laptop answered, it just said no (wrong code?)
    $("status").textContent = s.error || "Refused";
    $("status").className = "lost";
  }).catch(function () {}).then(function () {
    if (Date.now() - lastOk > 3000) {
      $("status").textContent = "NO CONNECTION to the laptop";
      $("status").className = "lost";
    }
    setTimeout(poll, 1000);
  });
}

$("blackout").onclick = function () { send({ action: "blackout", value: true }); };
$("disarm").onclick = function () { send({ action: "lasers", value: false }); };
$("strobeoff").onclick = function () { send({ action: "strobe", value: false }); };
var btns = document.querySelectorAll("button[data-act]");
for (var i = 0; i < btns.length; i++) {
  btns[i].onclick = function () {
    var body = { action: this.dataset.act };
    if (this.dataset.by !== undefined) body.by = parseFloat(this.dataset.by);
    else body.value = parseFloat(this.dataset.value);
    send(body);
  };
}
poll();
</script>
</body>
</html>
"""
