from __future__ import annotations

import csv
import io
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config as cfg

ET = ZoneInfo(cfg.TZ)
NAN = float("nan")


def snapshot_epoch(open_day: str) -> float:
    return pd.Timestamp(f"{open_day} {cfg.SNAPSHOT_HM}", tz=ET).timestamp()


def fee(x: float, c: float = 1.0) -> float:
    return c * cfg.T2_FEE_RATE * x * (1.0 - x) if 0.0 < x < 1.0 else 0.0


def clip(x: float) -> float:
    return min(max(x, cfg.PRICE_CLIP[0]), cfg.PRICE_CLIP[1])


def window_of(m: float, windows=cfg.T1_WINDOWS) -> str | None:
    for name, lo, hi in windows:
        if lo <= m < hi:
            return name
    return None


def yes_prints(prints: list[dict], t0: float, window_s: float = cfg.T2_WINDOW_S) -> list[dict]:
    rows = []
    for i, t in enumerate(prints):
        ts = t.get("timestamp")
        if ts is None:
            continue
        ts = float(ts)
        if not (t0 <= ts <= t0 + window_s):
            continue
        px, sd, out = float(t["price"]), str(t.get("side", "")).upper(), str(t.get("outcome", "")).lower()
        if sd not in ("BUY", "SELL"):
            continue
        if out == "yes":
            ypx, ysd = px, sd
        elif out == "no":
            ypx, ysd = 1.0 - px, ("BUY" if sd == "SELL" else "SELL")
        else:
            continue
        rows.append({"ts": ts, "order": -i, "px": ypx, "side": ysd, "size": float(t.get("size") or 0.0)})
    rows.sort(key=lambda r: (r["ts"], r["order"]))
    return rows


def edge(side: str, entry: float, lo: float, hi: float, c: float = 1.0) -> float:
    return (entry - fee(entry, c) - hi) if side == "sell YES" else (lo - entry - fee(entry, c))


def replay(rows: list[dict], side: str, lo: float, hi: float, c: float = 1.0, mode: str = "best") -> dict:
    need = "SELL" if side == "sell YES" else "BUY"
    sgn = -1.0 if side == "sell YES" else 1.0
    cand = [r for r in rows if r["side"] == need and r["size"] > 0]
    out = {"status": "no print on the side", "side_prints": len(cand), "print_px": NAN, "entry": NAN, "edge": NAN,
           "print_size": 0.0, "print_ts": NAN}
    if not cand:
        return out
    if mode == "best":
        best = max(r["px"] for r in cand) if side == "sell YES" else min(r["px"] for r in cand)
        at = [r for r in cand if abs(r["px"] - best) < 1e-9]
        entry = clip(best + sgn * c * cfg.T2_SLIP)
        e = edge(side, entry, lo, hi, c)
        out.update(print_px=best, entry=entry, edge=e, print_size=sum(r["size"] for r in at), print_ts=at[0]["ts"],
                   status="trade" if e >= cfg.T2_THETA - 1e-12 else "print, gap gone")
        return out
    if mode == "first":
        for r in cand:
            entry = clip(r["px"] + sgn * c * cfg.T2_SLIP)
            e = edge(side, entry, lo, hi, c)
            if e >= cfg.T2_THETA - 1e-12:
                out.update(print_px=r["px"], entry=entry, edge=e, print_size=r["size"], print_ts=r["ts"], status="trade")
                return out
        out.update(status="print, gap gone")
        return out
    raise ValueError(mode)


def pnl_per_contract(side: str, entry: float, outcome: float, c: float = 1.0) -> float:
    return (entry - fee(entry, c) - outcome) if side == "sell YES" else (outcome - entry - fee(entry, c))


def capital_per_contract(side: str, entry: float) -> float:
    return entry if side == "buy YES" else 1.0 - entry


def partner_net(side: str, px: float, y: float, enabled: bool, rate: float, exp: float, c: float = 1.0) -> float:
    q = px if side == "BUY" else 1.0 - px
    win = y if side == "BUY" else 1.0 - y
    f = rate * (q * (1.0 - q)) ** exp if (enabled and 0.0 < q < 1.0) else 0.0
    return win - (q + c * cfg.T1_TICK) - c * f


