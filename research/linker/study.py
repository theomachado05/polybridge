"""Second held-out test of the link agent, and its development run (linker/heldout2/PLAN.md sections 3 to 6 and 9).

Links come from linker/signal.py (version 3, by event; price-proxy links apart) and, where its labels exist, from the
control arm (two blind labellers, S5's ticker list, a link per question both called an event). Each link is scored as
linker/benchmark.py scores one, always on its own signal: the through-origin slope of the instrument's excess opening
gap on the direction-signed overnight move of the signal, errors clustered by date; next to it the robust verdict
(30 days, 10 nights with a move of a point or more, t from HC3 errors) and the slope before and from 2026-07-01.
Every block of PLAN section 5 is written to the results JSON.

How alive the odds are (odds_share_between_10_and_90, an input of every scorer) is read from the main leg's own odds,
never from a weighted sum, which is not a probability. A cluster is recalled (PLAN 9) when the recall agent answered
its main question (universe "main") right; every link of the cluster carries the flag. An off-list ticker counts only
when Massive serves it as a stock, an ADR, an ETF or an ETV (OFF_TYPES); the kept ones are listed for a manual check.

The fresh set (heldout2) is pulled and scored only when no frozen file changed (linker/freeze.py), or when every
changed file is named in --amended (as listed in a dated amendment of the plan).

Run from `research/` (S is dev or heldout2):
    python -m linker.study pull --study S [--amended a.py,b.py]   # odds and bars for every linked signal and ticker
    python -m linker.study --study S [--amended a.py,b.py]        # writes results/linker/<dev_v3|heldout2>.json, _links.csv
    python -m linker.study --study h1check                        # the control-arm path on the first held-out set
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s1_twin_spread.engine import asof
from s4_linked_assets import engine as en
from s5_big_moves import config as c5
from s5_big_moves import granular as g5
from s5_big_moves import run as r5

from . import freeze
from . import instruments as ins
from . import scorer as sc
from . import signal as sg
from . import store
from .benchmark import MIN_DAYS, OUT, link_stats, verdict

UTC = timezone.utc
NAMES = {"dev": "dev_v3", "heldout2": "heldout2", "h1check": "h1check"}
V3, CONTROL = "v3, by event", "control, by event"
EVENT, PROXY = "event", "price proxy"
PROBE_MARKET = "polymarket:601826"
BRAZIL = frozenset("EWZ EWZS FLBR PBR VALE ITUB BBD BSBR ABEV SBS ERJ GGB SID CIG EBR SUZ UGP TIMB VIV NU XP STNE PAGS BAK".split())
BARS = {"confirmed_share_above": 9 / 21, "confirmed_at_least": 9, "contradicted_at_most": 0, "auc_v2_at_least": 0.85}
MIN_TESTABLE = 20
TRUST_SCORE = 0.5
MIN_NIGHTS_1PT = 10
CUTOFF = c5.KNOWLEDGE_CUTOFF_DAY
H1_OLD = {"links": 42, "testable": 21, "confirmed": 9, "contradicted": 0}
ODDS = ("odds_mean_abs_move", "odds_share_nights_1pt", "odds_share_between_10_and_90")
ODDS_MODEL = ("log_mean_abs_move", "share_nights_1pt", "share_between_10_and_90", "log_days")
TRAIN_V2 = OUT / "train_v2.csv"
YES, NO = 0.9, 0.1
THREADS, PM_RATE = 4, 4.0
OFF_TYPES = frozenset({"CS", "ADRC", "ETF", "ETV"})     # Massive's codes: common stock, ADR, ETF, ETV (the list's own types)
COLUMNS = ("source linker kind market question ticker direction confidence two_models links_on_question odds_mean_abs_move "
           "odds_share_nights_1pt odds_share_between_10_and_90 days nights_with_a_move gap_bp_per_point gap_t "
           "intraday_bp_per_point intraday_t nights_10pt gap_on_10pt_nights_bp verdict theme score cluster signal "
           "signal_range_points structure impact_pct mechanism_class alternative seen_ladder probe remembered recalled scored_on "
           "nights_1pt gap_t_hc3 verdict_robust days_before_cutoff gap_bp_per_point_before_cutoff gap_t_before_cutoff "
           "days_since_cutoff gap_t_since_cutoff gap_bp_per_point_since_cutoff verdict_since_cutoff score_v1 score_v2 score_odds "
           "main_market").split()


def out_name(study: str | Path) -> str:
    return NAMES.get(study, sg.universe_name(study)) if isinstance(study, str) else sg.universe_name(study)


def _scrub(text: str, secret: str | None = None) -> str:
    if secret:
        text = text.replace(secret, "<key>")
    return re.sub(r"(?i)(bearer\s+|apikey=|api_key=)[^\s&'\"]+", r"\1<key>", text)


def _when(s) -> datetime:
    x = str(s).strip().replace(" ", "T")
    if re.search(r"[+-]\d\d$", x):
        x += ":00"
    ts = pd.Timestamp(x)
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")).to_pydatetime()


def _amended(argv: list[str]) -> list[str]:
    return [x.strip() for x in argv[argv.index("--amended") + 1].split(",") if x.strip()] if "--amended" in argv else []


def frozen_gate(study: str, amended: list[str]) -> str | None:
    """Why the fresh set may not be pulled or scored, or None. dev and h1check are never checked."""
    return freeze.gate(amended) if study == "heldout2" else None


# ---------------------------------------------------------------- the control arm

def control_pairs(study: str | Path) -> list[tuple[Path, Path]]:
    d = sg.study_dir(study)
    if study == "h1check":
        return [(d / "labels_B1.json", d / "labels_B2.json")]
    return [(f, d / f.name.replace("_C1_", "_C2_")) for f in sorted(d.glob("labels_control_C1_*.json"))
            if (d / f.name.replace("_C1_", "_C2_")).exists()]


def _load_control(files: list[Path], st: dict | None = None) -> dict[str, dict]:
    """As heldout.load: id -> family, remembered and {(ticker, direction): link}, tickers limited to S5's list. A
    question answered more than once over the files is dropped; a link without a ticker on the list or without a
    direction in sg.DIRECTIONS is skipped. Both are counted in `st`."""
    st = st if st is not None else {}
    seen: dict[str, list[dict]] = {}
    for f in files:
        answers, err = sg._read(f)
        for a in answers or []:
            if isinstance(a, dict) and isinstance(a.get("id"), str):
                seen.setdefault(a["id"], []).append(a)
    out: dict[str, dict] = {}
    for q, xs in seen.items():
        if len(xs) > 1:
            st["questions_answered_twice_dropped"] = st.get("questions_answered_twice_dropped", 0) + 1
            continue
        a, links = xs[0], {}
        for l in a.get("links") if isinstance(a.get("links"), list) else []:
            tk = l.get("ticker") if isinstance(l, dict) else None
            if not isinstance(tk, str) or tk not in c5.MENU:
                continue
            if l.get("direction") not in sg.DIRECTIONS:
                st["links_without_a_direction_skipped"] = st.get("links_without_a_direction_skipped", 0) + 1
                continue
            links[(tk, l["direction"])] = l
        out[q] = {"family": a.get("family", "none"), "remembered": bool(a.get("remembered")), "links": links}
    return out


def control_links(study: str | Path) -> tuple[list[dict], dict]:
    """A link is a (question, ticker, direction) both labellers named on a question both called an event. Questions
    map to clusters through universe.json."""
    pairs = control_pairs(study)
    mk = {m["id"]: m for m in sg.universe(study)["markets"]}
    cl = sg.clusters(study)
    of = {m["id"]: c for c, e in cl.items() for m in e["markets"]}
    st = {"questions": 0, "both_event": 0, "agreed": 0, "named_by_one": 0, "markets_with_link": 0,
          "questions_answered_twice_dropped": 0, "links_without_a_direction_skipped": 0, "questions_not_in_the_set": 0}
    a, b = _load_control([p for p, _ in pairs], st), _load_control([q for _, q in pairs], st)
    links = []
    for mid in sorted(a.keys() & b.keys()):
        if mid not in mk:
            st["questions_not_in_the_set"] += 1
            continue
        st["questions"] += 1
        both = a[mid]["family"] == "event" and b[mid]["family"] == "event"
        st["both_event"] += both
        agreed = set(a[mid]["links"]) & set(b[mid]["links"]) if both else set()
        st["agreed"] += len(agreed)
        st["named_by_one"] += len({t for t, _ in a[mid]["links"]} ^ {t for t, _ in b[mid]["links"]})
        st["markets_with_link"] += bool(agreed)
        c = mk[mid].get("cluster") or of.get(mid, "")
        ev = cl.get(c, {})
        for tk, dr in sorted(agreed):
            la, lb = a[mid]["links"][(tk, dr)], b[mid]["links"][(tk, dr)]
            imp = [sg._f(la.get("impact_pct")), sg._f(lb.get("impact_pct"))]
            links.append({"source": sg.universe_name(study), "linker": CONTROL, "kind": EVENT, "cluster": c, "market": mid,
                          "question": mk[mid]["question"], "ticker": tk, "direction": dr,
                          "confidence": sg.low(la.get("confidence"), lb.get("confidence")),
                          "two_models": 1, "links_on_question": len(agreed), "signal": json.dumps([[mid, 1.0]]), "signal_range_points": 100.0,
                          "structure": ev.get("structure", ""), "impact_pct": float(np.nanmean(imp)) if np.isfinite(imp).any() else float("nan"),
                          "mechanism_class": "", "alternative": la.get("alternative", ""), "seen_ladder": bool(ev.get("seen_ladder")),
                          "probe": bool(ev.get("probe")), "remembered": a[mid]["remembered"] or b[mid]["remembered"],
                          "main_market": ev.get("main", mid)})
    return links, st


# ---------------------------------------------------------------- pull

def _pull_file(study: str | Path) -> Path:
    return OUT / f"{out_name(study)}_pull.json"


def off_menu_verdict(ref: dict | None) -> dict:
    """Keep an off-list ticker only when Massive serves it as an exchange-listed stock, ADR, ETF or ETV (OFF_TYPES), with a
    primary exchange, and it is not a recent listing. Whether `name` is the company the labellers meant is the manual
    check of the kept ones (results: off_menu_kept)."""
    if ref is None:
        return {"keep": False, "note": "off the list and not served by Massive as an active ticker: links dropped"}
    if not ref.get("primary_exchange"):
        return {"keep": False, "note": "off the list, served without a primary exchange: links dropped", **ref}
    if ref.get("type") not in OFF_TYPES:
        return {"keep": False, "note": f"off the list, served as type {ref.get('type')!r}, not a stock, ADR, ETF or ETV: links dropped", **ref}
    if ref.get("recent_listing"):
        return {"keep": False, "note": f"off the list, listed {ref.get('list_date') or 'on an unknown date'} (recent: the ticker may be reused): links dropped", **ref}
    return {"keep": True, "note": f"off the list, served by Massive as {ref.get('name')!r} ({ref.get('type')}) on {ref.get('primary_exchange')}", **ref}


def pull_ids(study: str | Path, links: list[dict], stats: dict, ctrl: list[dict]) -> set[str]:
    """Every market whose odds the evaluation reads: each leg of every linked and market-wide signal, each control
    question with a link, and every cluster's main question (recall, PLAN 9, reads its last price)."""
    ids = {i for l in links for i, _ in json.loads(l["signal"])}
    ids |= {l["market"] for l in ctrl} | {i for m in stats["market_wide"] for i, _ in m["signal"]}
    return ids | {e["main"] for e in sg.clusters(study).values() if e.get("main")}


