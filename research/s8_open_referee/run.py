from __future__ import annotations

import json
import math
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s4_linked_assets.run import load_critic, verdict
from s5_big_moves import config as c5
from s5_big_moves.run import CACHE as S5_CACHE
from s5_big_moves.run import merge_links
from s6_monday_fade import config as c6
from s6_monday_fade.run import capital, closure_metrics, fee, pnl_end_of_day, verify, write_csv
from s7_weekend_straddle.run import boot_diff, boot_mean

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s8_open_referee"
CACHE = HERE / ".cache"
WINDOWS = (("y_close", "09:40 to the close"), ("y_first", "09:29 to 09:40"), ("y_next", "09:40 to the next 09:40"))


def links() -> list[dict]:
    out = [{"market": l["market"], "question": l["question"], "ticker": l["ticker"], "direction": int(l["direction"]), "source": "S5"}
           for l in merge_links()[0]]
    critic = load_critic()
    for l in d4.proposer_links():
        if (verdict(l, critic) == "agreed" and critic[l["market"]]["family"] == "event"
                and not d4.is_motivating(l["market"], l["question"])):
            out.append({"market": l["market"], "question": l["question"], "ticker": l["ticker"], "direction": int(l["direction"]), "source": "S4"})
    return [l for l in out if l["ticker"] != "SPY"]


def first_bar_close(bars: dict, opens: np.ndarray) -> np.ndarray:
    t, c = bars["t"], bars["c"]
    out = np.full(len(opens), np.nan)
    if len(t) == 0:
        return out
    idx = np.minimum(np.searchsorted(t, opens), len(t) - 1)
    hit = t[idx] == opens
    out[hit] = c[idx[hit]]
    return out


