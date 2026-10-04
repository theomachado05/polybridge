from __future__ import annotations

import argparse
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from leadlag_replication.closures import pm_covered
from polybridge_research.calendar import TradingCalendar

from .config import CACHE_DIR, PARAMS, R1_CSV, RESEARCH_DIR, RESULTS_DIR, SPAN_START, TZ
from .engine import VARIANTS, books, et_instant, run_loop, session_measures

DONE = RESULTS_DIR / ".done"


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RESEARCH_DIR, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def load_key() -> str:
    from polybridge_research.massive import MissingApiKey, _read_dotenv

    env = RESEARCH_DIR / ".env"
    key = _read_dotenv(env, "MASSIVE_API_KEY") if env.exists() else ""
    if not key or key == "your-key-here":
        raise MissingApiKey(f"MASSIVE_API_KEY not found in {env}")
    return key


def last_complete_session(meas: pd.DataFrame, daily: pd.DataFrame, early_closes) -> pd.Timestamp:
    for d in reversed(meas.index):
        t = meas.loc[d, "t_close"]
        if pd.isna(t) or d not in daily.index:
            continue
        end = (13, 0) if d.strftime("%Y-%m-%d") in early_closes else (16, 0)
        if t == et_instant(d, end):
            return d
    raise RuntimeError("no session with complete SPY minute bars")


def trim_points(pts, c):
    if not pts or isinstance(pts, Exception):
        return pts
    hi1 = int(c.nominal_close.timestamp())
    lo2 = int(et_instant(c.open_day, (7, 0)).timestamp())
    hi2 = int(c.nominal_open.timestamp())
    return [(t, p) for t, p in pts if t <= hi1 or lo2 <= t <= hi2]


def participation(markets: list[dict], closures_of: dict) -> dict:
    part: dict = {}
    for m in markets:
        for c in closures_of[m["market_slug"]]:
            part.setdefault(c.open_day, []).append(m["market_slug"])
    return part


def daily_frame(b: pd.DataFrame, sig: pd.DataFrame) -> pd.DataFrame:
    out = b.copy()
    out["f"] = sig["f"].reindex(out.index).fillna(0.0)
    return out


def trade_rows(variant: str, sig: pd.DataFrame, b1: pd.DataFrame, b2: pd.DataFrame, shares: float) -> pd.DataFrame:
    s = sig[sig["f"] > 0]
    if s.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "variant": variant, "day": s.index.strftime("%Y-%m-%d"), "closure": s["closure"], "trusted": s["trusted"],
        "driver": s["driver"], "rate": s["rate"], "x_pp": s["x_pp"], "E_bp": s["E_bp"], "f": s["f"],
        "entry_px": s["entry_px"], "exit_px": s["exit_px"], "shares_short": s["f"] * shares,
        "notional": b1.loc[s.index, "notional"], "gross": b1.loc[s.index, "hedge_gross"],
        "cost_1x": b1.loc[s.index, "hedge_cost"], "net_1x": b1.loc[s.index, "hedge_net"],
        "cost_2x": b2.loc[s.index, "hedge_cost"], "net_2x": b2.loc[s.index, "hedge_net"],
    })


