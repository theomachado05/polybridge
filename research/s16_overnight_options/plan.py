"""S16 plan: which ticker-days are events and which sessions are their controls. Odds and the calendar only; no option
price is read here (METHOD.md sections 1, 2, 9, 10)."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s5_big_moves.run import CACHE as S5_CACHE
from s8_open_referee.run import links

from . import config as cfg
from . import engine as eg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / ".cache"
MORNINGS = RESEARCH / "results" / "s8_open_referee" / "mornings.csv"
BAR_S = 300


class Ctx:
    """Sessions and the underlying's five-minute bars."""

    def __init__(self):
        spy = dict(np.load(S5_CACHE / "eq_SPY.npz"))
        self.sess = en.sessions_from(spy["t"])
        self.days = list(self.sess.day)
        self.idx = {d: i for i, d in enumerate(self.days)}
        self.op = self.sess.open.to_numpy().astype(np.int64)
        self.cl = self.sess.close.to_numpy().astype(np.int64)
        self.weekend = np.concatenate([[False], (self.op[1:] - self.cl[:-1]) > 40 * 3600])
        self._bars: dict[str, dict | None] = {}

    def bars(self, tk: str) -> dict | None:
        if tk not in self._bars:
            self._bars[tk] = None
            for c in (CACHE, S5_CACHE, d4.CACHE):      # this study's own pull first (KRE and XLF, amendment 2)
                f = c / f"eq_{tk}.npz"
                if f.exists():
                    b = dict(np.load(f))
                    if len(b["t"]):
                        self._bars[tk] = b
                        break
        return self._bars[tk]

    def first_price(self, tk: str, i: int) -> float | None:
        """The open of the first five-minute bar of session i, if it starts within 10 minutes of the open."""
        b = self.bars(tk)
        if b is None:
            return None
        a = int(np.searchsorted(b["t"], self.op[i]))
        if a >= len(b["t"]) or b["t"][a] - self.op[i] > cfg.OPEN_BAR_MAX_LATE_S or b["t"][a] >= self.cl[i]:
            return None
        return float(b["o"][a])

    def price_at(self, tk: str, at: int) -> float:
        """The close of the last five-minute bar that ended at or before `at` (at most 15 minutes earlier)."""
        b = self.bars(tk)
        if b is None:
            return float("nan")
        j = int(np.searchsorted(b["t"] + BAR_S, at, side="right")) - 1
        if j < 0 or at - (b["t"][j] + BAR_S) > 900:
            return float("nan")
        return float(b["c"][j])

    def instants(self, i: int) -> dict[str, int]:
        """Epoch of every instant of session i. "15:55" is five minutes before that session's close (amendment 1)."""
        o = int(self.op[i])
        return {"prev": int(self.cl[i - 1]) - 300, "0931": o + 60, "0935": o + 300, "0945": o + 900, "1000": o + 1800, "1030": o + 3600,
                "close": int(self.cl[i]) - 300}


def night_moves(ctx: Ctx, market: str, cache: Path) -> np.ndarray | None:
    """Overnight move of a question in points, per session (previous close to 09:29), as S8 measures it."""
    f = cache / f"pm_{market.split(':')[1]}.npz"
    if not f.exists():
        return None
    pm = np.load(f)
    if len(pm["t"]) == 0:
        return None
    t, p = pm["t"], pm["p"].astype(float)
    prev = np.concatenate([[0], ctx.cl[:-1]]).astype(np.int64)
    x = 100.0 * (asof((ctx.op - 60).astype(np.int64), t, p, cfg.PM_MAX_AGE_S) - asof(prev, t, p, cfg.PM_MAX_AGE_S))
    x[0] = np.nan
    return x


def _maxabs(arrs: list[np.ndarray], n: int) -> np.ndarray:
    out = np.zeros(n)
    for a in arrs:
        out = np.maximum(out, np.where(np.isfinite(a), np.abs(a), 0.0))
    return out


