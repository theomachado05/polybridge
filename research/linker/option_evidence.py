"""Does the listed option react to the prediction market? Evidence for a link, not a trade (linker/heldout2/PLAN.md, 7).

For each link and each calendar month of its life inside 2025-10-01..2026-10-02, one call and one put:
    strike   nearest the instrument's last close of the previous month (cached daily bars, `day_<TICKER>.npz`);
             only strikes listed with both a call and a put. Those bars are split-adjusted while the contract list is
             not, so every split executed after that close (Massive /v3/reference/splits, cached as
             `splits_<T>.npz`) is undone first: an adjusted close carries later splits, which is look-ahead and
             picks the wrong strike (XLE split 1-for-2 on 2025-12-05: its adjusted close of 2025-11-03 reads 44.07
             against a real 88). A pair whose strike is more than 10% away from that spot is not used; the month is
             skipped and named in `note`. A split inside the month retires the month's contracts from its date, so
             the month's later days drop out (never filled) and the month is named in `note`.
    expiry   the first standard monthly expiry (third Friday) at least 30 days after the month begins; weekly
             expiries trade too thinly to give an open and a close on most days. If no monthly expiry is
             listed in range, the first listed expiry
Nothing dated inside the month chooses the contract. Daily bars per contract come from Massive and are cached as
`linker/.cache/opt_<contract without "O:">.npz` (day, open, close, volume); the month's choice as `optpair_<T>_<YYYY-MM>.npz`.

Per session day, on days when both legs traded on that day and on the previous session (missing days are dropped,
never filled):
    direction  overnight return of the directional leg (call for up_on_yes, put for down_on_yes), previous close to
               open, in bp, on the overnight move of the signal in points signed so that a positive move is one the
               leg should gain from. The benchmark's direction-signed move (link_days' x_night) is positive when the
               underlying should rise, which a put loses from; so the put's regressor is -x_night (for both legs
               this is the plain move of the signal, "yes" rising). Without this, every put link that works would
               read "contradicted". Through-origin slope, errors clustered by date (s4 engine.clustered_slope), as
               the plan says. The same fit with an intercept is reported next to it, not used for the verdict.
    size       overnight return of the straddle, (call open + put open) / (call close + put close the session before)
               - 1, in bp, on the absolute overnight move. This one is fitted WITH an intercept: an at-the-money
               straddle loses value every night (theta, weekends) whatever the odds do, and the regressor is never
               negative, so a through-origin fit would load that drift onto the slope and read decay as
               "contradicted". The slope comes from the date-clustered fit on demeaned data (same slope and
               clustered error as the fit with an intercept, by Frisch-Waugh-Lovell).
Verdicts: t >= 2 confirmed, t <= -2 contradicted, unproven in between, under 30 days untestable.

The signal's overnight move is the equity benchmark's: linker.signal.series for a link with a "signal" column (the
single market's odds if that module is absent), then s4 engine.link_days with the link's direction. No position is
sized, no cost is charged and no profit is computed.

Run from `research/` (never on heldout2 before its evaluation runs):
    python -m linker.option_evidence --study benchmark|dev|heldout2 [--limit N]
Writes results/linker/option_evidence_<study>.csv and .json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from s4_linked_assets import data as d4
from s4_linked_assets import engine as en

from . import store
from .benchmark import MIN_DAYS, OUT

HERE = store.HERE
WINDOW = ("2025-10-01", "2026-10-02")
EXPIRY_MIN_DAYS = 30
MAX_STRIKE_GAP = 0.10                 # |strike / spot - 1| above this: the month is skipped, not traded on a far pair
CHAIN_SPAN_DAYS = 45                  # how far past the earliest allowed expiry the reference list is read
LIQUID = ("USO", "XLE", "IBIT", "TLT", "GLD", "QQQ", "IWM", "XOP", "EWZ", "FXI", "SLV", "HYG")
NY = "America/New_York"


# ---------------------------------------------------------------- contract choice (pure)

def months_between(first_day: str, last_day: str, window: tuple[str, str] = WINDOW) -> list[str]:
    """Calendar months (YYYY-MM) from first_day to last_day, clipped to the window."""
    a, b = max(first_day, window[0]), min(last_day, window[1])
    if a > b:
        return []
    return [p.strftime("%Y-%m") for p in pd.period_range(a[:7], b[:7], freq="M")]


def spot_before(day: np.ndarray, close: np.ndarray, month: str) -> float:
    """The last close strictly before the month begins (NaN if none)."""
    i = int(np.searchsorted(np.asarray(day, dtype=str), f"{month}-01", side="left")) - 1
    return float(close[i]) if i >= 0 else float("nan")


def split_factor(after_day: str, splits: dict | None) -> float:
    """Undoes split adjustment for a price dated `after_day`: the product of split_to / split_from over the splits
    executed after that day (adjusted price x factor = the price as it traded then)."""
    if splits is None or len(splits["execution_date"]) == 0:
        return 1.0
    ex = np.asarray(splits["execution_date"], dtype=str)
    later = ex > after_day
    return float(np.prod(np.asarray(splits["split_to"], float)[later] / np.asarray(splits["split_from"], float)[later]))


def raw_spot_before(day: np.ndarray, close: np.ndarray, month: str, splits: dict | None) -> float:
    """spot_before on split-adjusted closes, put back in the prices of its own date (splits after it undone)."""
    dd = np.asarray(day, dtype=str)
    i = int(np.searchsorted(dd, f"{month}-01", side="left")) - 1
    return float(close[i]) * split_factor(dd[i], splits) if i >= 0 else float("nan")


def splits_in_month(month: str, splits: dict | None) -> bool:
    return splits is not None and any(str(e)[:7] == month for e in np.asarray(splits["execution_date"], dtype=str))


def strike_too_far(strike: float, spot: float) -> bool:
    return not (np.isfinite(spot) and spot > 0 and abs(strike / spot - 1) <= MAX_STRIKE_GAP)


def is_monthly(expiry: str) -> bool:
    """The standard monthly expiry: the third Friday of its month."""
    d = date.fromisoformat(expiry)
    return d.weekday() == 4 and 15 <= d.day <= 21


def pick_pair(chain: list[dict], spot: float, month: str) -> dict | None:
    """Call and put at the strike nearest `spot` (lower strike on a tie) in the first monthly expiry at least 30 days
    after the month begins (the first listed expiry if no monthly one is in range), among standard (100-share)
    contracts listed with both a call and a put at that strike."""
    if not np.isfinite(spot):
        return None
    lo = (date.fromisoformat(f"{month}-01") + timedelta(days=EXPIRY_MIN_DAYS)).isoformat()
    rows = [r for r in chain if r.get("shares_per_contract", 100) == 100 and r["expiration_date"] >= lo]
    for expiry in sorted({r["expiration_date"] for r in rows}, key=lambda e: (not is_monthly(e), e)):
        legs: dict[float, dict[str, str]] = {}
        for r in rows:
            if r["expiration_date"] == expiry:
                legs.setdefault(float(r["strike_price"]), {})[r["contract_type"]] = r["ticker"]
        both = [k for k, v in legs.items() if "call" in v and "put" in v]
        if both:
            k = min(both, key=lambda s: (abs(s - spot), s))
            return {"month": month, "expiry": expiry, "strike": k, "spot": spot, "call": legs[k]["call"], "put": legs[k]["put"]}
    return None


# ---------------------------------------------------------------- returns (pure)

def overnight(days: list[str], bars: dict | None) -> np.ndarray:
    """Per session day: open(d) / close(previous session) - 1, NaN unless the contract traded on both days."""
    out = np.full(len(days), np.nan)
    if bars is None or len(bars["day"]) == 0:
        return out
    o = dict(zip(np.asarray(bars["day"], dtype=str), np.asarray(bars["open"], dtype=float)))
    c = dict(zip(np.asarray(bars["day"], dtype=str), np.asarray(bars["close"], dtype=float)))
    for i in range(1, len(days)):
        if days[i] in o and days[i - 1] in c and c[days[i - 1]] > 0:
            out[i] = o[days[i]] / c[days[i - 1]] - 1.0
    return out


def straddle_overnight(days: list[str], call: dict | None, put: dict | None) -> np.ndarray:
    """(call open + put open) / (call close + put close of the previous session) - 1, NaN unless both legs traded on
    both days."""
    out = np.full(len(days), np.nan)
    if call is None or put is None:
        return out
    m = [(dict(zip(np.asarray(b["day"], dtype=str), np.asarray(b["open"], dtype=float))),
          dict(zip(np.asarray(b["day"], dtype=str), np.asarray(b["close"], dtype=float)))) for b in (call, put)]
    for i in range(1, len(days)):
        d, p = days[i], days[i - 1]
        if all(d in o and p in c for o, c in m):
            den = m[0][1][p] + m[1][1][p]
            if den > 0:
                out[i] = (m[0][0][d] + m[1][0][d]) / den - 1.0
    return out


def verdict(t: float, days: int) -> str:
    if days < MIN_DAYS or not np.isfinite(t):
        return "untestable"
    return "confirmed" if t >= 2 else "contradicted" if t <= -2 else "unproven"


def slopes(x: np.ndarray, r_dir: np.ndarray, r_str: np.ndarray, days: np.ndarray) -> dict:
    """Both tests on the days when both legs traded. x is the overnight move in points, signed so the directional leg
    should gain when x > 0 (|x| is the same either way); returns in fractions (reported in bp)."""
    ok = np.isfinite(x) & np.isfinite(r_dir) & np.isfinite(r_str)
    x, yd, ys, g = x[ok], 1e4 * r_dir[ok], 1e4 * r_str[ok], days[ok]
    d = en.clustered_slope(x, yd, g)
    a = np.abs(x)
    di = en.clustered_slope(x - x.mean(), yd - yd.mean(), g) if len(x) else d
    si = en.clustered_slope(a - a.mean(), ys - ys.mean(), g) if len(x) else d
    n = int(ok.sum())
    icpt = float(ys.mean() - si["slope"] * a.mean()) if n and np.isfinite(si["slope"]) else float("nan")
    return {"days": n, "nights_with_a_move": int(np.sum(x != 0)),
            "dir_bp_per_point": d["slope"], "dir_t": d["t"], "dir_verdict": verdict(d["t"], n),
            "dir_bp_per_point_with_intercept": di["slope"], "dir_t_with_intercept": di["t"],
            "straddle_bp_per_abs_point": si["slope"], "straddle_t": si["t"], "straddle_intercept_bp": icpt,
            "straddle_verdict": verdict(si["t"], n)}


# ---------------------------------------------------------------- Massive (cached)

def _scrub(e: Exception, s) -> str:
    msg = repr(e)[:200]
    key = s.headers.get("Authorization", "") if s is not None else ""
    if key:
        msg = msg.replace(key, "<key>").replace(key.split(" ")[-1], "<key>")
    return msg


def chain(s, base: str, ticker: str, month: str) -> list[dict]:
    """Contracts on `ticker` expiring 30 to 75 days after the month begins, as listed the day before it begins.
    With `as_of` Massive returns the contracts live on that date (expired=false); strikes added later in the month
    are not seen, so they cannot be chosen. (Without `as_of`, past expiries need expired=true and include them.)"""
    m0 = date.fromisoformat(f"{month}-01")
    p = {"underlying_ticker": ticker, "expiration_date.gte": (m0 + timedelta(days=EXPIRY_MIN_DAYS)).isoformat(),
         "expiration_date.lte": (m0 + timedelta(days=EXPIRY_MIN_DAYS + CHAIN_SPAN_DAYS)).isoformat(),
         "as_of": (m0 - timedelta(days=1)).isoformat(), "expired": "false", "limit": 1000}
    return d4.massive_rows(s, f"{base}/v3/reference/options/contracts", p)


def splits(s, base: str, ticker: str) -> dict:
    """Every split of `ticker` (execution_date, split_from, split_to), cached as splits_<T>.npz."""
    name = f"splits_{ticker}.npz"
    c = store.npz(name)
    if c is None:
        rows = d4.massive_rows(s, f"{base}/v3/reference/splits", {"ticker": ticker, "limit": 1000})
        rows = sorted((r for r in rows if r.get("execution_date") and r.get("split_from") and r.get("split_to")),
                      key=lambda r: r["execution_date"])
        store.save(name, execution_date=np.array([r["execution_date"] for r in rows], dtype="U10"),
                   split_from=np.array([float(r["split_from"]) for r in rows]),
                   split_to=np.array([float(r["split_to"]) for r in rows]))
        c = store.npz(name)
    return c


def month_pair(s, base: str, ticker: str, month: str, spot: float) -> dict | None:
    """The month's pair, cached with the spot it was chosen on; a cache made on another spot is chosen again."""
    name = f"optpair_{ticker}_{month}.npz"
    c = store.npz(name)
    if c is None or "spot" not in c or not np.isclose(float(c["spot"]), spot, rtol=1e-9, equal_nan=True):
        pr = pick_pair(chain(s, base, ticker, month), spot, month)
        store.save(name, spot=np.array(float(spot)),
                   **{k: np.array(str((pr or {}).get(k, ""))) for k in ("expiry", "strike", "call", "put")})
        c = store.npz(name)
    if not str(c["call"]):
        return None
    return {"month": month, "expiry": str(c["expiry"]), "strike": float(str(c["strike"])), "spot": spot,
            "call": str(c["call"]), "put": str(c["put"])}


