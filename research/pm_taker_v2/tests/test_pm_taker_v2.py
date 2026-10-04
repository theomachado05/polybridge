"""Synthetic tests for the P2 study B taker study. No network, no key."""
import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import pm_taker_v2  # noqa: F401
from arbscan.implied import Quote, Spread
from pm_taker_v2 import analysis as A
from pm_taker_v2 import config as C
from pm_taker_v2 import core
from pm_taker_v2 import report
from pm_taker_v2.core import ET
from pm_taker_v2.run import fetch_trades

_p = Path(__file__).resolve().parents[2] / "arb" / "tests" / "synth.py"
_spec = importlib.util.spec_from_file_location("_pm_taker_synth", _p)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
make_chain, true_prob = _m.make_chain, _m.true_prob


@pytest.fixture(autouse=True)
def _v1_window(monkeypatch):
    monkeypatch.setattr(C, "RES_MIN", "2026-01-20")


def test_study_b_window():
    assert (C.RES_MAX, C.KILL_MAX, C.FREEZE_DEADLINE_ET) == ("2026-08-14", "2026-04-21", "2026-10-03T23:59:00")


def sessions(d):
    return d.weekday() < 5 and d not in {date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3)}


def listing(q="Will Apple (AAPL) close above $250 on March 4?", end="2026-03-04T21:00:00Z", start="2026-03-03T13:00:00Z", fees=True):
    return {"id": "1", "cond": "0xabc", "tok": ["111"], "tk": "AAPL", "k": 250.0, "end": end, "start": start, "fees": fees, "q": q}


def ts_et(d, h, m, s=0):
    return int(datetime(d.year, d.month, d.day, h, m, s, tzinfo=ET).timestamp())


def test_frame_keeps_weeknight_and_sets_window():
    r, why = core.frame_row(listing(), sessions)
    assert why == "" and r["res_date"] == "2026-03-04" and r["trade_day"] == "2026-03-03"
    assert r["w0"] == ts_et(date(2026, 3, 3), 10, 0) and r["w1"] == ts_et(date(2026, 3, 3), 15, 55)
    assert r["k"] == 250.0 and r["tk"] == "AAPL" and not r["empty_window"]


def test_frame_late_listing_moves_window_start():
    r, _ = core.frame_row(listing(start="2026-03-03T16:00:00Z"), sessions)
    assert r["w0"] == ts_et(date(2026, 3, 3), 11, 5)
    r, _ = core.frame_row(listing(start="2026-03-03T21:30:00Z"), sessions)
    assert r["empty_window"]


def test_frame_drops_reopening_days_and_out_of_window():
    _, why = core.frame_row(listing(end="2026-03-02T21:00:00Z", q="Will Apple (AAPL) close above $250 on March 2?"), sessions)
    assert why == "reopening_day"
    _, why = core.frame_row(listing(end="2026-02-17T21:00:00Z", q="Will Apple (AAPL) close above $250 on February 17?"), sessions)
    assert why == "reopening_day"
    _, why = core.frame_row(listing(end="2026-08-18T20:00:00Z", q="Will Apple (AAPL) close above $250 on August 18?"), sessions)
    assert why == "outside_window"
    _, why = core.frame_row(listing(q="Will Apple (AAPL) close above $250 at the end of the week of March 2?"), sessions)
    assert why.startswith("kind_")


def test_yes_equivalent_and_thinning():
    d = date(2026, 3, 3)
    t0 = ts_et(d, 10, 30, 5)
    raw = [
        {"timestamp": t0 + 70, "price": 0.40, "side": "SELL", "outcome": "No", "size": 5},
        {"timestamp": t0 + 10, "price": 0.62, "side": "BUY", "outcome": "Yes", "size": 3},
        {"timestamp": t0 + 10, "price": 0.61, "side": "BUY", "outcome": "Yes", "size": 2},
        {"timestamp": t0, "price": 0.30, "side": "BUY", "outcome": "No", "size": 7},
        {"timestamp": t0 - 4000, "price": 0.5, "side": "BUY", "outcome": "Yes", "size": 1},
    ]
    k = core.thin(raw, ts_et(d, 10, 0), ts_et(d, 15, 55))
    assert [(p["ts"], round(p["px"], 2), p["side"]) for p in k] == [(t0, 0.70, "SELL"), (t0 + 10, 0.61, "BUY"), (t0 + 70, 0.60, "BUY")]


