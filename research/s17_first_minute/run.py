"""S17: is the first minute of the session still pricing the night? (METHOD.md)

Run from `research/`:
    python -m s17_first_minute.run --pull    # one-minute bars and stock quotes from Massive (cached, not committed)
    python -m s17_first_minute.run           # F1, F2, the trades, the report
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from polybridge_research.massive import BASE_URL, MassiveClient, load_api_key
from s1_twin_spread.data import Throttle
from s4_linked_assets import engine as en
from s4_linked_assets.data import CACHE as S4_CACHE
from s5_big_moves.run import CACHE as S5_CACHE
from s6_monday_fade.run import closure_metrics, write_csv

from . import config as cfg

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
RESULTS = RESEARCH / "results" / "s17_first_minute"
CACHE = HERE / ".cache"
MORNINGS = RESEARCH / "results" / "s8_open_referee" / "mornings.csv"
ET, UTC = ZoneInfo("America/New_York"), timezone.utc
OIL = {"USO", "XLE", "XOP", "CVX", "VLO", "MPC", "PSX", "STNG", "FRO", "ZIM"}
RATES = {"SHY", "IEF", "TLT"}


# ---------------------------------------------------------------- calendar and events

def sessions() -> pd.DataFrame:
    return en.sessions_from(np.load(S5_CACHE / "eq_SPY.npz")["t"])


def events(threshold: float) -> pd.DataFrame:
    """One row per (ticker, day): the question with the largest |x| (ties: lowest market id). d = the asset's expected sign."""
    m = pd.read_csv(MORNINGS)
    m = m[m.x.abs() >= threshold]
    rows = []
    for r in m.itertuples():
        for tk in str(r.tickers).split():
            sgn = -1 if tk.startswith("-") else 1
            rows.append({"day": r.day, "ticker": tk.lstrip("+-"), "market": r.market, "mid": int(r.market.split(":")[1]),
                         "question": r.question, "x": float(r.x), "absx": abs(float(r.x)), "d": int(np.sign(r.x)) * sgn,
                         "weekend": bool(r.weekend)})
    df = pd.DataFrame(rows).sort_values(["day", "ticker", "absx", "mid"], ascending=[True, True, False, True])
    df = df.drop_duplicates(["day", "ticker"]).reset_index(drop=True)
    df["segment"] = np.where(df.day >= cfg.OOS_FROM, "OOS", "IS")
    df["theme"] = np.where(df.ticker.isin(OIL), "oil", np.where(df.ticker.isin(RATES), "rates", "other"))
    return df


# ---------------------------------------------------------------- Massive

class Client(MassiveClient):
    """MassiveClient that waits on a shared throttle only when the answer is not already cached."""

    def __init__(self, rate: float):
        super().__init__(load_api_key(search_from=RESEARCH), cache_dir=CACHE / "massive")
        self.throttle, self.calls = Throttle(rate), 0

    def get(self, path_or_url: str, params: dict | None = None) -> dict:
        url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
        full = requests.Request("GET", url, params=params).prepare().url
        if not (self.cache_dir / (hashlib.sha1(full.encode()).hexdigest() + ".json")).exists():
            self.throttle.wait()
            self.calls += 1
        return super().get(path_or_url, params)


def bars(c: Client, tk: str, prev_day: str, day: str) -> list[dict]:
    r = c.get(f"/v2/aggs/ticker/{tk}/range/1/minute/{prev_day}/{day}", {"adjusted": "true", "sort": "asc", "limit": 50000})
    return r.get("results") or []


def quote(c: Client, tk: str, at: float) -> dict | None:
    iso = datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = c.get(f"/v3/quotes/{tk}", {"limit": 1, "timestamp.lte": iso, "order": "desc", "sort": "timestamp"})
    res = r.get("results") or []
    if not res:
        return None
    x = res[0]
    return {"bid": float(x.get("bid_price") or 0), "ask": float(x.get("ask_price") or 0), "bid_size": float(x.get("bid_size") or 0),
            "ask_size": float(x.get("ask_size") or 0), "ts": float(x.get("sip_timestamp") or 0) / 1e9}


