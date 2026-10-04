"""Walk-forward out-of-sample test of the AI fit (pre-registered in research/fit_oos/METHOD.md).

    cd backend && uv sync --locked --group engine
    cd backend && uv run --group engine --env-file ../.env python scripts/walk_forward_fits.py \
        --cache /tmp/wf_cache      # optional: keep the fetched histories so a crash does not refetch

For every market the committed precompute scored (app/data/fits.json, scored == true): fetch its history the way the
pipeline does (build_ticks, bounded by the pipeline's 15 s budget), split it by tick count into train (first 60 %),
a purge gap (max(2, ceil(5 %)) ticks, dropped) and test (the rest), tune on train with the pipeline's own functions
(classify -> shortlist -> choose_division -> orient_to_adverse -> tune, real hedgecore engine), then replay the SINGLE
chosen preset on test with fresh engine state. Compares test vs_static against 0 (a same-size static hedge) and against
the family's default preset. Writes research/results/fit_oos/{SUMMARY.md, per_market.csv, chart.png, RUN_LOG.md}.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import shlex
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

from app.pipeline.classify import classify  # noqa: E402
from app.pipeline.engine_adapter import EngineAdapter, default_preset  # noqa: E402
from app.pipeline.llm import RulesProvider  # noqa: E402
from app.pipeline.service import TICKS_BUDGET_S, choose_division  # noqa: E402
from app.pipeline.shortlist import shortlist, unmet_requirements  # noqa: E402
from app.pipeline.ticks import MIN_TICKS, TickSet, available_requirements, build_ticks, orient_to_adverse  # noqa: E402
from app.pipeline.tune import _f, never_hedged, tune  # noqa: E402

DATA = BACKEND / "app" / "data"
REPO = BACKEND.parent
OUT = REPO / "research" / "results" / "fit_oos"

TRAIN_FRAC = 0.60
PURGE_FRAC = 0.05
MIN_PURGE = 2
SHARES = 1000.0
LONG_TEST = 100
SYMLOG_LIN = 0.05


def split_indices(n: int, train_frac: float = TRAIN_FRAC, purge_frac: float = PURGE_FRAC,
                  min_purge: int = MIN_PURGE) -> tuple[int, int, int]:
    if n < 0:
        raise ValueError("n must be >= 0")
    n_train = int(math.floor(train_frac * n))
    n_purge = max(int(min_purge), int(math.ceil(purge_frac * n)))
    test_start = min(n, n_train + n_purge)
    return n_train, n_purge, test_start


def slice_ticks(ticks: dict[str, Any], lo: int, hi: int) -> dict[str, Any]:
    out = {}
    for k, v in ticks.items():
        if isinstance(v, np.ndarray) and v.ndim == 1:
            out[k] = v[lo:hi].copy()
        else:
            out[k] = v
    return out


def _sub(ts: TickSet, lo: int, hi: int) -> TickSet:
    t = slice_ticks(ts.ticks, lo, hi)
    has_under = bool(np.isfinite(t.get("under_px", np.array([]))).any())
    return TickSet(t, ts.source, hi - lo, has_under, ts.quote_model, list(ts.notes), ts.token_id, ts.question)


def split_tickset(ts: TickSet) -> tuple[TickSet | None, TickSet | None, dict]:
    n = ts.n if ts.ticks is not None else 0
    n_train, n_purge, test_start = split_indices(n)
    info = {"n": n, "n_train": n_train, "n_purge": test_start - n_train, "n_test": n - test_start,
            "test_start": test_start}
    if ts.ticks is None or n == 0:
        return None, None, {**info, "reason": "no price history"}
    train, test = _sub(ts, 0, n_train), _sub(ts, test_start, n)
    if train.n < MIN_TICKS or test.n < MIN_TICKS:
        return None, None, {**info, "reason": f"train {train.n} / test {test.n} ticks (< {MIN_TICKS})"}
    if not train.has_underlying or not test.has_underlying:
        return None, None, {**info, "reason": "no equity prices in the " + ("train" if not train.has_underlying
                                                                            else "test") + " slice"}
    if test.ticks["ts_ns"][0] <= train.ticks["ts_ns"][-1]:
        return None, None, {**info, "reason": "ticks not in time order"}
    return train, test, info


def _test_value(row: dict | None) -> tuple[float | None, str | None]:
    if row is None:
        return None, "preset missing from the test replay"
    if never_hedged(row):
        return 0.0, "never hedged on test (0 by construction)"
    v = _f(row.get("hedge_var_reduction_vs_static"))
    if v is None:
        return None, "test vs_static undefined (NaN)"
    return v, None


async def evaluate_market(adapter: EngineAdapter, manifest: dict, question: str, ticker: str, direction: str,
                          ts: TickSet, shares: float = SHARES) -> dict:
    event_class, _ = await classify(question, RulesProvider(), manifest.get("event_classes"), ticker)
    train, test, info = split_tickset(ts)
    row: dict[str, Any] = {"event_class": event_class, **{k: info[k] for k in ("n", "n_train", "n_purge", "n_test")}}
    if train is None:
        return {**row, "status": "excluded", "reason": info["reason"]}
    available = available_requirements(train)
    lists = {d: [f for f in fams if not unmet_requirements(f, available)]
             for d, fams in shortlist(manifest, event_class, available).items()}
    division = choose_division(lists, shares, None)
    if division != "hedge":
        return {**row, "status": "excluded", "reason": f"division {division} (not hedge) on train"}
    families = lists["hedge"]
    position = {"shares_held": float(shares), "equity": 0.0, "pred_yes": 0.0, "pred_no": 0.0, "option": 0.0}
    train_o = TickSet(orient_to_adverse(train.ticks, direction), train.source, train.n, train.has_underlying,
                      train.quote_model, train.notes, train.token_id, train.question)
    t = tune(adapter, families, "hedge", position, train_o)
    row.update(n_families=len(families), n_presets=sum(int(f.get("preset_count") or 0) for f in families))
    if not t.get("scored"):
        return {**row, "status": "excluded", "reason": f"no scored preset on train ({t.get('unscored_reason')})"}
    fam = next(f for f in families if f["id"] == t["family"])
    d_idx, _ = default_preset(fam)
    row.update(family=t["family"], preset_index=t["preset_index"], default_preset_index=d_idx,
               train_vs_static=t["score"], train_avg_h=t.get("avg_hedge_ratio"))
    test_rows = adapter.replay_grid(t["family"], position, orient_to_adverse(test.ticks, direction)) or []
    by_idx = {int(r["preset_index"]): r for r in test_rows}
    chosen, default = by_idx.get(int(t["preset_index"])), by_idx.get(int(d_idx))
    v, note = _test_value(chosen)
    dv, dnote = _test_value(default)
    row.update(test_vs_static=v, test_note=note, default_test_vs_static=dv, default_test_note=dnote,
               test_avg_h=_f((chosen or {}).get("avg_hedge_ratio")), test_raw=_f((chosen or {}).get("hedge_var_reduction")),
               test_n_orders=_f((chosen or {}).get("n_orders")),
               test_best_vs_static=max((s for s in (_test_value(r)[0] for r in test_rows) if s is not None), default=None))
    if v is None:
        return {**row, "status": "excluded", "reason": note}
    return {**row, "status": "tested", "reason": note}


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + aa / c
            c = c if abs(c) > tiny else tiny
            de = d * c
            h *= de
        if abs(de - 1.0) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return tail if t >= 0 else 1.0 - tail


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def t_test_greater(x: list[float]) -> dict:
    n = len(x)
    if n < 2:
        return {"n": n, "t": None, "p": None}
    m, s = statistics.fmean(x), statistics.stdev(x)
    if s == 0:
        return {"n": n, "t": None, "p": None}
    t = m / (s / math.sqrt(n))
    return {"n": n, "t": t, "p": t_sf(t, n - 1)}


def sign_test_greater(x: list[float]) -> dict:
    pos, neg = sum(1 for v in x if v > 0), sum(1 for v in x if v < 0)
    m = pos + neg
    p = sum(math.comb(m, i) for i in range(pos, m + 1)) / 2 ** m if m else None
    return {"pos": pos, "neg": neg, "zero": len(x) - m, "p": p}


def _avg_ranks(a: list[float]) -> list[float]:
    order = sorted(range(len(a)), key=lambda i: a[i])
    ranks = [0.0] * len(a)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and a[order[j + 1]] == a[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def wilcoxon_greater(x: list[float]) -> dict:
    d = [v for v in x if v != 0]
    n = len(d)
    if n == 0:
        return {"n": 0, "w_plus": None, "p": None, "method": None}
    r = _avg_ranks([abs(v) for v in d])
    w = sum(rk for rk, v in zip(r, d) if v > 0)
    if n >= 25:
        mean = n * (n + 1) / 4.0
        counts = defaultdict(int)
        for rk in r:
            counts[rk] += 1
        var = n * (n + 1) * (2 * n + 1) / 24.0 - sum(c ** 3 - c for c in counts.values()) / 48.0
        z = (w - mean - 0.5) / math.sqrt(var)
        return {"n": n, "w_plus": w, "z": z, "p": norm_sf(z), "method": "normal"}
    r2 = [int(round(2 * rk)) for rk in r]
    dist = {0: 1}
    for rk in r2:
        nxt = defaultdict(int)
        for s, c in dist.items():
            nxt[s] += c
            nxt[s + rk] += c
        dist = nxt
    w2 = int(round(2 * w))
    p = sum(c for s, c in dist.items() if s >= w2) / 2 ** n
    return {"n": n, "w_plus": w, "p": p, "method": "exact"}


def describe(x: list[float]) -> dict:
    if not x:
        return {"n": 0}
    return {"n": len(x), "mean": statistics.fmean(x), "median": statistics.median(x), "min": min(x), "max": max(x),
            "sign": sign_test_greater(x), "t": t_test_greater(x), "wilcoxon": wilcoxon_greater(x)}


def success(desc: dict) -> bool:
    w = (desc.get("wilcoxon") or {}).get("p")
    return bool(desc.get("n")) and desc["median"] > 0 and w is not None and w < 0.05


def load_universe(fits_path: Path, universe: Path, ai_map: Path) -> tuple[list[dict], dict]:
    sys.path.insert(0, str(BACKEND / "scripts"))
    from precompute_fits import load_jobs
    fits = json.loads(fits_path.read_text())["fits"]
    scored = {k: f for k, f in fits.items() if f.get("scored")}
    by_key = {j["key"]: j for j in load_jobs(universe, ai_map)}
    jobs = []
    for k, f in scored.items():
        j = dict(by_key.get(k) or {"key": k, "source": k.split(":", 1)[0], "id": k.split(":", 1)[1]})
        j.update(ticker=f["ticker"], direction=f["direction"], question=f.get("question") or j.get("question"))
        jobs.append(j)
    return jobs, scored


def _save_cache(path: Path, ts: TickSet) -> None:
    meta = {"source": ts.source, "n": ts.n, "has_underlying": ts.has_underlying, "quote_model": ts.quote_model,
            "notes": ts.notes, "token_id": ts.token_id, "question": ts.question}
    arrays = {k: v for k, v in (ts.ticks or {}).items() if isinstance(v, np.ndarray)}
    np.savez_compressed(path.with_suffix(".npz"), **arrays)
    path.with_suffix(".json").write_text(json.dumps(meta))


def _load_cache(path: Path) -> TickSet | None:
    try:
        meta = json.loads(path.with_suffix(".json").read_text())
    except (OSError, ValueError):
        return None
    ticks = None
    if meta["source"] != "none":
        with np.load(path.with_suffix(".npz")) as z:
            ticks = {k: z[k] for k in z.files}
    return TickSet(ticks, meta["source"], meta["n"], meta["has_underlying"], meta["quote_model"], meta["notes"],
                   meta["token_id"], meta["question"])


async def fetch(job: dict, http, massive, offline: bool) -> tuple[TickSet, bool]:
    market = {"source": job["source"], "id": job["id"], "token_id": job.get("token_id")}
    try:
        return await asyncio.wait_for(build_ticks(market, job["ticker"], http=http, massive=massive, offline=offline),
                                      TICKS_BUDGET_S), False
    except asyncio.TimeoutError:
        return await build_ticks(market, job["ticker"], http=None, massive=None, offline=True), True


CSV_COLS = ["key", "ticker", "direction", "event_class", "ticks_source", "status", "reason", "n", "n_train", "n_purge",
            "n_test", "family", "preset_index", "default_preset_index", "train_vs_static", "test_vs_static",
            "default_test_vs_static", "default_test_note", "test_avg_h", "test_raw", "test_n_orders",
            "test_best_vs_static", "train_avg_h", "n_families", "n_presets", "fits_json_family",
            "fits_json_preset_index", "fits_json_vs_static", "fits_json_n_ticks", "fetch_timed_out"]


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLS)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in CSV_COLS])


def write_chart(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tested = [r for r in rows if r["status"] == "tested"]
    ink, muted, grid, blue, orange = "#0b0b0b", "#52514e", "#d9d8d2", "#2a78d6", "#eb6834"
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    for ax in (a1, a2):
        ax.set_facecolor("#fcfcfb")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(muted)
        ax.tick_params(colors=muted, labelsize=9)
        ax.grid(True, color=grid, linewidth=0.6)
        ax.set_axisbelow(True)
    x = np.array([r["train_vs_static"] for r in tested])
    y = np.array([r["test_vs_static"] for r in tested])
    a1.axhline(0, color=muted, linewidth=1)
    a1.axvline(0, color=muted, linewidth=1)
    a1.scatter(x, y, s=28, color=blue, edgecolor="#fcfcfb", linewidth=1.2, zorder=3)
    lo, hi = float(min(x.min(), y.min(), 0)), float(max(x.max(), y.max(), 0))
    a1.plot(np.linspace(lo, hi, 400), np.linspace(lo, hi, 400), color=muted, linestyle=(0, (4, 3)), linewidth=1)
    a1.text(hi, hi, " test = train", color=muted, fontsize=8, va="bottom", ha="right")
    a1.set_xlabel("train vs_static of the chosen preset (in-sample)", color=ink, fontsize=10)
    a1.set_ylabel("test vs_static of the same preset (out-of-sample)", color=ink, fontsize=10)
    for ax, axis in ((a1, "x"), (a1, "y"), (a2, "y")):
        (ax.set_xscale if axis == "x" else ax.set_yscale)("symlog", linthresh=SYMLOG_LIN)
    a1.set_title(f"Pick on train, score on test ({len(tested)} markets)", color=ink, fontsize=11, loc="left")
    ys = np.sort(y)
    colors = [blue if v > 0 else orange for v in ys]
    a2.bar(np.arange(len(ys)), ys, width=0.8, color=colors, linewidth=0)
    a2.axhline(0, color=muted, linewidth=1)
    med = float(np.median(ys))
    a2.axhline(med, color=ink, linestyle=(0, (4, 3)), linewidth=1)
    a2.text(len(ys) * 0.30, med, f" median {med:+.4f}", color=ink, fontsize=8, va="top")
    a2.set_xticks([])
    a2.set_xlabel("markets, sorted by test vs_static", color=ink, fontsize=10)
    a2.set_ylabel("test vs_static (> 0 beats a same-size static hedge)", color=ink, fontsize=10)
    a1.set_xticks([t for t in (-10.0, -1.0, -0.1, 0.0, 0.1, 1.0) if lo - 1e-9 <= t <= max(hi, 1.0)])
    fig.text(0.5, 0.005, f"Axes are symmetric-log: linear within +/-{SYMLOG_LIN:g}, logarithmic beyond.",
             color=muted, fontsize=8, ha="center", va="bottom")
    pos, neg = int((ys > 0).sum()), int((ys < 0).sum())
    a2.set_title(f"Out-of-sample: {pos} above 0 (blue), {neg} below (orange)", color=ink, fontsize=11, loc="left")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def _p(v: float | None) -> str:
    return "n/a" if v is None else (f"{v:.2g}" if v < 0.001 else f"{v:.3f}")


def _desc_line(d: dict) -> str:
    if not d.get("n"):
        return "n = 0"
    s, t, w = d["sign"], d["t"], d["wilcoxon"]
    return (f"n = {d['n']}, mean {d['mean']:+.4f}, median {d['median']:+.4f}; sign {s['pos']} > 0 / {s['neg']} < 0 "
            f"({s['zero']} = 0), p = {_p(s['p'])}; t = {t['t'] if t['t'] is None else round(t['t'], 2)}, "
            f"p = {_p(t['p'])}; Wilcoxon p = {_p(w['p'])}")


def analyze(rows: list[dict]) -> dict:
    tested = [r for r in rows if r["status"] == "tested"]
    test = [r["test_vs_static"] for r in tested]
    paired = [r for r in tested if r.get("default_test_vs_static") is not None]
    diff = [r["test_vs_static"] - r["default_test_vs_static"] for r in paired]
    per_ticker: dict[str, list[float]] = defaultdict(list)
    for r in tested:
        per_ticker[r["ticker"]].append(r["test_vs_static"])
    ticker_means = {k: statistics.fmean(v) for k, v in sorted(per_ticker.items())}
    long = [r["test_vs_static"] for r in tested if r["n_test"] >= LONG_TEST]
    primary = describe(test)
    return {
        "primary": primary, "success": success(primary),
        "train_of_tested": describe([r["train_vs_static"] for r in tested]),
        "default": describe([r["default_test_vs_static"] for r in paired]),
        "chosen_minus_default": describe(diff),
        "per_ticker": {"means": ticker_means, "sign": sign_test_greater(list(ticker_means.values())),
                       "n": len(ticker_means)},
        "long_test": describe(long),
        "oracle_best_in_test_median": statistics.median([r["test_best_vs_static"] for r in tested
                                                         if r.get("test_best_vs_static") is not None]) if tested else None,
        "oracle_best_gt0": sum(1 for r in tested if (r.get("test_best_vs_static") or 0) > 0),
        "never_hedged_on_test": sum(1 for r in tested if (r.get("reason") or "").startswith("never hedged")),
        "same_pick_as_fits_json": sum(1 for r in tested if r.get("family") == r.get("fits_json_family")
                                      and r.get("preset_index") == r.get("fits_json_preset_index")),
        "big_negative": [(r["key"], r["ticker"], r["test_vs_static"], r.get("test_avg_h")) for r in tested
                         if r["test_vs_static"] < -1.0],
        "n_universe": len(rows), "n_tested": len(tested),
        "excluded": [(r["key"], r["reason"]) for r in rows if r["status"] != "tested"],
    }


def write_summary(a: dict, meta: dict, path: Path) -> None:
    p, cmd = a["primary"], a["chosen_minus_default"]
    verdict = ("PASS: the pre-registered criterion is met (median test vs_static > 0 and one-sided Wilcoxon p < 0.05)."
               if a["success"] else
               "FAIL: the pre-registered criterion (median test vs_static > 0 and one-sided Wilcoxon p < 0.05) is not met.")
    tr = a["train_of_tested"]
    lines = [
        "# Walk-forward out-of-sample test of the AI fit: results",
        "",
        f"Method pre-registered in [research/fit_oos/METHOD.md](../../fit_oos/METHOD.md) (commit `{meta['method_commit']}`), "
        f"committed before this code was written or run. One run, {meta['finished']}.",
        "",
        f"**{verdict}**",
        "",
        "## Primary: test vs_static of the preset picked on train",
        "",
        f"Universe: {a['n_universe']} markets scored in-sample in `fits.json`; {a['n_tested']} entered the test "
        f"({len(a['excluded'])} excluded, reasons below and in `per_market.csv`).",
        "",
        "| | n | mean | median | > 0 / < 0 / = 0 | sign p | t p | Wilcoxon p |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def row(name: str, d: dict) -> str:
        if not d.get("n"):
            return f"| {name} | 0 | | | | | | |"
        s = d["sign"]
        return (f"| {name} | {d['n']} | {d['mean']:+.4f} | {d['median']:+.4f} | {s['pos']} / {s['neg']} / {s['zero']} | "
                f"{_p(s['p'])} | {_p(d['t']['p'])} | {_p(d['wilcoxon']['p'])} |")

    lines += [row("**test, chosen preset (primary)**", p),
              row("train, same preset (in-sample)", tr),
              row("test, family default preset", a["default"]),
              row("test, chosen minus default (paired)", cmd),
              row(f"test, chosen, markets with >= {LONG_TEST} test ticks", a["long_test"]),
              "",
              "All p values are one-sided (H1: > 0). vs_static = 1 - var(hedged) / var(unhedged x (1 - h)), h = the "
              "preset's average hedge ratio on the same window: > 0 means the preset beat a static short of the same "
              "average size, i.e. reading the prediction market added something.",
              "",
              "## Secondary",
              "",
              f"* **Shrinkage.** The chosen presets' median vs_static falls from {tr.get('median', float('nan')):+.4f} "
              f"on train (where they were picked) to {p.get('median', float('nan')):+.4f} on test.",
              f"* **Tuning vs the family default.** Chosen minus default on test: median {cmd.get('median', float('nan')):+.4f}, "
              f"chosen better on {cmd['sign']['pos'] if cmd.get('n') else 0} markets, worse on "
              f"{cmd['sign']['neg'] if cmd.get('n') else 0}, Wilcoxon p = {_p((cmd.get('wilcoxon') or {}).get('p'))}.",
              f"* **Clustering.** {a['per_ticker']['n']} distinct tickers; per-ticker mean test vs_static > 0 for "
              f"{a['per_ticker']['sign']['pos']}, < 0 for {a['per_ticker']['sign']['neg']} (sign p = "
              f"{_p(a['per_ticker']['sign']['p'])}). Per ticker: "
              + ", ".join(f"{k} {v:+.4f}" for k, v in a["per_ticker"]["means"].items()) + ".",
              f"* **Hindsight ceiling (descriptive only, not pre-registered).** Even the best preset of the chosen "
              f"family picked *on test* with hindsight (a preset that never hedges counts as 0) beats a same-size static "
              f"hedge in only {a['oracle_best_gt0']} of {a['n_tested']} markets (median "
              f"{a['oracle_best_in_test_median']:+.4f}). Better selection on train could not rescue the rest: on most "
              "test windows no preset of the family adds anything over a static hedge.",
              f"* **Idle picks.** {a['never_hedged_on_test']} chosen presets never held a hedge on test (signal-triggered "
              "hedges that did not trigger); they count as 0, per the method. Of the rest, "
              f"{p['sign']['pos'] if p.get('n') else 0} are above 0 and {p['sign']['neg'] if p.get('n') else 0} below.",
              f"* **Pick stability.** The train pick equals the full-history pick in fits.json for "
              f"{a['same_pick_as_fits_json']} of {a['n_tested']} markets: with ~100-400 presets and a few hundred hourly "
              "ticks, the winner changes when 40 % of the history is removed.",
              f"* **Mean vs median.** The mean ({p.get('mean', float('nan')):+.4f}) is driven by {len(a['big_negative'])} "
              "markets below -1, where the pick's test average hedge ratio is high, so the same-size static benchmark "
              "has a tiny residual variance and vs_static = 1 - var(hedged) / ((1 - h)^2 var(unhedged)) explodes: "
              + ", ".join(f"{t} {v:+.2f} (h {h if h is None else round(h, 2)})"
                          for _, t, v, h in sorted(a["big_negative"], key=lambda z: z[2])[:6])
              + ". The median and the sign test do not depend on them, and they agree.",
              "",
              "## Caveats",
              "",
              "* The live history was refetched for this run (" + meta["finished"] + "), a few hours after the "
              "committed precompute (fits.json, 2026-10-03 11:22 UTC), so the windows overlap but differ slightly; "
              "the train pick can differ from the fits.json pick (both are in `per_market.csv`).",
              "* Each history is about 30 days of hourly ticks at most (many markets are younger), so a test slice is "
              "days, not months. Markets sharing a ticker share equity moves and are not independent; see clustering.",
              "* vs_static benchmarks against a static hedge sized with hindsight (the preset's own average ratio on "
              "the same window), as the pipeline does.",
              "",
              "## Excluded",
              ""]
    lines += [f"* `{k}`: {why}" for k, why in a["excluded"]] or ["* none"]
    lines += ["", "Files: `per_market.csv` (one row per market), `chart.png`, `RUN_LOG.md`."]
    path.write_text("\n".join(lines) + "\n")


async def amain(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fits", type=Path, default=DATA / "fits.json")
    ap.add_argument("--universe", type=Path, default=DATA / "market_universe.json")
    ap.add_argument("--ai-map", type=Path, default=DATA / "ai_map.json")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--cache", type=Path, default=None, help="keep fetched histories here (reused if present)")
    ap.add_argument("--offline", action="store_true", help="recorded data only (no network)")
    ap.add_argument("--method-commit", default="", help="the commit of research/fit_oos/METHOD.md")
    ap.add_argument("--limit", type=int, default=None, help="debug only: first N markets")
    ap.add_argument("--note", default="", help="a line appended to RUN_LOG.md")
    a = ap.parse_args(argv)

    import httpx
    from app import chain

    adapter = EngineAdapter()
    if not adapter.can_score:
        raise SystemExit("the compiled hedgecore engine is required: cd backend && uv sync --locked --group engine")
    manifest, lib_source = adapter.library()
    jobs, scored = load_universe(a.fits, a.universe, a.ai_map)
    if a.limit:
        jobs = jobs[:a.limit]
    if a.cache:
        a.cache.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    log: list[str] = []
    rows: list[dict] = []
    box: list = []

    def massive():
        if not box:
            box.append(chain.make_client())
        return box[0]

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as http:
        for j in jobs:
            t0 = time.monotonic()
            cpath = a.cache / j["key"].replace(":", "_") if a.cache else None
            ts = _load_cache(cpath) if cpath else None
            timed_out = False
            if ts is None:
                ts, timed_out = await fetch(j, http, massive, a.offline)
                if cpath:
                    _save_cache(cpath, ts)
            r = await evaluate_market(adapter, manifest, j.get("question") or "", j["ticker"], j["direction"], ts)
            f = scored.get(j["key"]) or {}
            r.update(key=j["key"], ticker=j["ticker"], direction=j["direction"],
                     ticks_source=ts.source if ts.ticks is not None else "none", fetch_timed_out=timed_out,
                     fits_json_family=f.get("family"), fits_json_preset_index=f.get("preset_index"),
                     fits_json_vs_static=f.get("score"), fits_json_n_ticks=f.get("n_ticks"))
            if r.get("event_class") != f.get("event_class"):
                r["reason"] = ((r.get("reason") or "") + f"; event class {r.get('event_class')} != fits.json "
                               f"{f.get('event_class')}").lstrip("; ")
            rows.append(r)
            line = (f"{j['key']:>24} {j['ticker']:<6} {r['status']:<8} n={r.get('n')} train={r.get('n_train')} "
                    f"purge={r.get('n_purge')} test={r.get('n_test')} {r.get('family') or '-'}"
                    f"#{r.get('preset_index') if r.get('preset_index') is not None else '-'} "
                    f"train={_fmt(r.get('train_vs_static'))} test={_fmt(r.get('test_vs_static'))} "
                    f"default={_fmt(r.get('default_test_vs_static'))} src={r['ticks_source']}"
                    f"{' TIMEOUT' if timed_out else ''} ({time.monotonic() - t0:.1f}s)"
                    + (f" [{r['reason']}]" if r.get("reason") else ""))
            print(line, file=sys.stderr)
            log.append(line)

    finished = datetime.now(timezone.utc)
    analysis = analyze(rows)
    meta = {"method_commit": a.method_commit or "?", "finished": finished.isoformat(timespec="seconds")}
    a.out.mkdir(parents=True, exist_ok=True)
    write_csv(rows, a.out / "per_market.csv")
    if analysis["n_tested"]:
        write_chart(rows, a.out / "chart.png")
    write_summary(analysis, meta, a.out / "SUMMARY.md")
    srcs = defaultdict(int)
    for r in rows:
        srcs[r["ticks_source"]] += 1
    run_log = [
        "# RUN_LOG: walk-forward OOS test of the AI fit", "",
        f"* method: research/fit_oos/METHOD.md, commit `{meta['method_commit']}`",
        f"* command: `cd backend && uv run --group engine --env-file ../.env python scripts/walk_forward_fits.py "
        + shlex.join(argv if argv is not None else sys.argv[1:]) + "`",
        f"* started {started.isoformat(timespec='seconds')}, finished {meta['finished']}",
        f"* engine: hedgecore (library source `{lib_source}`, can_score {adapter.can_score}), provider rules",
        f"* split: train {TRAIN_FRAC:.0%} of ticks, purge max({MIN_PURGE}, ceil({PURGE_FRAC:.0%} n)), test the rest; "
        f"min {MIN_TICKS} ticks per slice; shares {SHARES:g}",
        f"* universe: {len(jobs)} markets scored in {a.fits.relative_to(REPO) if a.fits.is_relative_to(REPO) else a.fits}",
        f"* tick sources: {dict(srcs)}; fetch timeouts: {sum(1 for r in rows if r['fetch_timed_out'])}",
        f"* tested {analysis['n_tested']}, excluded {len(analysis['excluded'])}",
        f"* primary: {_desc_line(analysis['primary'])}",
        f"* verdict: {'PASS' if analysis['success'] else 'FAIL'}",
        *([f"* note: {a.note}"] if a.note else []),
        "", "## Per market", "", "```", *log, "```", ""]
    (a.out / "RUN_LOG.md").write_text("\n".join(run_log))
    print(f"primary: {_desc_line(analysis['primary'])} -> {'PASS' if analysis['success'] else 'FAIL'}", file=sys.stderr)
    return analysis


def main(argv: list[str] | None = None) -> int:
    asyncio.run(amain(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
