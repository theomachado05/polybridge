import math

import pytest

from arbscan import implied
from arbscan.costs import KalshiFee, PolyFee, commission_per_share, fee_from_gamma
from arbscan.implied import Quote, pick_spread, bracket_indices, edges, edge_for_trade, classify
from synth import make_chain, true_prob

S, SIG, T = 100.0, 0.30, 1 / 252


def _spread(k, extra=0, half=0.01, size=50, **kw):
    chain, quotes = make_chain(S, SIG, T, half=half, size=size)
    get = lambda s: quotes[chain[s]]  # noqa: E731
    return pick_spread(sorted(chain), k, get, T, extra=extra, **kw), chain, quotes


def test_mid_implied_probability_matches_lognormal_truth():
    for k in (97.0, 100.0, 102.0):
        sp, _, _ = _spread(k)
        # width-2 central difference around a listed strike: smoothing bias well under one point at sigma=30%, 1 day
        assert sp.p_mid == pytest.approx(true_prob(S, k, SIG, T, r=0.04), abs=0.012)


def test_bounds_bracket_mid_and_truth_with_realistic_spread():
    sp, _, _ = _spread(100.0, half=0.05)
    assert sp.p_lo <= sp.p_mid <= sp.p_hi
    assert sp.p_lo <= true_prob(S, 100.0, SIG, T, r=0.04) <= sp.p_hi
    # width 2, half spread 0.05 on each of four quote sides: bounds are +/- 0.1 around the mid
    assert sp.p_hi - sp.p_lo == pytest.approx(0.1 * math.exp(0.04 * T), abs=1e-3)


def test_listed_strike_uses_immediate_neighbours_unlisted_uses_bracket():
    strikes = [90, 95, 100, 105, 110]
    assert bracket_indices(strikes, 100) == (1, 3)           # central difference around a listed strike
    assert bracket_indices(strikes, 102) == (2, 3)           # unlisted: strikes just below and above
    assert bracket_indices(strikes, 100, extra=1) == (0, 4)  # wide spread
    assert bracket_indices(strikes, 90) is None              # no strike below
    assert bracket_indices(strikes, 110, extra=0) is None
    assert bracket_indices(strikes, 102, extra=2) is None


def test_wide_spread_is_wider_and_close_to_narrow_for_smooth_chain():
    nar, _, _ = _spread(100.0)
    wid, _, _ = _spread(100.0, extra=1)
    assert wid.width == 4.0 and nar.width == 2.0
    assert abs(nar.p_mid - wid.p_mid) < 0.02


def test_invalid_leg_steps_outward_and_stale_leg_is_invalid():
    chain, quotes = make_chain(S, SIG, T)
    # kill the 99 call (crossed/zero bid): the lower leg of the K=100 spread moves out to 98
    quotes[chain[99.0]] = Quote(bid=0.0, ask=1.0, bid_size=1, ask_size=1, ts=1000.0)
    sp = pick_spread(sorted(chain), 100.0, lambda s: quotes[chain[s]], T, snapshot_ts=1000.0)
    assert (sp.k1, sp.k2, sp.stepped) == (98.0, 101.0, 1)
    # stale: every quote older than 10 minutes at the snapshot
    assert pick_spread(sorted(chain), 100.0, lambda s: quotes[chain[s]], T, snapshot_ts=1000.0 + 601) is None
    # but a live row passes max_age=None
    assert pick_spread(sorted(chain), 100.0, lambda s: quotes[chain[s]], T, snapshot_ts=1000.0 + 5000, max_age=None) is not None


def test_noarb_violation_flagged_and_clamped():
    sp = implied.Spread(100.0, 102.0, Quote(5.0, 5.2), Quote(2.0, 2.2), T)   # slope (5.1-2.1)/2 = 1.5 > 1
    assert sp.noarb_violation and sp.p_mid == 1.0 and sp.p_lo <= sp.p_mid <= sp.p_hi


