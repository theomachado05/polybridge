"""Live Polymarket book recorder and stale-quote detector. Records only; no order is ever sent."""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parent.parent
for _p in (_R, _R / "arb"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
