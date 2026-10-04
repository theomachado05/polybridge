"""The frozen set of the second held-out test (linker/heldout2/PLAN.md section 8): the sha256 of every file that fixes
the test, written once at the commit that holds the plan, and checked before the fresh set is pulled or scored.

    FILES     the plan, heldout2/universe.json, every heldout2/input_*.json, the three prompts, instruments.json, every
              module the evaluation imports from research/ (the linker's, and S1's, S4's and S5's that it calls: the
              verdict, the sessions, the betas, the window, S5's ticker list and themes, the pullers), the frozen
              scorer weights and v1, the odds-only model's training table, and the linker tests (paths relative to
              research/). tests/test_freeze.py checks that no imported module is left out.
    write()   linker/heldout2/FROZEN.json: {path: sha256} and "#plan_bytes", the plan's length
    changed() files whose hash differs from FROZEN.json, files gone, and files of the set it does not hold
    gate()    the plan may only grow: the frozen text must be a byte prefix of the current one, ending under its
              "## Amendments" heading. Any other changed file must be named in --amended and, by path or file name, in
              the amendments' text.

Run from `research/`:  python -m linker.freeze write|check    (check: exit code 1 when a file changed)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FROZEN = HERE / "heldout2" / "FROZEN.json"
PLAN = "linker/heldout2/PLAN.md"
AMENDMENTS = "## Amendments"
FIXED = (PLAN, "linker/heldout2/universe.json", "linker/prompts/labeller_v3.md", "linker/prompts/labeller_control.md",
         "linker/prompts/recall.md", "linker/instruments.json", "results/linker/scorer_v2.json", "results/linker/scorer.json",
         "results/linker/train_v2.csv",
         # the code: every research/ module that study.py, signal.py, events.py, features.py, scorer2.py,
         # option_evidence.py and freeze.py import, directly or not
         "linker/__init__.py", "linker/events.py", "linker/signal.py", "linker/study.py", "linker/features.py", "linker/scorer2.py",
         "linker/option_evidence.py", "linker/store.py", "linker/instruments.py", "linker/freeze.py", "linker/benchmark.py",
         "linker/scorer.py", "linker/options.py",
         "s1_twin_spread/__init__.py", "s1_twin_spread/config.py", "s1_twin_spread/data.py", "s1_twin_spread/engine.py",
         "s4_linked_assets/__init__.py", "s4_linked_assets/config.py", "s4_linked_assets/data.py", "s4_linked_assets/engine.py",
         "s4_linked_assets/run.py",
         "s5_big_moves/__init__.py", "s5_big_moves/config.py", "s5_big_moves/granular.py", "s5_big_moves/run.py",
         "s5_big_moves/universe.py", "polybridge_research/__init__.py", "polybridge_research/calendar.py")
GLOBS = ("linker/heldout2/input_*.json", "linker/tests/*.py")
META = "#"


def files(root: Path | None = None) -> list[str]:
    """The frozen set as it stands on disk, sorted."""
    root = root or ROOT
    return sorted(set(FIXED) | {p.relative_to(root).as_posix() for g in GLOBS for p in root.glob(g)})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(root: Path | None = None) -> dict[str, str]:
    root = root or ROOT
    return {f: sha256(root / f) if (root / f).exists() else "missing" for f in files(root)}


def write(root: Path | None = None, out: Path | None = None) -> dict[str, str]:
    root, out = root or ROOT, out or FROZEN
    h = hashes(root)
    plan = root / PLAN
    out.write_text(json.dumps({**h, f"{META}plan_bytes": len(plan.read_bytes()) if plan.exists() else 0}, indent=1, sort_keys=True) + "\n")
    return h


def _frozen(frozen: Path) -> dict:
    return json.loads(frozen.read_text())


def changed(root: Path | None = None, frozen: Path | None = None) -> list[str]:
    """Paths whose hash is not the frozen one. Raises FileNotFoundError when FROZEN.json does not exist."""
    old = {k: v for k, v in _frozen(frozen or FROZEN).items() if not k.startswith(META)}
    now = hashes(root)
    return sorted(f for f in set(old) | set(now) if old.get(f) != now.get(f))


def plan_growth(root: Path | None = None, frozen: Path | None = None) -> tuple[str | None, str]:
    """(why the plan's change is not allowed or None, the text of its amendments section as it stands now)."""
    root, old = root or ROOT, _frozen(frozen or FROZEN)
    now = (root / PLAN).read_bytes() if (root / PLAN).exists() else b""
    tail = now.decode("utf-8", "replace").split(f"\n{AMENDMENTS}", 1)
    text = tail[1] if len(tail) == 2 else ""
    n = old.get(f"{META}plan_bytes")
    if old.get(PLAN) == hashlib.sha256(now).hexdigest():
        return None, text
    if not isinstance(n, int) or len(now) < n or hashlib.sha256(now[:n]).hexdigest() != old.get(PLAN):
        return f"{PLAN} was rewritten, not only added to: the frozen text is no longer its beginning", text
    if not re.search(rf"(?m)^{re.escape(AMENDMENTS)}\s*$", now[:n].decode("utf-8", "replace")):
        return f"the frozen {PLAN} has no '{AMENDMENTS}' heading, so text added to it is not an amendment", text
    return None, text


def _named(path: str, amended: list[str]) -> bool:
    return path in amended or Path(path).name in amended


def gate(amended: list[str], root: Path | None = None, frozen: Path | None = None) -> str | None:
    """None when the fresh set may be pulled or scored; otherwise why not. The plan may only grow under its Amendments
    heading. Any other changed file must be named in `amended` (its path relative to research/ or its file name) and
    named the same way in the amendments' text."""
    frozen = frozen or FROZEN
    if not frozen.exists():
        return f"{frozen.name} does not exist: the frozen set was never written, so the fresh set is not scored"
    why, text = plan_growth(root, frozen)
    if why:
        return why
    rest = [f for f in changed(root, frozen) if f != PLAN]
    left = [f for f in rest if not _named(f, amended)]
    if left:
        return ("frozen files changed and are not named in --amended (each needs a dated amendment in PLAN.md): "
                + ", ".join(left))
    unlisted = [f for f in rest if f not in text and Path(f).name not in text]
    if unlisted:
        return f"frozen files changed and named in --amended but in no amendment of {PLAN}: " + ", ".join(unlisted)
    return None


def main(argv: list[str]) -> int:
    if argv == ["write"]:
        h = write()
        print(f"{FROZEN.relative_to(ROOT)}: {len(h)} files", "(missing: " + ", ".join(f for f, v in h.items() if v == "missing") + ")"
              if "missing" in h.values() else "")
        return 0
    if argv == ["check"]:
        if not FROZEN.exists():
            print(f"{FROZEN.relative_to(ROOT)} does not exist")
            return 1
        ch = changed()
        print("\n".join(ch) if ch else "no frozen file changed")
        return 1 if ch else 0
    print("usage: python -m linker.freeze write|check")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
