import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from s21_options_anchor import config as cfg
from s21_options_anchor import engine as eg
from s21_options_anchor import checks, pull, run

B0, B1, B2 = cfg.BOOKS
AT = 1_000_000.0


def rec(question, title, label, sign, start="2026-02-25T19:00:00Z"):
    return {"question": question, "event_title": title, "label": label, "sign": sign, "start": start}


def q(bid, ask, age=1.0):
    return eg.Quote(bid=bid, ask=ask, bid_size=10, ask_size=10, ts=AT - age)


def test_parse_reads_ticker_level_direction_and_window():
    p, why = eg.parse_market(rec("Will NVIDIA dip to $192 in March?", "What will NVIDIA (NVDA) hit in March 2026?", "↓ $192", -1))
    assert why == "" and p == {"ticker": "NVDA", "level": 192.0, "direction": -1, "window_end": "2026-03-31", "end_session": "2026-03-31"}
    p, _ = eg.parse_market(rec("Will S&P 500 (SPY) hit (LOW) $680 in June?", "What will S&P 500 (SPY) hit in June 2026?", "↓ $680", -1))
    assert (p["ticker"], p["level"], p["direction"], p["window_end"]) == ("SPY", 680.0, -1, "2026-06-30")
    p, _ = eg.parse_market(rec("Will S&P 500 (SPX) hit $7,350 (HIGH) in February 2026?", "What will S&P 500 (SPX) hit by end of February?", "↑ $7,350", 1,
                               start="2026-01-05T00:00:00Z"))
    assert (p["ticker"], p["level"], p["direction"], p["window_end"]) == ("SPX", 7350.0, 1, "2026-02-28")
    assert p["end_session"] == "2026-02-27"
    p, _ = eg.parse_market(rec("Will S&P 500 (SPX) hit 5500 (LOW) in March?", "What will S&P 500 (SPX) hit in March?", "↓ 5500", -1))
    assert (p["level"], p["direction"], p["window_end"]) == (5500.0, -1, "2026-03-31")


def test_parse_takes_the_direction_from_the_label_when_the_question_has_none():
    p, _ = eg.parse_market(rec("Will NVIDIA (NVDA) hit $250 before 2026??", "What will NVIDIA (NVDA) hit before 2026?", "↑ $250", 1, start="2025-09-01T00:00:00Z"))
    assert (p["direction"], p["window_end"], p["end_session"]) == (1, "2025-12-31", "2025-12-31")
    p, _ = eg.parse_market(rec("Will S&P 500 (SPY) hit (HIGH) $730 Week of May 4 2026?", "What will S&P 500 (SPY) hit Week of May 4 2026?", "↑ $730", 1))
    assert p["window_end"] == "2026-05-08"


def test_parse_drops_what_disagrees():
    assert eg.parse_market(rec("Will NVIDIA dip to $192 in March?", "What will NVIDIA (NVDA) hit in March 2026?", "↓ $192", 1))[1] == \
        "the parsed direction and the universe's sign disagree"
    assert eg.parse_market(rec("Will NVIDIA dip to $192 in March?", "What will NVIDIA (NVDA) hit in March 2026?", "↓ $195", -1))[1] == \
        "the question's level and the label's level disagree"
    assert eg.parse_market(rec("Will Tesla (TSLA) hit $500 before 2026??", "What will NVIDIA (NVDA) hit before 2026?", "↑ $500", 1))[1] == \
        "the question's ticker and the event's ticker disagree"
    assert eg.parse_market(rec("Will NVIDIA dip to $192 in March?", "What will NVIDIA hit?", "↓ $192", -1))[1] == "no single ticker in the event title"
    assert eg.parse_market(rec("Will NVIDIA (NVDA) hit $250 someday?", "What will NVIDIA (NVDA) hit someday?", "$250", 1))[1] == \
        "no direction in the question or the label"


def test_window_end_without_a_year_is_the_first_such_month_end_after_listing():
    assert eg.window_end("What will S&P 500 (SPX) hit by end of June?", date(2026, 1, 5)) == date(2026, 6, 30)
    assert eg.window_end("What will S&P 500 (SPX) hit in March?", date(2025, 12, 20)) == date(2026, 3, 31)
    assert eg.window_end("What will Meta (META) hit in November 2025?", date(2025, 10, 30)) == date(2025, 11, 30)
    assert eg.last_weekday(date(2025, 11, 30)) == date(2025, 11, 28) and eg.last_weekday(date(2026, 5, 31)) == date(2026, 5, 29)
    assert eg.window_end("What will it hit one day?", date(2026, 1, 1)) is None


def test_put_ticker_swaps_the_right_letter():
    assert eg.put_ticker("O:NVDA260402C00192000") == "O:NVDA260402P00192000"
    assert eg.put_ticker("O:SPXW260630C06900000") == "O:SPXW260630P06900000"


