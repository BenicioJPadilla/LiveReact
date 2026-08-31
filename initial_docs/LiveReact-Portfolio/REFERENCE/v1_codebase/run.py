#!/usr/bin/env python3
"""
LiveReact — main entry point.

Usage:
    python run.py                          # auto-detect everything
    python run.py --audio "XDJ-XZ"        # specify audio device
    python run.py --rig rigs/full_show.json
    python run.py --list-audio             # find your XDJ-XZ device name
    python run.py --list-dmx               # find your Enttec port

First time setup on macOS:
    pip install sounddevice pyserial numpy scipy

The program runs in DEMO mode if no hardware is connected,
so you can develop and test without the XDJ-XZ or Enttec plugged in.
"""

import sys
import os

# ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.control_panel import main

if __name__ == "__main__":
    main()
