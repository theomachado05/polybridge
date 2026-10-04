from datetime import date

import pandas as pd
import pytest

import forward_monday  # noqa: F401
from forward_monday import config as C
from forward_monday import core
from forward_monday.run import score, sessions

SESS = sessions()


def meta(q="Will Apple (AAPL) close above $250 on October 5?", end="2026-10-05T20:00:00Z", start="2026-10-02T13:00:00Z"):
    m = {"id": "1", "conditionId": "0xabc", "clobTokenIds": '["111","222"]', "outcomes": '["Yes","No"]', "question": q,
         "startDate": start, "endDate": end, "feesEnabled": True, "outcomePrices": '["0.6","0.4"]', "bestBid": 0.59}
    return core.strip_meta(m)


def test_reopenings_in_window():
    assert core.reopenings(SESS) == [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26)]


def test_strip_meta_drops_prices():
    m = meta()
    assert "outcomePrices" not in m and "bestBid" not in m


def test_select_window_and_week():
    r, why = core.select(meta(), date(2026, 10, 5), SESS)
    assert why == "" and r["tk"] == "AAPL" and r["res_date"] == "2026-10-05" and r["tok"] == "111"
    assert r["w0"] == int(core.P.et(date(2026, 10, 5), (9, 45)).timestamp())
    r, _ = core.select(meta(q="Will Apple (AAPL) close above $250 on October 9?", end="2026-10-09T20:00:00Z"), date(2026, 10, 5), SESS)
    assert r["res_date"] == "2026-10-09"
    r, why = core.select(meta(end="2026-10-13T20:00:00Z"), date(2026, 10, 5), SESS)
    assert r is None and why == "outside_week"


def test_late_listing_shifts_window():
    r, _ = core.select(meta(start="2026-10-05T15:00:00Z"), date(2026, 10, 5), SESS)
    assert r["w0"] == int(core.P.parse_iso("2026-10-05T15:05:00Z").timestamp())


def test_verdict_rules():
    assert core.verdict(10, 1, None, None, False) == "RUNNING"
    assert core.verdict(10, 1, None, None, True) == "INSUFFICIENT"
    assert core.verdict(30, 4, 0.01, 0.1, True) == "PASS"
    assert core.verdict(30, 4, -0.1, -0.01, False) == "NEGATIVE"
    assert core.verdict(30, 4, -0.1, 0.1, False) == "NULL"


def test_score_net_pnl():
    rows = []
    for i, d in enumerate(["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]):
        for j in range(8):
            rows.append({"reopening": d, "market_id": f"{i}{j}", "tk": "AAPL", "k": 250, "res_date": d, "tau": C.TAU, "ts": 0,
                         "side": "BUY", "px": 0.40, "size": 100, "y": 1, "fee_enabled": False, "fee_rate": 0.04, "fee_exp": 1})
    s, prim = score(pd.DataFrame(rows), window_over=True)
    assert s["primary"]["n"] == 32 and s["primary"]["reopenings"] == 4
    assert s["primary"]["mean"] == pytest.approx(0.59)
    assert s["verdict"] == "PASS"
    assert s["secondary"]["capacity"]["dollars_deployed"] == pytest.approx(32 * 50 * 0.41)
