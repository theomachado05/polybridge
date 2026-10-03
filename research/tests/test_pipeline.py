import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.pipeline import run_family_study
from tests.fakes import FakeClient, FakeMarket, disclosure

CAL = TradingCalendar()
CFG = StudyConfig(n_placebo=12)
T = pd.Timestamp


def _client():
    days = pd.bdate_range("2024-02-01", "2024-08-30")[::7][:10]
    disc = {"material_litigation": [disclosure(f"m{i}", "1", ["AAPL"], d.strftime("%Y-%m-%d")) for i, d in enumerate(days)],
            "workforce_reduction": [disclosure("w1", "2", ["MSFT"], "2024-04-03")]}
    return FakeClient(disc, FakeMarket({"AAPL": 100.0, "MSFT": 400.0}))


def test_end_to_end_on_fake_market(tmp_path):
    out = run_family_study(_client(), CAL, CFG, "2024-01-01", "2024-12-31", T("2026-09-30"),
                           cache_dir=tmp_path, max_workers=2)
    assert set(out["events"].family) == {"hedge", "opportunity"}
    assert out["timing_counts"] == {"conservative": 11}
    assert set(out["checks"]) == {"hedge", "opportunity"}
    assert out["checks"]["hedge"]["strategy"] == "protective_put"
    assert isinstance(out["checks"]["hedge"]["passed"], bool)
    assert out["checks"]["opportunity"]["passed"] is False  # 1 event < 5: no CI, cannot pass
    assert not out["results"].empty and not out["placebo_results"].empty


def test_empty_window(tmp_path):
    out = run_family_study(_client(), CAL, CFG, "2022-01-01", "2022-03-31", T("2026-09-30"), cache_dir=tmp_path)
    assert out["events"].empty and out["results"].empty and out["checks"] == {}
