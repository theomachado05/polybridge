"""S23: the window clock, the print conversion, the replay rule, the costs, the bootstrap and the closure Sharpe."""
import math

import numpy as np
import pytest

from s23_monday_fade_real import config as cfg
from s23_monday_fade_real import run as s23


def test_snapshot_is_0945_new_york_in_winter_and_summer():
    assert s23.snapshot_epoch("2026-01-05") == 1767624300.0          # 14:45 UTC, standard time
    assert s23.snapshot_epoch("2026-07-06") == 1783345500.0          # 13:45 UTC, daylight saving


def test_windows_are_exact_seconds_lower_bound_in_upper_bound_out():
    assert s23.window_of(0.0) == "0-15" and s23.window_of(14.999) == "0-15"
    assert s23.window_of(15.0) == "15-60" and s23.window_of(15.5) == "15-60"       # 10:00:30 is not in the first 15 minutes
    assert s23.window_of(60.0) == "60-180" and s23.window_of(180.0) == "180+"
    assert s23.window_of(-0.1) is None


def test_fee_is_s6s():
    assert s23.fee(0.5) == pytest.approx(0.01) and s23.fee(0.5, 2.0) == pytest.approx(0.02)
    assert s23.fee(0.0) == 0.0 and s23.fee(1.0) == 0.0


def _prints(t0):
    return [{"timestamp": t0 + 1900, "price": 0.20, "side": "BUY", "outcome": "Yes", "size": 500},      # after 10:15: ignored
            {"timestamp": t0 + 900, "price": 0.70, "side": "SELL", "outcome": "No", "size": 30},       # taker sold NO at 0.70 = bought YES at 0.30
            {"timestamp": t0 + 600, "price": 0.33, "side": "BUY", "outcome": "Yes", "size": 40},
            {"timestamp": t0 + 300, "price": 0.60, "side": "BUY", "outcome": "No", "size": 25},        # taker bought NO at 0.60 = sold YES at 0.40
            {"timestamp": t0 + 60, "price": 0.36, "side": "SELL", "outcome": "Yes", "size": 10},
            {"timestamp": t0 - 5, "price": 0.10, "side": "BUY", "outcome": "Yes", "size": 500}]         # before 09:45: ignored


def test_prints_are_converted_to_yes_terms_and_cut_to_the_window():
    rows = s23.yes_prints(_prints(1000.0), 1000.0)
    assert [(r["ts"], r["side"], round(r["px"], 2)) for r in rows] == [(1060.0, "SELL", 0.36), (1300.0, "SELL", 0.40), (1600.0, "BUY", 0.33), (1900.0, "BUY", 0.30)]


def test_window_end_is_inclusive_and_same_second_prints_keep_api_order():
    ps = [{"timestamp": 2800, "price": 0.31, "side": "BUY", "outcome": "Yes", "size": 1},
          {"timestamp": 2800, "price": 0.32, "side": "BUY", "outcome": "Yes", "size": 1},              # listed later = printed earlier
          {"timestamp": 2801, "price": 0.10, "side": "BUY", "outcome": "Yes", "size": 1}]
    rows = s23.yes_prints(ps, 1000.0)
    assert [r["px"] for r in rows] == [0.32, 0.31]


def test_buy_takes_the_lowest_taker_purchase_plus_one_cent():
    rows = s23.yes_prints(_prints(1000.0), 1000.0)
    x = s23.replay(rows, "buy YES", 0.45, 0.50)
    assert x["status"] == "trade" and x["print_px"] == pytest.approx(0.30) and x["entry"] == pytest.approx(0.31)
    assert x["print_size"] == pytest.approx(30) and x["edge"] == pytest.approx(0.45 - 0.31 - 0.04 * 0.31 * 0.69)


