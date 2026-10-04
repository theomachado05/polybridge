"""Ladder replay engine (METHOD steps 1 and 2): gamma texts, the nesting rule, taker prints, the causal walk, metrics."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from s1_twin_spread import data as ds
from s11_bundles import config as s11cfg
from s11_bundles.engine import fee
from s11_bundles.universe import parse_date

from . import config as cfg

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
NY = ZoneInfo("America/New_York")
PT = ds.Throttle(cfg.REQ_RATE)


def ny_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, NY).date().isoformat()


def ts_of(s) -> float | None:
    if not s:
        return None
    s = str(s).replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


# ---------------------------------------------------------------- gamma records

def gamma_markets(ids: list[str]) -> dict[str, dict]:
    path = CACHE / "gamma"
    path.mkdir(parents=True, exist_ok=True)
    out, need = {}, []
    for i in ids:
        f = path / f"{i}.json"
        if f.exists():
            out[i] = json.loads(f.read_text())
        else:
            need.append(i)

    def get(chunk):
        got = []
        for closed in ("true", "false"):
            d = ds.get_json(f"{ds.GAMMA}/markets", [("id", x) for x in chunk] + [("closed", closed), ("limit", 100)], throttle=PT)
            got += d if isinstance(d, list) else []
        return got

    chunks = [need[k:k + 25] for k in range(0, len(need), 25)]
    with ThreadPoolExecutor(3) as ex:
        for got in ex.map(get, chunks):
            for m in got:
                m["_event_resolutionSource"] = ((m.get("events") or [{}])[0] or {}).get("resolutionSource") or ""
                m.pop("events", None)
                (path / f"{m['id']}.json").write_text(json.dumps(m))
                out[str(m["id"])] = m
    return out


def result_of(m: dict) -> float | None:
    if not m or not m.get("closed"):
        return None
    try:
        p = json.loads(m.get("outcomePrices") or "null")
    except ValueError:
        return None
    if not p:
        return None
    y = float(p[0])
    return y if y in (0.0, 0.5, 1.0) else None


def fee_of(m: dict) -> tuple[float, float]:
    fs = m.get("feeSchedule") or {}
    if not m.get("feesEnabled") or not fs:
        return 0.0, 1.0
    return float(fs.get("rate", 0.0)), float(fs.get("exponent", 1))


def tick_of(m: dict) -> float:
    try:
        return float(m.get("orderPriceMinTickSize") or cfg.DEFAULT_TICK)
    except (TypeError, ValueError):
        return cfg.DEFAULT_TICK


# ---------------------------------------------------------------- step 1: nesting rule

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def date_spellings(d: date) -> list[str]:
    m_full, m_abbr = d.strftime("%B").lower(), d.strftime("%b").lower()
    day = d.day
    suf = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    out = []
    for mo in (m_full, m_abbr + ".", m_abbr):
        for dd in (f"{day}{suf}", str(day)):
            out += [f"{mo} {dd}, {d.year}", f"{mo} {dd} {d.year}", f"{mo} {dd}"]
        out += [f"{day} {mo} {d.year}", f"{day} {mo}"]
    last = date(d.year + (d.month == 12), d.month % 12 + 1, 1).toordinal() - 1 == d.toordinal()
    if last:
        out += [f"end of {m_full} {d.year}", f"end of {m_full}", f"{m_full} {d.year}"]
    out += [d.isoformat(), f"{d.month}/{d.day}/{d.year}", f"{d.month}/{d.day}"]
    return sorted(set(out), key=len, reverse=True)


def level_spellings(v: float) -> list[str]:
    outs = set()
    for base in (v, v / 1e3, v / 1e6, v / 1e9):
        if base < 1 and base != v:
            continue
        s = f"{base:,.10f}".rstrip("0").rstrip(".")
        s2 = s.replace(",", "")
        suf = "" if base == v else {v / 1e3: "k", v / 1e6: "m", v / 1e9: "b"}.get(base, "")
        for x in {s, s2}:
            for cur in ("$", ""):
                outs.add(f"{cur}{x}{suf}")
                if suf:
                    outs.add(f"{cur}{x} {dict(k='thousand', m='million', b='billion')[suf]}")
        if base == v:
            outs |= {f"${v:,.2f}", f"{v:,.2f}", f"{v:.2f}"}
    return sorted(outs, key=len, reverse=True)


def mask(text: str, spellings: list[str], placeholder: str) -> str:
    t = norm(text)
    for s in spellings:
        t = re.sub(r"(?<![\w.,$])" + re.escape(s) + r"(?![\w]|[.,]\d)", placeholder, t)
    return t


def rung_key(kind: str, bundle: dict, leg: str):
    k = bundle["keys"][bundle["legs"].index(leg)]
    return date.fromisoformat(k) if kind == "date" else float(k)


ORDER_CHECK = False                     # amendment 5 (post hoc): re-derive each date rung's deadline before trusting the ladder order


def deadline(m: dict, key: date) -> date | None:
    """The rung's own deadline: an explicit year in its question or groupItemTitle wins; otherwise the first year in which
    the month and day fall on or after the market's start date (a "by <date>" market is never created after its date)."""
    for txt in (m.get("groupItemTitle") or "", m.get("question") or ""):
        for ph in re.findall(s11cfg.DATE_RE, txt):
            y = re.search(r"20\d\d", ph)
            d = parse_date(ph, int(y.group(0))) if y else None
            if d is not None and (d.month, d.day) == (key.month, key.day):
                return d
    st = ts_of(m.get("startDate") or m.get("createdAt"))
    if st is None:
        return None
    s0 = datetime.fromtimestamp(st - 86400, timezone.utc).date()
    for y in (s0.year, s0.year + 1, s0.year + 2):
        try:
            d = date(y, key.month, key.day)
        except ValueError:
            continue
        if d >= s0:
            return d
    return None


