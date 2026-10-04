#!/bin/sh
PIDF="$(cd "$(dirname "$0")/.." && pwd)/results/live_books/recorder.pid"
if [ ! -f "$PIDF" ]; then echo "no pid file at $PIDF"; exit 1; fi
PID=$(cat "$PIDF")
kill -TERM "$PID" 2>/dev/null || { echo "pid $PID not running"; rm -f "$PIDF"; exit 1; }
for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$PID" 2>/dev/null || { echo "stopped $PID"; exit 0; }; sleep 1; done
kill -KILL "$PID" 2>/dev/null && echo "killed $PID"
rm -f "$PIDF"
