#!/bin/bash
# ============================================================
#  LiveReact — First Time Setup
#  Double-click this ONCE before running the app
# ============================================================

clear
echo "============================================"
echo "  LiveReact — First Time Setup"
echo "============================================"
echo ""

# ── Find Python ──────────────────────────────────────────────
echo "Step 1/4  Looking for Python 3..."

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
    echo ""
    echo "  ERROR: Python 3 not found."
    echo ""
    echo "  Please install it from https://python.org/downloads"
    echo "  Then run this setup script again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "  Found: $PYTHON ($($PYTHON --version))"
echo ""

# ── Check / install Homebrew + PortAudio ─────────────────────
echo "Step 2/4  Checking PortAudio (needed for XDJ-XZ audio)..."

if python3 -c "import sounddevice" 2>/dev/null; then
    echo "  Already installed — skipping."
else
    if command -v brew &>/dev/null; then
        echo "  Installing portaudio via Homebrew..."
        brew install portaudio
    else
        echo "  Homebrew not found — installing Homebrew first..."
        echo "  (This may take a few minutes)"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # add brew to PATH for Apple Silicon
        if [ -f /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        brew install portaudio
    fi
fi

echo ""

# ── Install Python packages ───────────────────────────────────
echo "Step 3/4  Installing Python packages..."
echo "  (numpy, scipy, sounddevice, pyserial)"
echo ""

$PYTHON -m pip install --upgrade pip --quiet
$PYTHON -m pip install numpy scipy sounddevice pyserial

if [ $? -ne 0 ]; then
    echo ""
    echo "  ERROR: pip install failed."
    echo "  Try running manually: pip3 install numpy scipy sounddevice pyserial"
    read -p "Press Enter to close..."
    exit 1
fi

echo ""

# ── Verify ───────────────────────────────────────────────────
echo "Step 4/4  Verifying installation..."

$PYTHON -c "
import numpy, scipy
print('  numpy:', numpy.__version__, '✓')
print('  scipy:', scipy.__version__, '✓')
try:
    import sounddevice
    print('  sounddevice:', sounddevice.__version__, '✓')
except Exception as e:
    print('  sounddevice: WARNING —', e)
    print('  (App will run in demo mode without XDJ-XZ audio)')
try:
    import serial
    print('  pyserial:', serial.__version__, '✓')
except:
    print('  pyserial: WARNING — DMX output may not work')
"

echo ""
echo "============================================"
echo "  Setup complete!"
echo "  You can now double-click LiveReact.command"
echo "  to run the app."
echo "============================================"
echo ""
read -p "Press Enter to close..."
