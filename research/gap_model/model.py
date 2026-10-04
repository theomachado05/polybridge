from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd

from leadlag_closed.stats import THETA_TOL, binom_two_sided, ols_hc3

from .config import PARAMS


def fit_rate(x, g) -> dict:
    x, g = np.asarray(x, float), np.asarray(g, float)
    m = np.isfinite(x) & np.isfinite(g)
    x, g = x[m], g[m]
    n, nz = len(x), int((x != 0).sum())
    sxx = float((x ** 2).sum())
    if nz == 0 or sxx <= 0:
        return {"rate": float("nan"), "se": float("nan"), "resid_sd": float("nan"), "n": n, "n_nonzero": nz}
    rate = float((x * g).sum() / sxx)
    e = g - rate * x
    h = x ** 2 / sxx
    adj = e / np.clip(1 - h, 1e-8, None)
    se = sqrt(float((x ** 2 * adj ** 2).sum())) / sxx
    resid_sd = sqrt(float((e ** 2).sum()) / (n - 1)) if n > 1 else float("nan")
    return {"rate": rate, "se": se, "resid_sd": resid_sd, "n": n, "n_nonzero": nz}


def between_market_sd(own_rates: list[float], pooled_rate: float) -> float:
    r = [v for v in own_rates if np.isfinite(v)]
    if len(r) >= 2:
        return float(np.std(r, ddof=1))
    return abs(pooled_rate) if np.isfinite(pooled_rate) else float("nan")


def band_halfwidth(x: float, se_eff: float, resid_sd: float, z: float = PARAMS.z80) -> float:
    return z * sqrt(x ** 2 * se_eff ** 2 + resid_sd ** 2)


def walk_forward(df: pd.DataFrame, outcome: str, n_min: int = PARAMS.n_min, z: float = PARAMS.z80) -> pd.DataFrame:
    d = df.copy()
    if "test" not in d:
        d["test"] = True
    d = d[np.isfinite(d["x"].astype(float)) & np.isfinite(d[outcome].astype(float))]
    d = d.sort_values(["closure", "market"], kind="mergesort").reset_index(drop=True)
    x_all = d["x"].to_numpy(float)
    g_all = d[outcome].to_numpy(float)
    od = d["open_day"].astype(str).to_numpy()
    mk = d["market"].astype(str).to_numpy()
    out = []
    for i, r in d.iterrows():
        if not r["test"]:
            continue
        tr = od <= str(r["closure"])
        pooled = fit_rate(x_all[tr], g_all[tr])
        own_rates = []
        for m in np.unique(mk[tr]):
            fm = fit_rate(x_all[tr & (mk == m)], g_all[tr & (mk == m)])
            if fm["n_nonzero"] >= n_min:
                own_rates.append(fm["rate"])
        own = fit_rate(x_all[tr & (mk == r["market"])], g_all[tr & (mk == r["market"])])
        if own["n_nonzero"] >= n_min:
            src, fit, se_eff = "own", own, own["se"]
        elif pooled["n_nonzero"] >= n_min:
            tau = between_market_sd(own_rates, pooled["rate"])
            src, fit, se_eff = "pooled", pooled, sqrt(pooled["se"] ** 2 + tau ** 2)
        else:
            continue
        x = float(r["x"])
        pred = fit["rate"] * x
        hw = band_halfwidth(x, se_eff, fit["resid_sd"], z)
        past = g_all[tr]
        out.append({"market": r["market"], "closure": r["closure"], "open_day": r["open_day"],
                    "kind": r.get("kind", ""), "x_pp": x, "gap_bp": float(r[outcome]), "source": src,
                    "rate": fit["rate"], "rate_se": fit["se"], "se_eff": se_eff, "resid_sd": fit["resid_sd"],
                    "train_n": fit["n"], "train_n_nonzero": fit["n_nonzero"], "pred_bp": pred,
                    "band_lo": pred - hw, "band_hi": pred + hw,
                    "mean_past_bp": float(past.mean()) if len(past) else float("nan")})
    return pd.DataFrame(out)


def sign_accuracy(pred, gap, x=None, theta: float | None = None) -> dict:
    pred, gap = np.asarray(pred, float), np.asarray(gap, float)
    m = np.isfinite(pred) & np.isfinite(gap) & (pred != 0) & (gap != 0)
    if theta is not None:
        m &= np.abs(np.asarray(x, float)) >= theta - THETA_TOL
    n = int(m.sum())
    k = int((np.sign(pred[m]) == np.sign(gap[m])).sum())
    return {"n": n, "k": k, "rate": k / n if n else float("nan"), "p": binom_two_sided(k, n) if n else float("nan")}


