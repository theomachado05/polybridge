"""Link agent: the verdict rule, the scorer, the Fed composite's weights and the option resolver."""
import numpy as np
import pandas as pd
import pytest

from linker import benchmark as bm
from linker import composite as cp
from linker import options as op
from linker import scorer as sc


def test_verdict_rule():
    base = {"ticker": "USO", "days": 60}
    assert bm.verdict({**base, "gap_t": 2.0}) == "confirmed"
    assert bm.verdict({**base, "gap_t": -2.0}) == "contradicted"
    assert bm.verdict({**base, "gap_t": 1.9}) == "unproven"
    assert bm.verdict({**base, "days": 29, "gap_t": 5.0}) == "untestable"
    assert bm.verdict({"ticker": "SPY", "days": 200, "gap_t": 5.0}) == "untestable"       # excess over SPY is zero by construction
    assert bm.verdict({**base, "gap_t": float("nan")}) == "untestable"


def test_auc_and_top_third():
    y = np.array([1, 1, 0, 0, 0, 0])
    assert sc.auc(y, np.array([0.9, 0.8, 0.3, 0.2, 0.1, 0.0])) == 1.0
    assert sc.auc(y, np.array([0.0, 0.1, 0.2, 0.3, 0.8, 0.9])) == 0.0
    assert sc.auc(y, np.full(6, 0.5)) == 0.5
    assert sc.top_third(y, np.array([0.9, 0.8, 0.3, 0.2, 0.1, 0.0])) == 1.0


def test_logistic_fit_separates_and_predicts_probabilities():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 2))
    y = (x[:, 0] + 0.5 * x[:, 1] + rng.normal(scale=0.3, size=200) > 0).astype(float)
    m = sc.fit(x, y)
    p = sc.predict(m, x)
    assert ((p > 0) & (p < 1)).all() and sc.auc(y, p) > 0.95
    assert m["w"][1] > m["w"][2] > 0                                                      # the stronger feature gets the larger weight


def test_rule_needs_two_models_and_live_odds():
    df = pd.DataFrame({"two_models": [1, 1, 0, 1], "odds_share_between_10_and_90": [0.8, 0.2, 0.8, 0.8],
                       "odds_share_nights_1pt": [0.5, 0.5, 0.5, 0.1]})
    assert list(sc.rule(df)) == [1.0, 0.0, 0.0, 0.0]


def test_fed_outcomes_map_to_bp():
    assert cp.outcome_weight("Fed decreases interest rates by 25 bps after December 2025 meeting?") == -25
    assert cp.outcome_weight("Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?") == -50
    assert cp.outcome_weight("Fed increases interest rates by 25+ bps after January 2026 meeting?") == 25
    assert cp.outcome_weight("No change in Fed interest rates after December 2025 meeting?") is None
    assert cp.outcome_weight("Will no Fed rate cuts happen in 2026?") is None


def test_composite_is_easing_in_bp_and_needs_every_component():
    t = np.arange(0, 600, 60, dtype=np.int64) + 6000
    cut = np.full(10, 0.40)
    hike = np.full(10, 0.10)
    grid, v = cp.composite_series([(t, cut, -25), (t, hike, 25)])
    assert v[0] == pytest.approx((25 * 0.40 - 25 * 0.10) / 100)                           # 7.5 bp of expected easing
    late = (t[5:], hike[5:], 25)                                                          # one component starts later
    grid2, _ = cp.composite_series([(t, cut, -25), late])
    assert grid2[0] > t[5]


class FakeMassive:
    headers = {"Authorization": "Bearer x"}


def test_option_resolver_picks_first_expiry_and_nearest_strike(monkeypatch):
    def rows(s, url, params=None):
        if "options/contracts" in url:
            out = []
            for exp in ("2026-10-16", "2026-10-09"):
                for k in (37.0, 38.0, 39.0):
                    for ct in ("call", "put"):
                        out.append({"expiration_date": exp, "strike_price": k, "contract_type": ct, "shares_per_contract": 100,
                                    "ticker": f"O:EWZ{exp[2:4]}{exp[5:7]}{exp[8:]}{ct[0].upper()}{int(k * 1000):08d}"})
            return out
        return [{"c": 37.9}, {"c": 38.19}]

    monkeypatch.setattr(op.d4, "massive_rows", rows)
    r = op.resolve(FakeMassive(), "base", "EWZ", "up_on_yes", "2026-10-05", "2026-10-02")
    assert r["expiry"] == "2026-10-09" and r["strike"] == 38.0 and r["last_close"] == 38.19
    assert r["directional_leg"] == "O:EWZ261009C00038000" and r["put"] == "O:EWZ261009P00038000"
    down = op.resolve(FakeMassive(), "base", "EWZ", "down_on_yes", "2026-10-05", "2026-10-02")
    assert down["directional_leg"] == down["put"]
