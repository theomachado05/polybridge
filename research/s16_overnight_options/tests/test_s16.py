"""S16 (overnight options): the rules of METHOD.md as tests. No network."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from s16_overnight_options import config as cfg
from s16_overnight_options import engine as eg
from s16_overnight_options import pull, run


def test_expand_keeps_largest_move_per_ticker_day_and_signs_direction():
    m = pd.DataFrame([
        {"day": "2026-03-02", "market": "polymarket:20", "question": "a", "tickers": "-USO +JETS", "x": 12.0, "weekend": True},
        {"day": "2026-03-02", "market": "polymarket:10", "question": "b", "tickers": "+USO", "x": -15.0, "weekend": True},
        {"day": "2026-03-03", "market": "polymarket:10", "question": "b", "tickers": "+USO", "x": 9.9, "weekend": False},
    ])
    e = eg.expand(m, 10.0)
    assert len(e) == 2
    uso = e[e.ticker == "USO"].iloc[0]
    assert uso.market == "polymarket:10" and uso.x == -15.0 and uso.direction == -1       # down move, positive link: asset down
    jets = e[e.ticker == "JETS"].iloc[0]
    assert jets.direction == 1 and jets.x == 12.0
    assert len(eg.expand(m, 5.0)) == 3
    assert eg.expand(m, 5.0).query("ticker == 'USO' and day == '2026-03-02'").iloc[0].direction == -1


def test_expand_negative_link_flips_direction_and_tie_takes_lowest_id():
    m = pd.DataFrame([
        {"day": "d", "market": "polymarket:7", "question": "q7", "tickers": "-XLE", "x": 11.0, "weekend": False},
        {"day": "d", "market": "polymarket:3", "question": "q3", "tickers": "+XLE", "x": 11.0, "weekend": False},
    ])
    e = eg.expand(m, 10.0)
    assert len(e) == 1 and e.iloc[0].market == "polymarket:3" and e.iloc[0].direction == 1


def test_match_controls_nearest_earlier_on_tie_used_once_and_limit():
    assert eg.match_controls([10], {9, 11}) == {10: 9}                    # tie: the earlier one
    assert eg.match_controls([10, 11], {9, 12}) == {10: 9, 11: 12}
    assert eg.match_controls([10, 12], {11}) == {10: 11}                  # a session serves once
    assert eg.match_controls([50], {10}, max_dist=30) == {}               # 40 trading days away: no control
    assert eg.match_controls([50], {20}, max_dist=30) == {50: 20}
    used = {9}
    assert eg.match_controls([10], {9, 13}, used) == {10: 13} and used == {9, 13}


def test_oos_is_most_recent_fifth_of_event_dates():
    days = [f"2026-01-{d:02d}" for d in range(1, 11)]
    assert eg.oos_from(days) == "2026-01-09"
    assert eg.oos_from(days + days) == "2026-01-09"


def test_put_ticker():
    assert eg.put_ticker("O:USO260116C00080000") == "O:USO260116P00080000"


def test_valid_quote_rules():
    q = {"bid": 1.0, "ask": 1.2, "ts": 1000.0}
    assert eg.valid_quote(q, 1100.0, 900)
    assert not eg.valid_quote(q, 2000.0, 900)                             # too old
    assert not eg.valid_quote(q, 1100.0, 900, floor=1050.0)               # stamped before 09:30
    assert not eg.valid_quote(q, 900.0, 900)                              # stamped after the instant
    assert not eg.valid_quote({"bid": 0.0, "ask": 1.2, "ts": 1000.0}, 1100.0, 900)
    assert not eg.valid_quote({"bid": 1.3, "ask": 1.2, "ts": 1000.0}, 1100.0, 900)
    assert not eg.valid_quote(None, 1100.0, 900)


ENTRY = {"call": (1.00, 1.10), "put": (0.90, 1.00)}
EXIT = {"call": (1.50, 1.60), "put": (0.40, 0.50)}


def test_directional_trade_buys_at_ask_sells_at_bid():
    t = eg.trade("H-dir", +1, ENTRY, EXIT, 1.0)
    assert t["pnl"] == pytest.approx((1.50 - 1.10) * 100 - 2 * 0.65)
    assert t["ret"] == pytest.approx(((1.50 - 1.10) * 100 - 1.30) / 110.0)
    p = eg.trade("H-dir", -1, ENTRY, EXIT, 1.0)
    assert p["pnl"] == pytest.approx((0.40 - 1.00) * 100 - 1.30)
    m = eg.trade("H-dir", +1, ENTRY, EXIT, None)
    assert m["ret"] == pytest.approx((1.55 - 1.05) / 1.05)


def test_straddle_long_and_short_are_mirror_before_costs_and_both_pay_the_spread():
    lo = eg.trade("H-slow", 0, ENTRY, EXIT, None)
    sh = eg.trade("H-rich", 0, ENTRY, EXIT, None)
    assert lo["ret"] == pytest.approx(-sh["ret"]) == pytest.approx((2.00 - 2.00) / 2.00)
    lo1 = eg.trade("H-slow", 0, ENTRY, EXIT, 1.0)
    sh1 = eg.trade("H-rich", 0, ENTRY, EXIT, 1.0)
    assert lo1["pnl"] == pytest.approx((1.90 - 2.10) * 100 - 4 * 0.65)
    assert sh1["pnl"] == pytest.approx((1.90 - 2.10) * 100 - 4 * 0.65)    # flat mid: both sides lose the spread and commissions
    assert sh1["premium"] == pytest.approx(190.0) and lo1["premium"] == pytest.approx(210.0)


def test_double_costs_doubles_spread_and_commission():
    t2 = eg.trade("H-dir", +1, ENTRY, EXIT, 2.0)
    # call entry 1.00/1.10 widened to 0.95/1.15; exit 1.50/1.60 widened to 1.45/1.65
    assert t2["pnl"] == pytest.approx((1.45 - 1.15) * 100 - 2 * 2 * 0.65)
    assert eg.widen(0.01, 0.05, 2.0)[0] == 0.0                            # a bid cannot go below zero


def test_trade_needs_every_leg():
    assert eg.trade("H-slow", 0, {"call": (1, 1.1), "put": None}, EXIT, 1.0) is None
    assert eg.trade("H-dir", +1, {"call": (1, 1.1), "put": None}, EXIT, 1.0) is not None


def test_rel_spread():
    assert eg.rel_spread(ENTRY, ["call", "put"]) == pytest.approx(0.20 / 2.00)
    assert math.isnan(eg.rel_spread({"call": None, "put": (1, 2)}, ["call", "put"]))


def test_boot_mean_resamples_dates_and_is_deterministic():
    by = {f"d{i}": [0.01 * i, 0.01 * i] for i in range(10)}
    a, b = eg.boot_mean(by), eg.boot_mean(by)
    assert a == b and a[1] < a[0] < a[2] and a[0] == pytest.approx(0.045)
    assert math.isnan(eg.boot_mean({"d1": [0.1], "d2": [0.2]})[1])        # under five dates: no interval
    assert all(math.isnan(v) for v in eg.boot_mean({}))


def test_book_drawdown_and_worst_month():
    b = eg.book(np.array([0.1, -0.2, -0.1, 0.3]), ["2026-01-05", "2026-01-06", "2026-02-02", "2026-02-03"])
    assert b["max_drawdown"] == pytest.approx(0.3) and b["worst_month"] == pytest.approx(-0.1) and b["total_return"] == pytest.approx(0.1)


def test_verdict_lines():
    assert eg.verdict(40, 0.05, 0.01, 0.02, 0.03)[0].startswith("pass")
    assert eg.verdict(12, 0.05, 0.01, 0.02, 0.03)[0] == "too few observations"
    v, lines = eg.verdict(40, 0.05, -0.01, 0.02, 0.03)
    assert v == "fail" and [ok for _, ok, _ in lines] == [True, False, True, True]
    assert eg.verdict(40, -0.05, -0.09, -0.12, -0.03)[0] == "fail"
    assert eg.verdict(0, float("nan"), float("nan"), float("nan"), float("nan"))[0] == "fail"


class FakeCtx:
    op = np.array([0, 100_000])
    cl = np.array([23_400, 123_400])

    def first_price(self, tk, i):
        return 50.2

    def price_at(self, tk, at):
        return 50.0

    def instants(self, i):
        o = int(self.op[i])
        return {"prev": int(self.cl[i - 1]) - 300, "0931": o + 60, "0935": o + 300, "0945": o + 900, "1000": o + 1800, "1030": o + 3600,
                "close": int(self.cl[i]) - 300}


class FakeSrc:
    def __init__(self, bad=()):
        self.asked, self.bad = [], set(bad)

    def contracts(self, tk, day, spot):
        return {"expiry": "2026-03-13", "strikes": {"49.0000": "O:XYZ260313C00049000", "50.0000": "O:XYZ260313C00050000", "51.0000": "O:XYZ260313C00051000"}}

    def quote(self, opt, at):
        self.asked.append((opt, at))
        if (opt[-9], at) in self.bad:
            return None
        return {"bid": 1.0, "ask": 1.1, "bsz": 10.0, "asz": 20.0, "ts": at - 5.0}


ITEM = {"tier": 1, "sample": "main", "kind": "event", "ticker": "XYZ", "day": "2026-03-02", "i": 1, "event_day": "2026-03-02", "segment": "IS",
        "weekend": True, "x": 12.0, "direction": 1, "market": "polymarket:1", "question": "q", "full": True, "need_prev": True}


def test_observe_picks_nearest_strike_and_tracks_same_contracts_all_day():
    src = FakeSrc()
    r = pull.observe(src, ITEM, FakeCtx())
    assert r["status"] == "ok" and r["strike"] == 50.0 and r["put"] == "O:XYZ260313P00050000" and r["dte"] == 11
    assert {o for o, _ in src.asked} == {"O:XYZ260313C00050000", "O:XYZ260313P00050000"}
    assert len(src.asked) == 14 and src.asked[0][1] == 100_300 and src.asked[2][1] == 123_100      # 09:35 first, then 15:55
    assert r["c_ask_0931"] == 1.1 and r["p_bid_prev"] == 1.0


def test_observe_drops_without_a_primary_quote_and_asks_nothing_more():
    src = FakeSrc(bad={("P", 123_100)})
    r = pull.observe(src, ITEM, FakeCtx())
    assert r["status"] == "no valid quote at 15:55" and len(src.asked) == 4
    src = FakeSrc(bad={("C", 100_060)})                                   # a missing 09:31 quote does not drop the ticker-day
    r = pull.observe(src, ITEM, FakeCtx())
    assert r["status"] == "ok" and "c_bid_0931" not in r and r["c_why_0931"] == "no quote"


def test_observe_control_and_short_tiers_ask_fewer_instants():
    src = FakeSrc()
    pull.observe(src, {**ITEM, "kind": "control", "need_prev": False}, FakeCtx())
    assert len(src.asked) == 12
    src = FakeSrc()
    pull.observe(src, {**ITEM, "full": False, "need_prev": False}, FakeCtx())
    assert len(src.asked) == 4


def test_morning_quote_must_be_stamped_after_the_open():
    class Stale(FakeSrc):
        def quote(self, opt, at):
            self.asked.append((opt, at))
            return {"bid": 1.0, "ask": 1.1, "bsz": 1.0, "asz": 1.0, "ts": 99_990.0}      # ten seconds before the open

    r = pull.observe(Stale(), ITEM, FakeCtx())
    assert r["status"] == "no valid quote at 09:35"


def _rec(kind, day, event_day, c1, p1, c2, p2, direction=1, ticker="XYZ"):
    return {"status": "ok", "sample": "main", "kind": kind, "segment": "IS", "ticker": ticker, "day": day, "event_day": event_day, "weekend": False,
            "x": 12.0, "direction": direction, "market": "m", "question": "q", "expiry": "e", "strike": 50.0, "dte": 9, "spot_open": 50.0,
            "c_bid_0935": c1[0], "c_ask_0935": c1[1], "p_bid_0935": p1[0], "p_ask_0935": p1[1], "c_asz_0935": 7.0, "p_asz_0935": 3.0,
            "c_bsz_0935": 5.0, "p_bsz_0935": 9.0,
            "c_bid_close": c2[0], "c_ask_close": c2[1], "p_bid_close": p2[0], "p_ask_close": p2[1], "u_0935": 50.0, "u_close": 51.0}


def test_make_trades_and_pair_difference():
    recs = [_rec("event", "2026-03-02", "2026-03-02", (1.0, 1.1), (0.9, 1.0), (1.5, 1.6), (0.4, 0.5)),
            _rec("control", "2026-03-03", "2026-03-02", (1.0, 1.1), (0.9, 1.0), (1.0, 1.1), (0.9, 1.0))]
    tr = run.make_trades(recs, cfg.VARIANTS[0], ("main",))
    assert len(tr) == 6
    ev = [t for t in tr if t["kind"] == "event" and t["hypothesis"] == "H-dir"]
    ct = [t for t in tr if t["kind"] == "control" and t["hypothesis"] == "H-dir"]
    assert ev[0]["legs"] == "call" and ev[0]["size_at_entry_contracts"] == 7.0
    assert ev[0]["ret_mid"] == pytest.approx(0.5 / 1.05) and ct[0]["ret_mid"] == pytest.approx(0.0)
    d = run.pair_diffs(ev, ct, "ret_mid")
    assert d == {"2026-03-02": [pytest.approx(0.5 / 1.05)]}
    st = [t for t in tr if t["kind"] == "event" and t["hypothesis"] == "H-slow"][0]
    assert st["size_at_entry_contracts"] == 3.0 and st["entry_ask"] == pytest.approx(2.1)
    sh = [t for t in tr if t["kind"] == "event" and t["hypothesis"] == "H-rich"][0]
    assert sh["size_at_entry_contracts"] == 5.0 and sh["ret_mid"] == pytest.approx(-st["ret_mid"])


def test_weekend_variant_and_missing_exit():
    recs = [_rec("event", "2026-03-02", "2026-03-02", (1.0, 1.1), (0.9, 1.0), (1.5, 1.6), (0.4, 0.5))]
    assert run.make_trades(recs, cfg.VARIANTS[4], ("main",)) == []                       # not a weekend
    assert run.make_trades(recs, cfg.VARIANTS[2], ("main",)) == []                       # no 10:30 quote: no trade
    assert [v.id for v in cfg.VARIANTS] == ["V0", "V1", "V2", "V3", "V4"] and cfg.PRIMARY == "V0"


def test_config_is_the_registered_design():
    assert cfg.MAIN_THRESHOLD == 10.0 and cfg.OOS_FROM == "2026-06-22" and cfg.MIN_OOS_TRADES == 30
    assert (cfg.EXPIRY_MIN_DAYS, cfg.EXPIRY_MAX_DAYS) == (7, 45) and cfg.MAX_RPS <= 2.0
    assert cfg.MORNING == ("09:31", "09:35", "09:45", "10:00", "10:30") and cfg.COST_MULTIPLIERS == (1.0, 2.0)