def at_et(day: str, hhmm: str) -> float:
    h, m = (int(v) for v in hhmm.split(":"))
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ET).timestamp()


def past_stop() -> bool:
    now = datetime.now(ET)
    h, m = (int(v) for v in cfg.STOP_PULL_ET.split(":"))
    return now.date() >= date(2026, 10, 4) and (now.hour, now.minute) >= (h, m) and now.hour < 12


# ---------------------------------------------------------------- prices from bars

def day_prices(raw: list[dict], prev_day: str, day: str, sess: pd.DataFrame) -> dict | None:
    """prev_close, open and the close at each minute mark, regular session only (early closes respected)."""
    s = sess.set_index("day")
    if prev_day not in s.index or day not in s.index or not raw:
        return None
    t = np.array([b["t"] / 1000.0 for b in raw])
    o, cl = np.array([b["o"] for b in raw], float), np.array([b["c"] for b in raw], float)
    p0, p1 = (t >= s.loc[prev_day, "open"]) & (t < s.loc[prev_day, "close"]), (t >= s.loc[day, "open"]) & (t < s.loc[day, "close"])
    if not p0.any() or not p1.any():
        return None
    td, od, cd = t[p1], o[p1], cl[p1]
    op = float(s.loc[day, "open"])
    if td[0] - op > cfg.OPEN_BAR_MAX_LAG_MIN * 60:
        return None

    def close_at(hhmm: str) -> float:
        end = at_et(day, hhmm)
        k = np.searchsorted(td, end - 60, side="right") - 1      # last bar starting at or before end - 1 minute
        return float(cd[k]) if k >= 0 else float("nan")

    out = {"prev_close": float(cl[p0][-1]), "open": float(od[0]), "close": float(cd[-1]), "first_bar_lag_s": float(td[0] - op)}
    for hhmm in ("09:31", "09:35", "10:00", "15:55"):
        out[hhmm] = close_at(hhmm)
    return out


def window_returns(px: dict, spx: dict, beta: float, d: int) -> dict:
    out = {}
    for name, a, b in cfg.WINDOWS:
        ra, rs = px[b] / px[a] - 1.0, spx[b] / spx[a] - 1.0
        out[name] = 1e4 * d * (ra - beta * rs)
        out[name + "_raw"] = 1e4 * d * ra
    return out


def betas_for(ev: pd.DataFrame) -> np.ndarray:
    spy = np.load(S5_CACHE / "day_SPY.npz")
    out = np.ones(len(ev))
    for tk, g in ev.groupby("ticker"):
        f = next((p for p in (S5_CACHE / f"day_{tk}.npz", S4_CACHE / f"day_{tk}.npz") if p.exists()), None)
        if f is None:
            continue
        out[g.index.to_numpy()] = en.betas(dict(np.load(f)), dict(spy), list(g.day))
    return out


# ---------------------------------------------------------------- trades

def valid(q: dict | None, at: float, day: str) -> bool:
    if not q or q["bid"] <= 0 or q["ask"] < q["bid"]:
        return False
    mid = (q["bid"] + q["ask"]) / 2
    return at - q["ts"] <= cfg.QUOTE_MAX_AGE_S and q["ts"] >= at_et(day, "09:30") and 1e4 * (q["ask"] - q["bid"]) / mid <= cfg.MAX_SPREAD_BP


def trade_return(q_in: dict, q_out: dict, side: int, c: float) -> dict:
    """side +1 buy then sell, -1 short then cover. Every half-spread multiplied by c."""
    m1, h1 = (q_in["bid"] + q_in["ask"]) / 2, (q_in["ask"] - q_in["bid"]) / 2
    m2, h2 = (q_out["bid"] + q_out["ask"]) / 2, (q_out["ask"] - q_out["bid"]) / 2
    e, x = m1 + side * c * h1, m2 - side * c * h2
    net = side * (x - e) / e
    gross = side * (m2 - m1) / m1
    return {"entry_px": e, "exit_px": x, "gross_bp": 1e4 * gross, "net_bp": 1e4 * net, "cost_bp": 1e4 * (gross - net),
            "spread_in_bp": 1e4 * 2 * h1 / m1, "spread_out_bp": 1e4 * 2 * h2 / m2}


