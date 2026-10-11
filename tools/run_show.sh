#!/bin/zsh
# Relaunch loop for a live night (2026-10-08): Python 3.14.3's garbage
# collector segfaulted twice inside the show-engine thread (crash reports
# Python-2026-10-08-152952 / -160540: SIGSEGV in mark_stacks < _PyGC_Collect).
# A crash (non-zero exit) relaunches LiveReact in 3 s; closing the window
# (exit 0) or `touch logs/STOP` ends the loop.
#   nohup tools/run_show.sh --hardware --visualize --record --rig rigs/sophias_thai.json > logs/watchdog.log 2>&1 & disown
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
rm -f logs/STOP
# Python 3.13 venv (.venv313, built 2026-10-08 with uv) when present: the
# 3.14.3 GC segfault has not reproduced there. PY=... overrides.
PY="${PY:-}"
if [ -z "$PY" ]; then
  if [ -x .venv313/bin/python ]; then PY=.venv313/bin/python; else PY=.venv/bin/python; fi
fi
while true; do
  echo "$(date '+%H:%M:%S') launching with $PY ($($PY --version)): $*"
  "$PY" -m livereact "$@" --log-file "logs/launch-$(date +%Y%m%d-%H%M%S).log"
  code=$?
  if [ -f logs/STOP ]; then rm -f logs/STOP; echo "$(date '+%H:%M:%S') STOP file: done"; break; fi
  if [ $code -eq 0 ]; then echo "$(date '+%H:%M:%S') clean exit: done"; break; fi
  echo "$(date '+%H:%M:%S') LiveReact exited with code $code -- relaunching in 3 s"
  sleep 3
done