def boot_mean(values, clusters) -> dict:
    v, cl = np.asarray(values, float), np.asarray(clusters)
    if len(v) == 0:
        return {"n": 0, "closures": 0, "mean": NAN, "lo": NAN, "hi": NAN}
    keys, inv = np.unique(cl, return_inverse=True)
    out = {"n": int(len(v)), "closures": int(len(keys)), "mean": float(v.mean()), "lo": NAN, "hi": NAN}
    if len(keys) < cfg.MIN_CLUSTERS_FOR_INTERVAL:
        return out
    s, n = np.bincount(inv, weights=v, minlength=len(keys)), np.bincount(inv, minlength=len(keys)).astype(float)
    pick = np.random.default_rng(cfg.BOOT_SEED).integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    means = s[pick].sum(axis=1) / n[pick].sum(axis=1)
    out["lo"], out["hi"] = (float(x) for x in np.percentile(means, [2.5, 97.5]))
    return out


def boot_diff(va, ca, vb, cb) -> dict:
    va, vb, ca, cb = np.asarray(va, float), np.asarray(vb, float), np.asarray(ca), np.asarray(cb)
    if len(va) == 0 or len(vb) == 0:
        return {"diff": NAN, "lo": NAN, "hi": NAN, "dropped": 0, "closures": 0}
    keys = np.unique(np.concatenate([ca, cb]))
    ia, ib = np.searchsorted(keys, ca), np.searchsorted(keys, cb)
    sa, na = np.bincount(ia, weights=va, minlength=len(keys)), np.bincount(ia, minlength=len(keys)).astype(float)
    sb, nb = np.bincount(ib, weights=vb, minlength=len(keys)), np.bincount(ib, minlength=len(keys)).astype(float)
    out = {"diff": float(va.mean() - vb.mean()), "lo": NAN, "hi": NAN, "dropped": 0, "closures": int(len(keys))}
    if len(keys) < cfg.MIN_CLUSTERS_FOR_INTERVAL:
        return out
    pick = np.random.default_rng(cfg.BOOT_SEED).integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    A, B = na[pick].sum(axis=1), nb[pick].sum(axis=1)
    ok = (A > 0) & (B > 0)
    d = sa[pick].sum(axis=1)[ok] / A[ok] - sb[pick].sum(axis=1)[ok] / B[ok]
    out["lo"], out["hi"] = (float(x) for x in np.percentile(d, [2.5, 97.5]))
    out["dropped"] = int((~ok).sum())
    return out


def closure_sharpe(pnl_by_closure: dict[str, float], capital_by_closure: dict[str, float], calendar: list[str]) -> dict:
    K = max(capital_by_closure.values()) if capital_by_closure else 0.0
    if K <= 0 or len(calendar) < 3:
        return {"sharpe": NAN, "capital_base": K, "max_drawdown": NAN, "total_return": NAN, "worst_month": NAN, "per_closure_sharpe": NAN}
    r = np.array([pnl_by_closure.get(d, 0.0) for d in calendar]) / K
    sd = float(np.std(r, ddof=1))
    e = np.concatenate([[0.0], np.cumsum(r)])
    months: dict[str, float] = {}
    for x, d in zip(r, calendar):
        months[d[:7]] = months.get(d[:7], 0.0) + float(x)
    per = float(np.mean(r) / sd) if sd > 0 else NAN
    return {"sharpe": per * math.sqrt(cfg.CLOSURES_PER_YEAR) if sd > 0 else NAN, "capital_base": K,
            "max_drawdown": float(np.max(np.maximum.accumulate(e) - e)), "total_return": float(e[-1]),
            "worst_month": min(months.values()), "per_closure_sharpe": per}


def book(trades: list[dict], calendar: list[str]) -> dict:
    if not trades:
        return {"trades": 0, "closures_traded": 0, "calendar_closures": len(calendar), "mean": NAN, "lo": NAN, "hi": NAN, "total": 0.0,
                "hit_rate": NAN, "sharpe": NAN, "capital_base": 0.0, "max_drawdown": NAN, "total_return": NAN, "worst_month": NAN,
                "per_closure_sharpe": NAN, "printed_dollars": 0.0, "printed_dollars_uncapped": 0.0, "capital_deployed": 0.0,
                "best_closure": "", "best_closure_pnl": NAN}
    pnl = [t["pnl"] for t in trades]
    b = boot_mean(pnl, [t["closure"] for t in trades])
    by_p, by_c = {}, {}
    for t in trades:
        by_p[t["closure"]] = by_p.get(t["closure"], 0.0) + t["pnl"]
        by_c[t["closure"]] = by_c.get(t["closure"], 0.0) + t["capital"]
    best = max(by_p, key=by_p.get)
    return {"trades": len(trades), "closures_traded": len(by_p), "calendar_closures": len(calendar), "mean": b["mean"], "lo": b["lo"],
            "hi": b["hi"], "total": float(sum(pnl)), "hit_rate": float(np.mean([p > 0 for p in pnl])),
            **closure_sharpe(by_p, by_c, calendar),
            "printed_dollars": float(sum(t.get("printed", 0.0) for t in trades)),
            "printed_dollars_uncapped": float(sum(t.get("printed_uncapped", 0.0) for t in trades)),
            "capital_deployed": float(sum(t["capital"] for t in trades)), "best_closure": best, "best_closure_pnl": float(by_p[best])}


