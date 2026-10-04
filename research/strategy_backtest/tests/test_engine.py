import numpy as np
import pandas as pd
import pytest

from gap_model.model import fit_rate as gm_fit_rate
from strategy_backtest.engine import (VARIANTS, RecordStore, books, et_instant, fit_rate, gate, hedge_fraction, pm_at,
                                      run_loop, session_measures)

from .synth import A, bars_from, world

DECISION = ["f_signal", "trusted", "driver", "E_bp", "n_trusted"]


def test_pm_at_as_of_and_stale():
    t = pd.Timestamp("2024-03-01 14:30", tz="UTC")
    ts = int(t.timestamp())
    pts = [(ts - 3600, 0.40), (ts - 600, 0.45), (ts + 1, 0.90)]
    assert pm_at(pts, t) == pytest.approx(45.0)
    assert np.isnan(pm_at([(ts - 31 * 60, 0.4)], t))
    assert pm_at([(ts - 30 * 60, 0.4)], t) == pytest.approx(40.0)
    assert np.isnan(pm_at([(ts + 1, 0.4)], t))


def test_fit_rate_matches_gap_model():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 2, 60)
    g = 7 * x + rng.normal(0, 5, 60)
    a, b = fit_rate(x, g), gm_fit_rate(x, g)
    assert a["rate"] == pytest.approx(b["rate"])
    assert a["se"] == pytest.approx(b["se"])


def test_gate_rules():
    rng = np.random.default_rng(2)
    x = rng.normal(0, 2, 40)
    assert gate(x, 8 * x + rng.normal(0, 2, 40))[0]
    assert not gate(x[:19], 8 * x[:19])[0]
    assert not gate(x, -8 * x + rng.normal(0, 2, 40))[0]
    noise = rng.normal(0, 50, 40)
    assert gate(x, noise)[0] == (fit_rate(x, noise)["rate"] > 0 and fit_rate(x, noise)["t"] >= 1.96)
    z = np.r_[x[:19], np.zeros(10)]
    assert not gate(z, 8 * z)[0]


def test_hedge_fraction_product_rule():
    assert hedge_fraction(5.0) == 0.0
    assert hedge_fraction(-9.99) == 0.0
    assert hedge_fraction(-10.0) == pytest.approx(0.1)
    assert hedge_fraction(-25.0) == pytest.approx(0.25)
    assert hedge_fraction(-200.0) == pytest.approx(0.5)
    assert hedge_fraction(float("nan")) == 0.0


def test_store_filters_known_at():
    s = RecordStore()
    t = pd.Timestamp("2024-03-01 14:30", tz="UTC")
    s.add("m", 1.0, 2.0, t)
    s.add("m", 3.0, 4.0, t + pd.Timedelta(minutes=1))
    s.add("n", 5.0, 6.0, t)
    assert list(s.available(t)[0]) == [1.0, 5.0]
    assert list(s.available(t, "m")[0]) == [1.0]
    assert len(s.available(t - pd.Timedelta(seconds=1))[0]) == 0


def _perturb_after(w: dict, k: int, seed: int = 9) -> dict:
    rng = np.random.default_rng(seed)
    days = w["days"]
    meas = w["meas"].copy()
    cut = et_instant(days[k], (9, 29))
    for j, d in enumerate(days):
        cols = ["open_px", "px_1000", "rth_close"] if j == k else (["open_px", "px_1000", "rth_close", "px_0800"] if j > k else [])
        for c in cols:
            meas.loc[d, c] *= 1 + rng.normal(0, 0.02)
    cts = int(cut.timestamp())
    pm = {key: [(t, p if t <= cts else float(rng.uniform(0.01, 0.99))) for t, p in pts] for key, pts in w["pm"].items()}
    return {**w, "meas": meas, "pm": pm}


@pytest.mark.parametrize("variant", ["primary", "V1_premarket", "V2_no_gating", "V3_unwind_close"])
def test_no_look_ahead(variant):
    w = world(n=70, seed=3)
    v = VARIANTS[variant]
    base, _ = run_loop(w["days"], w["meas"], w["markets"], w["part"], w["pm"], v)
    assert (base["n_trusted"] > 0).sum() > 10
    assert (base["f_signal"] > 0).sum() >= 2
    for k in (25, 40, 60):
        alt = _perturb_after(w, k)
        got, _ = run_loop(alt["days"], alt["meas"], alt["markets"], alt["part"], alt["pm"], v)
        upto = [d for d in w["days"][1:] if d <= w["days"][k]]
        pd.testing.assert_frame_equal(base.loc[upto, DECISION], got.loc[upto, DECISION])
        later = [d for d in w["days"][1:] if d > w["days"][k]]
        assert not base.loc[later, "x_pp"].equals(got.loc[later, "x_pp"])


