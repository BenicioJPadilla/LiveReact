#!/bin/bash
# ============================================================
#  LiveReact — Double-click this to launch
# ============================================================

# Move to the folder this script lives in
cd "$(dirname "$0")"

clear
echo "============================================"
echo "  LiveReact BETA — Starting up..."
echo "============================================"
echo ""

# ── Find Python ──────────────────────────────────────────────
PYTHON=""
for candidate in \
    /usr/local/bin/python3 \
    /opt/homebrew/bin/python3 \
    /usr/bin/python3; do
    if [ -x "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found."
    echo ""
    echo "Please run Setup.command first."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

# ── Check dependencies are installed ─────────────────────────
$PYTHON -c "import numpy, scipy" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Dependencies not installed."
    echo "Please double-click Setup.command first, then try again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

# ── Check for XDJ-XZ audio device ────────────────────────────
echo "Checking audio devices..."
AUDIO_DEVICE=$($PYTHON -c "
try:
    import sounddevice as sd
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        name = d['name'].lower()
        if ('xdj' in name or 'pioneer' in name) and d['max_input_channels'] > 0:
            print(d['name'])
            break
except:
    pass
" 2>/dev/null)

if [ -n "$AUDIO_DEVICE" ]; then
    echo "  Found: $AUDIO_DEVICE"
    AUDIO_ARG="--audio \"$AUDIO_DEVICE\""
else
    echo "  XDJ-XZ not detected — running in demo mode"
    echo "  (Connect your XDJ-XZ via USB and restart to use live audio)"
    AUDIO_ARG=""
fi

# ── Check for Enttec DMX ─────────────────────────────────────
echo "Checking DMX interface..."
DMX_PORT=$($PYTHON -c "
import glob, sys
ports = glob.glob('/dev/tty.usbserial-*') + glob.glob('/dev/cu.usbserial-*')
if ports:
    print(ports[0])
" 2>/dev/null)

if [ -n "$DMX_PORT" ]; then
    echo "  Found: $DMX_PORT"
    DMX_ARG="--dmx \"$DMX_PORT\""
else
    echo "  Enttec not detected — DMX in null mode"
    echo "  (Connect your Enttec USB Pro and restart to output DMX)"
    DMX_ARG=""
fi

echo ""
echo "Launching control panel..."
echo "--------------------------------------------"
echo ""

# ── Launch ───────────────────────────────────────────────────
eval $PYTHON run.py $AUDIO_ARG $DMX_ARG

# If we get here, the app exited — show any error
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "--------------------------------------------"
    echo "App exited with error code $EXIT_CODE"
    echo "Check the output above for details."
    echo ""
    read -p "Press Enter to close..."
fi
