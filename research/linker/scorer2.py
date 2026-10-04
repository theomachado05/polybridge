"""Link scorer, version 2 (heldout2/PLAN.md section 2.4): predicts whether a link will be confirmed by prices, from what
is known before the link's own equity-against-odds data are used (linker/features.py).

Training rows: every testable link of results/linker/benchmark.csv (S4, S5) and of results/linker/heldout_links.csv
(the first held-out set, both arms, unique by market + ticker + direction). Label: verdict == "confirmed".

Model: version 1's penalised logistic regression (linker/scorer.py). On top of version 1's seven inputs, groups of
inputs (instrument family, its volatility, stated size, text) are added one at a time while the by-market 5-fold AUC
rises by more than 0.01, with the L2 penalty chosen from a grid at each step and at most 15 inputs. Every validation
reruns that selection on its own training side only, so the version-2 figures below are out of sample selection too.
If version 2 does not beat version 1 out of fold, version 1's inputs are frozen.

    validations   by market, 5 folds (a market, and a question seen in two sources, never split)
                  leave one theme out;  train S4 test S5;  train S5 test S4;  train S4+S5 test the first held-out set

Writes results/linker/train_v2.csv and results/linker/scorer_v2.json.
Interface: load() -> the frozen model;  score(df) -> probabilities (df needs the columns listed in linker/features.py).

Run from `research/`:  python -m linker.scorer2
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import features as F
from . import scorer as s1
from .benchmark import OUT

HERE = Path(__file__).resolve().parent
MODEL = OUT / "scorer_v2.json"
TABLE = OUT / "train_v2.csv"
AI_MAP = HERE.parent.parent / "backend" / "app" / "data" / "ai_map.json"
HELDOUT_LABELS = ("B1", "B2")
SOURCES = ("results/linker/benchmark.csv (S4, S5; verdict != untestable)",
           "results/linker/heldout_links.csv (first held-out set, arms A and B, unique by market + ticker + direction; verdict != untestable)")
L2_GRID = (0.3, 1.0, 3.0, 10.0, 30.0)
DELTA = 0.01
MAX_INPUTS = 15
MIN_ONES = 8
SEEDS = (0, 1)
K = 5


# ---------------------------------------------------------------- training rows

def _impacts() -> dict[tuple, float]:
    """(market, ticker, direction) -> stated impact in percent: S4's map, and the mean of the first held-out arm B labellers."""
    out: dict[tuple, list] = {}
    if AI_MAP.exists():
        for key, v in json.loads(AI_MAP.read_text())["items"].items():
            for m in v.get("mappings", []):
                if isinstance(m.get("impact_pct"), (int, float)):
                    out.setdefault((key, m["ticker"], m["direction"]), []).append(abs(float(m["impact_pct"])))
    for n in HELDOUT_LABELS:
        f = HERE / "heldout" / f"labels_{n}.json"
        if f.exists():
            for a in json.loads(f.read_text())["answers"]:
                for l in a.get("links", []):
                    if isinstance(l.get("impact_pct"), (int, float)):
                        out.setdefault((a["id"], l["ticker"], l["direction"]), []).append(abs(float(l["impact_pct"])))
    return {k: float(np.mean(v)) for k, v in out.items()}


def training_table() -> pd.DataFrame:
    b = pd.read_csv(OUT / "benchmark.csv")
    h = pd.read_csv(OUT / "heldout_links.csv")
    h = h[h.verdict != "untestable"].drop_duplicates(["market", "ticker", "direction"])
    df = pd.concat([b[b.verdict != "untestable"], h.drop(columns=["score"], errors="ignore")], ignore_index=True)
    imp = _impacts()
    df["impact_pct"] = [imp.get((m, t, d), np.nan) for m, t, d in zip(df.market, df.ticker, df.direction)]
    df.loc[df.source.str.startswith("S5"), "impact_pct"] = np.nan
    df["set"] = np.where(df.source.str.startswith("S4"), "S4", np.where(df.source.str.startswith("S5"), "S5", "heldout1"))
    df["group"] = groups(df)
    return df.reset_index(drop=True)


def groups(df: pd.DataFrame) -> np.ndarray:
    """Connected components of links that share a market or the same question text: the unit no fold may split."""
    parent: dict[str, str] = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    qs = df.question.astype(str).str.lower().str.split().str.join(" ")
    for m, q in zip(df.market.astype(str), qs):
        parent[find("m:" + m)] = find("q:" + q)
    roots = [find("m:" + m) for m in df.market.astype(str)]
    codes = {r: i for i, r in enumerate(dict.fromkeys(roots))}
    return np.array([codes[r] for r in roots])


def folds(group: np.ndarray, k: int = K, seed: int = 0) -> list[tuple[np.ndarray, np.ndarray]]:
    u = np.unique(group)
    f = dict(zip(u, np.random.default_rng(seed).permutation(len(u)) % k))
    fo = np.array([f[g] for g in group])
    idx = np.arange(len(group))
    return [(idx[fo != j], idx[fo == j]) for j in range(k)]


# ---------------------------------------------------------------- model

