from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .align import build_frame, equity_series, make_grid, pm_series
from .config import PARAMS, SENSITIVITY_K, Params
from .detect import Move, first_move, lead_class, lead_minutes
from .events import Event
from .xcorr import XCorr, cross_correlation


@dataclass
class InstrumentResult:
    ticker: str
    primary: bool
    frame: pd.DataFrame
    eq_move: Move | None
    lead: float | None
    lead_cls: str
    xc: XCorr
    eq_valid_frac: float
    eq_cov: float
    sens: dict = field(default_factory=dict)


@dataclass
class EventResult:
    event: Event
    pm_points: int
    pm_changes: int
    pm_move: Move | None
    instruments: dict[str, InstrumentResult]
    drop_reasons: list[str]
    sens_pm: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return not self.drop_reasons

    @property
    def primary(self) -> InstrumentResult | None:
        return self.instruments.get(self.event.primary)


def analyse_event(ev: Event, pm_points: list[tuple[int, float]], bars: dict[str, pd.DataFrame],
                  p: Params = PARAMS) -> EventResult:
    fetch_start = ev.start - pd.Timedelta(minutes=p.warmup_min)
    grid = make_grid(fetch_start, ev.end)
    pm = pm_series(pm_points, grid)
    in_win = pd.Series((grid >= ev.start) & (grid < ev.end), index=grid)
    pm_pts_win = int(pm.loc[in_win, "obs"].sum())

    probe = build_frame(pm, equity_series(None, grid), ev.expected_sign, ev.start, ev.end)
    pm_changes = int(((probe["y"] != 0) & probe["y"].notna() & probe["in_window"]).sum())
    pm_move = first_move(probe["pm_lvl"], probe["y"], probe["in_window"], p.pm_floor_pp, p=p)
    sens_pm = {k: first_move(probe["pm_lvl"], probe["y"], probe["in_window"], p.pm_floor_pp, k=k, p=p) for k in SENSITIVITY_K}

    results: dict[str, InstrumentResult] = {}
    for tkr in ev.instruments:
        eq = equity_series(bars.get(tkr), grid)
        fr = build_frame(pm, eq, ev.expected_sign, ev.start, ev.end)
        eq_move = first_move(fr["eq_lvl"], fr["x"], fr["in_window"], p.eq_floor_bp, p=p)
        lead = lead_minutes(pm_move, eq_move)
        xc = cross_correlation(fr["x"], fr["ys"], fr["in_window"], p)
        w = fr["in_window"]
        valid_frac = float((w & fr["eq_valid"]).sum() / max(w.sum(), 1))
        n_valid = int((w & fr["eq_valid"]).sum())
        cov = float((w & fr["eq_obs"] & fr["eq_valid"]).sum() / n_valid) if n_valid else 0.0
        sens = {}
        for k in SENSITIVITY_K:
            m = first_move(fr["eq_lvl"], fr["x"], fr["in_window"], p.eq_floor_bp, k=k, p=p)
            sens[k] = (m.time if m else None, lead_minutes(sens_pm[k], m))
        results[tkr] = InstrumentResult(tkr, tkr == ev.primary, fr, eq_move, lead, lead_class(lead, p), xc, valid_frac, cov, sens)

    reasons: list[str] = []
    prim = results[ev.primary]
    if pm_pts_win == 0 and not pm_points:
        reasons.append("no minute history (CLOB returned no points)")
    elif pm_pts_win < p.min_pm_points:
        reasons.append(f"no minute history (only {pm_pts_win} CLOB points in window, need {p.min_pm_points})")
    elif pm_changes < p.min_pm_changes:
        reasons.append(f"PM too flat ({pm_changes} minutes with a price change, need {p.min_pm_changes})")
    if prim.eq_valid_frac < p.min_eq_valid or prim.eq_cov < p.min_eq_cov:
        reasons.append(f"thin equity data for {ev.primary} (valid {prim.eq_valid_frac:.0%}, bar coverage {prim.eq_cov:.0%})")
    w = prim.frame["in_window"]
    overlap = int((w & prim.frame["x"].notna() & prim.frame["ys"].notna()).sum())
    if overlap < p.min_overlap and not reasons:
        reasons.append(f"too little overlap ({overlap} minutes with both changes)")
    return EventResult(ev, pm_pts_win, pm_changes, pm_move, results, reasons, sens_pm)
