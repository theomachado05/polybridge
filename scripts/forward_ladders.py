from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.forward import ladders  # noqa: E402


def main() -> int:
    rec = ladders.run()
    if rec.get("error"):
        print("ladder live check FAILED:", rec["error"])
        return 1
    show = {k: rec.get(k) for k in ("snapshot_utc", "events_read", "date_ladders", "pairs", "pairs_with_books", "nested_pairs",
                                    "violations_net_of_fees", "violations_nested", "locked_usd", "gap_points_to_arb")}
    print(json.dumps(show, indent=1))
    for v in rec["violations"]:
        print("violation after fees:", v)
    print(f"saved backend/data_forward/ladders/snapshots/{rec['stamp']}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
