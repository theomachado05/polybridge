#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
mkdir -p results/live_books
/usr/bin/python3 - "$@" <<'PY'
import subprocess, sys
out = open("results/live_books/nohup.out", "ab")
p = subprocess.Popen(["nohup", "caffeinate", "-i", ".venv/bin/python", "-m", "live_books.recorder", *sys.argv[1:]],
                     stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
print(f"launched pid {p.pid} in its own session; recorder pid in results/live_books/recorder.pid")
PY
