"""Hedge rules, expanding-window rate and bootstrap of METHOD.md sections 2-5. Pure numpy/pandas, no I/O."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PARAMS


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2 or np.ptp(x) == 0:
        return float("nan")
    xc = x - x.mean()
    return float((xc * (y - y.mean())).sum() / (xc ** 2).sum())


def _fit_ok(x: np.ndarray, min_prior: int, min_nonzero: int) -> bool:
    return len(x) >= min_prior and int((x != 0).sum()) >= min_nonzero and np.ptp(x) > 0


def sort_panel(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["open_day", "closure", "market"], kind="mergesort").reset_index(drop=True)


def expanding_rates(df: pd.DataFrame, x: str = "dpm_o_pp", y: str = "gap_bp",
                    min_prior: int = PARAMS.min_prior, min_nonzero: int = PARAMS.min_prior_nonzero) -> pd.DataFrame:
    """Section 2. For each row, OLS slope of y on x over rows whose open_day <= this row's closure day.

    Same-market rows first; pooled (all markets) fallback; negative slope clipped to 0. Returns columns
    rate (NaN = no rate yet), rate_raw (unclipped), rate_src ('market', 'pooled' or ''), n_prior.
    The row itself and every later row are never used (open_day of the row > its closure day).
    """
    closure = df["closure"].astype(str).to_numpy()
    open_day = df["open_day"].astype(str).to_numpy()
    market = df["market"].astype(str).to_numpy()
    xv, yv = df[x].to_numpy(float), df[y].to_numpy(float)
    ok = np.isfinite(xv) & np.isfinite(yv)
    rate, raw, src, nprior = [], [], [], []
    for i in range(len(df)):
        known = ok & (open_day <= closure[i])
        known[i] = False
        same = known & (market == market[i])
        r, s, n = float("nan"), "", 0
        if _fit_ok(xv[same], min_prior, min_nonzero):
            r, s, n = _slope(xv[same], yv[same]), "market", int(same.sum())
        elif _fit_ok(xv[known], min_prior, min_nonzero):
            r, s, n = _slope(xv[known], yv[known]), "pooled", int(known.sum())
        raw.append(r)
        rate.append(max(r, 0.0) if np.isfinite(r) else float("nan"))
        src.append(s)
        nprior.append(n)
    return pd.DataFrame({"rate": rate, "rate_raw": raw, "rate_src": src, "n_prior": nprior}, index=df.index)


def frac_b(expected_gap_bp, k_bp: float) -> np.ndarray:
    """Hedge B fraction: clip(-E / K, 0, 1)."""
    return np.clip(-np.asarray(expected_gap_bp, float) / k_bp, 0.0, 1.0)


def compound_bp(a_bp, b_bp) -> np.ndarray:
    a, b = np.asarray(a_bp, float) / 1e4, np.asarray(b_bp, float) / 1e4
    return 1e4 * ((1 + a) * (1 + b) - 1)


def hedge_a(gap, dpm_o, rate, hs_pp) -> np.ndarray:
    """Y_A = gap - rate * dpm_o - 2 * hs * rate (bp of position)."""
    rate = np.asarray(rate, float)
    return np.asarray(gap, float) - rate * np.asarray(dpm_o, float) - 2.0 * hs_pp * rate


def hedge_b(ret, f, cost_side_bp) -> np.ndarray:
    """Y_B = (1 - f) * ret - 2 * cost_side * f (bp of position, window from the hedge's execution)."""
    f = np.asarray(f, float)
    return (1.0 - f) * np.asarray(ret, float) - 2.0 * cost_side_bp * f


def strategies(df: pd.DataFrame, hs_pp: float, k_bp: float = PARAMS.k_bp, eq_side_bp: float = PARAMS.eq_cost_bp,
               eq_pre_side_bp: float = PARAMS.eq_cost_bp) -> pd.DataFrame:
    """Every strategy's P&L for the rows of df (which must already carry `rate`). Static sizes from these rows."""
    out = pd.DataFrame(index=df.index)
    g, x, r30 = df["gap_bp"].to_numpy(float), df["dpm_o_pp"].to_numpy(float), df["ret30_bp"].to_numpy(float)
    rate = df["rate"].to_numpy(float)
    rbar = float(np.nanmean(rate))
    out["Y0_A"] = g
    out["Y_A"] = hedge_a(g, x, rate, hs_pp)
    out["Y_SA"] = hedge_a(g, x, np.full_like(rate, rbar), hs_pp)
    out["cost_A"] = 2.0 * hs_pp * rate
    out["N_A"] = rate / 100.0

    e = rate * x
    f = frac_b(e, k_bp)
    fbar = float(np.nanmean(f))
    out["E_open_bp"] = e
    out["f_B"] = f
    out["Y0_B"] = r30
    out["Y_B"] = hedge_b(r30, f, eq_side_bp)
    out["Y_SB"] = hedge_b(r30, np.full_like(f, fbar), eq_side_bp)

    x08 = df["dpm_early_o_pp"].to_numpy(float)
    r08 = compound_bp(df["resid_bp"].to_numpy(float), r30)
    e08 = rate * x08
    f08 = np.where(np.isfinite(e08), frac_b(e08, k_bp), np.nan)
    ok08 = np.isfinite(f08) & np.isfinite(r08)
    fbar08 = float(np.nanmean(f08[ok08])) if ok08.any() else float("nan")
    out["E_0800_bp"] = e08
    out["f_B08"] = f08
    out["Y0_B08"] = np.where(ok08, r08, np.nan)
    out["Y_B08"] = np.where(ok08, hedge_b(r08, f08, eq_pre_side_bp), np.nan)
    out["Y_SB08"] = np.where(ok08, hedge_b(r08, np.full_like(f08, fbar08), eq_pre_side_bp), np.nan)

    # whole path, close to 10:00 ET (secondary)
    u = compound_bp(g, r30)
    pm_leg = -rate * x - 2.0 * hs_pp * rate
    eq_leg = -(f * r30 + 2.0 * eq_side_bp * f) * (1 + g / 1e4)
    out["W0"] = u
    out["W_A"] = u + pm_leg
    out["W_B"] = u + eq_leg
    out["W_AB"] = u + pm_leg + eq_leg
    out.attrs.update(rbar=rbar, fbar=fbar, fbar08=fbar08)
    return out


# ---------------- inference ----------------

def iid_indices(n: int, n_boot: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, n, size=(n_boot, n))


def block_indices(n: int, n_boot: int, block: int, seed: int) -> np.ndarray:
    """Moving-block bootstrap over the sorted rows."""
    rng = np.random.default_rng(seed)
    block = max(1, min(block, n))
    nb = -(-n // block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, nb * block)
    return idx[:, :n]


def cluster_indices(groups, n_boot: int, seed: int) -> list[np.ndarray]:
    """Resample groups (closure dates) with replacement; all rows of a drawn group come together."""
    groups = np.asarray(groups)
    uniq, inv = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inv == k) for k in range(len(uniq))]
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    return [np.concatenate([members[k] for k in row]) for row in draws]