def test_call_spread_gives_the_probability_of_finishing_above_with_its_band():
    quotes = {100.0: q(6.0, 6.4), 105.0: q(3.0, 3.2), 110.0: q(1.0, 1.2)}
    sp = eg.finish_beyond(list(quotes), 105.0, 1, quotes.get, 0.0, AT)
    assert (sp.k1, sp.k2, sp.stepped) == (100.0, 110.0, 0)
    assert sp.p_mid == pytest.approx((6.2 - 1.1) / 10) and sp.p_lo == pytest.approx((6.0 - 1.2) / 10) and sp.p_hi == pytest.approx((6.4 - 1.0) / 10)
    sp = eg.finish_beyond(list(quotes), 107.0, 1, quotes.get, 0.0, AT)
    assert (sp.k1, sp.k2) == (105.0, 110.0) and sp.p_mid == pytest.approx((3.1 - 1.1) / 5)
    one_year = eg.finish_beyond(list(quotes), 107.0, 1, quotes.get, 1.0, AT)
    assert one_year.p_mid == pytest.approx((3.1 - 1.1) / 5 * math.exp(cfg.RATE))


def test_put_spread_gives_the_probability_of_finishing_below():
    puts = {90.0: q(0.9, 1.1), 95.0: q(2.0, 2.4), 100.0: q(4.0, 4.4)}
    sp = eg.finish_beyond(list(puts), 97.0, -1, puts.get, 0.0, AT)
    assert (sp.k1, sp.k2) == (95.0, 100.0)
    assert sp.p_mid == pytest.approx((4.2 - 2.2) / 5) and sp.p_lo == pytest.approx((4.0 - 2.4) / 5) and sp.p_hi == pytest.approx((4.4 - 2.0) / 5)


def test_a_zero_bid_leg_is_used_and_a_stale_or_empty_leg_steps_outward():
    quotes = {100.0: q(0.05, 0.10), 105.0: q(0.0, 0.03), 110.0: q(0.0, 0.0), 95.0: q(0.3, 0.4)}
    sp = eg.finish_beyond(sorted(quotes), 102.0, 1, quotes.get, 0.0, AT)
    assert (sp.k1, sp.k2, sp.stepped) == (100.0, 105.0, 0) and sp.p_mid == pytest.approx((0.075 - 0.015) / 5) and sp.p_lo == pytest.approx(0.02 / 5)
    stale = {100.0: q(0.05, 0.10, age=cfg.STALE_OPTION_S + 1), 105.0: q(0.0, 0.03), 95.0: q(0.3, 0.4), 110.0: None}
    sp = eg.finish_beyond(sorted(stale), 102.0, 1, stale.get, 0.0, AT)
    assert (sp.k1, sp.k2, sp.stepped) == (95.0, 105.0, 1)
    assert not eg.usable(q(0.0, 0.0), AT) and not eg.usable(q(0.5, 0.4), AT) and not eg.usable(None, AT) and eg.usable(q(0.0, 0.01), AT)


def test_no_bracket_or_no_quotes_gives_no_anchor():
    quotes = {100.0: q(6.0, 6.4), 105.0: q(3.0, 3.2)}
    assert eg.finish_beyond(list(quotes), 1200.0, 1, quotes.get, 0.0, AT) is None
    assert eg.finish_beyond(list(quotes), 102.0, 1, lambda k: None, 0.0, AT) is None


def test_anchors_lower_bound_and_reflection_capped_at_one():
    assert eg.anchors(0.2) == (0.2, 0.4) and eg.anchors(0.7) == (0.7, 1.0) and eg.anchors(0.0) == (0.0, 0.0)


def test_gap_buckets_include_the_lower_edge():
    assert [eg.gap_bucket(x) for x in (-30, -5.01, -5, -0.01, 0, 4.99, 5, 9.99, 10, 60)] == \
        ["below -5", "below -5", "-5 to +0", "-5 to +0", "+0 to +5", "+0 to +5", "+5 to +10", "+5 to +10", "+10 or more", "+10 or more"]
    assert run.BUCKETS == ["below -5", "-5 to +0", "+0 to +5", "+5 to +10", "+10 or more"]


def test_the_rule_sells_above_the_central_anchor_and_buys_below_the_lower_bound():
    assert eg.selected(B0, 0.30, 0.25) and not eg.selected(B0, 0.2999, 0.25) and not eg.selected(B0, 0.20, 0.25)
    assert eg.selected(B1, 0.35, 0.25) and not eg.selected(B1, 0.30, 0.25)
    assert eg.selected(B2, 0.20, 0.25) and not eg.selected(B2, 0.21, 0.25) and not eg.selected(B2, 0.30, 0.25)
    assert not eg.selected(B0, float("nan"), 0.25) and not eg.selected(B0, 0.30, float("nan"))
    assert (B0.side, B0.anchor, B0.threshold, B1.threshold, B2.side, B2.anchor) == ("sell", "central", 5.0, 10.0, "buy", "lower")


