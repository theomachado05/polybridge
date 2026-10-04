"""Options evidence: contract choice without look-ahead, overnight alignment, the straddle return, the slopes, the verdict."""
import numpy as np
import pandas as pd
import pytest

from linker import option_evidence as oe


def _c(tk, kind, k, exp, spc=100):
    return {"ticker": tk, "contract_type": kind, "strike_price": k, "expiration_date": exp, "shares_per_contract": spc}


def test_spot_is_last_close_strictly_before_the_month():
    day = np.array(["2026-02-26", "2026-02-27", "2026-03-02", "2026-03-03"])
    close = np.array([80.0, 81.0, 95.0, 99.0])
    assert oe.spot_before(day, close, "2026-03") == 81.0                     # nothing dated inside March is used
    assert np.isnan(oe.spot_before(day, close, "2026-02"))


def test_pair_first_expiry_30_days_after_month_start_and_nearest_strike():
    chain = [_c("C1", "call", 80, "2026-03-27"), _c("P1", "put", 80, "2026-03-27"),       # 26 days: too soon
             _c("C2", "call", 80, "2026-04-02"), _c("P2", "put", 80, "2026-04-02"),       # 32 days: first allowed
             _c("C3", "call", 82, "2026-04-02"), _c("P3", "put", 82, "2026-04-02"),
             _c("C4", "call", 81, "2026-04-02"),                                          # no put at 81: not a pair
             _c("C5", "call", 81, "2026-04-02", spc=10), _c("P5", "put", 81, "2026-04-02", spc=10),  # adjusted contract
             _c("C6", "call", 81, "2026-04-10"), _c("P6", "put", 81, "2026-04-10")]
    p = oe.pick_pair(chain, 80.9, "2026-03")
    assert (p["expiry"], p["strike"], p["call"], p["put"]) == ("2026-04-02", 80.0, "C2", "P2")
    assert oe.pick_pair(chain, 81.0, "2026-03")["strike"] == 80.0                        # tie goes to the lower strike
    assert oe.pick_pair(chain, 90.0, "2026-03")["strike"] == 82.0
    assert oe.pick_pair(chain, float("nan"), "2026-03") is None
    on_day = [_c("C", "call", 80, "2026-03-31"), _c("P", "put", 80, "2026-03-31")]      # exactly 30 days after 03-01
    assert oe.pick_pair(on_day, 80, "2026-03")["expiry"] == "2026-03-31"
    monthly = chain + [_c("C7", "call", 80, "2026-04-17"), _c("P7", "put", 80, "2026-04-17")]      # the third Friday
    assert oe.pick_pair(monthly, 80.9, "2026-03")["expiry"] == "2026-04-17"              # a monthly beats an earlier weekly
    assert oe.is_monthly("2026-04-17") and not oe.is_monthly("2026-04-10") and not oe.is_monthly("2026-04-02")


def test_months_clip_to_window():
    assert oe.months_between("2025-09-15", "2025-11-03") == ["2025-10", "2025-11"]
    assert oe.months_between("2026-09-20", "2026-12-01") == ["2026-09", "2026-10"]
    assert oe.months_between("2027-01-01", "2027-02-01") == []


def _bars(days, o, c):
    return {"day": np.array(days), "open": np.array(o, float), "close": np.array(c, float), "volume": np.ones(len(days))}


def test_overnight_alignment_drops_missing_days():
    days = ["d1", "d2", "d3", "d4", "d5"]
    b = _bars(["d1", "d2", "d4", "d5"], [1.0, 2.2, 3.3, 4.4], [2.0, 3.0, 4.0, 5.0])         # no trade on d3
    r = oe.overnight(days, b)
    assert np.isnan(r[0])                                      # no previous session
    assert r[1] == pytest.approx(2.2 / 2.0 - 1)
    assert np.isnan(r[2]) and np.isnan(r[3])                   # d3 missing: neither d3 nor d4 (d3's close) is filled
    assert r[4] == pytest.approx(4.4 / 4.0 - 1)
    assert np.isnan(oe.overnight(days, None)).all()


