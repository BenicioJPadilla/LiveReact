# LiveReact.app for macOS

A double-click app bundle built with PyInstaller (`--onedir`, windowed), with
Python 3.13 and all dependencies inside. No terminal or venv needed on the gig
Mac. Apple Silicon (arm64) only; macOS 14 or later (the PySide6 6.12 wheels
require it).

## Building

On an Apple Silicon Mac, from the repo root:

```sh
packaging/macos/build_app.sh                    # zip goes to dist/LiveReact-macos-arm64.zip
packaging/macos/build_app.sh ~/Desktop/LiveReact.zip
```

The script makes a fresh build venv in `.build-venv/` (gitignored) with
`$HOME/.local/bin/python3.13` (uv-managed CPython 3.13.16; set `PYTHON=...` to use
another 3.13, which must ship a shared `libpython3.13.dylib`), installs
`.[ui,hardware]` plus PyInstaller, runs `LiveReact.spec`, and zips the result
with `ditto`. Outputs: `dist/LiveReact.app` (about 110 MB) and the zip (about
45 MB). If `python-prodj-link` is installed in the build venv it is bundled;
otherwise the app runs without it, as it does from source.

Smoke test a build without hardware (the binary inside the bundle accepts the
normal `livereact` arguments; `LIVEREACT_HOME` points it at a scratch data folder):

```sh
export LIVEREACT_HOME=/tmp/lr-smoke
LIVEREACT_IMPORT_CHECK=1 dist/LiveReact.app/Contents/MacOS/LiveReact   # optional modules import
dist/LiveReact.app/Contents/MacOS/LiveReact --demo --duration 5
dist/LiveReact.app/Contents/MacOS/LiveReact --doctor
QT_QPA_PLATFORM=offscreen dist/LiveReact.app/Contents/MacOS/LiveReact --demo --visualize
```

(The console does not honour `--duration`; stop the last one with Ctrl-C.)

## Running the unsigned app

The app is not signed with a Developer ID or notarized, so Gatekeeper blocks a
plain double-click the first time:

1. Unzip, and drag `LiveReact.app` into `/Applications` (or anywhere).
2. Right-click (or Control-click) `LiveReact.app` and choose **Open**, then
   **Open** again in the warning. On recent macOS versions, if there is no Open
   button: try to open it once, then go to System Settings > Privacy & Security
   and click **Open Anyway** next to the LiveReact message.
3. Allow the prompts for the Documents folder, the microphone (the XDJ's USB
   audio input) and the local network (Pro DJ Link, phone console). If one was
   denied by mistake, re-enable it under System Settings > Privacy & Security.

After the first time, a normal double-click works.

## Where data lives

Everything the app reads and writes is in **`~/Documents/LiveReact`** (falls
back to `~/Library/Application Support/LiveReact` if Documents is not
writable):

| Path | What |
| --- | --- |
| `launch-args.txt` | Arguments used when the app is opened from Finder (below) |
| `rigs/` | Rig files. The bundled rigs are copied in on launch, but a file that already exists is never overwritten (it may hold Venue-tab calibration). To get a fresh copy of a bundled rig, delete or rename yours. |
| `recordings/` | Sessions recorded with `--record` (logs, state, notes) |
| `logs/` | `app-<timestamp>.log` for runs without `--record`; `launcher.log` says which arguments each launch used and why it fell back to the demo |
| `config.json`, `midi_map.json`, `diagnostics/` | Settings, MIDI mapping, `--doctor` reports |

## Changing the launch arguments

Edit `~/Documents/LiveReact/launch-args.txt` with any text editor. One line of
the usual `livereact` arguments; lines starting with `#` are ignored; quote
paths with spaces; relative paths are relative to `~/Documents/LiveReact`.
The first launch from Finder creates it with:

```
--hardware --visualize --record --rig rigs/junior_crib.json
```

If the `--rig` file does not exist, or the arguments do not parse, the app
starts the demo (`--demo --visualize`) instead and writes the reason to
`logs/launcher.log`. Keep `--visualize` in the line: without it the app runs
with no window and has to be stopped from Activity Monitor. If neither
`--record` nor `--log-file` is given, `--log-file logs/app-<timestamp>.log` is
added so a Finder launch always leaves a log.

When the app binary is started with arguments (from a terminal, or the
supervisor relaunching the engine after a crash), `launch-args.txt` is not read
and the arguments are passed through unchanged; only the working directory is
set to the data folder.

## Signing and notarization (Benicio runs this)

Not done by the build script. Needs a paid Apple Developer account and a
"Developer ID Application" certificate in your login keychain. Replace the
placeholders; first change `BUNDLE_ID` in `LiveReact.spec` from the placeholder
`com.beniciojpadilla.livereact` if you want a different id, and rebuild.

Python under the hardened runtime needs the entitlements in
`packaging/macos/entitlements.plist`:
`com.apple.security.cs.allow-unsigned-executable-memory` and
`com.apple.security.cs.disable-library-validation` (Python and the Qt/NumPy
extension modules), plus `com.apple.security.device.audio-input` (the XDJ audio
capture).

```sh
# 1. Sign (deep, hardened runtime, secure timestamp, entitlements)
codesign --deep --force --options runtime --timestamp \
  --entitlements packaging/macos/entitlements.plist \
  --sign "Developer ID Application: <NAME> (<TEAMID>)" dist/LiveReact.app

# 2. Store notarization credentials once (interactive: Apple ID, team id and an
#    app-specific password; saved in your keychain under <PROFILE>)
xcrun notarytool store-credentials <PROFILE>

# 3. Zip, submit and wait
ditto -c -k --keepParent dist/LiveReact.app LiveReact.zip
xcrun notarytool submit LiveReact.zip --keychain-profile <PROFILE> --wait

# 4. Staple the ticket to the app, then check Gatekeeper accepts it
xcrun stapler staple dist/LiveReact.app
spctl -a -vvv -t install dist/LiveReact.app

# 5. Re-zip the stapled app for distribution
ditto -c -k --keepParent dist/LiveReact.app LiveReact.zip
```

If notarization fails, `xcrun notarytool log <SUBMISSION_ID> --keychain-profile <PROFILE>`
lists the offending files.
