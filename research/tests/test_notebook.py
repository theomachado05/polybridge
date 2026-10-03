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