def without_best(trades: list[dict], calendar: list[str]) -> tuple[list[dict], list[str], str]:
    by_p: dict[str, float] = {}
    for t in trades:
        by_p[t["closure"]] = by_p.get(t["closure"], 0.0) + t["pnl"]
    if not by_p:
        return [], calendar, ""
    best = max(by_p, key=by_p.get)
    return [t for t in trades if t["closure"] != best], [d for d in calendar if d != best], best


def write_csv(path: Path, recs: list[dict]) -> None:
    keys: list[str] = []
    for rec in recs:
        for k in rec:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(recs)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cfg.REPO, check=True).stdout


def segments(calendar: list[str]) -> dict[str, list[str]]:
    return {"IS": [d for d in calendar if d < cfg.OOS_FROM], "OOS": [d for d in calendar if d >= cfg.OOS_FROM], "ALL": list(calendar)}


def load_partner() -> pd.DataFrame:
    blob = git("rev-parse", f"{cfg.PARTNER_COMMIT}:{cfg.PARTNER_TRADES}").strip()
    if blob != cfg.PARTNER_TRADES_BLOB:
        raise SystemExit(f"partner trades blob {blob} is not the pre-registered {cfg.PARTNER_TRADES_BLOB}")
    d = pd.read_csv(io.StringIO(git("show", f"{cfg.PARTNER_COMMIT}:{cfg.PARTNER_TRADES}")), dtype={"market_id": str})
    t0 = d.open_day.map(snapshot_epoch)
    d["minutes"] = (d.ts - t0) / 60.0
    d["window"] = d.minutes.map(window_of)
    d["clock_minute"] = np.floor(d.minutes)
    for c in cfg.COST_MULTIPLIERS:
        d[f"net_{int(c)}x"] = [partner_net(a.side, a.px, a.y, bool(a.fee_enabled), a.fee_rate, a.fee_exp, c) for a in d.itertuples()]
    worst = float(np.abs(d["net_1x"] - d[cfg.T1_PNL]).max())
    if worst > 1e-9:
        raise SystemExit(f"the 1x recomputation does not reproduce {cfg.T1_PNL}: worst gap {worst}")
    d["q"] = np.where(d.side == "BUY", d.px, 1.0 - d.px)
    return d