def test_edges_trade_direction_costs_and_strip_loss():
    sp, _, _ = _spread(100.0, half=0.01)
    p = sp.p_mid
    fee = PolyFee(rate=0.04)
    # PM YES way too rich: sell YES at the bid, buy the spread
    e = edges(sp, 100.0, p + 0.15, p + 0.17, fee)
    assert e["trade"].startswith("A") and e["edge"] > 0.10
    expected = (p + 0.15) - fee.per_share(p + 0.15) - sp.p_hi - commission_per_share(2.0)
    assert e["edge"] == pytest.approx(expected)
    assert e["strip_loss"] == pytest.approx(0.5)               # centred spread: half a dollar worst case in the strip
    # PM YES too cheap: buy at the ask, sell the spread
    e2 = edges(sp, 100.0, p - 0.17, p - 0.15, fee)
    assert e2["trade"].startswith("B") and e2["edge"] > 0.10
    # PM at fair value: every spread crossed means negative edge
    e3 = edges(sp, 100.0, p - 0.02, p + 0.02, fee)
    assert e3["edge"] < 0


def test_costs_kill_a_small_gap():
    sp, _, _ = _spread(100.0, half=0.05)       # option bounds mid +/- 0.05
    p = sp.p_mid
    e = edges(sp, 100.0, p + 0.07, p + 0.09, PolyFee())   # PM mid 0.08 above the option mid: beyond p_hi by 0.03 before costs
    assert 0 < e["edge"] < implied.MIN_EDGE + 0.01         # ~0.03 minus fee (~0.016) minus commission: a sliver
    e = edges(sp, 100.0, p + 0.04, p + 0.06, PolyFee())   # inside the bound: costs make it negative
    assert e["edge"] < 0


def test_fees():
    assert PolyFee(rate=0.04).per_share(0.5) == pytest.approx(0.01)
    assert PolyFee(rate=0.04).per_share(1.0) == 0.0
    assert PolyFee(enabled=False).per_share(0.5) == 0.0
    # Kalshi: 0.07 * 100 * 0.5 * 0.5 = 1.75 -> rounds up to 1.75 (already cents); 0.07*3*.5*.5=0.0525 -> 0.06
    assert KalshiFee().total(0.5, 100) == pytest.approx(1.75)
    assert KalshiFee().total(0.5, 3) == pytest.approx(0.06)
    assert KalshiFee().per_share(0.5, 100) == pytest.approx(0.0175)
    g = {"feesEnabled": True, "feeSchedule": {"rate": 0.05, "exponent": 1}}
    assert fee_from_gamma(g).rate == 0.05 and not fee_from_gamma({"feesEnabled": False}).enabled


def _lab(**kw):
    base = dict(clean=True, informative=True, fresh=True, p_mid_narrow=0.5, p_lo=0.45, p_hi=0.55, pm_mid=0.5, edge=-0.05,
                edge_wide_same_trade=-0.05, live=False, options_open=False, pm_size_at_touch=None, width=2.0, legs_have_size=True)
    base.update(kw)
    return classify(**base)


def test_classify_ladder():
    assert _lab() == "none"
    assert _lab(pm_mid=0.55) == "gap_mid"                        # |gap| 0.05 from the narrow mid, still inside [p_lo, p_hi]
    assert _lab(pm_mid=0.56) == "gap_beyond_bounds"              # outside the bound strip
    assert _lab(pm_mid=0.57, p_mid_narrow=0.5) == "gap_beyond_bounds"
    assert _lab(pm_mid=0.7, edge=0.02, edge_wide_same_trade=-0.01) == "gap_net"
    assert _lab(pm_mid=0.7, edge=0.02, edge_wide_same_trade=0.01) == "gap_robust"
    assert _lab(clean=False, pm_mid=0.7, edge=0.2, edge_wide_same_trade=0.2) == "not_scored"
    assert _lab(informative=False) == "not_scored"
    assert _lab(pm_mid=0.7, edge=0.009, edge_wide_same_trade=0.2) == "gap_beyond_bounds"       # below one cent


def test_executable_needs_live_open_options_sizes_and_a_whole_spread():
    kw = dict(pm_mid=0.7, edge=0.05, edge_wide_same_trade=0.05, live=True, options_open=True, width=2.0, legs_have_size=True)
    assert _lab(pm_size_at_touch=200, **kw) == "gap_executable"          # 100 * w = 200 shares needed
    assert _lab(pm_size_at_touch=199, **kw) == "gap_robust"
    assert _lab(pm_size_at_touch=5000, **{**kw, "options_open": False}) == "gap_robust"
    assert _lab(pm_size_at_touch=5000, **{**kw, "live": False}) == "gap_robust"
    assert _lab(pm_size_at_touch=5000, **{**kw, "legs_have_size": False}) == "gap_robust"