def test_sell_takes_the_highest_taker_sale_minus_one_cent():
    rows = s23.yes_prints(_prints(1000.0), 1000.0)
    x = s23.replay(rows, "sell YES", 0.20, 0.25)
    assert x["status"] == "trade" and x["print_px"] == pytest.approx(0.40) and x["entry"] == pytest.approx(0.39)
    assert x["print_size"] == pytest.approx(25) and x["edge"] == pytest.approx(0.39 - 0.04 * 0.39 * 0.61 - 0.25)


def test_no_trade_when_the_printed_price_is_not_two_points_beyond_the_band_after_the_fee():
    rows = s23.yes_prints(_prints(1000.0), 1000.0)
    x = s23.replay(rows, "buy YES", 0.335, 0.40)                       # 0.335 - 0.31 - fee is under 2 points
    assert x["status"] == "print, gap gone" and x["print_px"] == pytest.approx(0.30)
    assert s23.replay(rows, "buy YES", 0.45, 0.50, c=2.0)["entry"] == pytest.approx(0.32)       # two cents at 2x costs
    assert s23.replay([], "buy YES", 0.45, 0.50)["status"] == "no print on the side"
    only_sales = [r for r in rows if r["side"] == "SELL"]
    assert s23.replay(only_sales, "buy YES", 0.45, 0.50)["status"] == "no print on the side"   # a sale never proves an offer


def test_size_sums_the_prints_at_the_best_price_only():
    rows = [{"ts": 1.0, "order": 0, "px": 0.30, "side": "BUY", "size": 60.0}, {"ts": 2.0, "order": 0, "px": 0.30, "side": "BUY", "size": 70.0},
            {"ts": 3.0, "order": 0, "px": 0.31, "side": "BUY", "size": 999.0}]
    assert s23.replay(rows, "buy YES", 0.45, 0.50)["print_size"] == pytest.approx(130.0)


def test_first_print_mode_takes_the_first_that_still_clears_the_line():
    rows = s23.yes_prints(_prints(1000.0), 1000.0)
    x = s23.replay(rows, "buy YES", 0.45, 0.50, mode="first")
    assert x["print_px"] == pytest.approx(0.33) and x["entry"] == pytest.approx(0.34) and x["print_size"] == pytest.approx(40)
    y = s23.replay(rows, "buy YES", 0.365, 0.40, mode="first")          # 0.33 does not clear it, 0.30 does
    assert y["print_px"] == pytest.approx(0.30) and y["status"] == "trade"
    assert s23.replay(rows, "buy YES", 0.30, 0.40, mode="first")["status"] == "print, gap gone"


def test_pnl_and_capital_held_to_the_result():
    assert s23.pnl_per_contract("buy YES", 0.31, 1.0) == pytest.approx(1 - 0.31 - s23.fee(0.31))
    assert s23.pnl_per_contract("buy YES", 0.31, 0.0, 2.0) == pytest.approx(-0.31 - s23.fee(0.31, 2.0))
    assert s23.pnl_per_contract("sell YES", 0.39, 0.0) == pytest.approx(0.39 - s23.fee(0.39))
    assert s23.pnl_per_contract("sell YES", 0.39, 1.0) == pytest.approx(0.39 - s23.fee(0.39) - 1.0)
    assert s23.capital_per_contract("buy YES", 0.31) == pytest.approx(0.31)
    assert s23.capital_per_contract("sell YES", 0.39) == pytest.approx(0.61)


def test_partner_net_matches_its_definition_and_doubles_costs():
    assert s23.partner_net("BUY", 0.30, 1, True, 0.04, 1.0) == pytest.approx(1 - 0.31 - 0.04 * 0.30 * 0.70)
    assert s23.partner_net("SELL", 0.70, 1, False, 0.04, 1.0) == pytest.approx(0 - 0.31)           # bought NO at 0.30, YES won
    assert s23.partner_net("SELL", 0.70, 0, True, 0.04, 1.0, 2.0) == pytest.approx(1 - 0.32 - 2 * 0.04 * 0.30 * 0.70)


