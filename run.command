#!/usr/bin/env bash
# LiveReact dev launcher (macOS/Linux). Activates the venv and runs demo mode.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "No virtual environment found. Create one with:"
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/python -m pip install -e \".[dev]\""
    exit 1
fi
exec .venv/bin/python -m livereact --demo "$@"
