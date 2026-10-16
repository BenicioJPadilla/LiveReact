# Bundled fonts

Both families are licensed under the SIL Open Font License 1.1; the full
licence for each is next to it (`OFL-InstrumentSans.txt`, `OFL-GeistMono.txt`).
Neither declares a Reserved Font Name.

| Files | Family | Source |
|---|---|---|
| `InstrumentSans-*.ttf` | Instrument Sans, normal width (400, 500, 600, 700) | `ofl/instrumentsans/InstrumentSans[wdth,wght].ttf` in github.com/google/fonts |
| `InstrumentSansCondensed-*.ttf` | Instrument Sans Condensed, wdth 75 (500, 600) | the same variable font |
| `GeistMono-*.ttf` | Geist Mono (400, 500, 600) | `ofl/geistmono/GeistMono[wght].ttf` in github.com/google/fonts |

These are static instances of the variable fonts (Qt stylesheets can't pick a
width axis). The Instrument Sans cuts also have the font's own `tnum`
substitutions written into the cmap, so every number in the console uses
tabular figures. Under the OFL these instances are Modified Versions and stay
under the same licence.
