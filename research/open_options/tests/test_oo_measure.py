from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

import open_options  # noqa: F401
from arbscan.implied import Quote
from open_options.tests.arb_synth import bs_call, make_chain, true_prob  # noqa: F401
from open_options import measure as ms
from open_options.closures import ET, Closure, build_closures, eligible, et
from open_options.stats import cluster_bootstrap, mean_ci, ols


def test_closures_weekends_holidays_and_early_close():
    cl = {c.key: c for c in build_closures("2025-11-01", "2026-01-31")}
    assert "2025-11-07" in cl and cl["2025-11-07"].kind == "weekend" and cl["2025-11-07"].open_day == date(2025, 11, 10)
    assert "2025-11-26" in cl and cl["2025-11-26"].open_day == date(2025, 11, 28)
    assert cl["2025-11-28"].close.hour == 13 and cl["2025-11-28"].opt_close.minute == 55
    assert cl["2025-12-24"].close.hour == 13 and cl["2025-12-24"].kind == "holiday"
    assert "2025-11-10" not in cl
    c = cl["2025-11-07"]
    assert c.open == datetime(2025, 11, 10, 9, 30, tzinfo=ET) and c.opt_open.minute == 45 and c.eod.hour == 16


def test_eligibility_rules():
    c = Closure(date(2026, 9, 25), date(2026, 9, 28))
    mon_close = et(date(2026, 9, 28), 16, 0)
    assert eligible(c, c.close - timedelta(hours=1), mon_close, date(2026, 9, 28)) == ""
    assert eligible(c, c.close - timedelta(minutes=5), mon_close, date(2026, 9, 28)) == "listed_after_close"
    assert eligible(c, None, mon_close, date(2026, 9, 28)) == "listed_after_close"
    assert eligible(c, c.close - timedelta(hours=1), c.open, date(2026, 9, 28)) == "resolves_before_reopen_close"


def test_pm_at_and_filters():
    pts = [(100.0, 0.40), (160.0, 0.42), (220.0, 0.45)]
    assert ms.pm_at(pts, 200.0) == 0.42 and ms.pm_at(pts, 1220.0) is None and ms.pm_at(pts, 50.0) is None
    assert ms.pm_filter(None, 0.4) == "f1_no_pm_price"
    assert ms.pm_filter(0.97, 0.90) == "f1_pm_close_extreme"
    assert ms.pm_filter(0.50, 0.60) == "f2_placeholder_050"
    assert ms.pm_filter(0.40, 0.42) == "f3_move_below_3pt"
    assert ms.pm_filter(0.40, 0.43) == "" and ms.pm_filter(0.40, 0.36) == ""


def _getq(quotes_by_ts):
    return lambda tk, ts: quotes_by_ts[ts].get(tk)


def test_catchup_metrics_full_partial_none():
    k, sig, t_fri, t_mon = 100.0, 0.25, 5 / 252, 3 / 252
    ch_f, q_f = make_chain(s=100.0, sigma=sig, t=t_fri, half=0.0, ts=1000.0)
    exp_close = 1000.0 + t_fri * 365 * 86400
    oc = ms.spread_at(ch_f, k, _getq({1000.0: q_f}), 1000.0, exp_close)
    t_open = 2000.0
    for s_mon, frac in ((103.0, 1.0), (100.0, 0.0)):
        ch_m, q_m = make_chain(s=s_mon, sigma=sig, t=t_mon, half=0.0, ts=t_open)
        oo = ms.spread_at(ch_m, k, _getq({t_open: q_m}), t_open, exp_close)
        d_opt = oo.p_mid - oc.p_mid
        pm_close = oc.p_mid
        pm_open = oc.p_mid + (d_opt if frac == 1.0 else 0.10)
        e = ms.event_metrics(pm_close, pm_open, oc, oo)
        if frac == 1.0:
            assert abs(e["G"]) < 1e-9 and e["s"] == 1
        else:
            assert e["G"] == pytest.approx(0.10 - d_opt, abs=1e-9)
        assert e["G_net"] == pytest.approx(e["G"] - e["cost_half"] - e["cost_comm"])


def test_cost_side_and_followthrough():
    q = {"A": Quote(5.0, 5.4, ts=10.0), "B": Quote(4.0, 4.2, ts=10.0)}
    oo = ms.spread_at({99.0: "A", 101.0: "B"}, 100.0, lambda tk, ts: q[tk], 10.0, 10.0)
    oc = oo
    up = ms.event_metrics(0.40, 0.50, oc, oo)
    dn = ms.event_metrics(0.60, 0.50, oc, oo)
    assert up["s"] == 1 and up["cost_half"] == pytest.approx(oo.p_hi - oo.p_mid)
    assert dn["s"] == -1 and dn["cost_half"] == pytest.approx(oo.p_mid - oo.p_lo)
    ft = ms.follow_through(1, oo, oo, 0.5, 0.45)
    assert ft["F"] == 0 and ft["rt_pnl"] < 0 and ft["pm_follow"] == pytest.approx(-0.05)


def test_open_floor_rejects_pre_open_quotes():
    ch, q = make_chain(ts=500.0)
    exp = 10_000.0
    assert ms.spread_at(ch, 100.0, lambda tk, ts: q[tk], 600.0, exp, max_age=900, floor_ts=550.0) is None
    assert ms.spread_at(ch, 100.0, lambda tk, ts: q[tk], 600.0, exp, max_age=900, floor_ts=400.0) is not None


def test_pair_mode_prices_given_strikes():
    ch, q = make_chain(ts=500.0)
    sp = ms.spread_at(ch, 100.0, lambda tk, ts: q[tk], 510.0, 10_000.0, pair=(97.0, 103.0))
    assert (sp.k1, sp.k2) == (97.0, 103.0)
    assert ms.spread_at(ch, 100.0, lambda tk, ts: q[tk], 510.0, 10_000.0, pair=(97.0, 1000.0)) is None


def test_trade_prints_three_states():
    tr = [{"timestamp": 50}, {"timestamp": 150}]
    assert ms.trade_prints_in(tr, 100, 200) is True
    assert ms.trade_prints_in([{"timestamp": 50}, {"timestamp": 300}], 100, 200) is False
    assert ms.trade_prints_in([{"timestamp": 300}], 100, 200) is None


def test_ols_and_cluster_bootstrap_recover_slope():
    rng = np.random.default_rng(1)
    n_cl, per = 40, 6
    cl = np.repeat(np.arange(n_cl), per)
    x = rng.normal(0, 0.06, n_cl * per)
    y = 0.4 * x + rng.normal(0, 0.01, n_cl)[cl] + rng.normal(0, 0.01, len(x))
    g = np.sign(x) * (x - y)
    r = cluster_bootstrap(x, y, g, cl, draws=2000)
    assert abs(ols(x, y)[1] - 0.4) < 0.05
    assert r["beta_ci"][0] < 0.4 < r["beta_ci"][1] and r["beta_ci"][1] < 1
    assert r["mean_ci"][0] > 0 and r["clusters"] == n_cl
    zero = mean_ci(rng.normal(0, 0.02, 200), np.repeat(np.arange(40), 5), draws=2000)
    assert zero["mean_ci"][0] < 0 < zero["mean_ci"][1]
