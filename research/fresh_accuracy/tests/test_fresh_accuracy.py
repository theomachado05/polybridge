"""Synthetic tests for the fresh-market accuracy study (no network)."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import fresh_accuracy  # noqa: F401
from arbscan.implied import Quote

from fresh_accuracy import freeze, rows as rw, stats as st
from fresh_accuracy.config import ARB_GAPS, PARAMS

ET = rw.ET
UTC = timezone.utc


def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(s, k, sig, t, r=0.04):
    d1 = (math.log(s / k) + (r + 0.5 * sig ** 2) * t) / (sig * math.sqrt(t))
    return s * _N(d1) - k * math.exp(-r * t) * _N(d1 - sig * math.sqrt(t))


def chain_quotes(snap: datetime, expiry: datetime, s=100.0, sig=0.3, age=60.0):
    t = (expiry - snap).total_seconds() / (365 * 86400)
    chain = {float(k): f"O:TST{k:05d}" for k in range(80, 121)}
    q = {tk: Quote(bid=max(bs_call(s, k, sig, t) - 0.01, 0.01), ask=bs_call(s, k, sig, t) + 0.01, bid_size=10, ask_size=10,
                   ts=snap.timestamp() - age) for k, tk in chain.items()}
    return chain, q


def market(start: datetime, end: datetime, strike=100.0) -> dict:
    return dict(id="1", ticker="TST", strike=str(strike), kind="daily", res_date=end.astimezone(ET).date().isoformat(),
                start=start.isoformat(), end=end.isoformat(), token="tok", cid="0xabc")


RD = date(2026, 3, 11)
END = datetime(2026, 3, 11, 16, 0, tzinfo=ET)
S1 = datetime(2026, 3, 10, 15, 45, tzinfo=ET)
S2 = datetime(2026, 3, 11, 12, 0, tzinfo=ET)
PREV = lambda d: d - timedelta(days=1)  # noqa: E731


def run_market(m, hist, chain, quotes):
    return rw.pm_market_rows(m, history_fn=lambda tok, a, b: hist, chain_fn=lambda u, d: chain,
                             quote_fn=lambda tk, snap: quotes.get(tk), prev_session_fn=PREV)


def test_snapshot_rules_listing_and_end():
    s, d = rw.snapshots(RD, S1 - timedelta(hours=1), END, PREV(RD))
    assert [x[0] for x in s] == ["S1", "S2"] and d == {}
    s, d = rw.snapshots(RD, S1 + timedelta(minutes=1), END, PREV(RD))
    assert [x[0] for x in s] == ["S2"] and d == {"snapshot_before_listing": 1}
    s, d = rw.snapshots(RD, S2 + timedelta(minutes=1), END, PREV(RD))
    assert s == [] and d == {"snapshot_before_listing": 2}
    s, d = rw.snapshots(RD, None, S2, PREV(RD))
    assert [x[0] for x in s] == ["S1"] and d == {"snapshot_not_before_end": 1}


def test_pm_price_at_or_before_snapshot_only():
    t = S2.timestamp()
    p, age = rw.pm_at([(int(t) - 120, 0.40), (int(t), 0.42), (int(t) + 30, 0.90)], t)
    assert p == 0.42 and age == 0
    assert rw.pm_at([(int(t) + 1, 0.5)], t) == (None, None)


def test_later_option_quote_never_fills_in():
    later = Quote(bid=1.0, ask=1.1, ts=S2.timestamp() + 1)
    earlier = Quote(bid=1.0, ask=1.1, ts=S2.timestamp() - 1)
    f = rw.strict_quote(lambda tk: later if tk == "L" else earlier, S2.timestamp())
    assert f("L") is None and f("E") is earlier


def test_market_rows_scored_and_filters():
    chain, q = chain_quotes(S2, END)
    hist = [(int(S1.timestamp()) - 60, 0.55), (int(S2.timestamp()) - 60, 0.60)]
    rows, drop = run_market(market(S1 - timedelta(days=1), END), hist, chain, q)
    assert [r["status"] for r in rows] == ["no_chain", "scored"]
    r = rows[1]
    assert rw.is_scored(r) and abs(r["p_mid"] - 0.5) < 0.1 and r["opt_half_band"] > 0 and r["pm_mid"] == 0.60
    rows, _ = run_market(market(S1 - timedelta(days=1), END), [(int(S2.timestamp()) - 10, 0.5)], chain, q)
    assert rows[1]["status"] == "pm_placeholder"
    rows, _ = run_market(market(S1 - timedelta(days=1), END), [(int(S2.timestamp()) - 901, 0.6)], chain, q)
    assert rows[1]["status"] == "pm_stale"
    rows, _ = run_market(market(S1 - timedelta(days=1), END), [(int(S2.timestamp()) - 10, 0.99)], chain, q)
    assert rows[1]["status"] == "pm_extreme"
    rows, _ = run_market(market(S1 - timedelta(days=1), END), [(int(S2.timestamp()) - 10, 0.6)], {}, q)
    assert rows[1]["status"] == "no_clean_expiry"


def test_stale_option_leg_rejected():
    chain, q = chain_quotes(S2, END, age=601)
    rows, _ = run_market(market(S1 - timedelta(days=1), END), [(int(S2.timestamp()) - 10, 0.6)], chain, q)
    assert rows[1]["status"] == "no_chain"


def test_scores_sign_and_values():
    y = np.array([1, 0])
    assert st.brier_diff([0.6, 0.4], [0.8, 0.2], y).tolist() == pytest.approx([0.16 - 0.04, 0.16 - 0.04])
    assert (st.log_diff([0.6, 0.4], [0.8, 0.2], y) > 0).all()
    assert st.log_score([0.0], [1])[0] == pytest.approx(-math.log(0.01))


def test_cluster_boot_reproducible_and_ratio_of_sums():
    rng = np.random.default_rng(0)
    cl = np.repeat(np.arange(50), rng.integers(1, 9, 50))
    v = rng.normal(0.01, 0.05, len(cl))
    a = st.cluster_boot({"x": v, "z": -v}, cl, draws=2000, seed=1)
    b = st.cluster_boot({"x": v, "z": -v}, cl, draws=2000, seed=1)
    assert a == b and a["x"]["mean"] == pytest.approx(v.mean()) and a["clusters"] == 50
    assert a["x"]["ci95"][0] < a["x"]["mean"] < a["x"]["ci95"][1]
    assert a["z"]["ci95"] == pytest.approx([-a["x"]["ci95"][1], -a["x"]["ci95"][0]])
    assert a["x"]["ci90"][0] > a["x"]["ci95"][0]


def _b(m, lo, hi):
    return {"mean": m, "ci95": [lo, hi], "cw_mean": m, "cw_ci95": [lo, hi]}


def test_verdict_rules():
    assert st.verdict(5000, 100, _b(1, 0.1, 2), _b(1, 0.1, 2)) == "PASS"
    assert st.verdict(5000, 100, _b(1, 0.1, 2), _b(1, -0.1, 2)) == "PARTIAL"
    assert st.verdict(5000, 100, _b(1, -0.1, 2), _b(1, -0.1, 2)) == "NULL"
    assert st.verdict(5000, 100, _b(-1, -2, -0.1), _b(1, 0.1, 2)) == "REVERSED"
    assert st.verdict(1999, 100, _b(1, 0.1, 2), _b(1, 0.1, 2)) == "INSUFFICIENT"
    assert st.verdict(5000, 39, _b(1, 0.1, 2), _b(1, 0.1, 2)) == "INSUFFICIENT"


def test_h3_verdict_rules():
    assert st.h3_verdict({"ci90": [-0.002, 0.002], "ci95": [-0.0025, 0.0025]}) == "EQUIVALENT"
    assert st.h3_verdict({"ci90": [0.001, 0.004], "ci95": [0.0005, 0.0045]}) == "OPTIONS-BETTER"
    assert st.h3_verdict({"ci90": [-0.006, -0.002], "ci95": [-0.007, -0.001]}) == "KALSHI-BETTER"
    assert st.h3_verdict({"ci90": [-0.004, 0.002], "ci95": [-0.005, 0.003]}) == "INCONCLUSIVE"


def test_logit_recovers_coefficients():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 1, (20000, 2))
    p = 1 / (1 + np.exp(-(0.2 + 1.0 * x[:, 0] + 0.0 * x[:, 1])))
    y = (rng.random(20000) < p).astype(float)
    r = st.logit_cluster(x, y, np.arange(20000) // 100)
    assert r["coef"][1] == pytest.approx(1.0, abs=0.08) and r["ci95"][2][0] < 0 < r["ci95"][2][1]


def test_ols_cluster_slope():
    rng = np.random.default_rng(4)
    x = rng.normal(0, 1, 5000)
    y = -0.05 * x + rng.normal(0, 0.1, 5000)
    r = st.ols_cluster(x, y, np.arange(5000) // 50)
    assert r["coef"][1] == pytest.approx(-0.05, abs=0.01) and r["ci95"][1][1] < 0


class Guard(dict):
    FORBIDDEN = {"outcomePrices", "lastTradePrice", "bestBid", "bestAsk"}

    def get(self, k, default=None):
        if k in self.FORBIDDEN:
            raise AssertionError(f"freeze read {k}")
        return super().get(k, default)

    def __getitem__(self, k):
        if k in self.FORBIDDEN:
            raise AssertionError(f"freeze read {k}")
        return super().__getitem__(k)


def _gm(i, q, end, closed=True):
    return Guard(id=i, question=q, closed=closed, clobTokenIds='["t%s","n"]' % i, endDate=end, startDate="2026-03-09T13:00:00Z",
                 conditionId=f"0x{i}", outcomePrices='["1","0"]', lastTradePrice=0.9)


def test_freeze_rules_and_outcome_blind():
    ev = [{"title": "Apple (AAPL)", "markets": [
        _gm("1", "Will Apple (AAPL) close above $240 on March 11?", "2026-03-11T20:00:00Z"),
        _gm("2", "Will Apple (AAPL) close above $250 on March 11?", "2026-03-11T20:00:00Z"),
        _gm("3", "Will Apple (AAPL) close above $240 on March 12?", "2026-03-12T20:00:00Z"),
        _gm("4", "Will Apple (AAPL) hit $240 on March 11?", "2026-03-11T20:00:00Z"),
        _gm("5", "Will Apple (AAPL) close above $240 on August 20?", "2026-08-20T20:00:00Z"),
        _gm("6", "Will Apple (AAPL) close above $240 on March 11?", "2026-03-11T20:00:00Z", closed=False),
    ]}]
    rows, c = freeze.frame(ev, ex_ids={"2"}, ex_dates={"2026-03-12"})
    assert [r["id"] for r in rows] == ["1"]
    assert rows[0]["ticker"] == "AAPL" and rows[0]["res_date"] == "2026-03-11" and rows[0]["strike"] == 240.0
    assert c["in_r3_events"] == 1 and c["on_r3_res_date"] == 1 and c["res_date_outside_window"] == 1 and c["not_closed"] == 1


def test_frozen_hash_enforced(tmp_path):
    p, h = tmp_path / "ids.csv", tmp_path / "ids.sha"
    freeze.write_frozen([dict(id="1", ticker="A", strike=1, kind="daily", res_date="2026-01-02", start="", end="", token="t",
                              cid="", question="q")], p, h)
    assert freeze.load_frozen(p, h)[0]["id"] == "1"
    p.write_text(p.read_text() + "x\n")
    with pytest.raises(RuntimeError):
        freeze.load_frozen(p, h)


def test_kalshi_two_sided_candle():
    t = S2.timestamp()
    c = [{"end_period_ts": int(t) - 120, "yes_bid": {"close": "0.4000"}, "yes_ask": {"close": "0.4400"}},
         {"end_period_ts": int(t) - 60, "yes_bid": {"close": "0.0000"}, "yes_ask": {"close": "1.0000"}},
         {"end_period_ts": int(t) + 60, "yes_bid": {"close_dollars": "0.5"}, "yes_ask": {"close_dollars": "0.6"}}]
    assert rw.kalshi_two_sided_at(c, t) == {"t": t - 120, "bid": 0.40, "ask": 0.44}
    assert rw.kalshi_two_sided_at(c[:1], t + 1000) is None
    assert rw.kalshi_event_ticker("KXINXU", date(2025, 11, 14)) == "KXINXU-25NOV14H1600"


def test_kalshi_select_top_by_volume():
    ms = [{"ticker": f"T{i}", "strike_type": "greater", "floor_strike": i, "volume_fp": str(i)} for i in range(12)]
    ms.append({"ticker": "B", "strike_type": "between", "floor_strike": 1, "volume_fp": "999"})
    sel = rw.kalshi_select(ms)
    assert [m["ticker"] for m in sel] == [f"T{i}" for i in range(11, 3, -1)]


@pytest.mark.skipif(not ARB_GAPS.exists(), reason="arb results not present")
def test_kill_a_scorer_reproduces_arb_brier():
    df = pd.read_csv(ARB_GAPS, low_memory=False)
    d = df[(df.venue == "polymarket") & (df.status == "scored") & df.clean.astype(bool) & ~df.live.astype(bool)
           & df.outcome.isin([0, 1])]
    assert len(d) == 2761 and round(float(st.brier_diff(d.pm_mid, d.p_mid, d.outcome).mean()), 4) == 0.0054
    e = d[d.pm_mid != PARAMS.placeholder]
    assert len(e) == 2743 and round(float(st.brier_diff(e.pm_mid, e.p_mid, e.outcome).mean()), 4) == 0.0044
    assert round(float(st.log_diff(e.pm_mid, e.p_mid, e.outcome).mean()), 4) == 0.0195


def test_analyse_and_report_end_to_end(tmp_path):
    from fresh_accuracy import report, run
    rng = np.random.default_rng(5)
    n = 3000
    dates = [f"2026-02-{d:02d}" for d in range(1, 29)] + [f"2026-03-{d:02d}" for d in range(1, 21)]
    p_opt = rng.uniform(0.05, 0.95, n)
    y = (rng.random(n) < p_opt).astype(int)
    sc = pd.DataFrame(dict(market_id=[str(i) for i in range(n)], snapshot=rng.choice(["S1", "S2"], n),
                           kind=rng.choice(["daily", "weekly", "monthly"], n), res_date=rng.choice(dates, n),
                           ticker=rng.choice(["AAPL", "SPY"], n), p_mid=p_opt,
                           pm_mid=np.clip(p_opt + rng.normal(0, 0.08, n), 0.02, 0.98), outcome=y,
                           opt_half_band=0.02, opt_comm_per_dollar=0.01, coarse=False, trade_print=rng.random(n) < 0.5))
    sc["event"] = sc.ticker + "|" + sc.res_date
    sc = run.score_frame(sc)
    res = run.analyse(sc)
    assert res["verdict"] in {"PASS", "PARTIAL"} and res["n_dates"] == 48
    res.update(no_outcome_rows=0, commit="abc", started_utc="2026-10-03T23:00:00+00:00", finished_utc="2026-10-04T00:00:00+00:00",
               seconds=1.0, requests={"http": {}, "massive": {}, "http_failures": 0, "massive_failures": 0},
               gate={"scored_rows": n, "dates": 48, "status": {}, "dropped_snapshots": {}},
               slice={"valid": 40, "rows": 90, "valid_rate": 0.44, "status": {}})
    report.write_summary(tmp_path, res)
    report.write_run_log(tmp_path, res, "primary")
    report.chart(sc, tmp_path / "c.png")
    s = (tmp_path / "SUMMARY.md").read_text()
    assert s.count("Verdict:") == 1 and "Equal weight per date" in s and (tmp_path / "c.png").stat().st_size > 1000
    res["h3"] = {"run": False, "reason": "test"}
    report.write_summary(tmp_path, res)
    assert "H3 not run: test" in (tmp_path / "SUMMARY.md").read_text()


def test_kalshi_rows_scored():
    chain, q = chain_quotes(S2, END)
    t = int(S2.timestamp())
    m = {"ticker": "KXINXU-26MAR11H1600-T100", "event_ticker": "KXINXU-26MAR11H1600", "floor_strike": 99.9999,
         "close_time": "2026-03-11T20:00:00Z", "open_time": "2026-03-10T21:00:00Z", "result": "yes"}
    candles = [{"end_period_ts": t - 60, "yes_bid": {"close": "0.50"}, "yes_ask": {"close": "0.54"}}]
    r = rw.kalshi_rows(m, "KXINXU", "SPX", "historical", candles_fn=lambda *a: candles, chain_fn=lambda u, d: chain,
                       quote_fn=lambda tk, snap: q.get(tk))
    assert rw.is_scored(r) and r["pm_mid"] == pytest.approx(0.52) and r["k_half_spread"] == pytest.approx(0.02)
    assert r["outcome"] == 1 and r["res_date"] == "2026-03-11"
    r = rw.kalshi_rows(m, "KXINXU", "SPX", "historical", candles_fn=lambda *a: [], chain_fn=lambda u, d: chain,
                       quote_fn=lambda tk, snap: q.get(tk))
    assert r["status"] == "no_two_sided_candle"