def execute(client, pm_session, cal: TradingCalendar, today: pd.Timestamp, log: dict) -> dict:
    from leadlag_replication.closures import EARLY_CLOSES

    from . import data
    from .analysis import capacity, reconcile_r1, segment_metrics, segments, verdict

    print("SPY minute bars ...", flush=True)
    bars = data.fetch_minutes(client, SPAN_START, today.strftime("%Y-%m-%d"))
    daily = data.fetch_daily(client, SPAN_START, today.strftime("%Y-%m-%d"))
    cand = [d for d in cal.sessions if pd.Timestamp(SPAN_START) <= d <= today]
    meas_all = session_measures(bars, cand)
    last = last_complete_session(meas_all, daily, EARLY_CLOSES)
    days = [d for d in cand if d <= last]
    meas = meas_all.loc[days]
    del bars
    divs = data.fetch_dividends(client, SPAN_START, last.strftime("%Y-%m-%d"))
    close = daily["close"].reindex(days)
    if close.isna().any():
        raise RuntimeError(f"daily close missing for {list(close[close.isna()].index.strftime('%Y-%m-%d'))}")
    log["last_session"] = last.strftime("%Y-%m-%d")
    print(f"span {days[0].date()} .. {last.date()} ({len(days) - 1} return days)", flush=True)

    pa = data.panel_a_markets(pm_session)
    primary = pa + data.replication_markets(range(1, 11))
    every = pa + data.replication_markets(None)
    closures_of, pm, cov = {}, {}, []
    for m in every:
        cl = data.market_closures(m, last, cal)
        pts = data.fetch_pm_for(m, cl, session=pm_session)
        closures_of[m["market_slug"]] = cl
        n_cov = n_fail = 0
        for c in cl:
            v = trim_points(pts.get(c.key), c)
            pm[(m["market_slug"], c.key)] = v
            if isinstance(v, Exception):
                n_fail += 1
            elif pm_covered(v or [], c):
                n_cov += 1
        cov.append({"market": m["market_slug"], "source": m["source"], "rank": m.get("rank"), "closures": len(cl),
                    "pm_both_ends": n_cov, "fetch_failed": n_fail, "v4": n_cov >= PARAMS.v4_min_closures})
        print(f"  {m['market_slug'][:60]:<60} closures {len(cl):>3}, quoted {n_cov:>3}, failed {n_fail}", flush=True)
    cov = pd.DataFrame(cov)
    empty = sorted(set(m["market_slug"] for m in primary) & set(cov.loc[cov["closures"] == 0, "market"]))
    if empty:
        raise RuntimeError(f"primary-universe markets with no closure in the span: {empty}")
    v4_slugs = set(cov.loc[cov["v4"], "market"])
    v4 = [m for m in every if m["market_slug"] in v4_slugs]
    universes = {"primary": primary, "V4": v4}
    parts = {k: participation(u, closures_of) for k, u in universes.items()}

    sig, rec, dly, trades = {}, {}, {}, []
    shares = PARAMS.book_usd / float(close.iloc[0])
    for name in PARAMS.variants:
        v = VARIANTS[name]
        uni = "V4" if name == "V4_expanded" else "primary"
        print(f"walk {name} ({len(universes[uni])} markets) ...", flush=True)
        sig[name], rec[name] = run_loop(days, meas, universes[uni], parts[uni], pm, v)
        entry = PARAMS.cost_pre_entry_bp if v.premarket else PARAMS.cost_rth_bp
        for mult in PARAMS.cost_mults:
            b = books(days, close, divs, sig[name], entry * mult, PARAMS.cost_rth_bp * mult)
            dly[(name, mult)] = daily_frame(b, sig[name])
        trades.append(trade_rows(name, sig[name], dly[(name, 1.0)], dly[(name, 2.0)], shares))

    segs = segments(days)
    bh = dly[("primary", 1.0)]["bh"]
    rows = []
    for seg, sd in segs.items():
        rows.append({"segment": seg, "cost": "-", "book": "buy_and_hold", **segment_metrics(bh, sd)})
        for (name, mult), d in dly.items():
            rows.append({"segment": seg, "cost": f"{mult:g}x", "book": name, **segment_metrics(d["strat"], sd, d)})
    metrics = pd.DataFrame(rows)

    def get(seg, book, cost):
        return metrics[(metrics.segment == seg) & (metrics.book == book) & (metrics.cost == cost)].iloc[0].to_dict()

    ver = verdict(get("OOS", "primary", "1x"), get("OOS", "buy_and_hold", "-"))
    log["split"] = segs["OOS"][0].strftime("%Y-%m-%d") if segs["OOS"] else "none"

    trusted = {}
    for name in PARAMS.variants:
        s = sig[name]
        for seg, sd in segs.items():
            ss = s.loc[sd]
            names = set()
            for t in ss["trusted"]:
                names.update(x.split(":")[0] for x in str(t).split(";") if x)
            trusted[(name, seg)] = {"markets": sorted(names), "days_with_trusted": int((ss["n_trusted"] > 0).sum()),
                                    "days_participating": int((ss["n_part"] > 0).sum()),
                                    "skipped_missing_px": int(ss["skipped_missing_px"].sum())}

    def hedges(name):
        d = dly[(name, 1.0)]
        return pd.DataFrame({"notional": d.loc[d["f"] > 0, "notional"]})

    cap = {"rth": capacity(meas, daily, days, hedges("primary")),
           "pre": capacity(meas, daily, days, hedges("V1_premarket"), vol_col="vol5_pre_usd")}
    r1 = pd.read_csv(R1_CSV) if R1_CSV.exists() else pd.DataFrame()
    recon_rows, recon = reconcile_r1(r1, meas, pm, pa, days) if not r1.empty else (pd.DataFrame(), {"n": 0})
    close_check = (meas["rth_close"] / close - 1).abs() * 1e4

    return {"days": days, "meas": meas, "close": close, "divs": divs, "segs": segs, "metrics": metrics,
            "verdict": ver, "sig": sig, "rec": rec, "daily": dly, "trades": pd.concat(trades, ignore_index=True),
            "coverage": cov, "universes": universes, "trusted": trusted, "capacity": cap, "recon": recon,
            "recon_rows": recon_rows, "close_check_bp": close_check, "last": last}


