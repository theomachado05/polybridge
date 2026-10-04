"""Offline checks on the version-2 scorer: no leaked input, pre-window volatility, the score() interface, grouped folds."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from linker import features as F
from linker import instruments as I
from linker import scorer2 as S

pytestmark = pytest.mark.skipif(not I.OUT.exists(), reason="instruments.json not built")

ITEM8 = ("question", "ticker", "direction", "confidence", "two_models", "links_on_question", "impact_pct", "days",
         "odds_mean_abs_move", "odds_share_nights_1pt", "odds_share_between_10_and_90")


def _frame(n: int = 6) -> pd.DataFrame:
    r = np.random.default_rng(1)
    return pd.DataFrame({"question": ["Will Bitcoin reach $150,000 by December 31?", "Strait of Hormuz traffic returns to normal by June 30?",
                                      "Will the Fed decrease interest rates by 25 bps after the March 2026 meeting?",
                                      "Will Google have the best AI model at the end of October 2026?", "Will X win the 2027 election?",
                                      "US x Iran permanent peace deal by June 30, 2026?"][:n],
                         "ticker": ["IBIT", "USO", "TLT", "GOOGL", "EWQ", "NOT_A_TICKER"][:n], "direction": ["up_on_yes"] * n,
                         "confidence": r.uniform(0, 1, n), "two_models": np.ones(n), "links_on_question": np.full(n, 2),
                         "impact_pct": [5.0, np.nan, 1.0, np.nan, 3.0, np.nan][:n], "days": r.integers(30, 200, n),
                         "odds_mean_abs_move": r.uniform(0, 5, n), "odds_share_nights_1pt": r.uniform(0, 1, n),
                         "odds_share_between_10_and_90": r.uniform(0, 1, n)})


def test_no_forbidden_input():
    cols = set(F.build(_frame()).columns) | {c for g in F.GROUPS.values() for c in g} | set(F.V1)
    assert not cols & set(F.FORBIDDEN)
    assert not any(f in c for c in cols for f in ("gap", "verdict", "intraday", "10pt"))
    if S.MODEL.exists():
        assert not set(S.load()["features"]) & set(F.FORBIDDEN)


def test_pre_window_volatility_ignores_the_window(monkeypatch):
    days = pd.bdate_range("2025-08-01", "2025-12-31").strftime("%Y-%m-%d").to_numpy()
    r = np.random.default_rng(0)
    pre = days < F.CUTOFF
    rets = np.where(pre, r.normal(0, 0.01, len(days)), r.normal(0, 0.2, len(days)))
    c = 100 * np.exp(np.cumsum(rets))
    monkeypatch.setattr(F.store, "npz", lambda name: {"day": days, "c": c, "o": c})
    v = F.pre_window_vol("ANY")
    assert v == pytest.approx(np.std(np.diff(np.log(c[pre])), ddof=1))
    assert v < 0.02
    c2 = c.copy()
    c2[~pre] *= 7.0
    monkeypatch.setattr(F.store, "npz", lambda name: {"day": days, "c": c2, "o": c2})
    assert F.pre_window_vol("ANY") == pytest.approx(v)
    short = days[(days >= "2025-09-20")]
    monkeypatch.setattr(F.store, "npz", lambda name: {"day": short, "c": np.linspace(10, 11, len(short)), "o": np.ones(len(short))})
    assert np.isnan(F.pre_window_vol("ANY"))
    monkeypatch.setattr(F.store, "npz", lambda name: None)
    assert np.isnan(F.pre_window_vol("ANY"))


def test_score_runs_on_item8_columns_only():
    if not S.MODEL.exists():
        pytest.skip("scorer_v2.json not frozen")
    df = _frame()[list(ITEM8)]
    p = S.score(df)
    assert p.shape == (len(df),) and np.all((p > 0) & (p < 1))
    p2 = S.score(df.drop(columns=["impact_pct"]))
    assert p2.shape == (len(df),) and np.all(np.isfinite(p2))


def test_score_matches_a_model_with_text_and_size_inputs():
    df = _frame()
    X = F.build(df)
    cols = list(F.V1) + ["log_impact", "impact_missing", "price_proxy", "log_vol"]
    y = np.array([1, 0, 0, 1, 0, 1], float)
    m = S.fit_cols(X, y, cols, 1.0)
    model = {"features": cols, "impute": m["fill"], "mean": m["mu"].tolist(), "sd": m["sd"].tolist(),
             "weights": {"intercept": float(m["w"][0]), **{c: float(w) for c, w in zip(cols, m["w"][1:])}}}
    assert np.allclose(S.score(df, model), S.predict_cols(m, X))


def test_text_and_family_rules():
    X = F.build(_frame())
    assert X.price_proxy.tolist()[:2] == [1.0, 0.0]
    assert X.has_threshold.iloc[0] == 1 and X.has_threshold.iloc[2] == 1
    assert F.family_of("USO") == "commodity" and F.family_of("TLT") == "rates" and F.family_of("NOT_A_TICKER") == "single_stock"
    assert F.mechanism_of("Strait of Hormuz traffic returns to normal by June 30?", "commodity") == "commodity_supply"
    assert F.mechanism_of("Will the Fed cut rates?", "rates") == "rates_policy"
    assert X.impact_missing.tolist() == [0, 1, 0, 1, 0, 1]


def test_folds_never_split_a_market_or_a_question():
    df = pd.DataFrame({"market": ["a", "a", "b", "c", "d", "e", "f", "g", "h", "i"],
                       "question": ["q1", "q1", "q2", "Q1 ", "q3", "q4", "q5", "q6", "q7", "q8"]})
    g = S.groups(df)
    assert g[0] == g[1] == g[3] and len(set(g)) == 8
    for seed in (0, 1, 2):
        fl = S.folds(g, 5, seed)
        assert sorted(np.concatenate([te for _, te in fl]).tolist()) == list(range(len(df)))
        for tr, te in fl:
            assert not set(df.market.iloc[tr]) & set(df.market.iloc[te])
            assert not set(g[tr]) & set(g[te])


def test_training_folds_on_real_rows():
    if not (S.OUT / "benchmark.csv").exists() or not (S.OUT / "heldout_links.csv").exists():
        pytest.skip("training tables absent")
    df = S.training_table()
    assert (df.verdict != "untestable").all()
    assert not df[df.set == "heldout1"].duplicated(["market", "ticker", "direction"]).any()
    assert df.loc[df.set == "S5", "impact_pct"].isna().all()
    for tr, te in S.folds(df.group.to_numpy(), 5, 0):
        assert not set(df.market.iloc[tr]) & set(df.market.iloc[te])
        q = lambda i: set(df.question.iloc[i].str.lower().str.split().str.join(" "))
        assert not q(tr) & q(te)
