"""Forward reopening taker (Study A). See METHOD.md. Reuses pm_taker and arbscan unchanged."""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parent.parent
for _p in (_R, _R / "arb"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
