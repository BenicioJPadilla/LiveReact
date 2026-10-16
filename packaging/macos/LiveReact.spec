# PyInstaller spec for the macOS LiveReact.app (onedir, windowed BUNDLE).
# Build with packaging/macos/build_app.sh; run from the repo root:
#   pyinstaller --noconfirm --distpath dist --workpath build/pyinstaller packaging/macos/LiveReact.spec
# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

REPO = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# Placeholder bundle id: Benicio, change this to your own reverse-DNS id before
# signing (it must match what you register for notarization).
BUNDLE_ID = "com.beniciojpadilla.livereact"
VERSION = "0.1.0"

# The app imports most hardware modules lazily (inside functions), so list them.
hiddenimports = (
    collect_submodules("livereact")
    + [
        "numpy",
        "sounddevice", "_sounddevice",
        "serial", "serial.tools", "serial.tools.list_ports", "serial.tools.list_ports_osx",
        "mido", "mido.backends", "mido.backends.rtmidi",
        "rtmidi",
    ]
)
# python-prodj-link is git-only and not pip-installable (no setup.py), so
# build_app.sh clones it at a pinned SHA into build/prodj-link and puts that
# on PYTHONPATH. inputs/prodj.py only uses its packet definitions (plus
# construct); the rest of the library pulls in PyQt5/OpenGL and stays out.
PRODJ_SRC = os.environ.get("LIVEREACT_PRODJ_SRC", "")
if importlib.util.find_spec("prodj") is not None:
    hiddenimports += ["prodj", "prodj.network", "prodj.network.packets", "construct"]

datas = [(os.path.join(REPO, "rigs"), "rigs")]
datas += collect_data_files("livereact")              # fixtures/default_rig.json etc.
datas += collect_data_files("_sounddevice_data")      # bundled libportaudio.dylib
# --doctor reports dependency versions via importlib.metadata.
for dist in ("pyserial", "mido", "python-rtmidi", "PySide6", "sounddevice", "numpy", "livereact"):
    try:
        datas += copy_metadata(dist)
    except Exception:  # noqa: BLE001 - optional dist not installed
        pass

# Qt modules the app does not use (keeps the bundle small).
excludes = [
    "tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization",
]

a = Analysis(
    [os.path.join(SPECPATH, "livereact_app.py")],
    pathex=[os.path.join(REPO, "src")] + ([PRODJ_SRC] if PRODJ_SRC else []),
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LiveReact",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,       # ad-hoc only; see packaging/macos/README.md
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LiveReact")

app = BUNDLE(
    coll,
    name="LiveReact.app",
    icon=None,
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": "LiveReact",
        "CFBundleDisplayName": "LiveReact",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "14.0",  # PySide6 6.12 wheels are macosx_14_0
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.music",
        "NSMicrophoneUsageDescription":
            "LiveReact listens to the DJ mixer's USB audio input to follow the music.",
        "NSLocalNetworkUsageDescription":
            "LiveReact talks to Pro DJ Link players and the phone console on the local network.",
    },
)
