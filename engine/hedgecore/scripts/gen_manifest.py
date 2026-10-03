"""Write engine/hedgecore/manifest.json from the compiled library's catalog().

The backend falls back to this file when the hedgecore module is not built, so it must always match the code.
Deterministic output (no timestamps): regenerating without code changes yields no diff.

Usage (from backend/, with the engine group installed):
    uv run --group engine python ../engine/hedgecore/scripts/gen_manifest.py          # write
    uv run --group engine python ../engine/hedgecore/scripts/gen_manifest.py --check  # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.json"


def render() -> str:
    import hedgecore

    return json.dumps(hedgecore.catalog(), indent=2, allow_nan=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if manifest.json differs from catalog()")
    ap.add_argument("--out", type=Path, default=MANIFEST)
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is stale; run gen_manifest.py", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.write_text(text)
    total = json.loads(text)["total"]
    print(f"wrote {args.out} ({total} presets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
