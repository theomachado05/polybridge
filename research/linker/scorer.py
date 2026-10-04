from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from .benchmark import OUT

FEATURES = ("confidence", "two_models", "log_mean_abs_move", "share_nights_1pt", "share_between_10_and_90", "log_days", "links_on_question")
L2 = 1.0


def design(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([df.confidence.to_numpy(float), df.two_models.to_numpy(float), np.log1p(df.odds_mean_abs_move.to_numpy(float)),
                            df.odds_share_nights_1pt.to_numpy(float), df.odds_share_between_10_and_90.to_numpy(float),
                            np.log(df.days.to_numpy(float)), df.links_on_question.to_numpy(float)])


def fit(X: np.ndarray, y: np.ndarray, l2: float = L2) -> dict:
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    w = np.zeros(Z.shape[1])
    pen = np.eye(Z.shape[1]) * l2
    pen[0, 0] = 0.0
    for _ in range(50):
        p = 1.0 / (1.0 + np.exp(-Z @ w))
        grad = Z.T @ (p - y) + pen @ w
        H = Z.T @ (Z * (p * (1 - p))[:, None]) + pen
        step = np.linalg.solve(H, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return {"w": w, "mu": mu, "sd": sd}


def predict(m: dict, X: np.ndarray) -> np.ndarray:
    Z = np.column_stack([np.ones(len(X)), (X - m["mu"]) / m["sd"]])
    return 1.0 / (1.0 + np.exp(-Z @ m["w"]))


def auc(y: np.ndarray, s: np.ndarray) -> float:
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()) / (len(pos) * len(neg)))


def top_third(y: np.ndarray, s: np.ndarray) -> float:
    k = max(1, len(y) // 3)
    return float(y[np.argsort(-s)[:k]].mean())


def rule(df: pd.DataFrame) -> np.ndarray:
    return ((df.two_models == 1) & (df.odds_share_between_10_and_90 >= 0.5) & (df.odds_share_nights_1pt >= 0.3)).to_numpy(float)


def evaluate(df: pd.DataFrame, folds: list[tuple[np.ndarray, np.ndarray]], name: str) -> dict:
    X, y = design(df), (df.verdict == "confirmed").to_numpy(float)
    oof = np.full(len(df), np.nan)
    for tr, te in folds:
        if y[tr].sum() == 0 or y[tr].sum() == len(tr) or not len(te):
            continue
        oof[te] = predict(fit(X[tr], y[tr]), X[te])
    ok = np.isfinite(oof)
    r = rule(df)
    return {"validation": name, "links_scored": int(ok.sum()), "base_rate": float(y[ok].mean()), "auc": auc(y[ok], oof[ok]),
            "confirmed_in_top_third": top_third(y[ok], oof[ok]), "rule_precision": float(y[ok][r[ok] == 1].mean()) if (r[ok] == 1).any() else float("nan"),
            "rule_keeps": int((r[ok] == 1).sum()), "_oof": oof}


def main() -> int:
    b = pd.read_csv(OUT / "benchmark.csv")
    df = b[b.verdict != "untestable"].reset_index(drop=True)
    y = (df.verdict == "confirmed").to_numpy(float)
    idx = np.arange(len(df))
    rng = np.random.default_rng(0)
    markets = df.market.unique()
    fold_of = dict(zip(markets, rng.permutation(len(markets)) % 5))
    f = df.market.map(fold_of).to_numpy()
    by_market = [(idx[f != k], idx[f == k]) for k in range(5)]
    s4, s5 = df.source.str.startswith("S4").to_numpy(), df.source.str.startswith("S5").to_numpy()
    across = [(idx[s5], idx[s4]), (idx[s4], idx[s5])]
    by_theme = [(idx[(df.theme != t).to_numpy()], idx[(df.theme == t).to_numpy()]) for t in df.theme.unique()]
    res = [evaluate(df, by_market, "by market, 5 folds"), evaluate(df, across[:1], "train on S5, test on S4"),
           evaluate(df, across[1:], "train on S4, test on S5"), evaluate(df, by_theme, "leave one theme out")]
    df["score_out_of_fold"] = res[0].pop("_oof")
    for r in res[1:]:
        r.pop("_oof")
    m = fit(design(df), y)
    coef = {"intercept": float(m["w"][0]), **{k: float(v) for k, v in zip(FEATURES, m["w"][1:])}}
    (OUT / "scorer.json").write_text(json.dumps({"features": list(FEATURES), "coefficients_standardised": coef, "mean": m["mu"].tolist(),
                                                 "sd": m["sd"].tolist(), "l2": L2, "trained_on": int(len(df)),
                                                 "confirmed": int(y.sum()), "validation": res}, indent=1))
    df["score_full_model"] = predict(m, design(df))
    df.sort_values("score_out_of_fold", ascending=False).to_csv(OUT / "benchmark_scored.csv", index=False)
    print(pd.DataFrame(res).round(3).to_string(index=False))
    print("standardised coefficients:", {k: round(v, 2) for k, v in coef.items()})
    q = pd.qcut(df.score_out_of_fold, 4, labels=["lowest quarter", "second", "third", "highest quarter"])
    print(df.groupby(q, observed=True).agg(links=("verdict", "size"), confirmed=("verdict", lambda v: (v == "confirmed").mean()),
                                           contradicted=("verdict", lambda v: (v == "contradicted").mean())).round(2).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