def _matrix(X: pd.DataFrame, cols: list[str], fill: dict[str, float]) -> np.ndarray:
    return np.column_stack([X[c].fillna(fill[c]).to_numpy(float) for c in cols]) if cols else np.zeros((len(X), 0))


def fit_cols(X: pd.DataFrame, y: np.ndarray, cols: list[str], l2: float) -> dict:
    fill = {c: float(np.nanmedian(X[c])) if X[c].notna().any() else 0.0 for c in cols}
    m = s1.fit(_matrix(X, cols, fill), y, l2)
    return {**m, "cols": list(cols), "fill": fill, "l2": l2}


def predict_cols(m: dict, X: pd.DataFrame) -> np.ndarray:
    return s1.predict(m, _matrix(X, m["cols"], m["fill"]))


def usable(X: pd.DataFrame, cols) -> list[str]:
    """Drop one-hot inputs with fewer than MIN_ONES rows on and inputs that never vary on this training side."""
    keep = []
    for c in cols:
        v = X[c].dropna()
        if v.nunique() < 2:
            continue
        if set(v.unique()) <= {0.0, 1.0} and min((v == 1).sum(), (v == 0).sum()) < MIN_ONES:
            continue
        keep.append(c)
    return keep


def cv_auc(X: pd.DataFrame, y: np.ndarray, group: np.ndarray, cols: list[str], l2: float, seeds=SEEDS) -> float:
    a = []
    for s in seeds:
        oof = np.full(len(y), np.nan)
        for tr, te in folds(group, K, s):
            if 0 < y[tr].sum() < len(tr):
                oof[te] = predict_cols(fit_cols(X.iloc[tr], y[tr], cols, l2), X.iloc[te])
        ok = np.isfinite(oof)
        a.append(s1.auc(y[ok], oof[ok]))
    return float(np.mean(a))


def select(X: pd.DataFrame, y: np.ndarray, group: np.ndarray) -> dict:
    """Forward selection of input groups on top of version 1, by grouped CV AUC on these rows only."""
    cols = usable(X, F.V1)
    best_l2, best = max(((l2, cv_auc(X, y, group, cols, l2)) for l2 in L2_GRID), key=lambda r: r[1])
    trace = [{"added": "version 1", "inputs": len(cols), "l2": best_l2, "cv_auc": round(best, 4)}]
    left = dict(F.GROUPS)
    while left:
        tries = []
        for name, gcols in left.items():
            new = [c for c in usable(X, gcols) if c not in cols]
            if not new or len(cols) + len(new) > MAX_INPUTS:
                continue
            for l2 in L2_GRID:
                tries.append((cv_auc(X, y, group, cols + new, l2), name, new, l2))
        if not tries:
            break
        a, name, new, l2 = max(tries, key=lambda r: r[0])
        if a <= best + DELTA:
            break
        cols, best, best_l2 = cols + new, a, l2
        trace.append({"added": name, "inputs": len(cols), "l2": l2, "cv_auc": round(a, 4)})
        left.pop(name)
    return {"cols": cols, "l2": best_l2, "cv_auc": best, "trace": trace}


# ---------------------------------------------------------------- validation

