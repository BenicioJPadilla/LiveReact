# Laser channel findings (Shehds 3W, 12-channel mode)

The evidence trail behind `fixtures/profiles.py`'s `Laser` constants.
`tools/laser_probe.py` appends a row per hold; add rows by hand for anything
seen another way. Only what is written here as SEEN on the real unit is
verified -- the QLC+ fixture file's names have been wrong before.

Verified so far (2026-09-06, isolated channel probing; see the `Laser`
docstring): CH1 42-83 manual; CH2=118 flattens the circle into a line;
CH3=0 held throughout; CH7 128-255 sweep speed (0-127 untested); CH9 must be
0 (any other value self-animates the size); CH11=190 turns the outline into
dots; CH12 green (32-39) confirmed, the other bands inferred from the file.

Open questions for the bench session (TESTING.md Test 6): CH11 < 128 = a
solid outline? CH3 sub-patterns inside the CH2=118 group = a curvy line?
CH7 0-127 = a still line at a position? CH4 0-127 = a rotated line? CH8
0-127 = vertical position (beam HEIGHT: this one matters for the 2.7 m
plane)? CH12 64-127 = colours drifting on their own, 128-191 = a rainbow
along the line? CH10 = "painting" speed?

| when | CH1..CH12 | note |
|---|---|---|
| 2026-09-06 | `60,118,0,0,0,0,128,0,0,0,190,35` | the verified dotted line, slowest sweep, green -- "success... this looks really good" |
| 2026-09-06 | `60,118,0,0,0,0,64,0,0,0,190,35` | CH7=64 (static half) during isolation: NOT assessed -- what the line did at 64 was never written down |
| 2026-09-06 | `60,118,0,0,0,0,128,0,128,0,190,35` | CH9=128: size grows steadily on its own (file said "static zoom") |
| 2026-09-06 | `60,118,0,0,0,0,128,0,64,0,190,35` | CH9=64: size shrinks steadily |
| 2026-09-06 | `60,118,0,0,0,0,128,0,96,0,190,35` | CH9=96: sawtooth -- shrink then snap back |
