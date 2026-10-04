from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import PARAMS, Params


@dataclass(frozen=True)
class XCorr:
    table: pd.DataFrame
    peak_lag: int | None
    peak_rho: float | None
    n: int
    significant: bool | None
    pm_lead_mass: float | None
    eq_lead_mass: float | None


def cross_correlation(x: pd.Series, ys: pd.Series, in_window: pd.Series, p: Params = PARAMS) -> XCorr:
    rows = []
    for lag in range(-p.xcorr_max_lag, p.xcorr_max_lag + 1):
        ysl = ys.shift(lag)
        m = in_window & x.notna() & ysl.notna()
        n = int(m.sum())
        rho = np.nan
        if n >= p.xcorr_min_n:
            a, b = x[m].to_numpy(), ysl[m].to_numpy()
            if a.std() > 0 and b.std() > 0:
                rho = float(np.corrcoef(a, b)[0, 1])
        rows.append((lag, rho, n))
    tab = pd.DataFrame(rows, columns=["lag", "rho", "n"])
    ok = tab.dropna(subset=["rho"])
    if ok.empty:
        return XCorr(tab, None, None, int(tab["n"].max()), None, None, None)
    order = ok.assign(a=ok["rho"].abs(), l=ok["lag"].abs()).sort_values(["a", "l"], ascending=[False, True])
    best = order.iloc[0]
    n0 = int(tab.loc[tab["lag"] == 0, "n"].iloc[0])
    M = p.lead_mass_lags
    pm_mass = ok.loc[(ok["lag"] >= 1) & (ok["lag"] <= M), "rho"].mean()
    eq_mass = ok.loc[(ok["lag"] <= -1) & (ok["lag"] >= -M), "rho"].mean()
    return XCorr(tab, int(best["lag"]), float(best["rho"]), n0, bool(abs(best["rho"]) > 2 / np.sqrt(n0)),
                 None if np.isnan(pm_mass) else float(pm_mass), None if np.isnan(eq_mass) else float(eq_mass))