def test_records_known_at_open_and_rate_recovered():
    w = world(n=70, seed=4, rate=8.0)
    sig, rec = run_loop(w["days"], w["meas"], w["markets"], w["part"], w["pm"], VARIANTS["primary"])
    ra = rec[rec.market == A]
    assert len(ra) == 70
    assert fit_rate(ra.x_pp, ra.gap_bp)["rate"] == pytest.approx(8.0, abs=0.5)
    ka = pd.to_datetime(ra.known_at)
    assert all(k.tz_convert("America/New_York").strftime("%H:%M") == "09:30" for k in ka)
    first = sig[sig.n_trusted > 0].index[0]
    assert (pd.Timestamp(rec.known_at.iloc[0]) <= et_instant(first, (16, 0)))
    assert sig.loc[sig.index[:20], "n_trusted"].eq(0).all()


def test_hedge_only_after_adverse_trusted_signal():
    w = world(n=70, seed=5)
    sig, _ = run_loop(w["days"], w["meas"], w["markets"], w["part"], w["pm"], VARIANTS["primary"])
    on = sig[sig.f > 0]
    assert len(on) > 0
    assert (on["driver"] == A).all()
    assert (on["E_bp"] <= -10).all()
    assert np.allclose(on["f"], np.minimum(0.5, 0.5 * -on["E_bp"] / 50))
    assert (np.array([w["xa"][d] for d in on.index]) < 0).all()


def test_session_measures_from_bars_and_early_close():
    w = world(n=10, seed=6)
    meas = session_measures(bars_from(w["meas"]), w["days"])
    for c in ("open_px", "px_1000", "px_0800", "rth_close"):
        assert np.allclose(meas[c], w["meas"][c])
    d = pd.Timestamp("2024-07-03")
    base = d.tz_localize("America/New_York")
    idx = pd.DatetimeIndex([base + pd.Timedelta(minutes=m) for m in range(570, 900)]).tz_convert("UTC")
    px = np.where(np.arange(570, 900) < 780, 500.0, 510.0)
    bars = pd.DataFrame({"open": px, "close": px, "volume": 1.0}, index=idx)
    m = session_measures(bars, [d]).loc[d]
    assert m["rth_close"] == 500.0
    assert m["t_close"] == et_instant(d, (13, 0))


def test_session_measures_missing_open_bar():
    w = world(n=3, seed=7)
    bars = bars_from(w["meas"])
    d = w["days"][2]
    et = bars.index.tz_convert("America/New_York")
    drop = (et.normalize().tz_localize(None) == d) & (et.hour * 60 + et.minute >= 570) & (et.hour * 60 + et.minute < 576)
    meas = session_measures(bars[~drop], w["days"])
    assert np.isnan(meas.loc[d, "open_px"]) and np.isnan(meas.loc[d, "px_1000"])


def test_books_hand_computed():
    days = [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]
    close = pd.Series([100.0, 101.0, 99.0], index=days)
    divs = pd.Series({days[2]: 0.5})
    sig = pd.DataFrame({"f": [0.25, 0.0], "entry_px": [102.0, np.nan], "exit_px": [100.0, np.nan]}, index=days[1:])
    b = books(days, close, divs, sig, 1.0, 1.0, book_usd=1000.0)
    q = 0.25 * 10
    gross = -q * (100.0 - 102.0)
    cost = q * 102.0 * 1e-4 + q * 100.0 * 1e-4
    assert b.loc[days[1], "hedge_net"] == pytest.approx(gross - cost)
    assert b.loc[days[1], "traded_usd"] == pytest.approx(q * 102 + q * 100)
    assert b.loc[days[2], "bh"] == pytest.approx(990.0 + 5.0)
    assert b.loc[days[2], "strat"] == pytest.approx(995.0 + gross - cost)
    assert b.loc[days[0], "strat"] == pytest.approx(1000.0)


def test_trim_points_keeps_every_lookup():
    from leadlag_closed.closures import build_closures
    from leadlag_replication.closures import calendar_close
    from strategy_backtest.run import trim_points

    rng = np.random.default_rng(8)
    for c in build_closures("2024-07-01", "2024-07-10"):
        a = int((c.nominal_close - pd.Timedelta(minutes=300)).timestamp())
        b = int((c.nominal_open + pd.Timedelta(minutes=30)).timestamp())
        ts = np.sort(rng.choice(np.arange(a, b, 60), size=(b - a) // 600, replace=False))
        pts = [(int(t), float(rng.uniform())) for t in ts]
        kept = trim_points(pts, c)
        assert len(kept) < len(pts)
        inst = [c.nominal_close, calendar_close(c), c.nominal_open, et_instant(c.open_day, (9, 29)),
                et_instant(c.open_day, (7, 59)), c.nominal_close - pd.Timedelta(minutes=7)]
        for t in inst:
            x, y = pm_at(pts, t), pm_at(kept, t)
            assert (np.isnan(x) and np.isnan(y)) or x == y
