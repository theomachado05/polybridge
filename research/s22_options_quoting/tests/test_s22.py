"""S22 unit tests on synthetic rows only. Nothing here reads the input file."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from s22_options_quoting import config as C
from s22_options_quoting import run as R


def frame(rows):
    base = {"market_id": "1", "tk": "SPY", "k": 500.0, "res_date": "2026-05-06", "ts": 1778000000, "side": "BUY",
            "px": 0.60, "size": 10.0, "status": "ok", "p_mid": 0.45, "p_lo": 0.40, "p_hi": 0.50, "y": 0}
    return pd.DataFrame([{**base, **r} for r in rows])


def one(**kw):
    variant = {k: kw.pop(k) for k in ("m", "through", "tick", "at_print") if k in kw}
    variant.setdefault("m", 0.05)
    f, info = R.fills(frame([kw]), **variant)
    return f, info


def test_config_is_the_registered_design():
    assert C.M_PRIMARY == 0.05 and C.M_VARIANTS == (0.02, 0.10)
    assert C.POST_RANGE == (0.02, 0.98) and C.QUOTE_SIZE == 100.0
    assert C.STRESS_WIDEN == 0.02 and C.STRESS_THROUGH == 0.01
    assert C.OOS_SHARE == 0.20 and C.MIN_FILLS == 100 and C.MIN_DAYS == 30


def test_quotes_sit_m_outside_the_band():
    bid, offer = R.quotes([0.40], [0.50], 0.05)
    assert bid[0] == pytest.approx(0.35) and offer[0] == pytest.approx(0.55)


def test_quotes_outside_the_posting_range_are_not_posted():
    bid, offer = R.quotes([0.05, 0.07, 0.90], [0.10, 0.93, 0.95], 0.05)
    assert math.isnan(bid[0]) and offer[0] == pytest.approx(0.15)          # bid 0.00 not posted
    assert bid[1] == pytest.approx(0.02) and offer[1] == pytest.approx(0.98)  # exactly on the edges: posted
    assert bid[2] == pytest.approx(0.85) and math.isnan(offer[2])          # offer 1.00 not posted


def test_tick_grid_rounds_away_from_the_band():
    bid, offer = R.quotes([0.418], [0.512], 0.05, tick=0.01)
    assert bid[0] == pytest.approx(0.36) and offer[0] == pytest.approx(0.57)
    bid, offer = R.quotes([0.40], [0.50], 0.05, tick=0.01)                 # already on the grid: unchanged
    assert bid[0] == pytest.approx(0.35) and offer[0] == pytest.approx(0.55)


def test_taker_buy_above_our_offer_fills_at_our_offer_not_at_the_print():
    f, _ = one(side="BUY", px=0.60, y=0)
    assert len(f) == 1 and f.loc[0, "our_side"] == "offer"
    assert f.loc[0, "quote"] == pytest.approx(0.55)
    assert f.loc[0, "pnl_pt"] == pytest.approx(55.0)                       # sold at 0.55, result NO
    f, _ = one(side="BUY", px=0.60, y=1)
    assert f.loc[0, "pnl_pt"] == pytest.approx(-45.0)                      # sold at 0.55, result YES


def test_taker_sell_below_our_bid_fills_at_our_bid():
    f, _ = one(side="SELL", px=0.30, y=1)
    assert len(f) == 1 and f.loc[0, "our_side"] == "bid" and f.loc[0, "quote"] == pytest.approx(0.35)
    assert f.loc[0, "pnl_pt"] == pytest.approx(65.0)
    f, _ = one(side="SELL", px=0.30, y=0)
    assert f.loc[0, "pnl_pt"] == pytest.approx(-35.0)


def test_print_at_the_quote_fills_and_inside_it_does_not():
    assert len(one(side="BUY", px=0.55)[0]) == 1
    assert len(one(side="BUY", px=0.54)[0]) == 0
    assert len(one(side="SELL", px=0.35)[0]) == 1
    assert len(one(side="SELL", px=0.36)[0]) == 0


def test_wrong_side_prints_never_fill():
    assert len(one(side="SELL", px=0.60)[0]) == 0                          # a seller above our offer is not our fill
    assert len(one(side="BUY", px=0.30)[0]) == 0                           # a buyer below our bid is not our fill


def test_unposted_quote_gives_no_fill():
    assert len(one(side="BUY", px=0.94, p_lo=0.90, p_mid=0.92, p_hi=0.94)[0]) == 0    # offer would be 0.99
    assert len(one(side="SELL", px=0.03, p_lo=0.06, p_mid=0.08, p_hi=0.10)[0]) == 0   # bid would be 0.01


def test_size_is_capped_at_100_and_capital_is_the_cash_locked():
    f, _ = one(side="BUY", px=0.60, size=250.0, y=0)
    assert f.loc[0, "contracts"] == 100.0
    assert f.loc[0, "capital_usd"] == pytest.approx(45.0)                  # sale: (1 - 0.55) x 100
    assert f.loc[0, "pnl_usd"] == pytest.approx(55.0)
    f, _ = one(side="SELL", px=0.30, size=10.0, y=1)
    assert f.loc[0, "contracts"] == 10.0
    assert f.loc[0, "capital_usd"] == pytest.approx(3.5)                   # purchase: 0.35 x 10
    assert f.loc[0, "pnl_usd"] == pytest.approx(6.5)


def test_stress_needs_one_cent_through_the_widened_quote():
    kw = dict(m=C.M_PRIMARY + C.STRESS_WIDEN, through=C.STRESS_THROUGH)
    assert len(one(side="BUY", px=0.57, **kw)[0]) == 0                     # at the widened offer: queue, no fill
    f, _ = one(side="BUY", px=0.58, y=0, **kw)
    assert len(f) == 1 and f.loc[0, "quote"] == pytest.approx(0.57) and f.loc[0, "pnl_pt"] == pytest.approx(57.0)
    assert len(one(side="SELL", px=0.33, **kw)[0]) == 0
    f, _ = one(side="SELL", px=0.32, y=0, **kw)
    assert len(f) == 1 and f.loc[0, "quote"] == pytest.approx(0.33) and f.loc[0, "pnl_pt"] == pytest.approx(-33.0)


def test_benchmark_is_the_other_side_of_every_print_at_its_own_price():
    f, _ = R.fills(frame([{"side": "BUY", "px": 0.45, "y": 1}, {"side": "SELL", "px": 0.45, "y": 1, "ts": 1778000060}]),
                   m=0.0, at_print=True)
    assert len(f) == 2
    assert sorted(f["pnl_pt"].round(6)) == [-55.0, 55.0]


def test_missing_result_and_zero_size_are_dropped_and_counted():
    df = frame([{"side": "BUY", "px": 0.60, "y": None}, {"side": "BUY", "px": 0.60, "size": 0.0, "ts": 1778000060},
                {"side": "BUY", "px": 0.60, "ts": 1778000120}])
    f, info = R.fills(df, m=0.05)
    assert len(f) == 1
    assert info == {"prints_through_quote": 3, "dropped_no_size": 1, "dropped_no_result": 1}


def test_sample_keeps_only_ok_rows():
    df = frame([{"status": "ok"}, {"status": "unusable"}, {"status": "no_spread"}])
    assert len(R.sample(df)) == 1


def test_dose_bins():
    assert list(R.dose_bin([0.05, 0.0999, 0.10, 0.1999, 0.20, 0.50], 0.05)) == \
        ["m to 2m", "m to 2m", "2m to 4m", "2m to 4m", "beyond 4m", "beyond 4m"]
    f, _ = one(side="BUY", px=0.62, y=0)
    assert f.loc[0, "dose_pt"] == pytest.approx(12.0) and f.loc[0, "dose_bin"] == "2m to 4m"
    f, _ = one(side="SELL", px=0.33, y=0)
    assert f.loc[0, "dose_pt"] == pytest.approx(7.0) and f.loc[0, "dose_bin"] == "m to 2m"


def test_p_mid_regions():
    assert list(R.region([0.05, 0.10, 0.249, 0.25, 0.749, 0.75, 0.899, 0.90, 0.97])) == \
        ["below 10%", "10 to 25%", "10 to 25%", "25 to 75%", "25 to 75%", "75 to 90%", "75 to 90%", "above 90%", "above 90%"]


def test_out_of_sample_is_the_last_fifth_of_the_dates():
    d = [f"2026-05-{i:02d}" for i in range(1, 11)]
    assert R.oos_dates(d + d) == ["2026-05-09", "2026-05-10"]
    assert R.oos_dates(d + ["2026-05-11"]) == ["2026-05-09", "2026-05-10", "2026-05-11"]     # ceil(2.2) = 3
    df = frame([{"side": "BUY", "px": 0.60, "res_date": "2026-05-01"}, {"side": "BUY", "px": 0.60, "res_date": "2026-05-10"}])
    f, _ = R.fills(df, m=0.05, oos=["2026-05-09", "2026-05-10"])
    assert list(f["sample"]) == ["in-sample", "out-of-sample"]


def test_cluster_bootstrap_resamples_days():
    lo, hi = R.cluster_boot([1.0, 2.0, 3.0], ["a", "a", "a"])
    assert lo == pytest.approx(2.0) and hi == pytest.approx(2.0)           # one day = one bet: no spread
    rng = np.random.default_rng(0)
    v = rng.normal(5.0, 10.0, 400)
    c = np.repeat(np.arange(40), 10)
    lo, hi = R.cluster_boot(v, c)
    assert lo < v.mean() < hi
    assert (lo, hi) == R.cluster_boot(v, c)                                # fixed seed
    # the same value repeated inside a day must not narrow the interval
    lo1, hi1 = R.cluster_boot(np.repeat(v[:40], 10), c)
    lo2, hi2 = R.cluster_boot(v[:40], np.arange(40))
    assert (lo1, hi1) == pytest.approx((lo2, hi2))


def test_weighted_bootstrap_and_day_weight():
    v, c, w = [10.0, 0.0, 0.0], ["a", "b", "b"], [1.0, 1.0, 8.0]
    lo, hi = R.cluster_boot(v, c, weights=w)
    assert lo == pytest.approx(0.0) and hi == pytest.approx(10.0)
    m, lo, hi = R.day_weight(v, c)
    assert m == pytest.approx(5.0) and lo == pytest.approx(0.0) and hi == pytest.approx(10.0)


def test_book_sharpe_drawdown_and_worst_month():
    dates = ["2026-04-01", "2026-04-02", "2026-04-30", "2026-05-01", "2026-05-29"]
    df = frame([{"side": "BUY", "px": 0.60, "size": 100.0, "y": 0, "res_date": dates[0]},              # +55
                {"side": "BUY", "px": 0.60, "size": 100.0, "y": 1, "res_date": dates[1], "ts": 1778000060},   # -45
                {"side": "SELL", "px": 0.30, "size": 100.0, "y": 0, "res_date": dates[3], "ts": 1778000120},  # -35
                {"side": "SELL", "px": 0.30, "size": 100.0, "y": 1, "res_date": dates[4], "ts": 1778000180}])  # +65
    f, _ = R.fills(df, m=0.05)
    daily, m = R.book(f, dates)
    pnl = np.array([55.0, -45.0, 0.0, -35.0, 65.0])
    assert list(daily["pnl_usd"].round(6)) == list(pnl)
    assert list(daily["cum_pnl_usd"].round(6)) == [55.0, 10.0, 10.0, -25.0, 40.0]
    assert m["max_drawdown_usd"] == pytest.approx(-80.0)                   # from +55 to -25
    assert m["bankroll_usd"] == pytest.approx(45.0)                        # a sale at 0.55 locks 45; a buy at 0.35 locks 35
    assert m["total_pnl_usd"] == pytest.approx(40.0) and m["total_capital_usd"] == pytest.approx(160.0)
    assert m["return_on_capital"] == pytest.approx(0.25)
    dpy = 5 * 365.25 / 59                                                  # 1 April to 29 May inclusive = 59 days
    assert m["days_per_year"] == pytest.approx(dpy)
    assert m["sharpe"] == pytest.approx(pnl.mean() / pnl.std(ddof=1) * math.sqrt(dpy))
    assert m["worst_month"] == "2026-04"
    assert m["worst_month_pnl_usd"] == pytest.approx(10.0)                 # April +10, May +30
    assert m["dates_with_fills"] == 4 and m["winning_dates"] == 2 and m["losing_dates"] == 2


def test_stat_row_counts_and_means():
    df = frame([{"side": "BUY", "px": 0.60, "size": 100.0, "y": 0, "market_id": "1", "res_date": "2026-04-01"},
                {"side": "BUY", "px": 0.60, "size": 10.0, "y": 1, "market_id": "2", "res_date": "2026-04-02"}])
    f, _ = R.fills(df, m=0.05)
    r = R.stat_row(f, "v", "all", "all")
    assert (r["n_fills"], r["days"], r["markets"]) == (2, 2, 2)
    assert r["mean_pt"] == pytest.approx(5.0)                              # (+55 - 45) / 2, each fill once
    assert r["contract_weight_mean_pt"] == pytest.approx(100 * (55.0 - 4.5) / 110)
    assert r["pnl_usd"] == pytest.approx(50.5)
    empty = R.stat_row(f.iloc[:0], "v", "all", "all")
    assert empty["n_fills"] == 0 and empty["mean_pt"] == ""


def test_verdict_names_the_failing_lines():
    def row(n, days, mean, lo, hi):
        return {"n_fills": n, "days": days, "mean_pt": mean, "ci_lo_pt": lo, "ci_hi_pt": hi}
    v, lines = R.verdict(row(150, 40, 5.0, 1.0, 9.0), row(120, 32, 5.0, 0, 0), row(30, 8, 4.0, 0, 0), row(90, 30, 2.0, 0, 0))
    assert v == "PASS" and all(h for _, h, _ in lines)
    v, lines = R.verdict(row(80, 25, 5.0, -1.0, 9.0), row(80, 25, 5.0, 0, 0), row(0, 0, "", "", ""), row(60, 20, -2.0, 0, 0))
    assert v == "FAIL"
    assert [t[:1] for t, h, _ in lines if not h] == ["1", "2", "4", "6", "7"]


def _world(truth: str, n: int = 4000) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    p_mid = rng.uniform(0.15, 0.85, n)
    px = np.clip(p_mid + rng.normal(0, 0.12, n), 0.02, 0.98)
    p_true = p_mid if truth == "options" else px
    dates = pd.bdate_range("2026-04-01", "2026-08-14").strftime("%Y-%m-%d").to_numpy()
    return pd.DataFrame({"market_id": rng.integers(1, 400, n).astype(str), "tk": "SPY", "k": 500.0,
                         "res_date": rng.choice(dates, n), "ts": 1778000000 + np.arange(n),
                         "side": rng.choice(["BUY", "SELL"], n), "px": px, "size": 10.0, "status": "ok", "p_mid": p_mid,
                         "p_lo": p_mid - 0.03, "p_hi": p_mid + 0.03, "y": (rng.uniform(size=n) < p_true).astype(int)})


def test_the_runner_has_no_built_in_sign():
    """If the options are the truth the maker earns about band + margin (8 pt); if the takers' price is the truth the
    maker loses. The code must be able to show both."""
    f, _ = R.fills(_world("options"), m=0.05)
    assert len(f) > 500 and 5.0 < f["pnl_pt"].mean() < 11.0
    f, _ = R.fills(_world("takers"), m=0.05)
    assert len(f) > 500 and f["pnl_pt"].mean() < -2.0