def test_clustered_ols_recovers_the_line_and_widens_the_error_for_copied_rows():
    rng = np.random.default_rng(1)
    x = rng.normal(size=200)
    y = 1.0 + 2.0 * x + rng.normal(size=200)
    b, se = eg.ols_cluster(y, x[:, None], np.arange(200))
    assert b[1] == pytest.approx(2.0, abs=0.2) and 0.04 < se[1] < 0.12
    b4, se4 = eg.ols_cluster(np.tile(y, 4), np.tile(x, 4)[:, None], np.tile(np.arange(200), 4))
    assert b4[1] == pytest.approx(b[1]) and se4[1] == pytest.approx(se[1], rel=0.02)
    exact, _ = eg.ols_cluster(np.array([1.0, 3.0, 5.0, 7.0]), np.array([[0.0], [1.0], [2.0], [3.0]]), ["a", "a", "b", "c"])
    assert exact == pytest.approx([1.0, 2.0])


def test_brier_and_the_bootstrap_slope():
    assert eg.brier(np.array([0.5, 0.0, 1.0]), np.array([1.0, 0.0, 1.0])) == pytest.approx(0.25 / 3)
    x = np.arange(40, dtype=float)
    ev = np.array([str(i // 4) for i in range(40)])
    b, lo, hi = run.boot_slope(x, -0.5 * x + 3.0, ev)
    assert b == pytest.approx(-0.5) and lo == pytest.approx(-0.5) and hi == pytest.approx(-0.5)
    assert all(v != v for v in run.boot_slope(x[:8], x[:8], ev[:8])[1:])


def test_anchor_instant_is_1555_or_1255_on_a_half_session():
    full = pd.Timestamp("2026-03-06 16:00", tz="America/New_York").timestamp()
    half = pd.Timestamp("2025-11-28 13:05", tz="America/New_York").timestamp()
    close = {"2026-03-06": full, "2025-11-28": half}
    day, at = pull.anchor_epoch(pd.Timestamp("2026-03-06 20:00", tz="America/New_York").timestamp(), close)
    assert day == "2026-03-06" and at == pd.Timestamp("2026-03-06 15:55", tz="America/New_York").timestamp()
    day, at = pull.anchor_epoch(pd.Timestamp("2025-11-28 20:00", tz="America/New_York").timestamp(), close)
    assert day == "2025-11-28" and at == pd.Timestamp("2025-11-28 12:55", tz="America/New_York").timestamp()


def test_build_anchor_walks_to_the_first_expiry_with_two_usable_legs():
    class Fake:
        def __init__(self):
            self.asked = []

        def contracts(self, und, expiry):
            self.asked.append(expiry)
            return {"2026-04-02": {"190.0000": "O:NVDA260402C00190000", "195.0000": "O:NVDA260402C00195000"},
                    "2026-04-10": {"190.0000": "O:NVDA260410C00190000", "195.0000": "O:NVDA260410C00195000"}}.get(expiry, {})

        def quote(self, opt, at):
            if "260402" in opt:
                return None
            assert opt[-9] == "P"
            return {"bid": 9.0, "ask": 9.4, "bsz": 5, "asz": 5, "ts": at - 2} if opt.endswith("195000") else {"bid": 7.0, "ask": 7.2, "bsz": 5, "asz": 5, "ts": at - 3}

    m = {"ticker": "NVDA", "level": 192.0, "direction": -1, "end_session": "2026-03-31", "anchor_day": "2026-03-06", "anchor_epoch": AT}
    src = Fake()
    a = pull.build_anchor(src, m)
    assert a["status"] == "ok" and a["expiry"] == "2026-04-10" and a["expiry_rank"] == 2 and a["days_expiry_after_end"] == 10
    assert a["option_type"] == "put" and (a["k_lo"], a["k_hi"]) == (190.0, 195.0)
    t = 35 / 365.0
    assert a["p_mid"] == pytest.approx((9.2 - 7.1) / 5 * math.exp(cfg.RATE * t)) and a["anchor_central"] == pytest.approx(min(1.0, 2 * a["p_mid"]))
    assert "2026-04-04" not in src.asked and src.asked[0] == "2026-03-31"
    none = pull.build_anchor(Fake(), {**m, "level": 500.0})
    assert none["status"] == "no listed strikes bracket the level"


def test_placebo_with_identical_anchors_equals_the_observed_difference():
    price = np.array([0.50, 0.60, 0.10, 0.12, 0.40, 0.05])
    pnl = np.array([30.0, 40.0, 5.0, -80.0, 20.0, 5.0])
    same = checks.placebo(price, np.full(6, 0.20), pnl, 5.0, draws=50)
    taken = np.array([True, True, False, False, True, False])
    assert same["observed"] == pytest.approx(pnl[taken].mean() - pnl[~taken].mean())
    assert same["placebo_mean"] == pytest.approx(same["observed"]) and same["share_at_least_observed"] == 1.0 and same["mean_markets_taken"] == 3.0


def test_placebo_keeps_prices_and_results_and_only_moves_the_anchors():
    price = np.array([0.50, 0.50, 0.50, 0.50])
    pnl = np.array([50.0, 50.0, -50.0, -50.0])
    out = checks.placebo(price, np.array([0.10, 0.10, 0.60, 0.60]), pnl, 5.0, draws=200)
    assert out["observed"] == pytest.approx(100.0) and out["placebo_mean"] < 60.0 and out["hi"] <= 100.0 and out["mean_markets_taken"] == 2.0
