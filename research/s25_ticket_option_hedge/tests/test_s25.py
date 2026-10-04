"""S25: the price and the payoff of the hedge spread, the split rules, the outcome cells, the two-leg book."""
import math

import numpy as np
import pandas as pd
import pytest

from s25_ticket_option_hedge import config as cfg
from s25_ticket_option_hedge import engine as eg
from s25_ticket_option_hedge import pull

COMM5 = 2 * 0.65 / (100 * 5.0)          # commission per unit of a 5-wide spread


def test_up_hedge_buys_the_low_call_at_the_ask_and_sells_the_high_call_at_the_bid():
    c = eg.unit_cost(+1, lo_bid=3.00, lo_ask=3.20, hi_bid=1.00, hi_ask=1.10, width=5.0)
    assert c["quotes"] == pytest.approx((3.20 - 1.00) / 5.0)
    assert c["commission"] == pytest.approx(COMM5)
    assert c["cost"] == pytest.approx(0.44 + COMM5)
    assert c["mid"] == pytest.approx((3.10 - 1.05) / 5.0)
    assert not c["crossed"] and not c["above_one"]


def test_down_hedge_buys_the_high_put_at_the_ask_and_sells_the_low_put_at_the_bid():
    c = eg.unit_cost(-1, lo_bid=1.00, lo_ask=1.10, hi_bid=3.00, hi_ask=3.20, width=5.0)
    assert c["quotes"] == pytest.approx((3.20 - 1.00) / 5.0)


def test_two_times_costs_move_each_leg_a_further_half_spread_and_double_the_commission():
    c = eg.unit_cost(+1, 3.00, 3.20, 1.00, 1.10, 5.0, cost_mult=2.0)
    assert c["quotes"] == pytest.approx(((3.20 + 0.10) - (1.00 - 0.05)) / 5.0)
    assert c["commission"] == pytest.approx(2 * COMM5)
    assert eg.leg_prices(0.0, 0.04, 2.0) == pytest.approx((0.06, 0.0))            # a sale is never below zero


def test_a_crossed_pair_costs_zero_before_commission_and_is_flagged():
    c = eg.unit_cost(+1, 1.00, 1.05, 1.20, 1.30, 5.0)
    assert c["crossed"] and c["quotes"] == 0.0 and c["cost"] == pytest.approx(COMM5)
    assert eg.unit_cost(+1, 5.0, 6.5, 0.5, 0.6, 5.0)["above_one"]


def test_payoff_is_zero_short_of_the_near_strike_one_beyond_the_far_strike_and_linear_between():
    assert eg.unit_payoff(+1, 99.0, 100.0, 105.0) == 0.0
    assert eg.unit_payoff(+1, 102.0, 100.0, 105.0) == pytest.approx(0.4)
    assert eg.unit_payoff(+1, 110.0, 100.0, 105.0) == 1.0
    assert eg.unit_payoff(-1, 110.0, 100.0, 105.0) == 0.0
    assert eg.unit_payoff(-1, 102.0, 100.0, 105.0) == pytest.approx(0.6)
    assert eg.unit_payoff(-1, 95.0, 100.0, 105.0) == 1.0
    assert eg.hedge_pnl_points(2.0, 1.0, 0.3) == pytest.approx(140.0)
    assert eg.hedge_pnl_points(1.0, 0.0, 0.3) == pytest.approx(-30.0)


def test_a_monday_quote_must_come_from_that_session_and_have_an_offer():
    at, op = 1_000_300.0, 1_000_000.0
    assert eg.usable({"bid": 0.0, "ask": 0.05, "ts": at - 10}, at, op)            # a zero bid is accepted
    assert not eg.usable({"bid": 1.0, "ask": 1.1, "ts": op - 1}, at, op)          # Friday's last quote is not Monday's
    assert not eg.usable({"bid": 1.0, "ask": 0.0, "ts": at - 10}, at, op)
    assert not eg.usable({"bid": 1.2, "ask": 1.1, "ts": at - 10}, at, op)
    assert not eg.usable(None, at, op)
    assert not eg.usable({"bid": 1.0, "ask": 1.1, "ts": at + 5}, at, op)


def test_split_rules():
    sp = [{"execution_date": "2025-11-17", "split_from": 1.0, "split_to": 10.0}]
    assert eg.split_between(sp, "2025-10-31", "2025-11-28")
    assert eg.split_between(sp, "2025-11-14", "2025-11-17")
    assert not eg.split_between(sp, "2025-11-17", "2025-12-19")                    # executed on the anchor day: already on the new basis
    assert not eg.split_between(sp, "2025-10-03", "2025-10-31")
    assert eg.later_split_factor(sp, "2025-10-31") == pytest.approx(0.1)
    assert eg.later_split_factor(sp, "2025-11-17") == 1.0
    assert eg.reconciles(110.0, 1100.0, sp, "2025-10-31")
    assert not eg.reconciles(1100.0, 1100.0, sp, "2025-10-31")
    assert eg.reconciles(95.0, 95.0, sp, "2025-12-19")
    assert not eg.reconciles(float("nan"), 95.0, sp, "2025-12-19")
    assert eg.level_ratio_ok(110.0, 120.0) and not eg.level_ratio_ok(110.0, 1200.0) and not eg.level_ratio_ok(1100.0, 120.0)


