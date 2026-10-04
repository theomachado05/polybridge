"""Touch-ticket forward test (research/touch_fresh/FORWARD.md, rules frozen). No trading.

Run from backend/:  uv run python ../scripts/forward_touch.py [list|snapshot|prints|evaluate]
  list      (default) list the "will it hit" markets listed from 2026-10-05 and record which can enter the book
  snapshot  the frozen runner's Friday 15:55 New York stage (option anchor); prints: after Sunday 20:00; evaluate: any time
Output: backend/data_forward/touch/. Nothing under research/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.forward import touch  # noqa: E402


def main(argv: list[str]) -> int:
    stage = argv[1] if len(argv) > 1 else "list"
    if stage == "list":
        rec = touch.list_state()
        print(json.dumps({k: rec[k] for k in ("first_listing_et", "markets_listed", "parsed", "eligible_first_weekend",
                                              "eligible_events", "by_entry_day", "not_eligible_reasons")}, indent=1))
        for m in rec["eligible"]:
            print("eligible:", m["entry_day"], m["ticker"], m["level"], m["direction"], "|", m["question"])
        if not rec["eligible"]:
            print(f"no eligible market yet (listings count from {rec['first_listing_et']} New York)")
        print(f"saved backend/data_forward/touch/snapshots/{rec['stamp']}.json")
        return 0
    if stage in touch.STAGES:
        rec = touch.run_stage(stage)
        print(rec["output"] or f"{stage}: done", rec["log_rows"])
        return int(rec["return_code"] or 0)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