def t1(d: pd.DataFrame, calendar: list[str]) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    seg = segments(calendar)

    def add(variant: str, x: pd.DataFrame, col: str, groups: list[tuple[str, pd.Series]], early: str, later: str, cost: float):
        for sname, days in seg.items():
            xs = x[x.open_day.isin(days)]
            got = {}
            for gname, mask in groups:
                g = xs[mask.reindex(xs.index)]
                got[gname] = g
                b = boot_mean(100 * g[col], g.open_day)
                rows.append({"test": "T1", "variant": variant, "segment": sname, "cost_mult": cost, "group": gname, "unit": "points per contract",
                             "trades": b["n"], "closures": b["closures"], "mean": b["mean"], "lo": b["lo"], "hi": b["hi"],
                             "hit_rate": float((g[col] > 0).mean()) if len(g) else NAN,
                             "print_dollars": float((g["size"] * (g.q + cfg.T1_TICK)).sum()),
                             "median_print_shares": float(g["size"].median()) if len(g) else NAN})
            for gname in got:
                if gname == early:
                    continue
                df = boot_diff(100 * got[early][col], got[early].open_day, 100 * got[gname][col], got[gname].open_day)
                rows.append({"test": "T1", "variant": variant, "segment": sname, "cost_mult": cost, "group": f"{early} minus {gname}",
                             "unit": "points per contract", "trades": len(got[early]) + len(got[gname]), "closures": df["closures"],
                             "mean": df["diff"], "lo": df["lo"], "hi": df["hi"], "dropped_draws": df["dropped"]})

    def by_window(x):
        g = [(name, x.window == name) for name, _, _ in cfg.T1_WINDOWS]
        return g + [("15+", x.minutes >= 15.0)]

    p = d[np.isclose(d.tau, cfg.T1_TAU)]
    add("primary (tau 0.05, exact seconds)", p, "net_1x", by_window(p), "0-15", "15+", 1.0)
    add("2x costs", p, "net_2x", by_window(p), "0-15", "15+", 2.0)
    for tau in cfg.T1_VARIANT_TAUS:
        x = d[np.isclose(d.tau, tau)]
        add(f"tau {tau:.2f}", x, "net_1x", by_window(x), "0-15", "15+", 1.0)
    add("first 30 minutes", p, "net_1x", [("0-30", p.minutes < cfg.T1_VARIANT_FIRST_MIN), ("30+", p.minutes >= cfg.T1_VARIANT_FIRST_MIN)], "0-30", "30+", 1.0)
    dly = p[p.kind == cfg.T1_VARIANT_KIND]
    add("daily markets only", dly, "net_1x", by_window(dly), "0-15", "15+", 1.0)
    cm = p.clock_minute
    add("whole clock minutes (through 10:00:59)", p, "net_1x",
        [("0-15", cm <= 15), ("15-60", (cm > 15) & (cm <= 60)), ("60-180", (cm > 60) & (cm <= 180)), ("180+", cm > 180), ("15+", cm > 15)], "0-15", "15+", 1.0)

    def pick(variant, segment, group):
        return next(r for r in rows if (r["variant"], r["segment"], r["group"]) == (variant, segment, group))
    pv = "primary (tau 0.05, exact seconds)"
    e_all, e_is, e_oos, h2 = pick(pv, "ALL", "0-15"), pick(pv, "IS", "0-15"), pick(pv, "OOS", "0-15"), pick(pv, "ALL", "0-15 minus 15+")
    verdict = {"H1": bool(e_all["mean"] > 0 and e_all["lo"] > 0), "H2": bool(h2["mean"] > 0 and h2["lo"] > 0),
               "earlier_80pct_above_zero": bool(e_is["mean"] > 0), "recent_20pct_above_zero": bool(e_oos["mean"] > 0) if e_oos["trades"] else False,
               "recent_trades": int(e_oos["trades"]), "recent_trades_needed": cfg.T1_MIN_RECENT_TRADES}
    verdict["pass"] = bool(verdict["H1"] and verdict["earlier_80pct_above_zero"] and verdict["recent_20pct_above_zero"]
                           and verdict["recent_trades"] >= cfg.T1_MIN_RECENT_TRADES)
    return rows, verdict


def t1_book(d: pd.DataFrame) -> list[dict]:
    p = d[np.isclose(d.tau, cfg.T1_TAU) & (d.window == cfg.T1_EARLY)]
    return [{"closure": a.open_day, "pnl": a.net_1x, "capital": a.q + cfg.T1_TICK, "printed": a.size * (a.q + cfg.T1_TICK),
             "printed_uncapped": a.size * (a.q + cfg.T1_TICK)} for a in p.itertuples()]


def load_s6() -> pd.DataFrame:
    s = pd.read_csv(cfg.S6_TRADES)
    return s[(s.variant == cfg.S6_PRIMARY) & (s.cost_mult == cfg.S6_COST_MULT)].reset_index(drop=True)