def pull(study: str, amended: list[str] | None = None) -> int:
    if study not in ("dev", "heldout2"):
        print("pull runs for dev or heldout2 only")
        return 2
    why = frozen_gate(study, amended or [])
    if why:
        print("refused:", why)
        return 2
    links, stats = sg.merge(study)
    ctrl = control_links(study)[0] if control_pairs(study) else []
    ids = pull_ids(study, links, stats, ctrl)
    mk = sg.markets(study)
    pt = ds.Throttle(PM_RATE)
    win_a = datetime.fromisoformat(c5.WINDOW_START).replace(tzinfo=UTC) - timedelta(days=4)
    t0, fails, cached = time.time(), [], 0
    todo = []
    for i in sorted(ids):
        if store.find(f"pm_{i.split(':')[1]}.npz"):
            cached += 1
        elif i not in mk or not mk[i].get("token"):
            fails.append({"market": i, "error": "not in the study's roster"})
        else:
            todo.append(mk[i])

    def job(m: dict) -> None:
        try:
            a = max(_when(m["start"]), win_a).replace(second=0, microsecond=0)
            b = min(_when(m["end"]) + timedelta(days=1), datetime.now(UTC))
            store.save(f"pm_{m['id'].split(':')[1]}.npz", **ds.pm_history({"token": m["token"]}, a, b, pt))
        except Exception as e:  # noqa: BLE001
            fails.append({"market": m["id"], "error": _scrub(repr(e))[:160]})

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        list(ex.map(job, todo))
    pulled = sum(1 for m in todo if store.find(f"pm_{m['id'].split(':')[1]}.npz"))
    print(f"{time.time() - t0:.0f}s odds: {len(ids)} markets, {cached} cached, {pulled} pulled, {len(fails)} failures", flush=True)
    tickers = sorted({l["ticker"] for l in links + ctrl} | {"SPY"})
    off: dict[str, dict] = {}
    eq_pulled, secret = 0, None
    try:
        from s4_linked_assets.data import _massive_session, daily_bars, equity_bars
        s, base = _massive_session()
        secret = s.headers.get("Authorization")
        for tk in tickers:
            try:
                if tk != "SPY" and not ins.on_menu(tk):
                    off[tk] = off_menu_verdict(ins.validate_off_menu(tk, s, base))
                    if not off[tk]["keep"]:
                        continue
                if not store.find(f"eq_{tk}.npz"):
                    store.save(f"eq_{tk}.npz", **equity_bars(s, base, tk, c5.WINDOW_START, c5.WINDOW_END))
                    eq_pulled += 1
                if not store.find(f"day_{tk}.npz"):
                    store.save(f"day_{tk}.npz", **daily_bars(s, base, tk, r5.DAILY_START, c5.WINDOW_END))
            except Exception as e:  # noqa: BLE001
                fails.append({"ticker": tk, "error": _scrub(repr(e), secret)[:160]})
    except Exception as e:  # noqa: BLE001
        fails.append({"equities": "no Massive session", "error": _scrub(repr(e), secret)[:160]})
    meta = {"study": study, "amended": amended or [], "t1": datetime.now(UTC).isoformat(timespec="seconds"), "markets": len(ids),
            "markets_cached": cached, "markets_pulled": pulled, "tickers": len(tickers), "equities_pulled": eq_pulled,
            "off_menu": off, "failures": fails, "seconds": round(time.time() - t0, 1)}
    OUT.mkdir(parents=True, exist_ok=True)
    _pull_file(study).write_text(json.dumps(meta, indent=1))
    print(f"{time.time() - t0:.0f}s equities: {len(tickers)} tickers, {eq_pulled} pulled, "
          f"{sum(not v['keep'] for v in off.values())} of {len(off)} off-list dropped, {len(fails)} failures in all", flush=True)
    for f in fails[:10]:
        print("  failure:", f, flush=True)
    return 0