def asset_vote(x: np.ndarray, moves: list[np.ndarray], directions: list[int]) -> tuple[np.ndarray, np.ndarray]:
    if not moves:
        return np.full(len(x), np.nan), np.zeros(len(x), int)
    m = np.vstack([d * e for d, e in zip(directions, moves)])
    n = np.isfinite(m).sum(axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        g = np.nanmean(m, axis=0)
    return np.sign(x) * g, n


def label(a: float) -> str:
    if a != a:
        return "no vote"
    return "confirmed" if a > 0 else "not confirmed"


def fade(x: float, p_in: float, p_out: float, c: float) -> tuple[str, float, float]:
    h = cfg.HALF_SPREAD
    if x > 0:
        side, entry = "sell YES", min(max(p_in - c * h, c6.PRICE_CLIP[0]), c6.PRICE_CLIP[1])
    else:
        side, entry = "buy YES", min(max(p_in + c * h, c6.PRICE_CLIP[0]), c6.PRICE_CLIP[1])
    return side, entry, pnl_end_of_day(side, entry, p_out, h, c)


def select(df: pd.DataFrame, v: cfg.Variant) -> pd.DataFrame:
    out = "p_close" if v.exit == "close" else "p_next"
    ok = (df.x.abs() >= v.threshold) & df.p_0940.between(*cfg.ENTRY_BAND) & df[out].notna()
    ok &= (df.vote == "not confirmed") if v.vote == "not confirmed" else (df.vote != "no vote")
    if v.weekends_only:
        ok &= df.weekend
    s = df[ok].assign(_ax=lambda d: d.x.abs()).sort_values(["day", "_ax", "market"], ascending=[True, False, True])
    return s.groupby("day", sort=True).head(cfg.MAX_POSITIONS).drop(columns="_ax").assign(p_exit=lambda d: d[out])


def build() -> tuple[pd.DataFrame, dict]:
    def npz(f: Path):
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz(S5_CACHE / "eq_SPY.npz"), npz(S5_CACHE / "day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    op, cl = sess.open.to_numpy(), sess.close.to_numpy()
    prev_cl = np.concatenate([[0], cl[:-1]]).astype(np.int64)
    weekend = np.concatenate([[False], (op[1:] - cl[:-1]) > cfg.WEEKEND_GAP_S])
    n_oos = int(math.ceil(cfg.OOS_FRACTION * len(days)))
    seg = np.array(["OOS" if i >= len(days) - n_oos else "IS" for i in range(len(days))])

    def shift(a):
        return np.concatenate([[np.nan], a[:-1]])

    spy_move = first_bar_close(spy_bars, op) / shift(en.session_prices(spy_bars, sess)["close"]) - 1.0
    moves: dict[str, np.ndarray | None] = {}

    def asset(tk: str):
        if tk not in moves:
            moves[tk] = None
            for cache in (S5_CACHE, d4.CACHE):
                b, d = npz(cache / f"eq_{tk}.npz"), npz(cache / f"day_{tk}.npz")
                if b is None or d is None or len(b["t"]) == 0:
                    continue
                r = first_bar_close(b, op) / shift(en.session_prices(b, sess)["close"]) - 1.0
                moves[tk] = 1e4 * (r - en.betas(d, spy_day, days) * spy_move)
                break
        return moves[tk]

    by_market: dict[str, list[dict]] = {}
    for l in links():
        by_market.setdefault(l["market"], []).append(l)
    frames, used = [], 0
    for mid, ls in sorted(by_market.items()):
        pm = npz((S5_CACHE if ls[0]["source"] == "S5" else d4.CACHE) / f"pm_{mid.split(':')[1]}.npz")
        voters = [(l["ticker"], l["direction"]) for l in ls if asset(l["ticker"]) is not None]
        if pm is None or len(pm["t"]) == 0 or not voters:
            continue
        used += 1
        pt, pp = pm["t"], pm["p"].astype(float)

        def p(at):
            return asof(np.asarray(at, dtype=np.int64), pt, pp, cfg.PM_MAX_AGE_S)

        p_prev, p_sig, p_in, p_out = p(prev_cl), p(op - cfg.SIGNAL_LEAD_S), p(op + cfg.ENTRY_AFTER_OPEN_S), p(cl)
        x = 100.0 * (p_sig - p_prev)
        a, n = asset_vote(x, [moves[t] for t, _ in voters], [d for _, d in voters])
        sx = np.sign(x)
        frames.append(pd.DataFrame({
            "day": days, "segment": seg, "weekend": weekend, "source": ls[0]["source"], "market": mid, "question": ls[0]["question"],
            "tickers": " ".join(f"{'+' if d > 0 else '-'}{t}" for t, d in voters), "x": x, "a": a, "voters": n,
            "p_prev": p_prev, "p_0929": p_sig, "p_0940": p_in, "p_close": p_out, "p_next": np.concatenate([p_in[1:], [np.nan]]),
            "entry_epoch": op + cfg.ENTRY_AFTER_OPEN_S,
            "y_first": sx * 100.0 * (p_in - p_sig), "y_close": sx * 100.0 * (p_out - p_in),
            "y_next": sx * 100.0 * (np.concatenate([p_in[1:], [np.nan]]) - p_in)}))
    df = pd.concat(frames, ignore_index=True)
    df = df[np.isfinite(df.x) & (df.x.abs() >= min(cfg.TEST_THRESHOLDS))].copy()
    df["vote"] = [label(v) for v in df.a]
    meta = {"sessions": len(days), "first_session": days[0], "last_session": days[-1], "oos_from": days[len(days) - n_oos], "oos_sessions": n_oos,
            "weekend_closures": int(weekend.sum()), "links": len(links()), "markets_with_links": len(by_market), "markets_used": used,
            "tickers": len({l["ticker"] for l in links()}), "days": days}
    return df, meta


def giveback(df: pd.DataFrame) -> list[dict]:
    rows = []
    for thr in cfg.TEST_THRESHOLDS:
        for scope, sm in (("all nights", np.ones(len(df), bool)), ("weekends and holidays", df.weekend.to_numpy())):
            for col, window in WINDOWS:
                s = df[sm & (df.x.abs() >= thr) & df[col].notna()]
                by = {g: {d: list(v) for d, v in s[s.vote == g].groupby("day")[col]} for g in ("not confirmed", "confirmed", "no vote")}
                for g, b in by.items():
                    m = boot_mean(b)
                    rows.append({"threshold": thr, "scope": scope, "window": window, "group": g, "n": int(sum(len(v) for v in b.values())),
                                 "dates": len(b), "markets": int(s[s.vote == g].market.nunique()), "mean": m[0], "ci_lo": m[1], "ci_hi": m[2]})
                d = boot_diff(by["not confirmed"], by["confirmed"])
                rows.append({"threshold": thr, "scope": scope, "window": window, "group": "not confirmed minus confirmed",
                             "n": rows[-3]["n"] + rows[-2]["n"], "dates": len(set(by["not confirmed"]) | set(by["confirmed"])),
                             "markets": int(s[s.vote != "no vote"].market.nunique()), "mean": d[0], "ci_lo": d[1], "ci_hi": d[2]})
    return rows


def load_prints(need: dict[str, list[float]]) -> dict[str, dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    pt, out = ds.Throttle(4.0), {}
    for mid, at in sorted(need.items()):
        f = CACHE / f"prints_{mid.split(':')[1]}.json"
        if f.exists():
            out[mid] = json.loads(f.read_text())
            continue
        rec = {"reach_oldest": None, "served": 0, "prints": []}
        try:
            g = ds.get_json(f"{ds.GAMMA}/markets/{mid.split(':')[1]}", throttle=pt)
            raw = ds.pm_trades(g["conditionId"], min(at) - c6.PRINT_WINDOW_S, pt, max_pages=cfg.PRINT_PAGES)
            ts = np.array([float(t.get("timestamp", 0)) for t in raw])
            ats = np.array(sorted(at))
            keep = [t for t, s in zip(raw, ts) if np.min(np.abs(ats - s)) <= c6.PRINT_WINDOW_S]
            rec = {"reach_oldest": float(ts.min()) if len(ts) else None, "served": len(raw),
                   "prints": [{k: t.get(k) for k in ("timestamp", "price", "side", "outcome", "size")} for t in keep]}
        except Exception as e:  # noqa: BLE001  (a market the API will not serve is recorded, not fatal)
            rec["error"] = str(e)[:200]
        f.write_text(json.dumps(rec))
        out[mid] = rec
    return out


def main() -> int:
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    df, meta = build()
    days = meta.pop("days")
    gb = giveback(df)

    trades = []
    for v in cfg.VARIANTS:
        sel = select(df, v)
        for c in cfg.COST_MULTIPLIERS:
            for r in sel.itertuples():
                side, entry, pnl = fade(r.x, r.p_0940, r.p_exit, c)
                gross = -np.sign(r.x) * (r.p_exit - r.p_0940)
                trades.append({"variant": v.id, "cost_mult": c, "segment": r.segment, "day": r.day, "weekend": bool(r.weekend), "source": r.source,
                               "market": r.market, "question": r.question, "tickers": r.tickers, "overnight_move_pp": r.x,
                               "asset_vote_bp": r.a, "vote": r.vote, "side": side, "p_0940": r.p_0940, "entry": entry, "p_exit": r.p_exit,
                               "gross_points": 100.0 * gross, "cost_points": 100.0 * (gross - pnl), "net_points": 100.0 * pnl,
                               "pnl": c6.CONTRACTS * pnl, "capital": capital(side, entry), "entry_epoch": float(r.entry_epoch)})

    prints: dict[str, dict] = {}
    if "--no-prints" not in sys.argv:
        need: dict[str, list[float]] = {}
        for t in trades:
            if t["variant"] == cfg.PRIMARY:
                need.setdefault(t["market"], []).append(t["entry_epoch"])
        prints = load_prints(need)
    for t in trades:
        rec = prints.get(t["market"])
        reach = rec is not None and rec.get("reach_oldest") is not None and rec["reach_oldest"] <= t["entry_epoch"] - c6.PRINT_WINDOW_S
        n, size = verify(rec["prints"], t["side"], t["entry"], t["entry_epoch"]) if rec and rec["prints"] else (0, 0.0)
        t["checkable"], t["verify_n"], t["verify_size"], t["verified"] = bool(reach), n, size, n > 0
        t["pnl_verified"] = t["pnl"] * min(size, c6.CONTRACTS) / c6.CONTRACTS if n else 0.0

    oos_from = meta["oos_from"]
    segments = (("IS", [d for d in days if d < oos_from]), ("OOS", [d for d in days if d >= oos_from]), ("ALL", days),
                ("from 2026-07-01", [d for d in days if d >= c5.KNOWLEDGE_CUTOFF_DAY]))
    rows, eq = [], []
    for v in cfg.VARIANTS:
        for c in cfg.COST_MULTIPLIERS:
            vt = [t for t in trades if t["variant"] == v.id and t["cost_mult"] == c]
            cap_by_day = pd.Series([t["capital"] for t in vt], index=[t["day"] for t in vt]).groupby(level=0).sum() if vt else pd.Series(dtype=float)
            K = float(cap_by_day.max()) if len(cap_by_day) else 0.0
            for seg, dl in segments:
                ds_ = set(dl)
                st = [t for t in vt if t["day"] in ds_]
                by_day: dict[str, list[dict]] = {}
                for t in st:
                    by_day.setdefault(t["day"], []).append(t)
                pc = np.array([sum(t["pnl"] for t in by_day.get(d, [])) for d in dl])
                m = closure_metrics(pc, dl, K, sum(t["capital"] for t in st), cfg.DAYS_PER_YEAR)
                b = boot_mean({d: [t["net_points"] for t in ts] for d, ts in by_day.items()})
                g = boot_mean({d: [t["gross_points"] for t in ts] for d, ts in by_day.items()})
                ver = [t for t in st if t["verified"]]
                bv = boot_mean({d: [t["net_points"] for t in ts if t["verified"]] for d, ts in by_day.items()})
                rows.append({"segment": seg, "variant": v.id, "threshold": v.threshold, "vote": v.vote, "exit": v.exit,
                             "weekends_only": v.weekends_only, "cost_mult": c, "sessions": len(dl), "dates_traded": len(by_day),
                             "trades": len(st), "markets": len({t["market"] for t in st}),
                             "mean_net_points": b[0], "ci_lo": b[1], "ci_hi": b[2], "mean_gross_points": g[0], "gross_ci_lo": g[1],
                             "gross_ci_hi": g[2], "mean_cost_points": float(np.mean([t["cost_points"] for t in st])) if st else float("nan"),
                             "cost_bp_of_capital": float(np.mean([t["cost_points"] / 100.0 * c6.CONTRACTS / t["capital"] * 1e4 for t in st])) if st else float("nan"),
                             "hit_rate": float(np.mean([t["pnl"] > 0 for t in st])) if st else float("nan"), "pnl": float(pc.sum()),
                             "capital_base": K, "capital_deployed": float(sum(t["capital"] for t in st)), **m,
                             "checkable_trades": sum(t["checkable"] for t in st), "verified_trades": len(ver),
                             "verified_share": len(ver) / len(st) if st else float("nan"),
                             "mean_net_points_verified": bv[0], "ci_lo_verified": bv[1], "ci_hi_verified": bv[2],
                             "pnl_verified": float(sum(t["pnl_verified"] for t in st))})
                if seg == "ALL":
                    pv = np.array([sum(t["pnl_verified"] for t in by_day.get(d, [])) for d in dl])
                    eq += [{"variant": v.id, "cost_mult": c, "day": d, "pnl": float(x), "pnl_verified": float(y)}
                           for d, x, y in zip(dl, np.cumsum(pc), np.cumsum(pv))]
    sys.path.insert(0, str(RESEARCH))
    from polybridge_research.stats import deflated_sharpe
    for row in rows:
        peers = [x["daily_sharpe"] for x in rows if (x["segment"], x["cost_mult"]) == (row["segment"], row["cost_mult"]) and x["daily_sharpe"] == x["daily_sharpe"]]
        row["deflated_sharpe_prob"] = deflated_sharpe(row["daily_sharpe"], row["sessions"], len(cfg.VARIANTS), float(np.var(peers)), row["skew"],
                                                      row["kurtosis"]) if row["daily_sharpe"] == row["daily_sharpe"] and len(peers) > 1 else float("nan")

    write_csv(RESULTS / "mornings.csv", df.to_dict("records"))
    write_csv(RESULTS / "giveback.csv", gb)
    write_csv(RESULTS / "trades.csv", trades)
    write_csv(RESULTS / "metrics.csv", rows)
    write_csv(RESULTS / "equity.csv", eq)
    cost = json.loads((RESEARCH / "results" / "s5_big_moves" / "pm_cost_snapshot.json").read_text())
    (RESULTS / "run_meta.json").write_text(json.dumps({
        **meta, "mornings_5pt": int(len(df)), "mornings_10pt": int((df.x.abs() >= 10).sum()),
        "votes_5pt": {k: int(n) for k, n in df.vote.value_counts().items()},
        "by_source_5pt": {k: int(n) for k, n in df.source.value_counts().items()},
        "markets_checked_for_prints": len(prints), "markets_served": sum(1 for r in prints.values() if r.get("served")),
        "half_spread": cfg.HALF_SPREAD, "cost_snapshot": cost, "run_seconds": round(time.time() - t_run, 1)}, indent=1))

    print(json.dumps({k: v for k, v in meta.items()}), "| mornings", len(df), dict(df.vote.value_counts()))
    for r in gb:
        if r["window"] == "09:40 to the close" or r["threshold"] == 5.0:
            print(f"{r['threshold']:4.0f}+ | {r['scope'][:10]:10} | {r['window']:23} | {r['group']:29} | n {r['n']:4d} dates {r['dates']:3d} "
                  f"mean {r['mean']:6.2f} [{r['ci_lo']:6.2f},{r['ci_hi']:6.2f}]")
    print("seg              var cost trades dates  net_pts [ci]             gross  cost   hit  sharpe  maxDD  check  ver")
    for x in rows:
        print(f"{x['segment']:16} {x['variant']} {x['cost_mult']:.0f}x {x['trades']:6d} {x['dates_traded']:5d} {x['mean_net_points']:7.2f} "
              f"[{x['ci_lo']:6.2f},{x['ci_hi']:6.2f}] {x['mean_gross_points']:6.2f} {x['mean_cost_points']:5.2f} {x['hit_rate']:5.2f} "
              f"{x['sharpe']:6.2f} {x['max_drawdown']:6.3f} {x['checkable_trades']:5d} {x['verified_trades']:4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