def t2(s6: pd.DataFrame) -> tuple[list[dict], dict]:
    recs, meta = [], {"cache_files_read": 0, "cache_missing": 0, "largest_cache_file": 0}
    cache: dict[int, list[dict]] = {}
    for mid in sorted(set(int(m) for m in s6.market_id)):
        f = cfg.S6_PRINTS / f"prints_{mid}.json"
        if not f.exists():
            meta["cache_missing"] += 1
            continue
        cache[mid] = json.loads(f.read_text())
        meta["cache_files_read"] += 1
        meta["largest_cache_file"] = max(meta["largest_cache_file"], len(cache[mid]))
        if len(cache[mid]) >= cfg.PRINT_PAGE_CAP:
            raise SystemExit(f"prints_{mid}.json is at the page cap: its history is cut off")
    for r in s6.itertuples():
        ps = cache.get(int(r.market_id))
        rows = yes_prints(ps, snapshot_epoch(r.closure)) if ps is not None else []
        for mode in ("best", "first"):
            for c in cfg.COST_MULTIPLIERS:
                x = replay(rows, r.side, float(r.opt_lo), float(r.opt_hi), c, mode)
                n = min(x["print_size"], cfg.T2_MAX_CONTRACTS) if x["status"] == "trade" else 0.0
                ppc = pnl_per_contract(r.side, x["entry"], float(r.outcome), c) if x["status"] == "trade" else NAN
                cpc = capital_per_contract(r.side, x["entry"]) if x["status"] == "trade" else NAN
                recs.append({"test": "T2", "mode": mode, "cost_mult": c, "segment": "OOS" if r.closure >= cfg.OOS_FROM else "IS",
                             "closure": r.closure, "market_id": int(r.market_id), "question": r.question, "underlying": r.underlying,
                             "kind": r.kind, "side": r.side, "pm_0945": float(r.pm_0945), "opt_lo": float(r.opt_lo), "opt_hi": float(r.opt_hi),
                             "s6_entry": float(r.entry), "s6_pnl": float(r.pnl), "s6_verified": bool(r.verified),
                             "status": x["status"] if ps is not None else "no cache", "window_prints": len(rows), "side_prints": x["side_prints"],
                             "print_px": x["print_px"], "print_minutes": (x["print_ts"] - snapshot_epoch(r.closure)) / 60.0 if x["print_ts"] == x["print_ts"] else NAN,
                             "entry": x["entry"], "edge_vs_options": x["edge"], "print_size": x["print_size"], "contracts": n, "outcome": float(r.outcome),
                             "pnl_per_contract": ppc, "pnl": n * ppc if n else 0.0, "capital": n * cpc if n else 0.0,
                             "printed": n * cpc if n else 0.0, "printed_uncapped": x["print_size"] * cpc if n else 0.0})
    return recs, meta


def t2_metrics(recs: list[dict], calendar: list[str]) -> tuple[list[dict], dict]:
    rows = []
    seg = segments(calendar)
    for mode in ("best", "first"):
        for c in cfg.COST_MULTIPLIERS:
            sub = [t for t in recs if t["mode"] == mode and t["cost_mult"] == c]
            tr = [t for t in sub if t["status"] == "trade"]
            base = {"test": "T2", "variant": f"{'T2' if mode == 'best' else 'T2b first print'}{'' if c == 1.0 else ', 2x costs'}", "cost_mult": c,
                    "unit": "dollars per trade", "entries": len(sub), "entries_with_window_print": sum(t["window_prints"] > 0 for t in sub),
                    "entries_with_side_print": sum(t["side_prints"] > 0 for t in sub)}
            for sname, days in seg.items():
                st = [t for t in tr if t["closure"] in set(days)]
                pc = boot_mean([100 * t["pnl_per_contract"] for t in st], [t["closure"] for t in st])
                rows.append({**base, "segment": sname, "group": "all", **book(st, days), "points_per_contract": pc["mean"], "points_lo": pc["lo"],
                             "points_hi": pc["hi"], "contracts": float(sum(t["contracts"] for t in st))})
            nb, cal_nb, best = without_best(tr, calendar)
            pc = boot_mean([100 * t["pnl_per_contract"] for t in nb], [t["closure"] for t in nb])
            rows.append({**base, "segment": "ALL", "group": f"best closure removed ({best})", **book(nb, cal_nb), "points_per_contract": pc["mean"],
                         "points_lo": pc["lo"], "points_hi": pc["hi"], "contracts": float(sum(t["contracts"] for t in nb))})
            for key in ("side", "kind"):
                for val in sorted({t[key] for t in tr}):
                    st = [t for t in tr if t[key] == val]
                    pc = boot_mean([100 * t["pnl_per_contract"] for t in st], [t["closure"] for t in st])
                    rows.append({**base, "segment": "ALL", "group": f"{key}: {val}", **book(st, calendar), "points_per_contract": pc["mean"],
                                 "points_lo": pc["lo"], "points_hi": pc["hi"], "contracts": float(sum(t["contracts"] for t in st))})

    def pick(variant, segment, group_prefix):
        return next(r for r in rows if r["variant"] == variant and r["segment"] == segment and r["group"].startswith(group_prefix))
    a, nb, fb = pick("T2", "ALL", "all"), pick("T2", "ALL", "best closure removed"), pick("T2b first print", "ALL", "all")
    verdict = {"mean_above_zero": bool(a["mean"] > 0), "interval_excludes_zero": bool(a["lo"] > 0) if a["lo"] == a["lo"] else False,
               "above_zero_without_best_closure": bool(nb["mean"] > 0) if nb["trades"] else False,
               "t2b_above_zero": bool(fb["mean"] > 0) if fb["trades"] else False}
    verdict["pass"] = bool(verdict["mean_above_zero"] and verdict["interval_excludes_zero"] and verdict["above_zero_without_best_closure"])
    verdict["pass_rests_on_hindsight"] = bool(verdict["pass"] and not verdict["t2b_above_zero"])
    return rows, verdict