def write_run_log(entry: str) -> None:
    path = RESULTS_DIR / "RUN_LOG.md"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Strategy backtest run log\n\nOne entry per invocation of `python -m strategy_backtest.run`: code "
                        "commit, wall time, network requests, last session, split date, exit status. Cached responses are "
                        "not counted (the cache is gitignored).\n")
    with path.open("a") as fh:
        fh.write("\n" + entry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None, help="last calendar date to consider (default: today, ET)")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc)
    if DONE.exists():
        msg = f"refused: {DONE} exists (the pre-registered backtest has already run once)"
        print(msg, file=sys.stderr)
        write_run_log(f"## {started:%Y-%m-%d %H:%M:%S}Z\n- result: {msg}\n- exit: 3\n")
        return 3

    from leadlag.data import CountingSession
    from polybridge_research.massive import MassiveClient, MissingApiKey

    t0 = time.time()
    commit = _git("rev-parse", "--short", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--", "strategy_backtest"))
    pm_session, massive_session = CountingSession(), CountingSession()
    log, exit_code, note = {"last_session": "n/a", "split": "n/a"}, 0, ""
    try:
        try:
            key = load_key()
        except MissingApiKey as exc:
            note = str(exc)
            print(note, file=sys.stderr)
            exit_code = 2
            return exit_code
        client = MassiveClient(key, cache_dir=CACHE_DIR / "massive", session=massive_session)
        today = pd.Timestamp(args.today) if args.today else pd.Timestamp.now(tz=TZ).tz_localize(None).normalize()
        res = execute(client, pm_session, TradingCalendar(), today, log)
        from .report import write_all

        write_all(res, commit)
        v = res["verdict"]
        note = f"verdict {v['verdict']} ({v['reason']})"
        print(note)
        DONE.write_text(f"{started.isoformat()} commit {commit}\n")
    except Exception:  # noqa: BLE001
        exit_code = 1
        note = "crashed: " + traceback.format_exc().splitlines()[-1]
        traceback.print_exc()
    finally:
        dur = time.time() - t0
        c = pm_session.counts
        reqs = (f"Polymarket CLOB {c.get('clob.polymarket.com', 0)}, gamma {c.get('gamma-api.polymarket.com', 0)}, "
                f"Massive {sum(massive_session.counts.values())} (cached responses are not counted)")
        write_run_log(
            f"## {started:%Y-%m-%d %H:%M:%S}Z\n"
            f"- code commit: `{commit}`{' + uncommitted changes in strategy_backtest/' if dirty else ''}\n"
            f"- wall time: {dur:.0f} s\n"
            f"- network requests: {reqs}\n"
            f"- last session: {log['last_session']}; first OOS day: {log['split']}\n"
            f"- result: {note}\n"
            f"- exit: {exit_code}\n"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