def contract_bars(s, base: str, contract: str, month: str, expiry: str) -> dict:
    """Daily bars of one contract from 10 days before the month to the end of the month (or expiry), cached."""
    name = f"opt_{contract.replace('O:', '')}.npz"
    c = store.npz(name)
    if c is not None:
        return c
    lo = (date.fromisoformat(f"{month}-01") - timedelta(days=10)).isoformat()
    hi = min((pd.Timestamp(f"{month}-01") + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d"), expiry, WINDOW[1])
    rows = d4.massive_rows(s, f"{base}/v2/aggs/ticker/{contract}/range/1/day/{lo}/{hi}",
                           {"adjusted": "false", "sort": "asc", "limit": 5000})
    day = [pd.Timestamp(r["t"], unit="ms", tz="UTC").tz_convert(NY).strftime("%Y-%m-%d") for r in rows]
    store.save(name, day=np.array(day, dtype="U10"), open=np.array([float(r["o"]) for r in rows]),
               close=np.array([float(r["c"]) for r in rows]), volume=np.array([float(r.get("v") or 0) for r in rows]))
    return store.npz(name)


# ---------------------------------------------------------------- the signal

def signal_odds(link: dict) -> dict | None:
    """(t, p) of the link's signal: linker.signal.series on the "signal" column when both exist, else the market's odds."""
    raw = link.get("signal")
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            from . import signal as sg              # written by another agent; optional
            out = sg.series(json.loads(raw))
            t, p = (out["t"], out["p"]) if isinstance(out, dict) else out
            return {"t": np.asarray(t, dtype=np.int64), "p": np.asarray(p, dtype=float)}
        except (ImportError, AttributeError):
            pass
    return store.npz(f"pm_{str(link['market']).split(':')[-1]}.npz")


def night_moves(pm: dict, direction: str, sess: pd.DataFrame) -> np.ndarray:
    """Direction-signed overnight move in points, through the benchmark's own path (engine.link_days). The equity
    legs of link_days are not used here, so they are given as NaN."""
    n = len(sess)
    blank = {"px": np.full((n, 2), np.nan), "close": np.full(n, np.nan)}
    ld = en.link_days(pm["t"], pm["p"].astype(float), 1 if direction == "up_on_yes" else -1, sess, blank, blank, np.ones(n))
    return ld.x_night


# ---------------------------------------------------------------- one link

def link_evidence(link: dict, sess: pd.DataFrame, s=None, base: str = "", fetch=None) -> dict:
    """The row for one link. `fetch(kind, *args)` replaces Massive in tests: kind is "splits", "pair" or "bars"."""
    row = {k: link.get(k) for k in ("source", "linker", "cluster", "market", "question", "ticker", "direction", "verdict", "score")}
    row["equity_verdict"] = row.pop("verdict")
    days = list(sess.day)
    pm, dayb = signal_odds(link), store.npz(f"day_{link['ticker']}.npz")
    empty = {"months": 0, "contracts": 0, "session_days": 0, "days": 0, "dir_verdict": "untestable", "straddle_verdict": "untestable"}
    if pm is None or len(pm["t"]) == 0 or dayb is None:
        return {**row, **empty, "note": "no odds" if pm is None or len(pm["t"]) == 0 else "no daily bars"}
    x = night_moves(pm, link["direction"], sess)
    live = [d for d, v in zip(days, x) if np.isfinite(v)]
    if not live:
        return {**row, **empty, "note": "no overnight move"}
    fetch = fetch or (lambda kind, *a: splits(s, base, *a) if kind == "splits"
                      else month_pair(s, base, *a) if kind == "pair" else contract_bars(s, base, *a))
    sp = fetch("splits", link["ticker"])
    mon = np.array([d[:7] for d in days])
    r_call, r_put, r_str = (np.full(len(days), np.nan) for _ in range(3))
    used, months, notes = set(), 0, []
    for m in months_between(live[0], live[-1]):
        spot = raw_spot_before(dayb["day"], dayb["c"], m, sp)
        pr = fetch("pair", link["ticker"], m, spot)
        if pr is None:
            continue
        if strike_too_far(float(pr["strike"]), spot):
            notes.append(f"{m} skipped: strike {pr['strike']:g} vs spot {spot:.2f}")
            continue
        if splits_in_month(m, sp):
            notes.append(f"{m} split inside the month: later days dropped")
        months += 1
        cb, pb = fetch("bars", pr["call"], m, pr["expiry"]), fetch("bars", pr["put"], m, pr["expiry"])
        used |= {pr["call"], pr["put"]}
        inm = mon == m
        ex = [str(e) for e in np.asarray(sp["execution_date"], dtype=str) if str(e)[:7] == m] if sp is not None else []
        if ex:                                            # from the split on, the month's contracts are retired
            inm = inm & (np.array(days) < min(ex))
        r_call[inm], r_put[inm] = overnight(days, cb)[inm], overnight(days, pb)[inm]
        r_str[inm] = straddle_overnight(days, cb, pb)[inm]
    in_life = np.isfinite(x) & np.isin(mon, months_between(live[0], live[-1]))
    r_dir = r_call if link["direction"] == "up_on_yes" else r_put
    n0 = int(in_life.sum())
    share = (lambda r: float(np.mean(np.isfinite(r[in_life]))) if n0 else float("nan"))
    leg_sign = 1.0 if link["direction"] == "up_on_yes" else -1.0      # a put gains when the underlying falls
    st = slopes(np.where(in_life, leg_sign * x, np.nan), r_dir, r_str, np.array(days))
    return {**row, "months": months, "contracts": len(used), "session_days": n0, "share_call_traded": share(r_call),
            "share_put_traded": share(r_put), "share_both_traded": share(r_str), **st, "note": "; ".join(notes)}


# ---------------------------------------------------------------- inputs and outputs

def load_links(study: str) -> list[dict]:
    """Benchmark: confirmed two-model S5 links. A study: every testable version-3 event link, whatever its equity
    verdict (PLAN 7), the probe left out."""
    if study == "benchmark":
        df = pd.read_csv(OUT / "benchmark_scored.csv")
        df = df[df.source.str.startswith("S5") & (df.two_models == 1) & (df.verdict == "confirmed")]
    else:
        f = OUT / f"{'dev_v3' if study == 'dev' else study}_links.csv"
        if not f.exists():
            return []
        df = pd.read_csv(f)
        df = df[df.linker.astype(str).str.startswith("v3") & (df.verdict != "untestable")]
        if "kind" in df:
            df = df[df.kind.astype(str) == "event"]
        if "probe" in df:
            df = df[~df.probe.astype(str).str.lower().isin(("true", "1"))]
    return df.to_dict("records")


def prefer_liquid(links: list[dict], n: int) -> list[dict]:
    """For --limit: one link per liquid underlying first (in LIQUID order, the highest t of each), then the rest."""
    rank = {t: i for i, t in enumerate(LIQUID)}
    srt = sorted(links, key=lambda l: (rank.get(l["ticker"], len(LIQUID)), -float(l.get("gap_t") or 0)))
    first, seen = [], set()
    for l in srt:
        if l["ticker"] not in seen:
            first.append(l)
            seen.add(l["ticker"])
    rest = [l for l in srt if not any(l is f for f in first)]
    return (first + rest)[:n]


def instrument_class() -> dict[str, str]:
    f = HERE / "instruments.json"
    if not f.exists():
        return {}
    d = json.loads(f.read_text())
    if isinstance(d, dict) and isinstance(d.get("classes"), dict):          # {"classes": {class: [{"ticker", ...}]}}
        return {r["ticker"]: c for c, rs in d["classes"].items() for r in rs if isinstance(r, dict) and "ticker" in r}
    items = d.get("instruments", d) if isinstance(d, dict) else d
    if isinstance(items, dict):
        return {k: (v.get("class") or v.get("kind") or "") if isinstance(v, dict) else str(v) for k, v in items.items()}
    return {r["ticker"]: str(r.get("class") or r.get("kind") or "") for r in items if isinstance(r, dict) and "ticker" in r}


def counts(df: pd.DataFrame) -> dict:
    out = {"links": int(len(df))}
    for k in ("dir", "straddle"):
        v = df[f"{k}_verdict"] if len(df) else pd.Series(dtype=str)
        out[k] = {"testable": int((v != "untestable").sum()), "confirmed": int((v == "confirmed").sum()),
                  "contradicted": int((v == "contradicted").sum())}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", choices=("benchmark", "dev", "heldout2"), required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    links = load_links(a.study)
    if not links:
        print(f"no links for {a.study} yet")
        return 0
    if a.limit:
        links = prefer_liquid(links, a.limit)
    spy = store.npz("eq_SPY.npz")
    sess = en.sessions_from(spy["t"])          # months outside WINDOW are never used (months_between clips)
    s, base = d4._massive_session()
    rows = []
    for l in links:
        try:
            r = link_evidence(l, sess, s, base)
        except Exception as e:  # noqa: BLE001  one bad link must not stop the run; the message never carries the key
            r = {k: l.get(k) for k in ("market", "question", "ticker", "direction")} | {
                "days": 0, "dir_verdict": "untestable", "straddle_verdict": "untestable", "note": _scrub(e, s)}
        rows.append(r)
        print(f"{r['ticker']:5} {r['direction']:11} months {r.get('months', 0):2} days {r.get('days', 0):3} "
              f"dir {r.get('dir_bp_per_point', float('nan')):8.1f} bp/pt t {r.get('dir_t', float('nan')):5.2f} {r['dir_verdict']:11} "
              f"straddle {r.get('straddle_bp_per_abs_point', float('nan')):8.1f} t {r.get('straddle_t', float('nan')):5.2f} "
              f"{r['straddle_verdict']:11} {str(r.get('question'))[:50]} {r.get('note', '')}", flush=True)
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"option_evidence_{a.study}.csv", index=False)
    res = {"study": a.study, "written": datetime.now(timezone.utc).isoformat(timespec="seconds"), **counts(df)}
    cls = instrument_class()
    if cls:
        res["by_instrument_class"] = {c: counts(g) for c, g in df.assign(cls=df.ticker.map(cls).fillna("unknown")).groupby("cls")}
    (OUT / f"option_evidence_{a.study}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