def staircase(s6: pd.DataFrame, t2_recs: list[dict], calendar: list[str]) -> list[dict]:
    modelled = [{"closure": r.closure, "pnl": float(r.pnl), "capital": float(r.capital),
                 "printed": min(float(r.verify_size), cfg.T2_MAX_CONTRACTS) * float(r.capital) / 100.0 if r.verified else 0.0,
                 "printed_uncapped": float(r.verify_size) * float(r.capital) / 100.0 if r.verified else 0.0} for r in s6.itertuples()]
    verified = [{"closure": r.closure, "pnl": float(r.pnl_verified), "capital": min(float(r.verify_size), cfg.T2_MAX_CONTRACTS) * float(r.capital) / 100.0,
                 "printed": min(float(r.verify_size), cfg.T2_MAX_CONTRACTS) * float(r.capital) / 100.0,
                 "printed_uncapped": float(r.verify_size) * float(r.capital) / 100.0} for r in s6.itertuples() if r.verified]
    printed = [t for t in t2_recs if t["mode"] == "best" and t["cost_mult"] == 1.0 and t["status"] == "trade"]
    v_nb, v_cal, v_best = without_best(verified, calendar)
    p_nb, p_cal, p_best = without_best(printed, calendar)
    steps = [("1. S6 as modelled", modelled, calendar), ("2. S6 at printed prices (T2)", printed, calendar),
             ("3. S6's own print-verified set", verified, calendar),
             (f"4. Verified set, best closure removed ({v_best})", v_nb, v_cal),
             (f"5. T2, best closure removed ({p_best})", p_nb, p_cal)]
    return [{"step": name, **book(tr, cal)} for name, tr, cal in steps]


INK, INK2, GRID, SURF, BLUE, GREY = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#2a78d6", "#a8a69d"


def _style(ax, title: str, ylabel: str):
    ax.set_facecolor(SURF)
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)
    ax.set_ylabel(ylabel, fontsize=9, color=INK2)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.axhline(0, color=INK2, linewidth=0.8)