def nested(kind: str, bundle: dict, rich: str, cheap: str, g: dict[str, dict]) -> tuple[bool, str]:
    a, b = g.get(rich), g.get(cheap)
    if not a or not b:
        return False, "no gamma record"
    if ORDER_CHECK and kind == "date":
        da_, db_ = deadline(a, rung_key(kind, bundle, rich)), deadline(b, rung_key(kind, bundle, cheap))
        if da_ is None or db_ is None or not da_ < db_:
            return False, "rung order wrong once each deadline's year is re-derived"
    sp = date_spellings if kind == "date" else level_spellings
    da = mask(a.get("description") or "", sp(rung_key(kind, bundle, rich)), "@k@")
    db = mask(b.get("description") or "", sp(rung_key(kind, bundle, cheap)), "@k@")
    if not da or not db:
        return False, "empty description"
    if da != db:
        return False, "descriptions differ"
    sa = norm(a.get("resolutionSource") or a.get("_event_resolutionSource"))
    sb = norm(b.get("resolutionSource") or b.get("_event_resolutionSource"))
    if sa != sb:
        return False, "sources differ"
    if re.search(r"market(?:'s|’s)? creation|market (?:was|is) created|creation of (?:this|the) market", da):
        ta, tb = ts_of(a.get("startDate") or a.get("createdAt")), ts_of(b.get("startDate") or b.get("createdAt"))
        if ta is None or tb is None or tb > ta + 60:
            return False, "window starts at creation and the cheap rung was created later"
    return True, "nested"


# ---------------------------------------------------------------- prints

def prints(m: dict) -> dict | None:
    """Taker prints of a market in YES terms: t, price, +1 YES purchase / -1 YES sale, size. Paged back by `end`."""
    cid = m.get("conditionId")
    if not cid:
        return None
    path = CACHE / "prints"
    path.mkdir(parents=True, exist_ok=True)
    f = path / f"{cid}.npz"
    if f.exists():
        z = np.load(f)
        return {k: z[k] for k in z.files}
    toks = json.loads(m["clobTokenIds"]) if isinstance(m.get("clobTokenIds"), str) else (m.get("clobTokenIds") or [])
    toks = [str(t) for t in toks] + ["", ""]
    oldest_needed = datetime.fromisoformat(cfg.WINDOW_START).replace(tzinfo=NY).timestamp()
    T, P, S, Z, seen = [], [], [], [], set()
    end, n_req, truncated = None, 0, False
    while True:
        p = {"market": cid, "limit": cfg.PRINT_PAGE}
        if end is not None:
            p["end"] = end
        d = ds.get_json(ds.DATA_API, p, throttle=PT, allow=(400, 404))
        n_req += 1
        if not isinstance(d, list) or not d:
            break
        for x in d:
            key = (x.get("transactionHash"), x.get("asset"), x.get("side"), x.get("size"), x.get("price"), x.get("timestamp"))
            if key in seen:
                continue
            seen.add(key)
            asset, out = str(x.get("asset") or ""), str(x.get("outcome") or "").lower()
            if asset and asset in toks:
                is_no = asset == toks[1]
            elif out in ("yes", "no"):
                is_no = out == "no"
            else:
                continue
            px, sd = float(x["price"]), 1 if str(x.get("side")).upper() == "BUY" else -1
            if is_no:
                px, sd = 1.0 - px, -sd
            T.append(int(x["timestamp"]))
            P.append(px)
            S.append(sd)
            Z.append(float(x.get("size") or 0))
        oldest = int(d[-1]["timestamp"])
        if len(d) < cfg.PRINT_PAGE or oldest < oldest_needed:
            break
        if n_req >= cfg.MAX_PRINT_REQUESTS:
            truncated = True
            break
        end = oldest
    o = np.argsort(np.array(T, dtype=np.int64), kind="stable")
    z = {"t": np.array(T, dtype=np.int64)[o], "p": np.array(P, dtype=np.float64)[o], "s": np.array(S, dtype=np.int8)[o],
         "z": np.array(Z, dtype=np.float64)[o], "truncated": np.array(truncated), "requests": np.array(n_req)}
    np.savez(f, **z)
    return z


