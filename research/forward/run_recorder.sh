#!/bin/bash
# Keeps the forward recorder alive until its end time (Sun 2026-10-04 09:30 ET). caffeinate stops the Mac from
# idle-sleeping while it runs. Usage, from the repo root:  nohup research/forward/run_recorder.sh >/dev/null 2>&1 &
cd "$(dirname "$0")/../.." || exit 1
echo $$ > research/forward/recorder.pid
until caffeinate -is research/.venv/bin/python research/forward/recorder.py "$@" >> research/forward/recorder.log 2>&1; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) recorder exited abnormally, restarting in 5 s" >> research/forward/recorder.log
  sleep 5
done
