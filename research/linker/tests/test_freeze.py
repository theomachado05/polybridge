"""The frozen set: write, check, the plan that may only grow under its Amendments heading, changed files that must be
named in --amended and in an amendment, and no research/ module the evaluation imports left out of the set."""
import json
import subprocess
import sys
from pathlib import Path

from linker import freeze

PLAN_TEXT = "# Plan\n\n## 4. Scoring\n\n- **confirmed** t \u2265 2\n\n## Amendments\n"
CODE = ("linker/signal.py", "linker/study.py", "linker/freeze.py", "linker/benchmark.py", "linker/scorer.py", "s4_linked_assets/engine.py",
        "s5_big_moves/config.py", "linker/heldout2/input_v3_1.json", "linker/tests/test_x.py")


def frozen_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "root"
    for f in CODE + (freeze.PLAN,):
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_text(PLAN_TEXT if f == freeze.PLAN else f)
    return root, root / "linker" / "heldout2" / "FROZEN.json"


def _append(p: Path, text: str) -> None:
    p.write_text(p.read_text() + text)


def test_write_check_refuse_and_amend(tmp_path):
    root, fz = frozen_root(tmp_path)
    assert "does not exist" in freeze.gate([], root, fz)
    h = freeze.write(root, fz)
    assert "linker/heldout2/input_v3_1.json" in h and "linker/tests/test_x.py" in h and h["linker/events.py"] == "missing"
    assert json.loads(fz.read_text())["#plan_bytes"] == len(PLAN_TEXT.encode())
    assert freeze.changed(root, fz) == [] and freeze.gate([], root, fz) is None
    (root / "linker/signal.py").write_text("changed")
    (root / "linker/tests/test_y.py").write_text("new")
    assert freeze.changed(root, fz) == ["linker/signal.py", "linker/tests/test_y.py"]
    assert "linker/signal.py" in freeze.gate([], root, fz)
    assert "test_y.py" in freeze.gate(["signal.py"], root, fz)
    assert "in no amendment" in freeze.gate(["signal.py", "linker/tests/test_y.py"], root, fz)   # named, but the plan says nothing
    _append(root / freeze.PLAN, "\n### 2026-10-04: signal.py crashed on an empty leg; test_y.py covers it. No link count changes.\n")
    assert freeze.gate(["signal.py", "linker/tests/test_y.py"], root, fz) is None
    assert "test_y.py" in freeze.gate(["signal.py"], root, fz)


def test_every_code_file_that_decides_a_verdict_is_frozen(tmp_path):
    root, fz = frozen_root(tmp_path)
    freeze.write(root, fz)
    for f in CODE[2:7]:                                         # freeze, benchmark, scorer, engine, config
        _append(root / f, "\n# edited\n")
    assert freeze.changed(root, fz) == sorted(CODE[2:7])
    assert "linker/benchmark.py" in freeze.gate([], root, fz)


def test_the_plan_may_only_grow_under_its_amendments_heading(tmp_path):
    root, fz = frozen_root(tmp_path)
    freeze.write(root, fz)
    plan = root / freeze.PLAN
    plan.write_text(PLAN_TEXT.replace("t \u2265 2", "t \u2265 1.5"))
    assert "rewritten" in freeze.gate(["PLAN.md"], root, fz)       # naming it does not help
    plan.write_text(PLAN_TEXT.replace("## Amendments", "Added above.\n\n## Amendments"))
    assert "rewritten" in freeze.gate(["PLAN.md"], root, fz)
    plan.write_text(PLAN_TEXT[:-5])
    assert "rewritten" in freeze.gate([], root, fz)
    plan.write_text(PLAN_TEXT + "\n### 2026-10-04: a note, no file changed.\n")
    assert freeze.gate([], root, fz) is None
    plan.write_text("# Plan\n")                                     # a frozen plan with no Amendments heading
    freeze.write(root, fz)
    plan.write_text("# Plan\nmore\n")
    assert "no '## Amendments' heading" in freeze.gate([], root, fz)


def test_no_imported_research_module_is_left_out_of_the_set():
    code = ("import importlib, sys, pathlib\n"
            "root = pathlib.Path('.').resolve()\n"
            "for m in ('linker.study', 'linker.signal', 'linker.events', 'linker.features', 'linker.scorer2', 'linker.option_evidence',\n"
            "          'linker.freeze', 'linker.options', 's4_linked_assets.data'):\n"
            "    importlib.import_module(m)\n"
            "for v in list(sys.modules.values()):\n"
            "    f = getattr(v, '__file__', None)\n"
            "    if f and pathlib.Path(f).resolve().is_relative_to(root) and '.venv' not in f:\n"
            "        print(pathlib.Path(f).resolve().relative_to(root).as_posix())\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=freeze.ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    used = {x for x in out.stdout.split() if not x.startswith("linker/tests/")}
    assert used and used <= set(freeze.FIXED), sorted(used - set(freeze.FIXED))
