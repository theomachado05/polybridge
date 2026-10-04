"""Study A: options-anchored Polymarket taker on reopening days. See METHOD.md."""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parent.parent
for _p in (_R, _R / "arb"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