# ---------------------------------------------------------------- scoring

class Prices:
    """SPY's sessions and every ticker's session prices and betas, from the caches."""

    def __init__(self) -> None:
        bars, self.spy_day = store.npz("eq_SPY.npz"), store.npz("day_SPY.npz")
        if bars is None or self.spy_day is None:
            raise FileNotFoundError("eq_SPY.npz or day_SPY.npz is in no cache")
        self.sess = en.sessions_from(bars["t"])
        self.days = list(self.sess.day)
        self.spy_px = en.session_prices(bars, self.sess)
        self.spy_raw = {"px": self.spy_px, "beta": np.zeros(len(self.days))}
        self._tk: dict[str, dict | None] = {}

    def asset(self, tk: str) -> dict | None:
        if tk not in self._tk:
            b, d = store.npz(f"eq_{tk}.npz"), store.npz(f"day_{tk}.npz")
            self._tk[tk] = None if b is None or d is None or len(b["t"]) == 0 else {
                "px": en.session_prices(b, self.sess), "beta": en.betas(d, self.spy_day, self.days)}
        return self._tk[tk]


def hc3_slope(x: np.ndarray, y: np.ndarray) -> dict:
    """Through-origin slope of y on x, one observation per date, with HC3 errors: leverage h_i = x_i^2 / sum x^2,
    var = sum(x_i^2 e_i^2 / (1 - h_i)^2) / (sum x^2)^2."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok].astype(float), y[ok].astype(float)
    sxx = float(np.sum(x * x))
    if sxx <= 0:
        return {"slope": float("nan"), "se": float("nan"), "t": float("nan")}
    b = float(np.sum(x * y) / sxx)
    h = x * x / sxx
    if np.any(h >= 1 - 1e-12):
        return {"slope": b, "se": float("nan"), "t": float("nan")}
    se = float(np.sqrt(np.sum(x * x * (y - b * x) ** 2 / (1 - h) ** 2)) / sxx)
    return {"slope": b, "se": se, "t": b / se if se > 0 else float("nan")}


def _days(pm: dict, direction: int, px: Prices, asset: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(x_night, e_gap, day) on sessions with both prices. A session's overnight move runs from the previous session's
    close to its own open, and belongs to its own day."""
    ld = en.link_days(pm["t"], pm["p"].astype(float), direction, px.sess, asset["px"], px.spy_px, asset["beta"])
    ok = np.isfinite(ld.x_night) & np.isfinite(ld.e_gap)
    return ld.x_night[ok], ld.e_gap[ok], np.array(px.days)[ok]