def charts(t1_rows: list[dict], stairs: list[dict], books: dict[str, tuple[list[dict], bool, str]], calendar: list[str]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [n for n, _, _ in cfg.T1_WINDOWS]
    pr = {r["group"]: r for r in t1_rows if r["variant"].startswith("primary") and r["segment"] == "ALL"}
    fig, ax = plt.subplots(figsize=(7.2, 4.2), facecolor=SURF)
    _style(ax, "Copying real taker prints toward the options price:\nP&L by minutes since the 09:45 options snapshot", "points per $1 contract")
    xs = np.arange(len(names))
    m = np.array([pr[n]["mean"] for n in names])
    lo, hi = np.array([pr[n]["lo"] for n in names]), np.array([pr[n]["hi"] for n in names])
    ax.vlines(xs, lo, hi, color=BLUE, linewidth=2)
    ax.plot(xs, m, "o", color=BLUE, markersize=8, markeredgecolor=SURF, markeredgewidth=2)
    for x, n in zip(xs, names):
        ax.annotate(f"{pr[n]['mean']:+.1f}\n[{pr[n]['lo']:+.1f}, {pr[n]['hi']:+.1f}]\n{pr[n]['trades']} trades, {pr[n]['closures']} closures",
                    (x, pr[n]["hi"]), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=8, color=INK)
    ax.set_xticks(xs, [f"{n} min" for n in names])
    ax.set_xlim(-0.6, len(names) - 0.4)
    ax.set_ylim(min(lo.min(), 0) - 3, hi.max() + 9)
    fig.text(0.01, 0.01, "402 trades at 5+ points from the options price, held to the result, net of 1 cent and the fee. Dot: mean.\n"
                         "Line: 95% interval, resampling closures. The data were seen by earlier studies: a re-analysis.", fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(cfg.RESULTS / "decay.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13.0, 4.8), facecolor=SURF)
    short = ["1 S6 as modelled", "2 at printed\nprices (T2)", "3 S6's print-\nverified set", "4 verified, best\nclosure removed", "5 T2, best\nclosure removed"]
    ticks = [f"{n}\n{s['trades']} trades\n{s['closures_traded']} closures\n${s['printed_dollars']:,.0f} printed" for n, s in zip(short, stairs)]
    for ax, key, title, fmt in ((axes[0], "total", "Total P&L, dollars", "{:+,.0f}"), (axes[1], "sharpe", "Sharpe on closure returns (52 a year)", "{:+.2f}")):
        _style(ax, title, "")
        vals = [0.0 if s[key] != s[key] else s[key] for s in stairs]
        ax.bar(np.arange(len(stairs)), vals, width=0.5, color=BLUE, edgecolor=SURF, linewidth=2)
        for i, s in enumerate(stairs):
            ax.annotate("n/a" if s[key] != s[key] else fmt.format(s[key]), (i, max(vals[i], 0)), textcoords="offset points", xytext=(0, 4),
                        ha="center", fontsize=9, color=INK)
        ax.set_xticks(np.arange(len(stairs)), ticks, fontsize=7.5)
        top = max(max(vals), 0)
        ax.set_ylim(min(min(vals), 0) * 1.25 - 0.02 * top, top * 1.12 + 1e-9)
    fig.suptitle("S6 Monday fade: from the modelled backtest to prices that printed", x=0.01, ha="left", fontsize=12, color=INK)
    fig.text(0.01, 0.01, "Printed dollars: capital of the contracts that had a public trade print behind them (up to 100 contracts per entry). "
                         "Step 1 has prints behind 21 of its 187 entries.", fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(cfg.RESULTS / "staircase.png", dpi=160)
    plt.close(fig)

    for fname, what in (("equity_curve.png", "equity"), ("drawdown.png", "drawdown")):
        fig, axes = plt.subplots(1, len(books), figsize=(5.6 * len(books), 4.0), facecolor=SURF, squeeze=False)
        for ax, (name, (tr, passed, unit)) in zip(axes[0], books.items()):
            by = {}
            for t in tr:
                by[t["closure"]] = by.get(t["closure"], 0.0) + t["pnl"]
            e = np.cumsum([by.get(d, 0.0) for d in calendar])
            y = e if what == "equity" else e - np.maximum.accumulate(np.concatenate([[0.0], e]))[1:]
            _style(ax, f"{name}\n{'PASSES its line' if passed else 'DOES NOT PASS its line'}: {'cumulative P&L' if what == 'equity' else 'drawdown'}", unit)
            ax.plot(pd.to_datetime(calendar), y, color=BLUE, linewidth=2, drawstyle="steps-post")
            ax.annotate(f"{y[-1]:+,.2f}", (pd.to_datetime(calendar)[-1], y[-1]), textcoords="offset points", xytext=(4, 0), fontsize=8, color=INK, va="center")
            ax.tick_params(axis="x", labelrotation=30)
        fig.tight_layout()
        fig.savefig(cfg.RESULTS / fname, dpi=160)
        plt.close(fig)


def main() -> int:
    t_run = time.time()
    cfg.RESULTS.mkdir(parents=True, exist_ok=True)
    calendar = sorted(pd.read_csv(cfg.EVENTS, usecols=["open_day"]).open_day.dropna().unique())
    s6 = load_s6()
    d = load_partner()

    t1_rows, t1_v = t1(d, calendar)
    t2_recs, t2_meta = t2(s6)
    t2_rows, t2_v = t2_metrics(t2_recs, calendar)
    stairs = staircase(s6, t2_recs, calendar)

    seg = segments(calendar)
    b1 = t1_book(d)
    b2 = [t for t in t2_recs if t["mode"] == "best" and t["cost_mult"] == 1.0 and t["status"] == "trade"]
    book_rows = []
    for name, tr in (("T1 first-15-minute book (one contract per trade)", b1), ("T2 book (S6 at printed prices)", b2)):
        for sname, days in seg.items():
            book_rows.append({"test": "book", "variant": name, "segment": sname, "group": "all", "unit": "dollars per trade",
                              **book([t for t in tr if t["closure"] in set(days)], days)})
        nb, cal_nb, best = without_best(tr, calendar)
        book_rows.append({"test": "book", "variant": name, "segment": "ALL", "group": f"best closure removed ({best})", "unit": "dollars per trade",
                          **book(nb, cal_nb)})

    t1_out = d.assign(test="T1", closure_day=d.open_day).drop(columns=["tx"]).to_dict("records")
    write_csv(cfg.RESULTS / "trades.csv", t2_recs + t1_out)
    write_csv(cfg.RESULTS / "metrics.csv", t1_rows + t2_rows + book_rows + [{"test": "T3", "variant": s["step"], "segment": "ALL", "group": "staircase",
                                                                           "unit": "dollars per trade", **{k: v for k, v in s.items() if k != "step"}} for s in stairs])
    write_csv(cfg.RESULTS / "staircase.csv", stairs)
    charts(t1_rows, stairs, {"T2: S6 at printed prices (dollars)": (b2, t2_v["pass"], "dollars"),
                             "T1: first 15 minutes, one contract per trade": (b1, t1_v["pass"], "dollars per contract traded")}, calendar)
    meta = {"calendar_closures": len(calendar), "first_closure": calendar[0], "last_closure": calendar[-1], "oos_from": cfg.OOS_FROM,
            "oos_closures": len(seg["OOS"]), "s6_entries": int(len(s6)), "s6_verified": int(s6.verified.sum()),
            "partner_rows": int(len(d)), "partner_commit": cfg.PARTNER_COMMIT, "t1_verdict": t1_v, "t2_verdict": t2_v, "t2_cache": t2_meta,
            "t2_status_counts": {f"{m}/{c:.0f}x": pd.Series([t["status"] for t in t2_recs if t["mode"] == m and t["cost_mult"] == c]).value_counts().to_dict()
                                 for m in ("best", "first") for c in cfg.COST_MULTIPLIERS},
            "t1_window_counts_exact": {n: int((d[np.isclose(d.tau, cfg.T1_TAU)].window == n).sum()) for n, _, _ in cfg.T1_WINDOWS},
            "code_commit": git("rev-parse", "--short", "HEAD").strip(), "run_seconds": round(time.time() - t_run, 1)}
    (cfg.RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=1))

    print(json.dumps({k: meta[k] for k in ("t1_verdict", "t2_verdict", "t2_cache", "t2_status_counts", "t1_window_counts_exact")}, indent=1))
    print("\nT1 (points per contract)")
    for r in t1_rows:
        if r["segment"] == "ALL" or r["group"] in ("0-15", "0-30"):
            print(f"  {r['variant'][:38]:38} {r['segment']:3} {r['group']:18} n={r['trades']:4d} k={r['closures']:3d} {r['mean']:+7.2f} [{r['lo']:+7.2f}, {r['hi']:+7.2f}]")
    print("\nT2 (dollars per trade)")
    for r in t2_rows:
        print(f"  {r['variant'][:26]:26} {r['segment']:3} {r['group'][:34]:34} n={r['trades']:3d} k={r['closures_traded']:3d} {r['mean']:+8.2f} [{r['lo']:+8.2f}, {r['hi']:+8.2f}] "
              f"total {r['total']:+9.2f} sharpe {r['sharpe']:+6.2f} printed ${r['printed_dollars']:,.0f}")
    print("\nbooks")
    for r in book_rows:
        print(f"  {r['variant'][:30]:30} {r['segment']:3} {r['group'][:34]:34} n={r['trades']:3d} k={r['closures_traded']:3d} {r['mean']:+8.4f} [{r['lo']:+8.4f}, {r['hi']:+8.4f}] "
              f"total {r['total']:+9.2f} sharpe {r['sharpe']:+6.2f}")
    print("\nT3 staircase")
    for s in stairs:
        print(f"  {s['step'][:52]:52} n={s['trades']:3d} k={s['closures_traded']:3d} {s['mean']:+8.2f} [{s['lo']:+8.2f}, {s['hi']:+8.2f}] total {s['total']:+9.2f} "
              f"sharpe {s['sharpe']:+6.2f} printed ${s['printed_dollars']:,.0f} (uncapped ${s['printed_dollars_uncapped']:,.0f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
