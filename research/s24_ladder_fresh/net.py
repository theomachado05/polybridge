"""S24 network gate: one worker, at most one request a second, a request budget, and the recorder check.

Every request of this study goes through `GATE.wait()`. The count survives restarts (`.cache/requests.json`).
The recorder's log is only read.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
COUNTER = CACHE / "requests.json"
LOG = RESEARCH / cfg.RECORDER_LOG


class BudgetExhausted(RuntimeError):
    pass


def recorder_fails() -> int:
    try:
        with open(LOG, "r", errors="replace") as fh:
            return sum("fetch failed" in line for line in fh)
    except OSError:
        return -1


class Gate:
    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        st = json.loads(COUNTER.read_text()) if COUNTER.exists() else {}
        self.n = int(st.get("n", 0))
        self.by = dict(st.get("by", {}))
        self.baseline = st.get("recorder_baseline")
        self.slow = bool(st.get("slow", False))
        self.pauses = list(st.get("pauses", []))
        self.next = 0.0
        self.kind = "other"
        self.limit = cfg.MAX_REQUESTS
        if self.baseline is None:
            self.baseline = recorder_fails()
            self._save()

    def _save(self) -> None:
        COUNTER.write_text(json.dumps({"n": self.n, "by": self.by, "recorder_baseline": self.baseline, "slow": self.slow,
                                       "pauses": self.pauses, "recorder_now": getattr(self, "last_seen", self.baseline)}))

    def wait(self) -> None:
        if self.n >= self.limit:
            raise BudgetExhausted(f"{self.n} requests made, budget {self.limit}")
        gap = 1.0 / (cfg.SLOW_RATE if self.slow else cfg.RATE)
        now = time.monotonic()
        at = max(now, self.next)
        time.sleep(max(0.0, at - now))
        self.next = time.monotonic() + gap
        self.n += 1
        self.by[self.kind] = self.by.get(self.kind, 0) + 1
        if self.n % cfg.RECORDER_CHECK_EVERY == 0:
            self.last_seen = recorder_fails()
            if self.last_seen - self.baseline > cfg.RECORDER_MAX_NEW_FAILS:
                self.pauses.append({"at_request": self.n, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "fails_before": self.baseline, "fails_now": self.last_seen})
                self.slow = True
                self.baseline = self.last_seen          # a further 5 new lines pause again
                self._save()
                print(f"recorder check tripped at request {self.n}: pausing {cfg.RECORDER_PAUSE_S}s, then slow", flush=True)
                time.sleep(cfg.RECORDER_PAUSE_S)
                self.next = time.monotonic() + 1.0 / cfg.SLOW_RATE
        self._save()


GATE = Gate()