def _slope(x, y):
    xc = x - x.mean()
    d = float((xc ** 2).sum())
    return float((xc * (y - y.mean())).sum() / d) if d > 0 else 0.0


def slope_test(pred, gap, n_perm: int = PARAMS.n_perm, seed: int = PARAMS.seed, groups=None) -> dict:
    pred, gap = np.asarray(pred, float), np.asarray(gap, float)
    m = np.isfinite(pred) & np.isfinite(gap)
    pred, gap = pred[m], gap[m]
    n = len(pred)
    nan = float("nan")
    if n < 4 or np.ptp(pred) == 0:
        return {"n": n, "c": nan, "a": nan, "t": nan, "t_c_minus_1": nan, "r2": nan, "p_perm": nan}
    fit = ols_hc3(gap, np.column_stack([np.ones(n), pred]))
    c, se = float(fit["beta"][1]), float(fit["se"][1])
    rng = np.random.default_rng(seed)
    c_obs = abs(_slope(pred, gap))
    cnt = 0
    if groups is None:
        for _ in range(n_perm):
            cnt += abs(_slope(pred, rng.permutation(gap))) >= c_obs - 1e-12
    else:
        g = np.asarray(groups)[m]
        uniq, inv = np.unique(g, return_inverse=True)
        date_gap = np.array([gap[inv == j][0] for j in range(len(uniq))])
        for _ in range(n_perm):
            cnt += abs(_slope(pred, rng.permutation(date_gap)[inv])) >= c_obs - 1e-12
    return {"n": n, "c": c, "a": float(fit["beta"][0]), "t": float(fit["t"][1]),
            "t_c_minus_1": (c - 1) / se if se > 0 else nan, "r2": fit["r2"], "p_perm": (cnt + 1) / (n_perm + 1)}


def oos_r2(pred, gap, bench) -> float:
    pred, gap, bench = (np.asarray(a, float) for a in (pred, gap, bench))
    m = np.isfinite(pred) & np.isfinite(gap) & np.isfinite(bench)
    den = float(((gap[m] - bench[m]) ** 2).sum())
    return 1 - float(((gap[m] - pred[m]) ** 2).sum()) / den if den > 0 else float("nan")


def bucket_of(p: float) -> str:
    if p == 0:
        return "= 0"
    if p <= -10:
        return "<= -10"
    if p <= -3:
        return "(-10, -3]"
    if p < 0:
        return "(-3, 0)"
    if p < 3:
        return "(0, 3)"
    if p < 10:
        return "[3, 10)"
    return ">= 10"


def calibration_table(pred, gap) -> pd.DataFrame:
    d = pd.DataFrame({"pred": np.asarray(pred, float), "gap": np.asarray(gap, float)})
    d["bucket"] = [bucket_of(p) for p in d["pred"]]
    rows = []
    for b in PARAMS.buckets:
        s = d[d["bucket"] == b]
        nz = s[(s["pred"] != 0) & (s["gap"] != 0)]
        rows.append({"bucket": b, "n": len(s),
                     "mean_pred_bp": s["pred"].mean() if len(s) else float("nan"),
                     "mean_realized_bp": s["gap"].mean() if len(s) else float("nan"),
                     "median_realized_bp": s["gap"].median() if len(s) else float("nan"),
                     "hit_rate": float((np.sign(nz["pred"]) == np.sign(nz["gap"])).mean()) if len(nz) else float("nan"),
                     "n_hit_eligible": len(nz)})
    return pd.DataFrame(rows)


def band_coverage(pr: pd.DataFrame) -> dict:
    inside = (pr["gap_bp"] >= pr["band_lo"]) & (pr["gap_bp"] <= pr["band_hi"])
    out = {"all": {"n": len(pr), "coverage": float(inside.mean()) if len(pr) else float("nan")}}
    for s in ("own", "pooled"):
        m = pr["source"] == s
        out[s] = {"n": int(m.sum()), "coverage": float(inside[m].mean()) if m.any() else float("nan")}
    return out


def verdict(g1: dict, g2: dict, alpha: float = PARAMS.alpha) -> tuple[str, bool, bool]:
    i = bool(g1["n"] and g1["rate"] > 0.5 and g1["p"] < alpha)
    ii = bool(np.isfinite(g2["c"]) and g2["c"] > 0 and g2["p_perm"] < alpha)
    if i and ii:
        return "Accurate out of sample", i, ii
    if i or ii:
        return "Partial", i, ii
    return "Not accurate out of sample", i, ii
