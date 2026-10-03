import pandas as pd

from polybridge_research.analysis import sample_placebo
from polybridge_research.atlas import count_variants, run_atlas
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig, TOP_100
from polybridge_research.evaluate import evaluate
from polybridge_research.pricing import price_events
from tests.fakes import FakeClient, FakeMarket, disclosure

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def test_count_variants():
    assert count_variants(CFG) == 3 * 2 * 3 * 9 * 5
    assert count_variants(CFG, n_tags=119) == 3 * 2 * 3 * 9 * 5 * 119


def test_run_atlas_rows_and_rare_tag():
    days = pd.bdate_range("2024-02-01", "2024-09-30")[::5][:12]
    disc = {"dividend_declaration": [disclosure(f"d{i}", "1", ["AAPL"], d.strftime("%Y-%m-%d")) for i, d in enumerate(days)],
            "going_concern": [disclosure("g1", "1", ["AAPL"], "2024-04-02")]}
    client = FakeClient(disc, FakeMarket({"AAPL": 100.0}))
    pl_ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2023-01-03")]})
    placebo = sample_placebo(pl_ev, 20, "2024-01-01", "2024-12-31", CAL, gap_days=0, seed=3)
    base = {CFG.baseline_bucket: CFG.buckets[CFG.baseline_bucket]}
    pl_priced, _ = price_events(client, placebo, CAL, CFG, buckets=base, max_workers=2)
    pl_res = evaluate(pl_priced, CAL, CFG, last_session=T("2026-09-30"))
    atlas = run_atlas(client, CAL, CFG, ["dividend_declaration", "going_concern"], "2024-01-01", "2024-12-31",
                      T("2026-09-30"), pl_res, max_events_per_tag=30, max_workers=2)
    assert set(atlas.tag) == {"dividend_declaration", "going_concern"}
    assert atlas.exploratory.all()
    assert len(atlas[atlas.tag == "dividend_declaration"]) == 5 * 3          # 5 strategies x 3 headline horizons
    rare = atlas[atlas.tag == "going_concern"]
    assert rare.p_value.isna().all() and rare.q_value.isna().all()
    common = atlas[atlas.tag == "dividend_declaration"]
    assert common.q_value.notna().all()