def build_plan() -> tuple[list[dict], Ctx, dict]:
    ctx = Ctx()
    n = len(ctx.days)
    L = links()
    moves: dict[str, np.ndarray] = {}
    for l in L:
        if l["market"] not in moves:
            x = night_moves(ctx, l["market"], S5_CACHE if l["source"] == "S5" else d4.CACHE)
            if x is not None:
                moves[l["market"]] = x
    by_ticker: dict[str, list[np.ndarray]] = {}
    for l in L:
        if l["market"] in moves:
            by_ticker.setdefault(l["ticker"], []).append(moves[l["market"]])
    tick_max = {tk: _maxabs(a, n) for tk, a in by_ticker.items()}

    def tmax(tk):
        return tick_max.get(tk, np.zeros(n))

    mornings = pd.read_csv(MORNINGS)
    ev10 = eg.expand(mornings, cfg.MAIN_THRESHOLD)
    ev5 = eg.expand(mornings, cfg.LOOSE_THRESHOLD)
    key10 = set(zip(ev10.ticker, ev10.day))
    extra = ev5[[(t, d) not in key10 for t, d in zip(ev5.ticker, ev5.day)]]
    plan: list[dict] = []

    def item(tier, sample, kind, tk, i, ev, full, event_day=None):
        return {"tier": tier, "sample": sample, "kind": kind, "ticker": tk, "day": ctx.days[i], "i": int(i), "event_day": event_day or ctx.days[i],
                "x": float(ev["x"]), "direction": int(ev["direction"]), "market": ev["market"], "question": ev["question"],
                "weekend": bool(ctx.weekend[ctx.idx[event_day or ctx.days[i]]]),
                "segment": "OOS" if (event_day or ctx.days[i]) >= cfg.OOS_FROM else "IS", "full": bool(full), "need_prev": bool(full and kind == "event")}

    def add(tier, sample, tk, evs: pd.DataFrame, quiet: set[int], used: set[int], full: bool):
        evs = evs[evs.day.isin(ctx.idx)]
        idx = [ctx.idx[d] for d in evs.day if ctx.idx[d] >= 1]
        m = eg.match_controls(idx, quiet, used)
        for ev in evs.to_dict("records"):
            i = ctx.idx[ev["day"]]
            if i < 1:
                continue
            plan.append(item(tier, sample, "event", tk, i, ev, full))
            if i in m:
                plan.append(item(tier, sample, "control", tk, m[i], ev, full, event_day=ev["day"]))

    # ---- tiers 1 and 5: the main sample, then the extra events of V3
    for tk in sorted(set(ev5.ticker)):
        e5 = {ctx.idx[d] for d in ev5[ev5.ticker == tk].day if d in ctx.idx}
        quiet = {i for i in range(1, n) if tmax(tk)[i] < cfg.QUIET_BELOW and i not in e5}
        used: set[int] = set()
        add(1, "main", tk, ev10[ev10.ticker == tk], quiet, used, True)
        add(5, "v3extra", tk, extra[extra.ticker == tk], quiet, used, False)

    # ---- tier 2: Brazil
    bz = {m: night_moves(ctx, m, d4.CACHE) for m in cfg.BRAZIL_MARKETS}
    bz = {m: x for m, x in bz.items() if x is not None}
    q_bz = {m: l["question"] for l in d4.proposer_links() for m in [l["market"]] if m in cfg.BRAZIL_MARKETS}
    rows = []
    for i in range(1, n):
        best = None
        for m, x in sorted(bz.items()):
            if np.isfinite(x[i]) and abs(x[i]) >= cfg.LOOSE_THRESHOLD and (best is None or abs(x[i]) > abs(best[1])):
                best = (m, float(x[i]))
        if best:
            rows.append({"day": ctx.days[i], "ticker": cfg.BRAZIL_TICKER, "x": best[1], "direction": int(np.sign(best[1])) * cfg.BRAZIL_MARKETS[best[0]],
                         "market": best[0], "question": q_bz.get(best[0], ""), "weekend": bool(ctx.weekend[i])})
    bz_ev = pd.DataFrame(rows)
    bz_max = np.maximum(_maxabs(list(bz.values()), n), tmax(cfg.BRAZIL_TICKER))
    bz_idx = {ctx.idx[d] for d in bz_ev.day} if len(bz_ev) else set()
    add(2, "brazil", cfg.BRAZIL_TICKER, bz_ev, {i for i in range(1, n) if bz_max[i] < cfg.QUIET_BELOW and i not in bz_idx}, set(), True)

    # ---- tier 4: Fed and banks (straddles only; direction is not used)
    rx = re.compile(cfg.FED_REGEX, re.I)
    fed = sorted({l["market"] for l in L if rx.search(l["question"])})
    fm = mornings[mornings.market.isin(fed)].assign(ax=lambda d: d.x.abs()).sort_values(["day", "ax"], ascending=[True, False]).drop_duplicates("day")
    fed_max = _maxabs([moves[m] for m in fed if m in moves], n)
    fed_idx = {ctx.idx[d] for d in fm.day if d in ctx.idx}
    for tk in cfg.FED_TICKERS:
        evs = pd.DataFrame([{"day": r.day, "ticker": tk, "x": float(r.x), "direction": 0, "market": r.market, "question": r.question,
                             "weekend": bool(r.weekend)} for r in fm.itertuples()])
        quiet = {i for i in range(1, n) if fed_max[i] < cfg.QUIET_BELOW and tmax(tk)[i] < cfg.QUIET_BELOW and i not in fed_idx}
        add(4, "fed", tk, evs, quiet, set(), False)

    # ---- order: tiers 1 and 2 by event date; tiers 4 and 5 in a seeded shuffle of events (a control follows its event)
    def groups(tier):
        g: dict[tuple, list[dict]] = {}
        for p in plan:
            if p["tier"] == tier:
                g.setdefault((p["event_day"], p["ticker"]), []).append(p)
        return g

    ordered: list[dict] = []
    for tier in (1, 2, 4, 5):
        g = groups(tier)
        ks = sorted(g)
        if tier in (4, 5):
            rng = np.random.default_rng(cfg.TIER_SEED + tier)
            ks = [ks[j] for j in rng.permutation(len(ks))]
        for k in ks:
            ordered += sorted(g[k], key=lambda p: p["kind"] != "event")
    meta = {"sessions": n, "first_session": ctx.days[0], "last_session": ctx.days[-1], "links": len(L), "fed_markets": len(fed),
            "fed_dates": int(len(fm)), "main_events": int(len(ev10)), "v3_extra_events": int(len(extra)), "brazil_events": int(len(bz_ev)),
            "main_event_dates": int(ev10.day.nunique()), "oos_from_check": eg.oos_from(list(ev10.day))}
    return ordered, ctx, meta