def _bottom_third(y: np.ndarray, s: np.ndarray) -> float:
    return float(y[np.argsort(s)[: max(1, len(y) // 3)]].mean())


def validate(df: pd.DataFrame, X: pd.DataFrame, y: np.ndarray, splits: list[tuple[np.ndarray, np.ndarray]], name: str, version: str,
             fixed: dict | None = None) -> tuple[dict, np.ndarray]:
    """version "v1": version 1's inputs, L2 = 1. version "v2": selection rerun on each training side (or `fixed` cols and l2)."""
    oof = np.full(len(df), np.nan)
    chosen = []
    for tr, te in splits:
        if not len(te) or not 0 < y[tr].sum() < len(tr):
            continue
        if version == "v1":
            cols, l2 = list(F.V1), s1.L2
        elif fixed is not None:
            cols, l2 = fixed["cols"], fixed["l2"]
        else:
            sel = select(X.iloc[tr], y[tr], df.group.to_numpy()[tr])
            cols, l2 = sel["cols"], sel["l2"]
            chosen.append([t["added"] for t in sel["trace"][1:]])
        oof[te] = predict_cols(fit_cols(X.iloc[tr], y[tr], cols, l2), X.iloc[te])
    ok = np.isfinite(oof)
    r = {"validation": name, "version": version, "links_scored": int(ok.sum()), "base_rate": float(y[ok].mean()),
         "auc": s1.auc(y[ok], oof[ok]), "confirmed_in_top_third": s1.top_third(y[ok], oof[ok]),
         "confirmed_in_bottom_third": _bottom_third(y[ok], oof[ok])}
    if chosen:
        r["groups_chosen_per_split"] = chosen
    return r, oof


def splits_of(df: pd.DataFrame) -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
    idx = np.arange(len(df))
    st, th = df.set.to_numpy(), df.theme.to_numpy()
    return {"by market, 5 folds": folds(df.group.to_numpy(), K, 0),
            "leave one theme out": [(idx[th != t], idx[th == t]) for t in pd.unique(th)],
            "train S4, test S5": [(idx[st == "S4"], idx[st == "S5"])],
            "train S5, test S4": [(idx[st == "S5"], idx[st == "S4"])],
            "train S4+S5, test first held-out": [(idx[st != "heldout1"], idx[st == "heldout1"])]}


# ---------------------------------------------------------------- frozen model

def load() -> dict:
    return json.loads(MODEL.read_text())


def score(df: pd.DataFrame, model: dict | None = None) -> np.ndarray:
    """Probability that each link is confirmed, from the frozen model. df needs the columns named in linker/features.py."""
    m = model or load()
    X = F.build(df.reset_index(drop=True))
    Z = np.column_stack([X[c].fillna(m["impute"][c]).to_numpy(float) for c in m["features"]])
    w = np.array([m["weights"]["intercept"]] + [m["weights"][c] for c in m["features"]])
    Z = np.column_stack([np.ones(len(Z)), (Z - np.array(m["mean"])) / np.array(m["sd"])])
    return 1.0 / (1.0 + np.exp(-Z @ w))


def main() -> int:
    df = training_table()
    X = F.build(df)
    assert not set(X.columns) & set(F.FORBIDDEN)
    y = (df.verdict == "confirmed").to_numpy(float)
    sp = splits_of(df)
    table, oofs = [], {}
    for name, s in sp.items():
        for v in ("v1", "v2"):
            r, o = validate(df, X, y, s, name, v)
            table.append(r)
            oofs[(name, v)] = o
            print(f"  {name:34s} {v}  AUC {r['auc']:.3f}", flush=True)
    final = select(X, y, df.group.to_numpy())
    fixed = validate(df, X, y, sp["by market, 5 folds"], "by market, 5 folds", "v2 frozen selection, not nested", fixed=final)[0]
    get = lambda n, v: next(r["auc"] for r in table if r["validation"] == n and r["version"] == v)
    mean = {v: float(np.mean([get(n, v) for n in sp])) for v in ("v1", "v2")}
    better = get("by market, 5 folds", "v2") > get("by market, 5 folds", "v1") and mean["v2"] > mean["v1"]
    if better:
        cols, l2, why = final["cols"], final["l2"], "version 2 beats version 1 by market and on the mean AUC of the five validations"
    else:
        cols, l2, why = list(F.V1), s1.L2, "version 2 did not beat version 1 out of fold, so version 1's inputs are frozen (refit on all rows)"
    m = fit_cols(X, y, cols, l2)
    model = {"features": cols, "groups": [t["added"] for t in final["trace"][1:]] if better else [], "mean": m["mu"].tolist(),
             "sd": m["sd"].tolist(), "weights": {"intercept": float(m["w"][0]), **{c: float(w) for c, w in zip(cols, m["w"][1:])}},
             "l2": l2, "impute": m["fill"], "trained_on": int(len(df)), "confirmed": int(y.sum()), "training_sources": list(SOURCES),
             "choice": why, "selection_on_all_rows": final, "frozen_selection_by_market_not_nested": fixed,
             "mean_auc_over_validations": mean, "validation": table,
             "rules": {"l2_grid": list(L2_GRID), "add_if_auc_gain_above": DELTA, "max_inputs": MAX_INPUTS, "min_rows_per_one_hot": MIN_ONES,
                       "fold_seeds_inside_selection": list(SEEDS), "volatility_cutoff": F.CUTOFF, "min_sessions": F.MIN_SESSIONS}}
    MODEL.write_text(json.dumps(model, indent=1, default=float) + "\n")
    out = pd.concat([df[["source", "linker", "set", "market", "question", "ticker", "direction", "theme", "impact_pct", "group", "verdict"]],
                     F.labels(df), X], axis=1)
    out["confirmed"] = y
    for j, (_, te) in enumerate(sp["by market, 5 folds"]):
        out.loc[te, "fold"] = j
    out["score_v1_oof"] = oofs[("by market, 5 folds", "v1")]
    out["score_v2_oof_nested"] = oofs[("by market, 5 folds", "v2")]
    out["score_v2_frozen"] = predict_cols(m, X)
    out.to_csv(TABLE, index=False)
    pd.set_option("display.width", 220)
    t = pd.DataFrame(table)
    wide = t.pivot(index="validation", columns="version", values=["auc", "confirmed_in_top_third", "confirmed_in_bottom_third"]).round(3)
    wide.insert(0, "links", t.groupby("validation").links_scored.first())
    wide.insert(1, "base_rate", t.groupby("validation").base_rate.first().round(3))
    print(wide.reindex(list(sp)).to_string())
    print(f"mean AUC: v1 {mean['v1']:.3f}  v2 {mean['v2']:.3f}")
    print(f"selection on all rows: {[(r['added'], r['l2'], r['cv_auc']) for r in final['trace']]}")
    print(f"frozen selection, scored by market without nesting: AUC {fixed['auc']:.3f} (nested {get('by market, 5 folds', 'v2'):.3f})")
    print("frozen:", why)
    print("standardised coefficients:", {k: round(v, 2) for k, v in model["weights"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