def test_bootstrap_resamples_whole_closures():
    v, c = [1.0, 1.0, 1.0, -1.0], ["a", "a", "a", "b"]
    b = s23.boot_mean(v, c)
    assert b["mean"] == pytest.approx(0.5) and math.isnan(b["lo"])                              # two closures: no interval
    v = [1.0] * 6 + [-1.0] * 6
    c = ["a", "a", "b", "b", "c", "c", "d", "d", "e", "e", "f", "f"]
    b = s23.boot_mean(v, c)
    assert b["closures"] == 6 and b["lo"] < 0 < b["hi"]
    tight = s23.boot_mean([2.0] * 12, c)
    assert tight["lo"] == pytest.approx(2.0) and tight["hi"] == pytest.approx(2.0)


def test_difference_bootstrap_is_joint_over_closures():
    c = ["a", "b", "c", "d", "e", "f"]
    d = s23.boot_diff([3.0] * 6, c, [1.0] * 6, c)
    assert d["diff"] == pytest.approx(2.0) and d["lo"] == pytest.approx(2.0) and d["hi"] == pytest.approx(2.0) and d["dropped"] == 0
    d2 = s23.boot_diff([3.0, 3.0], ["a", "b"], [1.0] * 4, ["c", "d", "e", "f"])
    assert d2["dropped"] > 0 and d2["lo"] == pytest.approx(2.0)


def test_closure_sharpe_counts_idle_closures_as_zero_and_uses_52_a_year():
    cal = ["2026-01-05", "2026-01-12", "2026-01-20", "2026-01-26"]
    m = s23.closure_sharpe({"2026-01-05": 10.0, "2026-01-20": -5.0}, {"2026-01-05": 50.0, "2026-01-20": 100.0}, cal)
    r = np.array([0.10, 0.0, -0.05, 0.0])
    assert m["capital_base"] == 100.0
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(52))
    assert m["max_drawdown"] == pytest.approx(0.05) and m["total_return"] == pytest.approx(0.05)


def test_best_closure_is_removed_from_the_trades_and_the_calendar():
    tr = [{"closure": "a", "pnl": 5.0, "capital": 1.0}, {"closure": "a", "pnl": 5.0, "capital": 1.0}, {"closure": "b", "pnl": 8.0, "capital": 1.0},
          {"closure": "c", "pnl": -1.0, "capital": 1.0}]
    rest, cal, best = s23.without_best(tr, ["a", "b", "c", "d"])
    assert best == "a" and cal == ["b", "c", "d"] and [t["closure"] for t in rest] == ["b", "c"]


def test_book_totals_and_printed_dollars():
    tr = [{"closure": "a", "pnl": 5.0, "capital": 10.0, "printed": 10.0, "printed_uncapped": 30.0}, {"closure": "b", "pnl": -2.0, "capital": 20.0, "printed": 20.0, "printed_uncapped": 20.0}]
    b = s23.book(tr, ["a", "b", "c"])
    assert b["trades"] == 2 and b["closures_traded"] == 2 and b["total"] == pytest.approx(3.0) and b["capital_base"] == 20.0
    assert b["printed_dollars"] == pytest.approx(30.0) and b["printed_dollars_uncapped"] == pytest.approx(50.0) and b["best_closure"] == "a"
    assert s23.book([], ["a"])["trades"] == 0


def test_config_is_the_pre_registered_one():
    assert cfg.T1_TAU == 0.05 and cfg.T1_PNL == "pnl_t1" and cfg.T2_WINDOW_S == 1800 and cfg.T2_SLIP == 0.01 and cfg.T2_THETA == 0.02
    assert cfg.T2_MAX_CONTRACTS == 100 and cfg.CLOSURES_PER_YEAR == 52.0 and cfg.OOS_FROM == "2026-08-03" and cfg.T1_MIN_RECENT_TRADES == 30
