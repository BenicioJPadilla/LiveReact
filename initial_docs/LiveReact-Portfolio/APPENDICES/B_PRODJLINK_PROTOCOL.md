# B — Pro DJ Link Protocol Notes

Pro DJ Link is Pioneer DJ's proprietary networking protocol for sharing musical state between DJ gear. It is **undocumented officially** — the entire third-party ecosystem (DeepSymmetry/dysentery, prodjlink, Beat Link, etc.) is the result of reverse engineering. For LiveReact we use the `python-prodj-link` library, which abstracts the protocol details. This appendix describes only what you need to know to debug issues.

---

## What Pro DJ Link is

A set of UDP broadcasts on a local network. Pioneer gear (CDJs, XDJs, DJM mixers) and the Rekordbox software all speak it. Each device broadcasts its own state and listens for others'. There is no central master — devices negotiate sync roles among themselves.

Multiple packet types share the protocol:
- **Keep-alive announcements** — every ~1.5 sec, each device says "I exist, I'm at IP X, my name is Y."
- **Beat packets** — broadcast on every beat, containing BPM, beat-within-bar, and on-air status.
- **Status packets** — broadcast continuously (multiple times per second), containing track position, loop state, deck state, master assignment.

---

## Network setup

Pro DJ Link runs over **standard Ethernet**. No special networking gear is needed — just a direct cable (or hub) between the DJ device(s) and the listening computer.

For LiveReact's single-XDJ setup, the simplest topology is:

```
XDJ-XZ  ←──(Ethernet)──→  MacBook
              (USB-C to Ethernet adapter on the MacBook side)
```

### IP configuration

The XDJ-XZ and the MacBook need to be on the same subnet. Two ways:

**Option 1 — Auto-IP (link-local, easiest)**

When two devices are connected with no DHCP server on the network, both fall back to link-local IPs in the `169.254.0.0/16` range. This usually "just works" on macOS — within ~20 seconds of cable connect, the MacBook's Ethernet interface will have a `169.254.x.x` IP, and the XDJ will have one too. They'll be on the same subnet automatically.

To verify on macOS:

```bash
ifconfig | grep "inet 169.254"
```

Should show your Ethernet interface (often `en7` or similar with a USB-C-to-Ethernet adapter).

**Option 2 — Static IPs (more reliable for production)**

Configure both devices with static IPs in the same subnet. For example:
- MacBook: `192.168.10.10` / `255.255.255.0`
- XDJ-XZ: `192.168.10.20` / `255.255.255.0`

On the XDJ-XZ: Menu → Utility → LAN Settings.

Static is more reliable in environments where you might accidentally have other networking active (a venue Wi-Fi, a virtual machine bridge).

### Verifying connectivity

Before testing with code, verify the XDJ is broadcasting:

```bash
# Listen for any traffic on the Pro DJ Link port
sudo tcpdump -i en7 port 50000 or port 50001 or port 50002
```

You should see UDP packets every second or two when the XDJ is powered on with Link enabled.

---

## What `python-prodj-link` exposes

The library wraps the protocol and gives you a `ProDjLink` object that you can subscribe to. Approximate API (check the library's actual docs for current syntax):

```python
from prodjlink import ProDjLink

pdl = ProDjLink(interface='en7')  # or auto-detect
pdl.start()

# Subscribe to beats
@pdl.on('beat')
def on_beat(event):
    print(event.player_number, event.bpm, event.beat)  # 1, 124.0, 3

# Subscribe to status
@pdl.on('status')
def on_status(event):
    print(event.player_number, event.track_position, event.on_air, event.master)

# Or poll
state = pdl.state_of_player(1)  # snapshot dict
```

The events that matter for LiveReact:

| Event | Provides |
|---|---|
| `beat` | `player_number`, `bpm`, `beat_within_bar` (1..4), `pitch` |
| `status` | `player_number`, `track_position_ms`, `on_air`, `master`, `loop_active`, `loop_size`, `play_state` |
| `announcement` | When a new player joins the network |

---

## Per-deck state

The XDJ-XZ has **4 decks** (it's an all-in-one with 4 internal channels). Each deck is a "player" in PDL terms with a player_number (1, 2, 3, 4). For most DJ sets you'll see traffic on decks 1 and 2 (the primary ones); decks 3 and 4 are the layered/sampler channels and may be quiet.

LiveReact's ShowState fields like `bpm`, `beat`, `bar` reflect the **master deck's** state. Track which player is master via the `status` event's `master` flag.

For transition detection, you need state from **both active decks simultaneously**. The Transition Engine reads:
- `on_air_deck` — which deck is currently audible (changes during a mix)
- `bpm` of master deck — for the primary clock
- `bpm` of opposite deck — for "are the BPMs aligned" checks

---

## Beat phase derivation

PDL beat packets arrive **on each beat** — so at 120 BPM you get 2 packets per second. For visual smoothness, you need sub-beat phase information (60+ updates per second). The architecture's `LocalMetronome` handles this:

```
On PDL beat arrival:
    metronome.last_beat_at = now
    metronome.last_beat_phase = 0.0

Each rendering tick:
    phase = (now - metronome.last_beat_at) / (60.0 / current_bpm)
    phase = phase % 1.0
```

Resync to PDL on every beat packet. Free-run if no packet arrives for >1 second.

---

## Bar phase

Bar tracking is **inferred**, not transmitted directly in beat packets. The protocol provides `beat_within_bar` (1, 2, 3, 4) but not the bar count.

For Phrase Engine logic (rotate every 16 bars), maintain a local bar counter:

```python
prev_beat = 1
bar_counter = 0

def on_beat(event):
    nonlocal prev_beat, bar_counter
    if event.beat_within_bar == 1 and prev_beat == 4:
        bar_counter += 1  # crossed a bar boundary
    prev_beat = event.beat_within_bar
```

Reset the counter when on_air changes, when a track loads, or on a long PDL silence (likely the music stopped or the cable was unplugged).

---

## Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `python-prodj-link` reports no players | Wrong network interface specified or no IP on the interface | Verify `ifconfig`, specify the correct interface name |
| Player appears then disappears every 30 seconds | Auto-IP cycling because of intermittent DHCP visibility | Configure static IPs |
| Beat packets arrive but `on_air` is always False | The XDJ's mixer routing isn't asserting on-air | Check XDJ master output is enabled |
| BPM jumps by ±1.0 randomly | Pitch fader on the XDJ being moved | Filter with low-pass smoothing or detect via the pitch field |
| All values are zero | Library subscribed before XDJ started broadcasting | Wait 5–10 seconds after XDJ boot before starting listener |
| BPM seems halved or doubled | Track tagged with half-time or double-time pattern | This is a Rekordbox-side analysis issue; accept it |

---

## Don't reinvent

It is tempting, after reading reverse-engineering docs, to write your own PDL parser. **Don't.** The protocol has many edge cases — handshake races, packet ordering quirks, deck-numbering oddities — that take months to discover and handle. Use `python-prodj-link`.

If you find a bug in the library, file an issue or fork. Don't rebuild from scratch.

---

## References

- `python-prodj-link` library: search PyPI / GitHub for the current canonical fork.
- DeepSymmetry's `dysentery` project (Clojure/Java) has the most thorough protocol documentation: https://github.com/Deep-Symmetry/dysentery
- Beat Link Trigger (a Pioneer-protocol app) has a useful field reference: https://github.com/Deep-Symmetry/beat-link-trigger

These references are protocol-level deep dives; you should not need to consult them unless `python-prodj-link` is missing a feature.
