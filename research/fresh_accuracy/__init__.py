import sys
from pathlib import Path

_ARB = Path(__file__).resolve().parent.parent / "arb"
if str(_ARB) not in sys.path:
    sys.path.insert(0, str(_ARB))