def test_the_four_cells():
    assert eg.cell(0.0, +1, 95.0, 100.0) == "never touched"
    assert eg.cell(1.0, +1, 100.0, 100.0) == "touched and finished beyond"
    assert eg.cell(1.0, +1, 99.0, 100.0) == "touched and came back"
    assert eg.cell(0.0, +1, 101.0, 100.0) == "finished beyond without a recorded touch"
    assert eg.cell(1.0, -1, 99.0, 100.0) == "touched and finished beyond"
    assert eg.cell(1.0, -1, 101.0, 100.0) == "touched and came back"


def test_sd_ratio_and_its_interval():
    rng = np.random.default_rng(1)
    b = rng.normal(0, 10, 200)
    a = b / 2.0
    ev = np.repeat(np.arange(40), 5)
    r, lo, hi = eg.boot_sd_ratio(a, b, ev)
    assert r == pytest.approx(0.5) and lo == pytest.approx(0.5) and hi == pytest.approx(0.5)
    r, lo, hi = eg.boot_sd_ratio(rng.normal(0, 10, 200), b, ev)
    assert lo < r < hi and 0.6 < r < 1.5
    assert math.isnan(eg.boot_sd_ratio(a[:8], b[:8], [1, 1, 2, 2, 3, 3, 4, 4])[1])  # under 5 events: no interval


def test_worst_month_difference():
    a = np.array([[1.0, -2.0], [1.0, -1.0], [0.5, 0.5], [0.0, 1.0], [1.0, 0.0]])
    b = a * 2.0
    d, lo, hi, share = eg.boot_worst_month_diff(a, b)
    assert d == pytest.approx(a.sum(axis=0).min() - b.sum(axis=0).min())
    assert lo <= d <= hi and 0.0 <= share <= 1.0


def test_book_with_two_legs_books_each_leg_in_its_own_month_and_locks_both_capitals():
    jan, feb = 1767700000.0, 1770400000.0            # 2026-01-06, 2026-02-06 UTC
    legs = pd.DataFrame([
        {"market": "1", "event": "e", "segment": "IS", "pnl": 40.0, "capital": 60.0, "entry_epoch": jan, "end_epoch": jan + 86400},
        {"market": "1", "event": "e", "segment": "IS", "pnl": -25.0, "capital": 25.0, "entry_epoch": jan + 100, "end_epoch": feb},
        {"market": "2", "event": "f", "segment": "IS", "pnl": 10.0, "capital": 50.0, "entry_epoch": feb - 5, "end_epoch": feb + 5},
    ])
    monthly, out = eg.book(legs)
    assert list(monthly.month) == ["2026-01", "2026-02"] and list(monthly.pnl) == [40.0, -15.0]
    assert out["ALL"]["capital_base"] == 85.0 and out["ALL"]["pnl"] == 25.0 and out["ALL"]["markets"] == 2
    assert out["ALL"]["worst_month_dollars"] == -15.0 and out["ALL"]["max_drawdown"] == pytest.approx(15.0 / 85.0)
    assert out["OOS"]["months"] == 0


def test_the_copied_book_reproduces_s18s_book_on_the_ticket_leg_alone():
    from s18_price_market_calibration.report import book as s18_book
    d = pull.plan()
    entries = pd.read_csv(pull.S18 / "entries.csv")
    x = d.copy()
    x["market"] = x.market.astype(int)
    mon18, bk18 = s18_book(x, entries, "sell")
    size = np.minimum(d.sell_size, cfg.CONTRACTS)
    legs = pd.DataFrame({"market": d.market, "event": d.event, "segment": d.segment, "pnl": size * d.sell_pnl_points / 100.0,
                         "capital": size * (1.0 - d.sell_price), "entry_epoch": d.entry_epoch, "end_epoch": d.result_epoch})
    mon, bk = eg.book(legs)
    assert list(mon.month) == list(mon18.result_month)
    assert np.allclose(mon.pnl.to_numpy(), mon18.pnl.to_numpy())
    for seg in ("IS", "OOS", "ALL"):
        for k in ("sharpe", "max_drawdown", "worst_month", "capital_base", "pnl", "months"):
            assert bk[seg][k] == pytest.approx(bk18[seg][k]), (seg, k)


def test_the_plan_is_s21s_markets_and_s21s_rule_subset():
    d = pull.plan()
    assert len(d) == 277 and d.event.nunique() == 62 and int(d.rule.sum()) == 60
    b0 = pd.read_csv(pull.S21 / "trades.csv", dtype={"market": str})
    assert set(d[d.rule].market) == set(b0[b0.book == "B0"].market)
    assert (d.hedge_day > d.anchor_day).all() and (d.expiry > d.hedge_day).all()
    assert all(pd.Timestamp(x).weekday() in (0, 1) for x in d.hedge_day)           # a Monday, or a Tuesday after a holiday
    assert ((d.hedge_epoch - d.open_epoch) == 300).all()
