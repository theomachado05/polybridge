"""Verdict badges: confirmatory H1/H2 family verdicts and the exploratory atlas (read-only over research/results)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from polybridge_research.schema import H1_TAGS, H2_TAGS

Label = Literal["hedge", "opportunity", "no_edge"]
Kind = Literal["confirmatory", "exploratory", "none"]

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[2] / "research" / "results"
ATLAS_Q = 0.10
ATLAS_MIN_HORIZONS = 2
ATLAS_STRATEGY = {"hedge": "protective_put", "opportunity": "cash_secured_put"}


class Evidence(BaseModel):
    strategy: str | None = None
    horizon: str | None = None
    difference: float | None = None
    ci_lo: float | None = None
    ci_hi: float | None = None
    q_value: float | None = None


class TagVerdict(BaseModel):
    tag: str
    family: Literal["hedge", "opportunity"] | None
    kind: Kind
    label: Label
    evidence: Evidence
    note: str


def results_dir() -> Path:
    env = os.environ.get("RESULTS_DIR")
    return Path(env) if env else DEFAULT_RESULTS_DIR


def _f(x) -> float | None:
    return None if pd.isna(x) else float(x)


class VerdictBook:
    def __init__(self, family_verdict: dict[str, str], pass_check: dict[str, pd.DataFrame], atlas: pd.DataFrame | None):
        self.family_verdict = family_verdict
        self.pass_check = pass_check
        self.atlas = atlas

    def tags(self) -> list[str]:
        out = set(H1_TAGS) | set(H2_TAGS)
        if self.atlas is not None and len(self.atlas):
            out |= set(self.atlas["tag"].astype(str))
        return sorted(out)

    def _confirmatory(self, tag: str, family: str) -> TagVerdict:
        passed = self.family_verdict.get(family, "NULL").strip().lower() == "passed"
        ev = Evidence(strategy=ATLAS_STRATEGY[family])
        chk = self.pass_check.get(family)
        if chk is not None and len(chk):
            ok = chk[chk["pnl_ok"].astype(bool)] if "pnl_ok" in chk else chk.iloc[0:0]
            row = (ok if len(ok) else chk).iloc[0]
            ev = Evidence(strategy=ATLAS_STRATEGY[family], horizon=str(row["horizon"]),
                          difference=_f(row["pnl_difference"]), ci_lo=_f(row["ci_lo"]), ci_hi=_f(row["ci_hi"]))
        verdict = self.family_verdict.get(family, "NULL").strip()
        return TagVerdict(tag=tag, family=family, kind="confirmatory", label=family if passed else "no_edge",
                          evidence=ev, note=f"Confirmatory {family} family verdict (in-sample): {verdict}.")

    def _exploratory(self, tag: str) -> TagVerdict:
        a = self.atlas[self.atlas["tag"].astype(str) == tag]
        if a.empty:
            raise KeyError(tag)
        best: tuple[int, str, pd.Series | None] = (-1, "", None)
        for family, strat in ATLAS_STRATEGY.items():
            s = a[a["strategy"] == strat]
            hit = s[(s["q_value"] < ATLAS_Q) & (s["difference"] > 0)]
            if len(hit) >= ATLAS_MIN_HORIZONS and len(hit) > best[0]:
                best = (len(hit), family, hit.sort_values("q_value").iloc[0])
        if best[2] is not None:
            r, family = best[2], best[1]
            return TagVerdict(tag=tag, family=None, kind="exploratory", label=family,  # type: ignore[arg-type]
                              evidence=Evidence(strategy=r["strategy"], horizon=str(r["horizon"]), difference=_f(r["difference"]),
                                                ci_lo=_f(r["ci_lo"]), ci_hi=_f(r["ci_hi"]), q_value=_f(r["q_value"])),
                              note=f"Exploratory atlas ({best[0]} horizons with q<{ATLAS_Q}). Not confirmatory.")
        r = a.sort_values("q_value").iloc[0]
        return TagVerdict(tag=tag, family=None, kind="exploratory", label="no_edge",
                          evidence=Evidence(strategy=str(r["strategy"]), horizon=str(r["horizon"]), difference=_f(r["difference"]),
                                            ci_lo=_f(r["ci_lo"]), ci_hi=_f(r["ci_hi"]), q_value=_f(r["q_value"])),
                          note="Exploratory atlas: no strategy clears q<0.10 at 2 horizons. Not confirmatory.")

    def for_tag(self, tag: str) -> TagVerdict:
        if tag in H1_TAGS:
            return self._confirmatory(tag, "hedge")
        if tag in H2_TAGS:
            return self._confirmatory(tag, "opportunity")
        if self.atlas is None:
            return TagVerdict(tag=tag, family=None, kind="none", label="no_edge", evidence=Evidence(), note="not tested")
        return self._exploratory(tag)

    def all(self) -> list[TagVerdict]:
        return [self.for_tag(t) for t in self.tags()]


def load_verdicts(results_dir: Path) -> VerdictBook:
    results_dir = Path(results_dir)
    ins = results_dir / "in_sample"
    fv: dict[str, str] = {}
    pc: dict[str, pd.DataFrame] = {}
    for fam in ("hedge", "opportunity"):
        p = ins / f"{fam}_verdict.txt"
        fv[fam] = p.read_text().strip() if p.exists() else "NULL"
        c = ins / f"{fam}_pass_check.csv"
        if c.exists():
            pc[fam] = pd.read_csv(c)
    ap = results_dir / "atlas" / "atlas.csv"
    atlas = pd.read_csv(ap) if ap.exists() else None
    return VerdictBook(fv, pc, atlas)


router = APIRouter()


def _book(request: Request) -> VerdictBook:
    return load_verdicts(results_dir())


@router.get("/verdicts", response_model=list[TagVerdict])
def list_verdicts(request: Request) -> list[TagVerdict]:
    return _book(request).all()


@router.get("/verdicts/{tag}", response_model=TagVerdict)
def get_verdict(tag: str, request: Request) -> TagVerdict:
    try:
        return _book(request).for_tag(tag)
    except KeyError:
        raise HTTPException(404, f"Unknown tag {tag}.")