def test_straddle_needs_both_legs_on_both_days():
    days = ["d1", "d2", "d3"]
    call = _bars(["d1", "d2", "d3"], [1.0, 2.5, 1.0], [2.0, 1.5, 1.0])
    put = _bars(["d1", "d2"], [1.0, 1.5], [3.0, 1.0])
    r = oe.straddle_overnight(days, call, put)
    assert r[1] == pytest.approx((2.5 + 1.5) / (2.0 + 3.0) - 1)
    assert np.isnan(r[0]) and np.isnan(r[2])                   # the put did not trade on d3


def test_verdict_rule():
    assert oe.verdict(2.0, 30) == "confirmed"
    assert oe.verdict(-2.0, 30) == "contradicted"
    assert oe.verdict(1.99, 300) == "unproven"
    assert oe.verdict(9.0, 29) == "untestable"
    assert oe.verdict(float("nan"), 300) == "untestable"


def test_straddle_slope_is_not_fooled_by_decay():
    rng = np.random.default_rng(1)
    n = 200
    x = rng.choice([-3.0, 0.0, 0.0, 1.0, 4.0], size=n)
    r_dir = 1e-4 * (50 * x + rng.normal(0, 20, n))
    r_str = 1e-4 * (-150 + rng.normal(0, 20, n))               # pure theta decay, nothing to do with the odds
    s = oe.slopes(x, r_dir, r_str, np.arange(n).astype(str))
    assert s["days"] == n and s["dir_verdict"] == "confirmed" and s["dir_bp_per_point"] == pytest.approx(50, abs=3)
    assert s["straddle_verdict"] == "unproven" and s["straddle_intercept_bp"] == pytest.approx(-150, abs=5)


def test_link_evidence_end_to_end_offline(monkeypatch):
    days = list(pd.bdate_range("2026-02-20", "2026-04-30").strftime("%Y-%m-%d"))
    sess = pd.DataFrame({"day": days, "open": np.arange(len(days)) * 86400 + 14 * 3600, "close": np.arange(len(days)) * 86400 + 20 * 3600})
    rng = np.random.default_rng(2)
    p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.03, len(days))), 0.02, 0.98)
    pm = {"t": np.concatenate([sess.open - 120, sess.close - 60]).astype(np.int64), "p": np.concatenate([p, p])}
    o = np.argsort(pm["t"])
    pm = {"t": pm["t"][o], "p": pm["p"][o]}
    hist = list(pd.bdate_range("2026-01-02", "2026-04-30").strftime("%Y-%m-%d"))
    dayb = {"day": np.array(hist), "c": np.full(len(hist), 50.0)}
    monkeypatch.setattr(oe.store, "npz", lambda name: pm if name.startswith("pm_") else dayb if name.startswith("day_") else None)
    seen = []

    def fetch(kind, *a):
        seen.append((kind, *a))
        if kind == "splits":
            return None
        if kind == "pair":
            return {"month": a[1], "expiry": "x", "strike": 50.0, "spot": a[2], "call": f"C{a[1]}", "put": f"P{a[1]}"}
        gain = np.concatenate([[0.0], np.diff(p)]) if a[0].startswith("P") else np.zeros(len(days))
        return _bars(days, 2.0 * (1 + gain + rng.normal(0, 0.002, len(days))), np.full(len(days), 2.0))

    r = oe.link_evidence({"market": "polymarket:1", "question": "q", "ticker": "USO", "direction": "down_on_yes"}, sess, fetch=fetch)
    assert r["months"] == 3 and r["contracts"] == 6           # Feb, Mar, Apr: a call and a put each
    assert all(a[3] == 50.0 for a in seen if a[0] == "pair")
    assert r["share_both_traded"] == 1.0 and r["days"] == r["session_days"] > 30
    # down_on_yes: the put gains when "yes" rises, so a put that works is confirmed, not contradicted
    assert r["dir_verdict"] == "confirmed" and r["dir_bp_per_point"] == pytest.approx(100, rel=0.1)


def _splits(*rows):
    return {"execution_date": np.array([r[0] for r in rows], dtype="U10"),
            "split_from": np.array([r[1] for r in rows], float), "split_to": np.array([r[2] for r in rows], float)}


