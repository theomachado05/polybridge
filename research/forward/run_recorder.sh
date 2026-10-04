#!/bin/bash
cd "$(dirname "$0")/../.." || exit 1
echo $$ > research/forward/recorder.pid
until caffeinate -is research/.venv/bin/python research/forward/recorder.py "$@" >> research/forward/recorder.log 2>&1; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) recorder exited abnormally, restarting in 5 s" >> research/forward/recorder.log
  sleep 5
done
