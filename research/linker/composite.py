from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof
from s4_linked_assets import engine as en
from s5_big_moves import run as r5

from .benchmark import OUT, link_stats, verdict

MEETING = re.compile(r"(december 2025|january 2026|march 2026|april 2026|june 2026|july 2026)")
TICKERS = ("TLT", "IEF", "SHY")
MAX_AGE_S = 1800


def outcome_weight(question: str) -> int | None:
    q = question.lower()
    if "no change" in q or "no fed rate cuts" in q:
        return None
    m = re.search(r"(decrease|increase)s? interest rates by (\d+)\+? bps", q)
    if not m:
        return None
    return (-1 if m.group(1) == "decrease" else 1) * int(m.group(2))


def composite_series(parts: list[tuple[np.ndarray, np.ndarray, int]]) -> tuple[np.ndarray, np.ndarray]:
    start, end = max(int(t[0]) for t, _, _ in parts), min(int(t[-1]) for t, _, _ in parts)
    grid = np.arange((start // 60 + 1) * 60, end, 60, dtype=np.int64)
    total = np.zeros(len(grid))
    for t, p, w in parts:
        total += -w * asof(grid, t, p.astype(float), MAX_AGE_S)
    ok = np.isfinite(total)
    return grid[ok], total[ok] / 100.0


def main() -> int:
    uni = json.loads((r5.HERE / "universe.json").read_text())["markets"]
    meetings: dict[str, list[tuple[str, int, str]]] = {}
    for m in uni:
        w, mt = outcome_weight(m["question"]), MEETING.search(m["question"].lower())
        if w is None or not mt or "fed" not in m["question"].lower():
            continue
        meetings.setdefault(mt.group(1), []).append((m["id"], w, m["question"]))

    def npz(name):
        f = r5.CACHE / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    spy_px = en.session_prices(spy_bars, sess)
    assets = {}
    for tk in TICKERS:
        b, d = npz(f"eq_{tk}.npz"), npz(f"day_{tk}.npz")
        assets[tk] = {"px": en.session_prices(b, sess), "beta": en.betas(d, spy_day, days)}

    rows, pooled = [], {tk: [] for tk in TICKERS}
    for meeting, comps in sorted(meetings.items()):
        parts, used = [], []
        for mid, w, q in comps:
            pm = npz(f"pm_{mid.split(':')[1]}.npz")
            if pm is not None and len(pm["t"]):
                parts.append((pm["t"], pm["p"], w))
                used.append(f"{w:+d}")
        if not parts:
            continue
        t, v = composite_series(parts)
        if len(t) < 100:
            continue
        for tk in TICKERS:
            r = {"meeting": meeting, "outcomes_used": " ".join(sorted(used)), "ticker": tk, "direction": "up_on_yes",
                 **link_stats({"t": t, "p": v}, 1, sess, days, assets[tk], spy_px)}
            r["verdict"] = verdict(r)
            rows.append(r)
            ld = en.link_days(t, v, 1, sess, assets[tk]["px"], spy_px, assets[tk]["beta"])
            ok = np.isfinite(ld.x_night) & np.isfinite(ld.e_gap)
            pooled[tk].append(pd.DataFrame({"day": np.array(days)[ok], "x": ld.x_night[ok], "gap": ld.e_gap[ok], "after": ld.e_day[ok]}))
    df = pd.DataFrame(rows)
    pool_rows = []
    for tk in TICKERS:
        p = pd.concat(pooled[tk], ignore_index=True)
        g = en.clustered_slope(p.x.to_numpy(), p.gap.to_numpy(), p.day.to_numpy())
        a = en.clustered_slope(p.x.to_numpy(), p.after.to_numpy(), p.day.to_numpy())
        big = p[p.x.abs() >= 2]
        pool_rows.append({"ticker": tk, "meeting_days": int(len(p)), "dates": int(p.day.nunique()), "gap_bp_per_bp_of_expected_rate": g["slope"],
                          "gap_t": g["t"], "same_sign": g["sign_agree"], "after_open_bp_per_bp": a["slope"], "after_open_t": a["t"],
                          "nights_2bp_plus": int(len(big)), "gap_on_those_nights_bp": float((np.sign(big.x) * big.gap).mean()) if len(big) else float("nan"),
                          "after_on_those_nights_bp": float((np.sign(big.x) * big.after).mean()) if len(big) else float("nan")})
    bench = pd.read_csv(OUT / "benchmark.csv")
    single = bench[(bench.theme == "Fed rate decision") & (bench.source.str.startswith("S5")) & (bench.verdict != "untestable")]
    summary = {"single_question_links": {"testable": int(len(single)), "confirmed": int((single.verdict == "confirmed").sum()),
                                         "contradicted": int((single.verdict == "contradicted").sum()),
                                         "right_sign_share": float((single.gap_bp_per_point > 0).mean())},
               "composite_links": {"testable": int((df.verdict != "untestable").sum()), "confirmed": int((df.verdict == "confirmed").sum()),
                                   "contradicted": int((df.verdict == "contradicted").sum()),
                                   "right_sign_share": float((df[df.verdict != "untestable"].gap_bp_per_point > 0).mean())},
               "pooled": pool_rows}
    df.to_csv(OUT / "fed_composite.csv", index=False)
    (OUT / "fed_composite.json").write_text(json.dumps(summary, indent=1))
    pd.set_option("display.width", 220)
    print(df[["meeting", "outcomes_used", "ticker", "days", "nights_with_a_move", "gap_bp_per_point", "gap_t", "intraday_t", "verdict"]].round(2).to_string(index=False))
    print(pd.DataFrame(pool_rows).round(2).to_string(index=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "pooled"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
