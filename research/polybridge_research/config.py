"""Study configuration. Defaults are the pre-registered values (HYPOTHESIS.md §3) and the starter's mechanics."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import pandas as pd

TOP_100: tuple[str, ...] = tuple("""
AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY BRK.B C
CAT CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR FDX GD GE GILD
GM GOOGL GS HD HON IBM INTC INTU ISRG JNJ JPM KO LIN LLY LMT LOW MA MCD MDLZ MDT
MET META MMM MO MRK MS MSFT NEE NFLX NKE NOW NVDA ORCL PEP PFE PG PLTR PM PYPL QCOM
RTX SBUX SCHW SO T TGT TMO TMUS TSLA TXN UBER UNH UNP UPS USB V VZ WFC WMT XOM
""".split())

EXPIRY_BUCKETS: dict[str, tuple[int, int, int]] = {"1m": (21, 45, 30), "2m": (46, 80, 60), "3-6m": (90, 180, 120)}
HORIZONS: tuple[int, ...] = (1, 2, 3, 5, 10, 21, 42, 63)


@dataclass(frozen=True)
class StudyConfig:
    study_start: str = "2024-01-01"
    study_end: str = "2025-12-31"
    oos_start: str = "2026-01-01"
    oos_end: str = "2026-08-31"
    universe: tuple[str, ...] = TOP_100
    buckets: dict = field(default_factory=lambda: dict(EXPIRY_BUCKETS))
    baseline_bucket: str = "3-6m"
    horizons: tuple[int, ...] = HORIZONS
    headline_horizons: tuple = (21, 42, "exp")
    otm_pct: float = 0.05
    otm_grid: tuple[float, ...] = (0.03, 0.05, 0.10)
    entry: str = "post"
    risk_free: float = 0.04
    strike_window: float = 0.25
    max_stale_sessions: int = 3
    n_placebo: int = 120
    placebo_gap_days: int = 30
    cost_haircut: float = 0.05
    confirmatory_level: float = 0.975

    def validate(self) -> None:
        for name in ("study_start", "study_end", "oos_start", "oos_end"):
            try:
                pd.Timestamp(getattr(self, name))
            except ValueError:
                raise ValueError(f"{name} = {getattr(self, name)!r} is not a real date") from None
        if not (self.study_start < self.study_end and self.oos_start < self.oos_end):
            raise ValueError("each window's start must be before its end")
        if self.otm_pct not in self.otm_grid:
            raise ValueError("otm_pct must be one of otm_grid")
        if self.baseline_bucket not in self.buckets:
            raise ValueError("baseline_bucket must be one of buckets")
        if self.entry not in ("pre", "post"):
            raise ValueError("entry must be 'pre' or 'post'")

    def with_window(self, start: str, end: str) -> "StudyConfig":
        return dataclasses.replace(self, study_start=start, study_end=end)
