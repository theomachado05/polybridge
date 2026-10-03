import numpy as np
import pandas as pd

from polybridge_research.analysis import decay_table, difference_board, pass_check, sample_placebo, scoreboard
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.strategies import STRATEGIES

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def _res(n, pp_mean, csp_mean, ratio_mean, seed):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        for entry in ("pre", "post"):
            for h in (5, 21, 42, "exp"):
                row = {"ticker": f"T{i % 7}", "bucket": "3-6m", "entry": entry, "otm": 0.05, "horizon": h,
                       "ratio": rng.normal(ratio_mean, 0.05)}
                for s in STRATEGIES:
                    row[s] = rng.normal(0.0, 0.01)
                row["protective_put"] = rng.normal(pp_mean, 0.01)
                row["cash_secured_put"] = rng.normal(csp_mean, 0.01)
                rows.append(row)
    return pd.DataFrame(rows)


def test_hedge_passes_when_edge_and_ratio_point_the_right_way():
    events = _res(80, pp_mean=0.03, csp_mean=0.0, ratio_mean=1.4, seed=1)
    placebo = _res(200, pp_mean=0.0, csp_mean=0.0, ratio_mean=1.0, seed=2)
    out = pass_check(events, placebo, "hedge", CFG)
    assert out["strategy"] == "protective_put"
    assert out["horizons_pnl_ok"] == [21, 42, "exp"] and out["horizons_ratio_ok"] == [21, 42, "exp"]
    assert out["passed"] is True


def test_opportunity_needs_ratio_below_placebo():
    events = _res(80, pp_mean=0.0, csp_mean=0.03, ratio_mean=1.4, seed=3)   # ratio points the wrong way
    placebo = _res(200, pp_mean=0.0, csp_mean=0.0, ratio_mean=1.0, seed=4)
    out = pass_check(events, placebo, "opportunity", CFG)
    assert out["strategy"] == "cash_secured_put"
    assert out["horizons_pnl_ok"] == [21, 42, "exp"] and out["horizons_ratio_ok"] == []
    assert out["passed"] is False


def test_null_effect_fails():
    out = pass_check(_res(80, 0, 0, 1.0, 5), _res(200, 0, 0, 1.0, 6), "hedge", CFG)
    assert out["passed"] is False


def test_difference_board_level_and_p_value():
    a, b = _res(80, 0.03, 0, 1.0, 7), _res(200, 0, 0, 1.0, 8)
    d95 = difference_board(a, b, CFG, level=0.95)
    d975 = difference_board(a, b, CFG, level=0.975)
    r95 = d95[(d95.strategy == "protective_put") & (d95.horizon == 21)].iloc[0]
    r975 = d975[(d975.strategy == "protective_put") & (d975.horizon == 21)].iloc[0]
    assert r975.ci_lo < r95.ci_lo and r95.p_value < 0.01
    ratio = difference_board(a, b, CFG, column="ratio", entry="pre")
    assert set(ratio.strategy) == {"ratio"}


def test_scoreboard_and_decay_shapes():
    res = _res(30, 0, 0, 1.2, 9)
    sb = scoreboard(res, CFG)
    assert {"strategy", "horizon", "n", "mean", "ci_lo", "ci_hi"} <= set(sb.columns)
    dt = decay_table(res, CFG)
    assert list(dt.index) == [5, 21, 42, "exp"] and dt.loc[21, "n"] == 30


def test_sample_placebo_respects_gap_and_window():
    ev = pd.DataFrame({"ticker": ["AAPL"] * 3, "filing_date": [T("2024-03-01"), T("2024-07-01"), T("2024-11-01")],
                       "family": ["hedge"] * 3})
    pl = sample_placebo(ev, 50, "2024-01-01", "2024-12-31", CAL, gap_days=30, seed=1)
    assert len(pl) == 50 and set(pl.ticker) == {"AAPL"} and set(pl.family) == {"hedge"}
    for d in pl.filing_date:
        assert all(abs((d - a).days) > 30 for a in ev.filing_date)
        assert T("2024-01-01") <= d <= T("2024-12-31")
    assert (pl.t_pre < pl.t_0).all()