def prefetch(markets: list[dict], workers: int = 4) -> None:
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(prints, markets))


# ---------------------------------------------------------------- step 2: causal walk

def candidates(pa: dict, pb: dict, ma: dict, mb: dict, t_lo: float, t_hi: float) -> list[tuple]:
    """Every (completion time, edge, size, fill_a, fill_b, fees) where a YES-sale print on A and a YES-purchase print on B
    within the window lock in money after ticks and fees. Completion time = the later print's time (both known then)."""
    ta_, tb_ = tick_of(ma), tick_of(mb)
    fa, fb = fee_of(ma), fee_of(mb)
    sa = pa["s"] == -1
    sb = pb["s"] == 1
    tA, aA, zA = pa["t"][sa], pa["p"][sa] - cfg.TICKS_AGAINST * ta_, pa["z"][sa]
    tB, bB, zB = pb["t"][sb], pb["p"][sb] + cfg.TICKS_AGAINST * tb_, pb["z"][sb]
    kA = (aA > 0) & (tA >= t_lo) & (tA < t_hi + cfg.PAIR_WINDOW_S)
    kB = (bB < 1) & (tB >= t_lo - cfg.PAIR_WINDOW_S) & (tB < t_hi + cfg.PAIR_WINDOW_S)
    tA, aA, zA, tB, bB, zB = tA[kA], aA[kA], zA[kA], tB[kB], bB[kB], zB[kB]
    if not len(tA) or not len(tB):
        return []
    feeA, feeB = fee(aA, *fa), fee(bB, *fb)
    rA, cB = aA - feeA, bB + feeB
    out = []
    lo = np.searchsorted(tB, tA - cfg.PAIR_WINDOW_S, "left")
    hi = np.searchsorted(tB, tA + cfg.PAIR_WINDOW_S, "right")
    for i in np.nonzero(hi > lo)[0]:
        sl = slice(lo[i], hi[i])
        e = rA[i] - cB[sl]
        for j in np.nonzero(e > 0)[0]:
            jj = lo[i] + j
            tc = max(tA[i], tB[jj])
            if t_lo <= tc < t_hi:
                out.append((int(tc), float(e[j]), float(min(zA[i], zB[jj])), float(aA[i]), float(bB[jj]), float(feeA[i]), float(feeB[jj]),
                            int(tA[i]), int(tB[jj])))
    out.sort(key=lambda x: (x[0], -x[1]))
    return out


def walk(all_cands: list[tuple]) -> list[dict]:
    """all_cands: (pair_id, candidate). Time order; pair cooldown; day cap, first come first served."""
    all_cands.sort(key=lambda x: (x[1][0], -x[1][1]))
    last, per_day, trades = {}, {}, []
    for pid, c in all_cands:
        tc = c[0]
        if pid in last and tc - last[pid] < cfg.PAIR_COOLDOWN_S:
            continue
        d = ny_date(tc)
        if per_day.get(d, 0) >= cfg.MAX_NEW_TRADES_PER_DAY:
            continue
        last[pid] = tc
        per_day[d] = per_day.get(d, 0) + 1
        trades.append({"pair": pid, "t_entry": tc, "date": d, "edge": c[1], "print_size": c[2], "size": min(c[2], cfg.MAX_CONTRACTS),
                       "fill_rich": c[3], "fill_cheap": c[4], "fee_rich": c[5], "fee_cheap": c[6], "t_print_rich": c[7], "t_print_cheap": c[8]})
    return trades