def test_spot_undoes_splits_after_the_close():
    # XLE: 1-for-2 on 2025-12-05; the adjusted bars read 44 in November against a real 88
    day = np.array(["2025-10-30", "2025-10-31", "2025-11-03", "2025-12-05", "2025-12-08"])
    close = np.array([44.0, 44.1, 44.07, 45.0, 45.2])
    sp = _splits(("2025-12-05", 1, 2), ("2024-06-10", 1, 4))          # an older split is already in the raw price
    assert oe.raw_spot_before(day, close, "2025-11", sp) == pytest.approx(88.2)
    assert oe.raw_spot_before(day, close, "2025-12", sp) == pytest.approx(88.14)  # split after Nov's last close
    assert oe.raw_spot_before(day, close, "2026-01", sp) == pytest.approx(45.2)   # after the split: as adjusted
    assert oe.raw_spot_before(day, close, "2025-11", None) == pytest.approx(44.1)
    assert oe.split_factor("2025-12-05", sp) == 1.0                    # executed that day: already in that price
    assert oe.splits_in_month("2025-12", sp) and not oe.splits_in_month("2025-11", sp)


def test_strike_guard():
    assert not oe.strike_too_far(90.0, 88.14) and not oe.strike_too_far(97.0, 88.2)
    assert oe.strike_too_far(50.0, 88.14) and oe.strike_too_far(50.0, float("nan"))


def test_link_with_a_split_after_the_month_starts(monkeypatch):
    """Adjusted closes of 44 (real 88) and a split on 2025-12-05: the pair is chosen on 88, Dec's days from the split
    on are dropped, and a pair far from the spot is skipped."""
    days = list(pd.bdate_range("2025-10-20", "2026-01-30").strftime("%Y-%m-%d"))
    sess = pd.DataFrame({"day": days, "open": np.arange(len(days)) * 86400 + 14 * 3600, "close": np.arange(len(days)) * 86400 + 20 * 3600})
    rng = np.random.default_rng(3)
    p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.03, len(days))), 0.02, 0.98)
    t = np.concatenate([sess.open - 120, sess.close - 60]).astype(np.int64)
    o = np.argsort(t)
    pm = {"t": t[o], "p": np.concatenate([p, p])[o]}
    hist = list(pd.bdate_range("2025-09-01", "2026-01-30").strftime("%Y-%m-%d"))
    dayb = {"day": np.array(hist), "c": np.full(len(hist), 44.0)}
    monkeypatch.setattr(oe.store, "npz", lambda name: pm if name.startswith("pm_") else dayb if name.startswith("day_") else None)
    spots = {}

    def fetch(kind, *a):
        if kind == "splits":
            return _splits(("2025-12-05", 1, 2))
        if kind == "pair":
            spots[a[1]] = a[2]
            k = 50.0 if a[1] == "2026-01" else round(a[2])   # January: a far pair, which must not be used
            return {"month": a[1], "expiry": "x", "strike": k, "spot": a[2], "call": f"C{a[1]}", "put": f"P{a[1]}"}
        return _bars(days, 2.0 * (1 + rng.normal(0, 0.01, len(days))), np.full(len(days), 2.0))

    r = oe.link_evidence({"market": "polymarket:1", "question": "q", "ticker": "XLE", "direction": "up_on_yes"}, sess, fetch=fetch)
    assert spots["2025-10"] == spots["2025-11"] == spots["2025-12"] == pytest.approx(88.0)   # not 44: no look-ahead
    assert spots["2026-01"] == pytest.approx(44.0)
    assert r["months"] == 3 and r["contracts"] == 6 and "2026-01 skipped" in r["note"] and "2025-12 split" in r["note"]
    dec = [d for d in days if d[:7] == "2025-12"]
    after = sum(d >= "2025-12-05" for d in dec)
    # traded share: every in-life day of Oct, Nov and Dec before the split (less the first day, which has no previous session)
    n_traded = sum(d[:7] in ("2025-10", "2025-11") for d in days[1:]) + sum(d < "2025-12-05" for d in dec)
    assert r["days"] == n_traded and after > 0, (r["days"], n_traded)
    assert r["share_both_traded"] == pytest.approx(r["days"] / r["session_days"])
