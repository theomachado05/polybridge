import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generated_notebook_is_clean_and_safe(tmp_path):
    out = tmp_path / "nb.ipynb"
    subprocess.run([sys.executable, str(ROOT / "make_notebook.py"), str(out)], check=True)
    nb = json.loads(out.read_text())
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert all(not c.get("outputs") and c.get("execution_count") is None for c in code)
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "RUN_OOS = False" in src
    assert 'START, END = "2024-01-01", "2025-12-31"' in src
    assert "hedgecore" not in src and "anthropic" not in src.lower()
    assert "run_family_study" in src and "pass_check" in src and "run_atlas" in src
    assert "SEC_USER_AGENT" not in src and "user_agent=UA" not in src and "user_agent=None" in src
    assert "LAST_SESSION = None" in src and "pd.Timestamp(LAST_SESSION)" in src
    for c in code:
        compile("".join(c["source"]), "<cell>", "exec")


SECTION_TITLE = "## Closed-market evidence"
NO_NET = '''\
import os, socket
assert "MASSIVE_API_KEY" not in os.environ
def _blocked(*a, **k):
    raise RuntimeError("network blocked in the offline test")
socket.socket.connect = _blocked
socket.create_connection = _blocked
import matplotlib
matplotlib.use("Agg")
'''


def _build(tmp_path):
    out = tmp_path / "nb.ipynb"
    subprocess.run([sys.executable, str(ROOT / "make_notebook.py"), str(out)], check=True)
    return json.loads(out.read_text())


def _section(nb):
    start = next(i for i, c in enumerate(nb["cells"]) if c["cell_type"] == "markdown" and SECTION_TITLE in "".join(c["source"]))
    return start, nb["cells"][start:]


def test_closed_market_section_follows_the_8k_sections(tmp_path):
    nb = _build(tmp_path)
    ids = [c["id"] for c in nb["cells"]]
    assert ids == [f"cell-{i:02d}" for i in range(len(ids))]
    start, cells = _section(nb)
    srcs = ["".join(c["source"]) for c in nb["cells"]]
    assert start > max(i for i, s in enumerate(srcs) if "RUN_OOS" in s or "Known limitations" in s)
    body = "\n".join("".join(c["source"]) for c in cells)
    for d in ("leadlag_closed", "leadlag_replication", "gap_model", "closed_hedge", "open_options"):
        assert d in body
    assert "load_api_key" not in body and "MassiveClient" not in body
    assert sum(c["cell_type"] == "code" for c in cells) >= 3


def test_closed_market_numbers_recompute_offline(monkeypatch):
    import socket

    def blocked(*a, **k):
        raise RuntimeError("network blocked")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    import closed_market_section as cms

    data = cms.load()
    rec = cms.recompute(data)
    chk = cms.comparison(rec, data)
    assert chk["match"].all(), chk[~chk["match"]]
    s = cms.summary(rec).set_index("finding")["verdict"]
    assert s.str.contains("does not replicate").sum() == 1
    assert (s.str.startswith("NULL")).sum() == 1
    assert rec["r2"]["by_market"]["recession"]["verdict"] == "Accurate out of sample"
    assert rec["r2"]["by_market"]["election"]["verdict"] == "Not accurate out of sample"
    assert rec["r1"]["B"]["verdict"] == "reduces the loss variance" and rec["r1"]["B"]["block"]["verdict"] == "partial"
    assert rec["r1"]["A"]["verdict"] == "no evidence"


def test_closed_market_section_executes_offline(tmp_path, monkeypatch):
    import pytest

    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    nb = _build(tmp_path)
    _, cells = _section(nb)
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    sub = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(NO_NET)])
    sub.cells += [nbformat.v4.new_code_cell("".join(c["source"])) if c["cell_type"] == "code"
                  else nbformat.v4.new_markdown_cell("".join(c["source"])) for c in cells]
    sub.metadata["kernelspec"] = nb["metadata"]["kernelspec"]
    nbclient.NotebookClient(sub, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}}).execute()
    text = "\n".join(o.get("text", "") for c in sub.cells if c.cell_type == "code" for o in c.get("outputs", []))
    errors = [o for c in sub.cells if c.cell_type == "code" for o in c.get("outputs", []) if o.get("output_type") == "error"]
    assert not errors
    assert "22 of 22 recomputed numbers match the committed JSON" in text