# ---------------------------------------------------------------- statistics

def boot(groups: list[str], vals) -> tuple[float, float, float]:
    by: dict[str, list[float]] = {}
    for g, v in zip(groups, vals):
        if np.isfinite(v):
            by.setdefault(g, []).append(float(v))
    return en.date_bootstrap(by, cfg.N_BOOT, cfg.BOOT_SEED)


def boot_diff(ga, a, gb, b) -> tuple[float, float, float]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return (float("nan"),) * 3
    keys = sorted(set(ga) | set(gb))
    ix = {k: i for i, k in enumerate(keys)}
    ia, ib = np.array([ix[g] for g in ga]), np.array([ix[g] for g in gb])
    sa, na = np.bincount(ia, a, len(keys)), np.bincount(ia, None, len(keys))
    sb, nb = np.bincount(ib, b, len(keys)), np.bincount(ib, None, len(keys))
    pick = np.random.default_rng(cfg.BOOT_SEED).integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    NA, NB = na[pick].sum(1), nb[pick].sum(1)
    ok = (NA > 0) & (NB > 0)
    dd = sa[pick].sum(1)[ok] / NA[ok] - sb[pick].sum(1)[ok] / NB[ok]
    lo, hi = np.percentile(dd, [2.5, 97.5])
    return float(a.mean() - b.mean()), float(lo), float(hi)


# ---------------------------------------------------------------- pull

def pull() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    c = Client(cfg.MASSIVE_RATE)
    days = list(sessions().day)
    prev = {d: days[i - 1] for i, d in enumerate(days) if i > 0}
    t0, log = time.time(), open(CACHE / "pull.log", "a")
    for thr in (cfg.MAIN_THRESHOLD, cfg.LOOSE_THRESHOLD):
        ev = events(thr)
        for stage in ("bars", "quotes"):
            for r in ev.itertuples():
                if past_stop():
                    print("STOP time reached", file=log, flush=True)
                    return
                if r.day not in prev:
                    continue
                try:
                    if stage == "bars":
                        bars(c, r.ticker, prev[r.day], r.day)
                        bars(c, "SPY", prev[r.day], r.day)
                    else:
                        for hhmm in (cfg.ENTRY, *sorted(set(cfg.EXITS.values()))):
                            quote(c, r.ticker, at_et(r.day, hhmm))
                except Exception as e:  # noqa: BLE001  (recorded, the run counts the gap)
                    print(f"FAIL {stage} {r.ticker} {r.day}: {str(e)[:150]}", file=log, flush=True)
            print(f"{time.time() - t0:6.0f}s threshold {thr:g} {stage} done, {c.calls} calls", file=log, flush=True)


# ---------------------------------------------------------------- run

