import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent):          # arbscan (research/arb) and polybridge_research (research)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
