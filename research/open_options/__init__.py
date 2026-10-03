"""R3: do options catch up at the Monday open? See METHOD.md. Reuses research/arb/arbscan unchanged."""
import sys
from pathlib import Path

_ARB = Path(__file__).resolve().parent.parent / "arb"
if str(_ARB) not in sys.path:
    sys.path.insert(0, str(_ARB))