def period(x: np.ndarray, g: np.ndarray, d: np.ndarray, side: str, cutoff: str = CUTOFF) -> dict:
    """The benchmark's slope on sessions before `cutoff` (side "before") or from it ("since"). The two masks split the
    sessions exactly: the first session from the cutoff (previous close on the last session before it) is "since"."""
    m = d < cutoff if side == "before" else d >= cutoff
    c = en.clustered_slope(x[m], g[m], d[m])
    return {f"days_{side}_cutoff": int(m.sum()), f"gap_bp_per_point_{side}_cutoff": c["slope"], f"gap_t_{side}_cutoff": c["t"]}


def since_cutoff(pm: dict, direction: int, px: Prices, asset: dict, cutoff: str = CUTOFF) -> dict:
    """The benchmark's slope on sessions from `cutoff` only."""
    return period(*_days(pm, direction, px, asset), "since", cutoff)


EMPTY = {"days": 0, "gap_t": float("nan"), "gap_bp_per_point": float("nan"), "nights_1pt": 0, "gap_t_hc3": float("nan"),
         **{f"{k}_{s}_cutoff": (0 if k == "days" else float("nan")) for s in ("before", "since") for k in ("days", "gap_bp_per_point", "gap_t")}}


def live_share(main_pm: dict | None, px: Prices) -> float:
    """Share of sessions on which the main leg's own odds at 09:29 (at most 30 minutes old) are between 10% and 90%: the
    benchmark's odds_share_between_10_and_90, on a probability even when the signal is a weighted sum."""
    if main_pm is None or not len(main_pm["t"]):
        return float("nan")
    p = asof((px.sess.open.to_numpy() - 60).astype(np.int64), main_pm["t"], np.abs(main_pm["p"].astype(float)), sg.MAX_AGE_S)
    live = p[np.isfinite(p)]
    return float(np.mean((live >= 0.10) & (live <= 0.90))) if len(live) else float("nan")


def _stats(pm: dict | None, direction: int, px: Prices, asset: dict, main_pm: dict | None = None) -> dict:
    """The benchmark's statistics of one link. `main_pm`: the main leg's own odds, for a signal of several questions."""
    if pm is None or not len(pm["t"]):
        return dict(EMPTY)
    x, g, d = _days(pm, direction, px, asset)
    r = {**link_stats(pm, direction, px.sess, px.days, asset, px.spy_px), "nights_1pt": int(np.sum(np.abs(x) >= 1)),
         "gap_t_hc3": hc3_slope(x, g)["t"], **period(x, g, d, "before"), **period(x, g, d, "since")}
    if main_pm is not None:
        r["odds_share_between_10_and_90"] = live_share(main_pm, px)
    return r


def robust_verdict(row: dict) -> str:
    """PLAN section 4: testable with 30 days and 10 nights with a move of a point or more; t from HC3 errors."""
    if row["ticker"] == "SPY" or row["days"] < MIN_DAYS or row.get("nights_1pt", 0) < MIN_NIGHTS_1PT or not np.isfinite(row["gap_t_hc3"]):
        return "untestable"
    return "confirmed" if row["gap_t_hc3"] >= 2 else "contradicted" if row["gap_t_hc3"] <= -2 else "unproven"


def _pm(components: list, main: str | None, cache: dict) -> dict | None:
    key = json.dumps([components, main])
    if key not in cache:
        t, p = sg.series(components, main=main)
        cache[key] = {"t": t, "p": p} if len(t) else None
    return cache[key]


def score_link(l: dict, px: Prices, cache: dict, asset: dict | None = None, ticker: str | None = None) -> dict:
    """One link scored on its own signal (PLAN section 4): whole window, robust verdict, before and from the cutoff."""
    tk = ticker or l["ticker"]
    asset = asset if asset is not None else px.asset(tk)
    comps = json.loads(l["signal"])
    d = 1 if l["direction"] == "up_on_yes" else -1
    lead = l.get("market")
    main_pm = _pm([[lead, 1.0]], lead, cache) if len(comps) > 1 else None
    r = _stats(_pm(comps, lead, cache), d, px, asset, main_pm) if asset is not None else dict(EMPTY)
    row = {**l, **r, "scored_on": "signal"}
    row["verdict"] = verdict({**row, "ticker": tk})
    row["verdict_robust"] = robust_verdict({**row, "ticker": tk})
    row["verdict_since_cutoff"] = verdict({"ticker": tk, "days": row["days_since_cutoff"], "gap_t": row["gap_t_since_cutoff"]})
    return row


# ---------------------------------------------------------------- tables

COLS = {"whole": ("verdict", "gap_t", "gap_bp_per_point"), "since": ("verdict_since_cutoff", "gap_t_since_cutoff", "gap_bp_per_point_since_cutoff"),
        "robust": ("verdict_robust", "gap_t_hc3", "gap_bp_per_point")}


def summary(d: pd.DataFrame, since: bool | str = False) -> dict:
    v, g, b = COLS["since" if since is True else since or "whole"]
    t = d[d[v] != "untestable"] if len(d) else d
    n = len(t)
    return {"links": int(len(d)), "testable": int(n), "confirmed": int((t[v] == "confirmed").sum()) if n else 0,
            "contradicted": int((t[v] == "contradicted").sum()) if n else 0, "unproven": int((t[v] == "unproven").sum()) if n else 0,
            "confirmed_share": float((t[v] == "confirmed").mean()) if n else float("nan"),
            "contradicted_share": float((t[v] == "contradicted").mean()) if n else float("nan"),
            "right_sign_share": float((t[b] > 0).mean()) if n and b in t else float("nan"),
            "median_t": float(t[g].median()) if n else float("nan")}