def build(thr: float, c: Client, sess: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    ev = events(thr)
    days = list(sess.day)
    prev = {d: days[i - 1] for i, d in enumerate(days) if i > 0}
    ev["beta"] = betas_for(ev)
    drops: dict[str, int] = {}
    rows = []
    for r in ev.to_dict("records"):
        def drop(why):
            drops[why] = drops.get(why, 0) + 1
        if r["day"] not in prev:
            drop("no previous session")
            continue
        try:
            px = day_prices(bars(c, r["ticker"], prev[r["day"]], r["day"]), prev[r["day"]], r["day"], sess)
            spx = day_prices(bars(c, "SPY", prev[r["day"]], r["day"]), prev[r["day"]], r["day"], sess)
        except Exception:  # noqa: BLE001
            px = spx = None
        if px is None or spx is None or not all(np.isfinite(list(px.values()))):
            drop("bars missing or first bar after 09:32")
            continue
        rec = {**r, **{f"px_{k}": v for k, v in px.items()}, **window_returns(px, spx, r["beta"], r["d"])}
        rec["confirmed"] = rec["gap"] > 0
        try:
            qs = {h: quote(c, r["ticker"], at_et(r["day"], h)) for h in (cfg.ENTRY, *sorted(set(cfg.EXITS.values())))}
        except Exception:  # noqa: BLE001
            qs = {}
        for h, q in qs.items():
            ok = valid(q, at_et(r["day"], h), r["day"])
            rec[f"q_{h}_ok"] = ok
            if q:
                rec.update({f"q_{h}_{k}": v for k, v in q.items()})
        rows.append(rec)
    return pd.DataFrame(rows), drops


def main() -> int:
    if "--pull" in sys.argv:
        pull()
        return 0
    t_run = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    c, sess = Client(cfg.MASSIVE_RATE), sessions()
    stats, trades, allev, meta = [], [], [], {"drops": {}}
    for thr in cfg.THRESHOLDS:
        ev, drops = build(thr, c, sess)
        meta["drops"][f"{thr:g}"] = drops
        ev["threshold"] = thr
        allev.append(ev)
        for seg in ("IS", "OOS", "ALL"):
            s = ev if seg == "ALL" else ev[ev.segment == seg]
            for name, _, _ in cfg.WINDOWS:
                m = boot(list(s.day), s[name])
                sl = en.clustered_slope(s.absx.to_numpy(), s[name].to_numpy(), s.day.to_numpy())
                stats.append({"test": "F1", "threshold": thr, "segment": seg, "window": name, "n": len(s), "dates": s.day.nunique(),
                              "mean_bp": m[0], "lo": m[1], "hi": m[2], "slope_bp_per_point": sl["slope"], "t": sl["t"],
                              "raw_mean_bp": float(s[name + "_raw"].mean())})
            u, k = s[~s.confirmed], s[s.confirmed]
            for name in ("0931_close", "0931_0935", "0935_1000"):
                du = boot_diff(list(u.day), u[name], list(k.day), k[name])
                mu = boot(list(u.day), u[name])
                stats.append({"test": "F2", "threshold": thr, "segment": seg, "window": name, "n": len(u), "n_confirmed": len(k),
                              "dates": u.day.nunique(), "mean_bp": mu[0], "lo": mu[1], "hi": mu[2],
                              "confirmed_mean_bp": float(k[name].mean()) if len(k) else np.nan,
                              "diff_bp": du[0], "diff_lo": du[1], "diff_hi": du[2]})
        for tr in cfg.TRADES:
            ex = tr.exit
            for r in ev.itertuples():
                if tr.only_unconfirmed and r.confirmed:
                    continue
                rd = r._asdict()
                ok_in, ok_out = rd.get(f"q_{cfg.ENTRY}_ok"), rd.get(f"q_{ex}_ok")
                if not (ok_in is True and ok_out is True):
                    continue
                qi = {k: rd[f"q_{cfg.ENTRY}_{k}"] for k in ("bid", "ask")}
                qo = {k: rd[f"q_{ex}_{k}"] for k in ("bid", "ask")}
                side = r.d if tr.direction == "follow" else -r.d
                for cm in cfg.COST_MULTIPLIERS:
                    tres = trade_return(qi, qo, side, cm)
                    trades.append({"trade": tr.id, "threshold": thr, "cost_mult": cm, "segment": r.segment, "day": r.day, "ticker": r.ticker,
                                   "theme": r.theme, "weekend": r.weekend, "question": r.question, "x": r.x, "d": r.d,
                                   "side": "long" if side > 0 else "short", "gap_bp": r.gap, "confirmed": r.confirmed, **tres,
                                   "pnl": cfg.NOTIONAL * tres["net_bp"] / 1e4,
                                   "touch_size_usd": (rd[f"q_{cfg.ENTRY}_ask_size"] * rd[f"q_{cfg.ENTRY}_ask"] if side > 0
                                                      else rd[f"q_{cfg.ENTRY}_bid_size"] * rd[f"q_{cfg.ENTRY}_bid"])})
    from .report import report
    report(pd.concat(allev, ignore_index=True), pd.DataFrame(stats), pd.DataFrame(trades), sess, meta, c, t_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
