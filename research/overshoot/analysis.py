"""Decomposition of the closure gap and paired forecast scores (METHOD.md sections 3 and 4)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from open_options.stats import _weights, ols

from .config import COLUMNS, PARAMS, Params


def load(path) -> pd.DataFrame:
    d = pd.read_csv(path)
    missing = [c for c in COLUMNS if c not in d.columns]
    if missing:
        raise SystemExit(f"events.csv lacks columns {missing}; METHOD section 1 says stop and amend")
    e = d[d["status"].astype(str) == "event"].copy()
    e["closure"] = e["closure"].astype(str)
    e["prints"] = e["prints_in_closure"].astype(str) == "True"
    return e


def decompose(e: pd.DataFrame, pm_ref: str = "pm_open") -> pd.DataFrame:
    s = np.where(e["pm_open"] > e["pm_close"], 1.0, -1.0)
    out = pd.DataFrame(index=e.index)
    out["s"] = s
    out["G"] = s * ((e[pm_ref] - e["pm_close"]) - (e["oo_mid"] - e["oc_mid"]))
    out["R"] = -s * (e["pm_eod"] - e[pm_ref])
    out["F"] = s * (e["oe_mid"] - e["oo_mid"])
    out["L"] = s * ((e["pm_eod"] - e["pm_close"]) - (e["oe_mid"] - e["oc_mid"]))
    return out


def brier(p, y) -> np.ndarray:
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def log_score(p, y, eps: float = PARAMS.log_eps) -> np.ndarray:
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _ci(a) -> list[float]:
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))] if len(a) else [float("nan")] * 2


class Boot:
    """Closure-cluster bootstrap with one set of multinomial weights shared by every statistic of a sample."""

    def __init__(self, clusters, params: Params = PARAMS):
        self.keys, self.inv = np.unique(np.asarray(clusters).astype(str), return_inverse=True)
        self.c = len(self.keys)
        self.n = np.bincount(self.inv, minlength=self.c).astype(float)
        self.w = _weights(self.c, params.draws, params.seed)

    def _sum(self, v) -> np.ndarray:
        return np.bincount(self.inv, np.asarray(v, float), self.c)

    def mean(self, v) -> dict:
        v = np.asarray(v, float)
        sv = self._sum(v)
        cm = sv / self.n
        draws = (self.w @ sv) / (self.w @ self.n)
        cw = (self.w @ cm) / self.w.sum(axis=1)
        return dict(n=int(len(v)), clusters=int(self.c), mean=float(v.mean()), ci=_ci(draws),
                    cw_mean=float(cm.mean()), cw_ci=_ci(cw))

    def ratio(self, num, den) -> dict:
        sn, sd = self._sum(num), self._sum(den)
        with np.errstate(invalid="ignore", divide="ignore"):
            draws = (self.w @ sn) / (self.w @ sd)
        return dict(value=float(sn.sum() / sd.sum()), ci=_ci(draws))

    def slope(self, x, y) -> dict:
        x, y = np.asarray(x, float), np.asarray(y, float)
        N = self.w @ self.n
        SX, SY, SXX, SXY = (self.w @ self._sum(v) for v in (x, y, x * x, x * y))
        with np.errstate(invalid="ignore", divide="ignore"):
            b = (SXY - SX * SY / N) / (SXX - SX * SX / N)
        return dict(beta=ols(x, y)[1], ci=_ci(b))

    def lpm(self, X, y) -> dict:
        X = np.column_stack([np.ones(len(y)), np.asarray(X, float)])
        y = np.asarray(y, float)
        k = X.shape[1]
        xtx = np.zeros((self.c, k * k))
        xty = np.zeros((self.c, k))
        for i in range(k):
            xty[:, i] = self._sum(X[:, i] * y)
            for j in range(k):
                xtx[:, i * k + j] = self._sum(X[:, i] * X[:, j])
        point = np.linalg.solve(xtx.sum(0).reshape(k, k), xty.sum(0))
        A = (self.w @ xtx).reshape(-1, k, k)
        bvec = self.w @ xty
        det = np.linalg.det(A)
        ok = np.abs(det) > 1e-12
        draws = np.full((len(A), k), np.nan)
        draws[ok] = np.linalg.solve(A[ok], bvec[ok][..., None])[..., 0]
        return dict(coef=[float(v) for v in point], ci=[_ci(draws[:, i]) for i in range(k)])


def enough(n: int, clusters: int, params: Params = PARAMS) -> bool:
    return n >= params.min_events and clusters >= params.min_clusters


def decomp_stats(e: pd.DataFrame, pm_ref: str = "pm_open", params: Params = PARAMS) -> dict:
    need = ["pm_eod", "oe_mid", pm_ref]
    d = e.dropna(subset=need)
    if len(d) == 0:
        return dict(n=0, clusters=0)
    p = decompose(d, pm_ref)
    if not np.allclose(p["G"], p["R"] + p["F"] + p["L"], atol=1e-9):
        raise AssertionError("G != R + F + L")
    b = Boot(d["closure"], params)
    out = dict(n=int(len(d)), clusters=int(b.c))
    for k in ("G", "R", "F", "L"):
        out[k] = b.mean(p[k])
    for k in ("R", "F", "L"):
        out[f"share_{k}"] = b.ratio(p[k], p["G"])
    out["beta_open"] = b.slope(d["pm_open"] - d["pm_close"], d["oo_mid"] - d["oc_mid"])
    out["beta_perm"] = b.slope(d["pm_eod"] - d["pm_close"], d["oo_mid"] - d["oc_mid"])
    out["beta_eod"] = b.slope(d["pm_eod"] - d["pm_close"], d["oe_mid"] - d["oc_mid"])
    return out


def verdict_a(st: dict, params: Params = PARAMS) -> dict:
    if not enough(st.get("n", 0), st.get("clusters", 0), params):
        return dict(label="SAMPLE-TOO-SMALL", overshoot=False, majority=False, lag=False, persists=False)
    over = st["R"]["ci"][0] > 0
    major = over and st["share_R"]["ci"][0] > params.majority
    lag = st["F"]["ci"][0] > 0
    persists = st["L"]["ci"][0] > 0
    lab = "OVERSHOOT-MAJORITY" if major else "OVERSHOOT-PARTIAL" if over else "NO-OVERSHOOT-SHOWN"
    lab += " / " + ("LAG-SHOWN" if lag else "NO-LAG-SHOWN")
    return dict(label=lab, overshoot=bool(over), majority=bool(major), lag=bool(lag), persists=bool(persists),
                persists_label="GAP-PERSISTS" if persists else "GAP-NOT-SHOWN-TO-PERSIST")


def pair_stats(e: pd.DataFrame, pm_col: str, opt_col: str, params: Params = PARAMS) -> dict:
    d = e.dropna(subset=[pm_col, opt_col, "outcome"])
    d = d[d["outcome"].isin([0, 1])]
    if len(d) == 0:
        return dict(n=0, clusters=0)
    y = d["outcome"].astype(float)
    b = Boot(d["closure"], params)
    out = dict(n=int(len(d)), clusters=int(b.c))
    for name, f in (("brier", brier), ("log", log_score)):
        sp, so = f(d[pm_col], y), f(d[opt_col], y)
        out[name] = dict(pm=float(sp.mean()), opt=float(so.mean()), d=b.mean(sp - so))
    return out


def verdict_b(st: dict, params: Params = PARAMS) -> str:
    if not enough(st.get("n", 0), st.get("clusters", 0), params):
        return "SAMPLE-TOO-SMALL"
    lo = [st[k]["d"]["ci"][0] > 0 for k in ("brier", "log")]
    hi = [st[k]["d"]["ci"][1] < 0 for k in ("brier", "log")]
    if all(lo):
        return "OPTIONS-BETTER"
    if all(hi):
        return "PM-BETTER"
    if not any(lo) and not any(hi):
        return "NO-DIFFERENCE-SHOWN"
    return "MIXED"


def closure_change(e: pd.DataFrame, params: Params = PARAMS) -> dict:
    d = e.dropna(subset=["pm_open", "oo_mid", "pm_close", "oc_mid", "outcome"])
    d = d[d["outcome"].isin([0, 1])]
    if len(d) == 0:
        return dict(n=0, clusters=0)
    y = d["outcome"].astype(float)
    b = Boot(d["closure"], params)
    out = dict(n=int(len(d)), clusters=int(b.c))
    for name, f in (("brier", brier), ("log", log_score)):
        dd = (f(d["pm_open"], y) - f(d["oo_mid"], y)) - (f(d["pm_close"], y) - f(d["oc_mid"], y))
        out[name] = b.mean(dd)
    return out


def encompassing(e: pd.DataFrame, params: Params = PARAMS) -> dict:
    d = e.dropna(subset=["pm_open", "oo_mid", "outcome"])
    d = d[d["outcome"].isin([0, 1])]
    if len(d) == 0:
        return dict(n=0, clusters=0)
    b = Boot(d["closure"], params)
    r = b.lpm(d[["pm_open", "oo_mid"]].to_numpy(float), d["outcome"].astype(float).to_numpy())
    return dict(n=int(len(d)), clusters=int(b.c), a=r["coef"][0], b1=r["coef"][1], b1_ci=r["ci"][1],
                b2=r["coef"][2], b2_ci=r["ci"][2], pm_adds=bool(r["ci"][1][0] > 0))


def subsets(e: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {"Polymarket trade print inside the closure": e[e["prints"]]}
    for k in ("daily", "weekly", "monthly"):
        out[f"kind = {k}"] = e[e["kind"].astype(str) == k]
    return out


def analyse(e: pd.DataFrame, params: Params = PARAMS) -> dict:
    a = decomp_stats(e, "pm_open", params)
    po = pair_stats(e, "pm_open", "oo_mid", params)
    pc = pair_stats(e, "pm_close", "oc_mid", params)
    sec_a = {"same instant (PM at 09:45)": decomp_stats(e, "pm_0945", params)}
    sec_b = {"same instant (PM 09:45 vs options 09:45)": pair_stats(e, "pm_0945", "oo_mid", params),
             "end of day (PM 16:00 vs options 15:55)": pair_stats(e, "pm_eod", "oe_mid", params)}
    for name, sub in subsets(e).items():
        sec_a[name] = decomp_stats(sub, "pm_open", params)
        sec_b[f"{name}, open pair"] = pair_stats(sub, "pm_open", "oo_mid", params)
    return dict(n_events=int(len(e)), clusters_events=int(e["closure"].nunique()),
                decomposition=a, verdict_a=verdict_a(a, params),
                open_pair=po, verdict_open=verdict_b(po, params),
                close_pair=pc, verdict_close=verdict_b(pc, params),
                secondary_a=sec_a, secondary_b=sec_b,
                closure_change=closure_change(e, params), encompassing=encompassing(e, params))