def _var_rows(Y: np.ndarray, idx) -> np.ndarray:
    if isinstance(idx, np.ndarray):
        return Y[idx].var(axis=1, ddof=1)
    return np.array([Y[i].var(ddof=1) for i in idx])


def variance_test(y0, yh, ys, idx) -> dict:
    """VR0 = 1 - Var(H)/Var(0); VRS = (Var(S) - Var(H))/Var(0); paired bootstrap percentile CIs."""
    y0, yh, ys = (np.asarray(a, float) for a in (y0, yh, ys))
    v0, vh, vs = y0.var(ddof=1), yh.var(ddof=1), ys.var(ddof=1)
    b0, bh, bs = _var_rows(y0, idx), _var_rows(yh, idx), _var_rows(ys, idx)
    vr0_b, vrs_b = 1 - bh / b0, (bs - bh) / b0
    return {
        "n": int(len(y0)), "var0": float(v0), "varH": float(vh), "varS": float(vs),
        "sd0": float(np.sqrt(v0)), "sdH": float(np.sqrt(vh)), "sdS": float(np.sqrt(vs)),
        "VR0": float(1 - vh / v0), "VR0_lo": float(np.percentile(vr0_b, 2.5)), "VR0_hi": float(np.percentile(vr0_b, 97.5)),
        "VRS": float((vs - vh) / v0), "VRS_lo": float(np.percentile(vrs_b, 2.5)), "VRS_hi": float(np.percentile(vrs_b, 97.5)),
        "VRstatic0": float(1 - vs / v0),
    }


def verdict(t: dict) -> str:
    """Section 4: both CIs above 0 -> reduces; exactly one -> partial; else no evidence / increases."""
    a, b = t["VR0_lo"] > 0, t["VRS_lo"] > 0
    if a and b:
        return "reduces the loss variance"
    if a or b:
        return "partial"
    if t["VR0_hi"] < 0:
        return "increases variance"
    return "no evidence"


def describe(y, y0=None, bad_bp: float = PARAMS.bad_open_bp) -> dict:
    y = np.asarray(y, float)
    d = {"mean": float(y.mean()), "sd": float(y.std(ddof=1)), "p5": float(np.percentile(y, 5)), "worst": float(y.min())}
    if y0 is not None:
        m = np.asarray(y0, float) < bad_bp
        d["bad_n"] = int(m.sum())
        d["bad_mean"] = float(y[m].mean()) if m.any() else float("nan")
    return d