def sp(p_mid, band=0.04):
    s = Spread(100.0, 101.0, Quote(0.6, 0.6), Quote(0.1, 0.1), 0.0, rate=0.0)
    s.p_mid, s.p_lo, s.p_hi, s.raw_mid = p_mid, p_mid - band / 2, p_mid + band / 2, p_mid
    return s


def test_evaluate_market_rule_and_stop():
    prints = [
        {"ts": 1, "px": 0.99, "side": "BUY", "size": 1},
        {"ts": 2, "px": 0.50, "side": "BUY", "size": 1},
        {"ts": 3, "px": 0.46, "side": "BUY", "size": 1},
        {"ts": 4, "px": 0.60, "side": "SELL", "size": 2},
        {"ts": 5, "px": 0.70, "side": "SELL", "size": 3},
        {"ts": 6, "px": 0.80, "side": "SELL", "size": 3},
    ]
    mids = {2: 0.52, 3: 0.50, 4: 0.53, 5: 0.58, 6: 0.50}
    seen = []

    def spread_at(t):
        seen.append(t)
        return sp(mids[t])

    ev, tr = core.evaluate_market(prints, spread_at)
    assert seen == [2, 3, 4, 5]
    assert tr[0.03]["ts"] == 3 and tr[0.05]["ts"] == 4 and tr[0.10]["ts"] == 5
    assert [e["status"] for e in ev] == ["ok"] * 4


def test_spread_status():
    assert core.spread_status(None) == "no_spread"
    assert core.spread_status(sp(0.5, band=0.25)) == "unusable"
    assert core.spread_status(sp(0.98)) == "unusable"
    assert core.spread_status(sp(0.5)) == "ok"


def test_option_spread_uses_quotes_strictly_before_print():
    t = 1000
    exp = t + 43200
    tyr = (exp - t) / (365 * 86400)
    chain, quotes = make_chain(s=100.0, sigma=0.3, t=tyr, ts=995.0, half=0.005)
    asked = []

    def quote_at(tkr, s):
        asked.append(s)
        return quotes[tkr]

    s = core.option_spread(chain, 100.5, quote_at, t, exp)
    assert s is not None and set(asked) == {t - 1}
    assert abs(s.p_mid - true_prob(100.0, 100.5, 0.3, tyr, 0.04)) < 0.1
    stale = {k: Quote(q.bid, q.ask, ts=t - 1 - 301) for k, q in quotes.items()}
    assert core.option_spread(chain, 100.5, lambda tkr, s: stale[tkr], t, exp) is None


def test_net_pnl_and_fee():
    f = lambda p: core.fee_per_share(p, True)
    assert core.net_pnl("BUY", 0.40, 1, 0.01, f) == pytest.approx(1 - 0.41 - 0.04 * 0.4 * 0.6)
    assert core.net_pnl("SELL", 0.70, 0, 0.01, f) == pytest.approx(1 - 0.31 - 0.04 * 0.3 * 0.7)
    assert core.net_pnl("SELL", 0.70, 1, 0.0, lambda p: 0.0) == pytest.approx(-0.30)
    assert core.fee_per_share(0.5, False) == 0.0
    assert core.fee_params({"feesEnabled": True, "feeSchedule": {"rate": 0.04, "exponent": 1}}) == (True, 0.04, 1.0)
    assert core.fee_params({"feesEnabled": False}) == (False, 0.04, 1.0)


