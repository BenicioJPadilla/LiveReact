#!/bin/zsh
# Start a live night (2026-10-16): the relaunch loop that used to live here
# (2026-10-08, after Python 3.14.3's GC segfaulted twice mid-set) is now in
# the app itself, src/livereact/supervisor.py: a --hardware run relaunches
# its engine within ~1 s of a crash and restores blackout / brightness /
# strobe cap / laser disarm. This script only picks the interpreter and
# keeps a log per night. Closing the window ends it; so does
# `touch logs/STOP` (then close the window or kill the engine).
#   nohup tools/run_show.sh --hardware --visualize --record --rig rigs/sophias_thai.json > logs/watchdog.log 2>&1 & disown
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
# Python 3.13 venv (.venv313, built 2026-10-08 with uv) when present: the
# 3.14.3 GC segfault has not reproduced there. PY=... overrides.
PY="${PY:-}"
if [ -z "$PY" ]; then
  if [ -x .venv313/bin/python ]; then PY=.venv313/bin/python; else PY=.venv/bin/python; fi
fi
echo "$(date '+%H:%M:%S') launching with $PY ($($PY --version)): $*"
exec "$PY" -m livereact "$@" --supervise --log-file "logs/launch-$(date +%Y%m%d-%H%M%S).log"
