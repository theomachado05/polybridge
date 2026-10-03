from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.verdicts import load_verdicts

FIX = Path(__file__).parent / "fixtures" / "results"


def test_h1_tag_confirmatory_no_edge():
    v = load_verdicts(FIX).for_tag("material_litigation")
    assert (v.kind, v.label, v.family) == ("confirmatory", "no_edge", "hedge")
    assert v.evidence.strategy == "protective_put" and v.evidence.difference is not None


def test_h2_tag_uses_opportunity_family():
    v = load_verdicts(FIX).for_tag("restructuring_plan")
    assert (v.kind, v.label, v.family) == ("confirmatory", "no_edge", "opportunity")


def test_passed_family_gives_family_label(tmp_path):
    (tmp_path / "in_sample").mkdir()
    (tmp_path / "in_sample" / "hedge_verdict.txt").write_text("passed\n")
    assert load_verdicts(tmp_path).for_tag("class_action_filing").label == "hedge"


def test_exploratory_hedge_leaning():
    v = load_verdicts(FIX).for_tag("leaning_tag")
    assert (v.kind, v.label) == ("exploratory", "hedge")
    assert v.evidence.q_value is not None and v.evidence.q_value < 0.10


def test_exploratory_no_edge():
    v = load_verdicts(FIX).for_tag("flat_tag")
    assert (v.kind, v.label) == ("exploratory", "no_edge")


def test_missing_atlas(tmp_path):
    v = load_verdicts(tmp_path).for_tag("some_other_tag")
    assert (v.kind, v.label, v.note) == ("none", "no_edge", "not tested")


def test_http(monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(FIX))
    c = TestClient(create_app())
    assert c.get("/verdicts/leaning_tag").json()["label"] == "hedge"
    assert c.get("/verdicts/nope").status_code == 404
    tags = {v["tag"] for v in c.get("/verdicts").json()}
    assert {"leaning_tag", "flat_tag", "material_litigation"} <= tags