def test_outcome_from_gamma():
    assert core.outcome_from_gamma({"outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]'}) == 1
    assert core.outcome_from_gamma({"outcomes": '["No","Yes"]', "outcomePrices": '["1","0"]'}) == 0
    assert core.outcome_from_gamma({"outcomes": '["Yes","No"]', "outcomePrices": '["0.5","0.5"]'}) is None


def test_cluster_boot_and_verdict():
    rng = np.random.default_rng(0)
    days = np.repeat(np.arange(60), 5)
    v = 0.05 + rng.normal(0, 0.3, 60)[days] * 0.2 + rng.normal(0, 0.4, 300)
    lo, hi = core.cluster_boot(v, days, draws=2000)
    assert lo < v.mean() < hi
    assert core.verdict(99, 50, 0.01, 0.1) == "INSUFFICIENT"
    assert core.verdict(150, 29, 0.01, 0.1) == "INSUFFICIENT"
    assert core.verdict(150, 40, 0.01, 0.1) == "PASS"
    assert core.verdict(150, 40, -0.1, -0.01) == "NEGATIVE"
    assert core.verdict(150, 40, -0.01, 0.1) == "NULL"


def test_kill_projection():
    k = core.kill_projection(20, 8, 200, 2400, 14, 83, 500, 100)
    assert k["projected_trades"] == pytest.approx(240) and k["projected_days"] == pytest.approx(8 * 83 / 14) and not k["stop"]
    k = core.kill_projection(5, 3, 200, 2400, 14, 83, 500, 200)
    assert set(k["reasons"]) == {"projected_trades_below_100", "projected_days_below_30", "no_spread_share_above_30pct"}


def test_mid_variant():
    ev = [{"ts": 100, "status": "ok", "p_mid": 0.5}, {"ts": 200, "status": "ok", "p_mid": 0.5}]
    assert core.mid_variant_trade(ev, [(50, 0.47), (150, 0.44)])["ts"] == 200
    assert core.mid_variant_trade(ev, [(50, 0.56)])["side"] == "SELL"
    assert core.mid_variant_trade(ev, [(-2000, 0.1)]) is None


class FakeHttp:
    def __init__(self, n):
        self.rows = [{"timestamp": i} for i in range(n)]
        self.calls = []

    def get_json(self, url, params=None, **kw):
        self.calls.append(params)
        o, l = params["offset"], params["limit"]
        return self.rows[o:o + l]


def test_fetch_trades_paging_and_cap():
    h = FakeHttp(1200)
    rows, cap = fetch_trades(h, "0x", 0, 10)
    assert len(rows) == 1200 and not cap and [c["offset"] for c in h.calls] == [0, 500, 1000]
    assert h.calls[0]["start"] == 0 and h.calls[0]["end"] == 10
    rows, cap = fetch_trades(FakeHttp(20000), "0x", 0, 10)
    assert cap and len(rows) == 10000


def synth_frames(n_days=40, per_day=4, edge=0.08, seed=1):
    rng = np.random.default_rng(seed)
    rows, evals = [], []
    for d in range(n_days):
        day = (date(2026, 3, 2) + timedelta(days=d)).isoformat()
        for j in range(per_day):
            p = rng.uniform(0.2, 0.8)
            y = int(rng.random() < p)
            side = "BUY" if j % 2 == 0 else "SELL"
            px = p - edge if side == "BUY" else p + edge
            for tau in (0.03, 0.05, 0.10):
                rows.append({"market_id": f"{d}-{j}", "tk": "SPY" if j < 2 else "NVDA", "k": 500.0, "res_date": day, "tau": tau,
                             "ts": 1, "side": side, "px": px, "size": 10.0, "p_mid": p, "y": y,
                             "fee_enabled": j % 2 == 0, "fee_rate": 0.04, "fee_exp": 1.0})
            evals.append({"market_id": f"{d}-{j}", "status": "ok", "p_mid": p, "px": px, "y": y})
    return pd.DataFrame(rows), pd.DataFrame(evals)


def test_score_and_summary_render():
    tr, ev = synth_frames()
    res = A.score(tr, ev)
    p = res["primary"]
    assert p["n"] == 160 and p["days"] == 40 and p["mean"] > 0
    assert p["verdict"] in {"PASS", "NULL"}
    assert res["secondary"]["tick_0.02"]["mean"] == pytest.approx(p["mean"] - 0.01)
    assert res["secondary"]["calibration"]["n_prints"] == 160
    prim = res.pop("primary_trades")
    md = report.summary_md({**res, "verdict": p["verdict"], "unresolved_trades": 0, "settlement_disagreements": [],
                            "scope": {}, "requests": {}, "commit": "x"}, prim)
    assert md.startswith(f"# P2 study B options-anchored Polymarket taker: {p['verdict']}")


def test_score_insufficient_when_few_trades():
    tr, ev = synth_frames(n_days=10, per_day=2)
    assert A.score(tr, ev)["primary"]["verdict"] == "INSUFFICIENT"


def test_chart_writes(tmp_path):
    tr, ev = synth_frames()
    res = A.score(tr, ev)
    report.chart(res["primary_trades"], ev, tmp_path / "c.png")
    assert (tmp_path / "c.png").stat().st_size > 1000