def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    return float(sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p))
                     for i in range(0, k + 1)))


def binom_ci(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Exact (Clopper-Pearson) interval for k successes in n, by bisection on the binomial distribution."""
    if n <= 0:
        return float("nan"), float("nan")
    a = (1 - level) / 2

    def solve(f) -> float:          # f increasing in p, root in [0, 1]
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        return (lo + hi) / 2

    low = 0.0 if k == 0 else solve(lambda p: (1 - _binom_cdf(k - 1, n, p)) - a)
    high = 1.0 if k == n else solve(lambda p: a - _binom_cdf(k, n, p))
    return low, high


def contradicted_share(d: pd.DataFrame) -> dict:
    s = summary(d)
    lo, hi = binom_ci(s["contradicted"], s["testable"])
    return {"contradicted": s["contradicted"], "testable": s["testable"], "share": s["contradicted_share"], "interval_95_exact": [lo, hi]}


def _cluster_key(d: pd.DataFrame) -> pd.Series:
    k = d.cluster.fillna("").astype(str)
    return k.where(~k.isin(["", "nan"]), d.market)


def by_cluster(d: pd.DataFrame) -> dict:
    if not len(d):
        return {"linked": 0, "testable": 0, "with_a_confirmed_link": 0}
    g = d.assign(k=_cluster_key(d)).groupby("k")
    return {"linked": int(g.ngroups), "testable": int(g.verdict.apply(lambda v: (v != "untestable").any()).sum()),
            "with_a_confirmed_link": int(g.verdict.apply(lambda v: (v == "confirmed").any()).sum())}


def top_theme(d: pd.DataFrame) -> str | None:
    c = d[d.verdict == "confirmed"].theme.value_counts() if len(d) else pd.Series(dtype=int)
    return str(sorted(c.index, key=lambda t: (-c[t], t))[0]) if len(c) else None


def by_theme(d: pd.DataFrame) -> list[dict]:
    return [{"theme": th, **summary(x)} for th, x in d.groupby("theme")] if len(d) else []


def paired(v3: pd.DataFrame, ctrl: pd.DataFrame) -> dict:
    """For every cluster with a testable link in either arm: any confirmed link, any contradicted link, in each arm."""
    def flags(d: pd.DataFrame) -> dict[str, dict]:
        if not len(d):
            return {}
        g = d.assign(k=_cluster_key(d)).groupby("k").verdict
        return {k: {"testable": bool((v != "untestable").any()), "confirmed": bool((v == "confirmed").any()),
                    "contradicted": bool((v == "contradicted").any())} for k, v in g}

    a, b = flags(v3), flags(ctrl)
    none = {"testable": False, "confirmed": False, "contradicted": False}
    keys = sorted(k for k in a.keys() | b.keys() if a.get(k, none)["testable"] or b.get(k, none)["testable"])
    rows = [{"cluster": k, **{f"v3_{f}": a.get(k, none)[f] for f in none}, **{f"control_{f}": b.get(k, none)[f] for f in none}} for k in keys]

    def table(f: str) -> dict:
        return {"both": sum(r[f"v3_{f}"] and r[f"control_{f}"] for r in rows), "v3_only": sum(r[f"v3_{f}"] and not r[f"control_{f}"] for r in rows),
                "control_only": sum(r[f"control_{f}"] and not r[f"v3_{f}"] for r in rows),
                "neither": sum(not r[f"v3_{f}"] and not r[f"control_{f}"] for r in rows)}

    return {"clusters": len(rows), "any_confirmed": table("confirmed"), "any_contradicted": table("contradicted"), "rows": rows}


def _auc(d: pd.DataFrame, col: str) -> float:
    t = d[(d.verdict != "untestable") & d[col].notna()] if len(d) else d
    return sc.auc((t.verdict == "confirmed").to_numpy(float), t[col].to_numpy(float)) if len(t) else float("nan")


def four(v3: pd.DataFrame) -> dict:
    """The brief's four measures on a set of version-3 event links, pass or fail each."""
    s = summary(v3)
    auc = _auc(v3, "score_v2")
    m = {"confirmed_share": {"value": s["confirmed_share"], "bar": f"> {BARS['confirmed_share_above']:.4f} (9 of 21)",
                             "pass": bool(s["confirmed_share"] > BARS["confirmed_share_above"])},
         "confirmed": {"value": s["confirmed"], "bar": f">= {BARS['confirmed_at_least']}", "pass": s["confirmed"] >= BARS["confirmed_at_least"]},
         "contradicted": {"value": s["contradicted"], "bar": f"<= {BARS['contradicted_at_most']}", "pass": s["contradicted"] <= BARS["contradicted_at_most"]},
         "auc_v2_v3_testable": {"value": auc, "bar": f">= {BARS['auc_v2_at_least']}", "pass": bool(auc >= BARS["auc_v2_at_least"])}}
    ok = all(v["pass"] for v in m.values())
    return {**m, "testable": s["testable"], "all_four_pass": ok,
            "verdict": "inconclusive" if s["testable"] < MIN_TESTABLE else "meets the brief's bar" if ok else "does not meet the brief's bar"}


def trusted_bar(v3: pd.DataFrame) -> dict:
    """The brief's first three measures on the trusted links: score_v2 of 0.5 or more (PLAN 5)."""
    k = v3[v3.score_v2 >= TRUST_SCORE] if len(v3) else v3
    s = summary(k)
    m = {"confirmed_share": {"value": s["confirmed_share"], "bar": f"> {BARS['confirmed_share_above']:.4f} (9 of 21)",
                             "pass": bool(s["confirmed_share"] > BARS["confirmed_share_above"])},
         "confirmed": {"value": s["confirmed"], "bar": f">= {BARS['confirmed_at_least']}", "pass": s["confirmed"] >= BARS["confirmed_at_least"]},
         "contradicted": {"value": s["contradicted"], "bar": f"<= {BARS['contradicted_at_most']}", "pass": s["contradicted"] <= BARS["contradicted_at_most"]}}
    ok = all(v["pass"] for v in m.values())
    return {**m, "links": s["links"], "testable": s["testable"], "clusters_with_a_confirmed_link": by_cluster(k)["with_a_confirmed_link"],
            "all_three_pass": ok, "verdict": "meets the bar on trusted links" if ok else "does not meet the bar on trusted links"}


def fit_odds_model() -> dict | None:
    """The odds-only model: linker.scorer.fit on results/linker/train_v2.csv with the three odds inputs and log days."""
    if not TRAIN_V2.exists():
        return None
    t = pd.read_csv(TRAIN_V2)
    t = t[t.verdict.isin(["confirmed", "unproven", "contradicted"])].dropna(subset=list(ODDS_MODEL))
    return sc.fit(t[list(ODDS_MODEL)].to_numpy(float), (t.verdict == "confirmed").to_numpy(float))


def odds_design(df: pd.DataFrame) -> np.ndarray:
    """The odds-only inputs as linker/features.py defines them."""
    return np.column_stack([np.log1p(df.odds_mean_abs_move.to_numpy(float)), df.odds_share_nights_1pt.to_numpy(float),
                            df.odds_share_between_10_and_90.to_numpy(float), np.log(np.clip(df.days.to_numpy(float), 1, None))])


def add_scores(df: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    """score_v1 (results/linker/scorer.json, as heldout.py applies it), score_v2 (linker/scorer2.py) and score_odds (the
    odds-only model) on every row with odds and at least one day; score = score_v2."""
    df = df.copy()
    df["score_v1"] = df["score_v2"] = df["score_odds"] = np.nan
    if not len(df):
        df["score"] = np.nan
        return df
    ok = (df.days.fillna(0) > 0) & np.isfinite(df[list(ODDS)].astype(float)).all(axis=1)
    model = json.loads((OUT / "scorer.json").read_text())
    m = {"w": np.array([model["coefficients_standardised"]["intercept"]] + [model["coefficients_standardised"][k] for k in sc.FEATURES]),
         "mu": np.array(model["mean"]), "sd": np.array(model["sd"])}
    if ok.any():
        df.loc[ok, "score_v1"] = sc.predict(m, sc.design(df[ok]))
        mo = fit_odds_model()
        if mo is None:
            notes.append("score_odds is NaN: results/linker/train_v2.csv is missing")
        else:
            df.loc[ok, "score_odds"] = sc.predict(mo, odds_design(df[ok]))
        try:
            from . import scorer2
            scorer2.load()
            df.loc[ok, "score_v2"] = np.asarray(scorer2.score(df[ok].reset_index(drop=True)), dtype=float)
        except Exception as e:  # noqa: BLE001
            notes.append(f"score_v2 is NaN: scorer2 unavailable ({type(e).__name__}: {_scrub(str(e))[:120]})")
    df["score"] = df.score_v2
    return df


def scorer_block(v3: pd.DataFrame, ctrl: pd.DataFrame, col: str) -> dict:
    def block(x: pd.DataFrame) -> dict:
        x = x[(x.verdict != "untestable") & x[col].notna()] if len(x) else x
        if not len(x):
            return {"links_scored": 0, "base_rate": float("nan"), "auc": float("nan"), "confirmed_in_top_third": float("nan"),
                    "confirmed_in_bottom_third": float("nan")}
        y, s = (x.verdict == "confirmed").to_numpy(float), x[col].to_numpy(float)
        return {"links_scored": int(len(x)), "base_rate": float(y.mean()), "auc": sc.auc(y, s), "confirmed_in_top_third": sc.top_third(y, s),
                "confirmed_in_bottom_third": float(y[np.argsort(s)[: max(1, len(y) // 3)]].mean())}

    def trusted(x: pd.DataFrame) -> dict:
        k = x[x[col] >= 0.5] if len(x) else x
        tt = k[k.verdict != "untestable"] if len(k) else k
        return {"links": int(len(k)), "testable": int(len(tt)), "confirmed": int((tt.verdict == "confirmed").sum()) if len(tt) else 0,
                "confirmed_share": float((tt.verdict == "confirmed").mean()) if len(tt) else float("nan"),
                "contradicted": int((tt.verdict == "contradicted").sum()) if len(tt) else 0}

    both = pd.concat([v3, ctrl], ignore_index=True)
    pooled = both[(both.verdict != "untestable") & both[col].notna()].drop_duplicates(["market", "ticker", "direction"]) if len(both) else both
    return {"v3_testable (the bar)": block(v3), "control_alone": block(ctrl), "pooled_unique_both_arms (as heldout.py)": block(pooled),
            "trusted_score_0_5_or_more": {V3: trusted(v3), CONTROL: trusted(ctrl)}}


def hindsight(d: pd.DataFrame) -> dict:
    """Links with 30 days before and 30 days from the cutoff: count, median slope in each, share with the same sign."""
    t = d[(d.days_before_cutoff >= MIN_DAYS) & (d.days_since_cutoff >= MIN_DAYS)] if len(d) else d
    a, b = (t.gap_bp_per_point_before_cutoff.astype(float), t.gap_bp_per_point_since_cutoff.astype(float)) if len(t) else (pd.Series(dtype=float),) * 2
    return {"links": int(len(t)), "median_slope_before": float(a.median()) if len(t) else float("nan"),
            "median_slope_since": float(b.median()) if len(t) else float("nan"),
            "same_sign_share": float((np.sign(a) == np.sign(b)).mean()) if len(t) else float("nan")}


# ---------------------------------------------------------------- recall (PLAN section 9)

def resolution(market: dict | None) -> str | None:
    """yes when the market is closed in the roster and its last cached odds price is at least 0.9, no at most 0.1."""
    if not market or market.get("closed") is not True:
        return None
    pm = store.npz(f"pm_{str(market['id']).split(':')[-1]}.npz")
    if pm is None or not len(pm["p"]):
        return None
    p = float(pm["p"][np.argmax(pm["t"])])
    return "yes" if p >= YES else "no" if p <= NO else None


def recall_answers(study: str | Path) -> dict[str, set[str]]:
    """id -> the yes or no answers given to it. A question one recall labeller answered more than once over its files
    counts for nothing from that labeller."""
    by: dict[str, dict[str, list]] = {}
    for f in sorted(sg.study_dir(study).glob("labels_recall_*_*.json")):
        answers, _ = sg._read(f)
        for a in answers or []:
            if isinstance(a, dict) and isinstance(a.get("id"), str):
                by.setdefault(sg._parts(f)[1], {}).setdefault(a["id"], []).append(a.get("resolved"))
    out: dict[str, set[str]] = {}
    for got in by.values():
        for q, rs in got.items():
            if len(rs) == 1 and rs[0] in ("yes", "no"):
                out.setdefault(q, set()).add(rs[0])
    return out


def recalled_clusters(study: str | Path) -> set[str]:
    """Clusters whose main question (universe "main") the recall agent answered right (PLAN 9)."""
    mains = {c: e["main"] for c, e in sg.clusters(study).items() if e.get("main")}
    hit = recalled_markets(study, set(mains.values()))
    return {c for c, m in mains.items() if m in hit}


def recalled_markets(study: str | Path, ids: set[str]) -> set[str]:
    """Markets among `ids` whose resolution the recall agent answered right."""
    ans, mk = recall_answers(study), sg.markets(study)
    return {i for i in ids if i in ans and (r := resolution(mk.get(i))) is not None and r in ans[i]}


# ---------------------------------------------------------------- the evaluation

def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in COLUMNS:
        if c not in df:
            df[c] = np.nan
    if len(df):
        df["theme"] = df.question.fillna("").map(g5.theme_of)
    return df


def _probe(study: str | Path, a_all: dict, b_all: dict, cmap: dict) -> dict:
    """PLAN section 6: passes when the valid common signal weights 601826 and both name a Brazilian instrument the same way."""
    out = {}
    for c in sorted(c for c in a_all.keys() & b_all.keys() if cmap.get(c, {}).get("probe")):
        r = sg.pair(a_all[c], b_all[c], cmap[c])
        w = dict(r["signal"]).get(PROBE_MARKET, 0.0)
        la, lb = (sg._links(x) for x in (r["a"], r["b"])) if not r["discarded"] else ({}, {})
        same = sorted(t for t in la.keys() & lb.keys() if la[t]["direction"] == lb[t]["direction"])
        brazil = sorted(set(same) & BRAZIL)
        out[c] = {"discarded": r["discarded"], "signal": [[i, w_] for i, w_ in r["signal"]], "signal_valid": r["valid"],
                  "weight_on_601826": w, "cluster_main_by_code": cmap[c]["main"], "family": [r["a"].get("family") if r["a"] else None,
                                                                                         r["b"].get("family") if r["b"] else None],
                  "named_by_both_same_direction": same, "brazilian_instruments_agreed": brazil,
                  "passes": bool(r["valid"] and w != 0 and brazil)}
    return out


def off_menu_kept(off: dict, df: pd.DataFrame) -> list[dict]:
    """The off-list tickers the pull kept, with Massive's name and type and the clusters they link, for the manual check
    that the name is the company the labellers meant."""
    return [{"ticker": tk, **{k: v.get(k) for k in ("name", "type", "primary_exchange", "list_date")},
             "clusters": sorted(df[df.ticker == tk].cluster.dropna().astype(str).unique()) if len(df) else []}
            for tk, v in sorted(off.items()) if v.get("keep")]


def evaluate(study: str | Path, px: Prices | None = None, write: bool = True, amended: list[str] | None = None) -> tuple[dict, pd.DataFrame]:
    px = px or Prices()
    notes: list[str] = []
    pf = _pull_file(study)
    off = json.loads(pf.read_text()).get("off_menu", {}) if pf.exists() else {}
    links, stats = sg.merge(study, off_menu=off)
    pairs = control_pairs(study)
    ctrl, ctrl_stats = control_links(study) if pairs else ([], {})
    if not pairs:
        notes.append("no control-arm labels in this study")
    cache: dict = {}
    df = add_scores(_frame([score_link(l, px, cache) for l in links + ctrl]), notes)
    if len(df):
        df["recalled"] = df.cluster.isin(recalled_clusters(study))
        df["remembered"] = df.remembered.fillna(False).astype(bool)
    keep = (~df.probe.fillna(False).astype(bool)) if len(df) else []
    v3 = df[(df.linker == V3) & (df.kind == EVENT) & keep] if len(df) else df
    proxy = df[(df.linker == V3) & (df.kind == PROXY) & keep] if len(df) else df
    cl = df[(df.linker == CONTROL) & keep] if len(df) else df

    mw_rows = []
    cmap = sg.clusters(study)
    for m in stats.pop("market_wide"):
        l = {"cluster": m["cluster"], "ticker": "SPY", "direction": "up_on_yes" if m["direction"] == "up" else "down_on_yes",
             "signal": json.dumps([[i, round(w, 6)] for i, w in m["signal"]]), "market": m["signal"][0][0]}
        r = score_link(l, px, cache, asset=px.spy_raw, ticker="SPY, raw")
        mw_rows.append({k: r.get(k) for k in ("cluster", "direction", "signal", "days", "gap_bp_per_point", "gap_t", "verdict",
                                              "nights_1pt", "gap_t_hc3", "verdict_robust", "days_since_cutoff", "gap_t_since_cutoff",
                                              "verdict_since_cutoff")})
    mw = pd.DataFrame(mw_rows)

    a_all, b_all = sg.load_v3(study, "P"), sg.load_v3(study, "S")
    nonprobe = [c for c in a_all.keys() & b_all.keys() if not cmap.get(c, {}).get("probe")
                and not sg.discard(a_all[c], cmap.get(c, {})) and not sg.discard(b_all[c], cmap.get(c, {}))]
    ni_both = sorted(c for c in nonprobe if a_all[c].get("no_instrument") and b_all[c].get("no_instrument"))
    ni_one = sorted(c for c in nonprobe if bool(a_all[c].get("no_instrument")) != bool(b_all[c].get("no_instrument")))
    test_ids = {m["id"] for m in sg.universe(study).get("markets", [])}

    def ctrl_on(cs: list[str]) -> dict:
        ids = {m["id"] for c in cs for m in cmap.get(c, {}).get("markets", []) if m["id"] in test_ids}
        return summary(cl[cl.market.isin(ids)]) if len(cl) else summary(cl)

    s3 = summary(v3)
    th = top_theme(v3)
    menu = v3[v3.ticker.isin(c5.MENU)] if len(v3) else v3
    out = {"study": out_name(study), "amended": amended or [], "notes": notes,
           "brief_bar": four(v3),
           "brief_bar_trusted_links": trusted_bar(v3),
           "below_confidence_floor": {"floor": sg.MIN_CONFIDENCE, "links_dropped": len([x for x in stats.get("below_confidence_floor", [])
                                                                                          if not x.get("probe") and x.get("kind") == "event"])},
           "against_control": {V3: s3, CONTROL: summary(cl), "paired_by_cluster": paired(v3, cl)},
           "without_seen_ladder": four(v3[~v3.seen_ladder.astype(bool)] if len(v3) else v3),
           "by_cluster": {V3: by_cluster(v3), CONTROL: by_cluster(cl), "top_theme": th,
                          f"{V3} without the top theme": by_cluster(v3[v3.theme != th] if len(v3) else v3),
                          f"{CONTROL} without the top theme": by_cluster(cl[cl.theme != th] if len(cl) else cl)},
           "contradicted_share": {V3: contradicted_share(v3), CONTROL: contradicted_share(cl)},
           "by_theme": {V3: by_theme(v3), CONTROL: by_theme(cl)},
           "robust": {V3: summary(v3, "robust"), CONTROL: summary(cl, "robust")},
           "v3_on_s5_ticker_list": summary(menu),
           "hindsight": {"cutoff": CUTOFF, V3: hindsight(v3), CONTROL: hindsight(cl),
                         "since_cutoff": {V3: summary(v3, True), CONTROL: summary(cl, True)},
                         "v3 without remembered clusters": summary(v3[~v3.remembered.astype(bool)] if len(v3) else v3),
                         "v3 without recalled clusters": summary(v3[~v3.recalled.astype(bool)] if len(v3) else v3),
                         "recall_files": len(list(sg.study_dir(study).glob("labels_recall_*_*.json")))},
           "scorer": {"v1": scorer_block(v3, cl, "score_v1"), "v2": scorer_block(v3, cl, "score_v2"), "odds_only": scorer_block(v3, cl, "score_odds")},
           "no_instrument": {"clusters_by_both": len(ni_both), "clusters_by_one": len(ni_one), "by_both": ni_both, "by_one": ni_one,
                             "control_arm_on_markets_of_by_both": ctrl_on(ni_both), "control_arm_on_markets_of_by_one": ctrl_on(ni_one)},
           "market_wide_on_spy_raw_gap": {"answers": mw_rows, **summary(mw)},
           "price_proxy_links": {**summary(proxy), "robust": summary(proxy, "robust"),
                                 "rows": proxy[["cluster", "ticker", "direction", "days", "gap_t", "verdict"]].to_dict("records") if len(proxy) else []},
           "brazil_check": _probe(study, a_all, b_all, cmap),
           "off_menu_kept": off_menu_kept(off, df),
           "merge_stats": {V3: stats, CONTROL: ctrl_stats}}
    if out_name(study) in ("dev_v3", "dev"):
        old_file = OUT / "heldout.json"
        old = json.loads(old_file.read_text())["arms"]["B, by event"] if old_file.exists() else H1_OLD
        out["control_reconstruction"] = {"reconstruction": {**ctrl_stats, **summary(cl)}, "original_arm_B": old}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        df[COLUMNS].to_csv(OUT / f"{out_name(study)}_links.csv", index=False)
        (OUT / f"{out_name(study)}.json").write_text(json.dumps(out, indent=1, default=float))
    return out, df


# ---------------------------------------------------------------- the check against the first held-out test

def h1check(px: Prices | None = None) -> dict:
    """The control-arm path on linker/heldout (labels_B1, labels_B2), from caches only, against heldout.json arm B; the
    same links re-scored with the robust verdict."""
    px = px or Prices()
    links, st = control_links("h1check")
    df = _frame([score_link(l, px, {}) for l in links])
    new = {**st, **summary(df)}
    old_file = OUT / "heldout.json"
    old = json.loads(old_file.read_text())["arms"]["B, by event"] if old_file.exists() else H1_OLD
    match = all(new[k] == old[k] for k in H1_OLD) and all(new[k] == H1_OLD[k] for k in H1_OLD)
    return {"new": new, "old": {k: old[k] for k in old}, "match": bool(match), "robust": summary(df, "robust")}


def main(argv: list[str]) -> int:
    study = argv[argv.index("--study") + 1] if "--study" in argv and argv.index("--study") + 1 < len(argv) else None
    if study not in NAMES:
        print("usage: python -m linker.study [pull] --study dev|heldout2|h1check [--amended a.py,b.py]")
        return 2
    amended = _amended(argv)
    if "pull" in argv:
        return pull(study, amended)
    if study == "h1check":
        r = h1check()
        print(json.dumps(r, indent=1, default=float))
        return 0 if r["match"] else 1
    why = frozen_gate(study, amended)
    if why:
        print("refused:", why)
        return 2
    out, df = evaluate(study, amended=amended)
    print(json.dumps({k: out[k] for k in ("notes", "brief_bar", "against_control", "robust", "by_cluster")}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