def settle(tr: dict, ga: dict, gb: dict) -> dict:
    cap = (1 - tr["fill_rich"]) + tr["fill_cheap"] + tr["fee_rich"] + tr["fee_cheap"]
    ya, yb = result_of(ga), result_of(gb)
    if ya is not None and yb is not None:
        payoff, settled = (1 - ya) + yb, True
        lock_end = max(ts_of(ga.get("closedTime")) or 0, ts_of(gb.get("closedTime")) or 0) or ts_of(gb.get("endDate"))
    else:
        payoff, settled = 1.0, False
        lock_end = ts_of(gb.get("endDate")) or tr["t_entry"]
    lock_days = max(1.0, (lock_end - tr["t_entry"]) / 86400)
    pnl_c = payoff - cap
    return dict(tr, capital_per=cap, payoff=payoff, settled=settled, result_rich=ya, result_cheap=yb, lock_end=lock_end,
                lock_days=lock_days, pnl_points=100 * pnl_c, pnl_usd=tr["size"] * pnl_c, capital_usd=tr["size"] * cap,
                pnl_usd_uncapped=tr["print_size"] * pnl_c)


# ---------------------------------------------------------------- metrics

def boot(rows: list[dict]) -> tuple[float, float, float]:
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r["date"], []).append(r["pnl_points"])
    keys = sorted(by)
    if not keys:
        return (float("nan"),) * 3
    allv = [x for k in keys for x in by[k]]
    if len(keys) < 2:
        return float(np.mean(allv)), float("nan"), float("nan")
    rng = np.random.default_rng(cfg.BOOT_SEED)
    sums, cnts = np.array([sum(by[k]) for k in keys]), np.array([len(by[k]) for k in keys])
    pick = rng.integers(0, len(keys), size=(cfg.N_BOOT, len(keys)))
    means = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(np.mean(allv)), float(lo), float(hi)


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"trades": 0}
    mean, lo, hi = boot(rows)
    pnl = sum(r["pnl_usd"] for r in rows)
    cap = sum(r["capital_usd"] for r in rows)
    cap_years = sum(r["capital_usd"] * r["lock_days"] / 365 for r in rows)
    months: dict[str, list[float]] = {}
    for r in rows:
        mth = datetime.fromtimestamp(r["lock_end"], NY).strftime("%Y-%m")
        x = months.setdefault(mth, [0.0, 0.0])
        x[0] += r["pnl_usd"]
        x[1] += r["capital_usd"]
    ks = sorted(months)
    allm, y, mo = [], int(ks[0][:4]), int(ks[0][5:])
    while f"{y:04d}-{mo:02d}" <= ks[-1]:
        k = f"{y:04d}-{mo:02d}"
        allm.append(months[k][0] / months[k][1] if k in months and months[k][1] > 0 else 0.0)
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    mr = np.array(allm)
    sharpe = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if len(mr) > 2 and mr.std(ddof=1) > 0 else float("nan")
    ev = sorted(rows, key=lambda r: r["lock_end"])
    cum = np.cumsum([r["pnl_usd"] for r in ev])
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0], cum])) - np.concatenate([[0], cum])))
    pts = sorted([(r["t_entry"], r["capital_usd"]) for r in rows] + [(r["lock_end"], -r["capital_usd"]) for r in rows])
    peak = float(np.max(np.cumsum([c for _, c in pts]))) if pts else 0.0
    return {"trades": n, "pairs": len({r["pair"] for r in rows}), "dates": len({r["date"] for r in rows}),
            "pnl_points_mean": mean, "ci_lo": lo, "ci_hi": hi, "pnl_usd": pnl, "capital_usd": cap,
            "cap_weighted_return": pnl / cap if cap else float("nan"), "ann_return_locked": pnl / cap_years if cap_years else float("nan"),
            "sharpe_monthly": sharpe, "months": len(mr), "max_dd_usd": dd, "peak_capital_locked": peak,
            "max_dd_over_peak_capital": dd / peak if peak else float("nan"), "losers": sum(r["pnl_usd"] < -1e-9 for r in rows),
            "winners": sum(r["pnl_usd"] > 1e-9 for r in rows), "unsettled": sum(not r["settled"] for r in rows),
            "median_size": float(np.median([r["size"] for r in rows])), "size_under_5": sum(r["size"] < 5 for r in rows),
            "median_lock_days": float(np.median([r["lock_days"] for r in rows])),
            "pnl_usd_uncapped": sum(r["pnl_usd_uncapped"] for r in rows)}
