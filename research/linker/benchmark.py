from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread.engine import asof
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s4_linked_assets import run as r4
from s5_big_moves import granular as g5
from s5_big_moves import run as r5

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "results" / "linker"
MIN_DAYS = 30


def link_stats(pm: dict, direction: int, sess: pd.DataFrame, days: list[str], asset: dict, spy_px: dict) -> dict:
    ld = en.link_days(pm["t"], pm["p"].astype(float), direction, sess, asset["px"], spy_px, asset["beta"])
    ok = np.isfinite(ld.x_night) & np.isfinite(ld.e_gap)
    x, g, d = ld.x_night[ok], ld.e_gap[ok], np.array(days)[ok]
    c = en.clustered_slope(x, g, d)
    gt = en.gate(np.append(ld.sxx, 0.0), np.append(ld.sxy, 0.0), np.append(ld.nbin, 0))
    big = np.abs(x) >= 10
    p_sig = asof((sess.open.to_numpy() - 60).astype(np.int64), pm["t"], np.abs(pm["p"].astype(float)), 1800)
    live = p_sig[np.isfinite(p_sig)]
    feats = {"odds_mean_abs_move": float(np.mean(np.abs(x))) if len(x) else float("nan"),
             "odds_share_nights_1pt": float(np.mean(np.abs(x) >= 1)) if len(x) else float("nan"),
             "odds_share_between_10_and_90": float(np.mean((live >= 0.10) & (live <= 0.90))) if len(live) else float("nan")}
    return {**feats, "days": int(ok.sum()), "nights_with_a_move": int(np.sum(x != 0)), "gap_bp_per_point": c["slope"], "gap_t": c["t"],
            "intraday_bp_per_point": float(gt["slope"][-1]), "intraday_t": float(gt["t"][-1]), "nights_10pt": int(big.sum()),
            "gap_on_10pt_nights_bp": float((np.sign(x[big]) * g[big]).mean()) if big.any() else float("nan")}


def verdict(row: dict) -> str:
    if row["ticker"] == "SPY" or row["days"] < MIN_DAYS or not np.isfinite(row["gap_t"]):
        return "untestable"
    return "confirmed" if row["gap_t"] >= 2 else "contradicted" if row["gap_t"] <= -2 else "unproven"


def frame(cache: Path, links: list[dict]) -> list[dict]:
    def npz(name):
        f = cache / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    spy_px = en.session_prices(spy_bars, sess)
    tk: dict[str, dict | None] = {}
    rows = []
    for l in links:
        if l["ticker"] not in tk:
            b, d = npz(f"eq_{l['ticker']}.npz"), npz(f"day_{l['ticker']}.npz")
            tk[l["ticker"]] = None if b is None or d is None or len(b["t"]) == 0 else {
                "px": en.session_prices(b, sess), "beta": en.betas(d, spy_day, days)}
        a, pm = tk[l["ticker"]], npz(f"pm_{l['market'].split(':')[1]}.npz")
        base = {k: l[k] for k in ("source", "linker", "market", "question", "ticker", "direction", "confidence", "two_models", "links_on_question")}
        if a is None or pm is None or len(pm["t"]) == 0:
            rows.append({**base, "days": 0, "gap_t": float("nan"), "verdict": "untestable"})
            continue
        r = {**base, **link_stats(pm, 1 if l["direction"] == "up_on_yes" else -1, sess, days, a, spy_px)}
        r["verdict"] = verdict(r)
        rows.append(r)
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    critic = r4.load_critic()
    conf4 = {}
    for f in sorted((HERE.parent / "s4_linked_assets").glob("critic_*.json")):
        for a in json.loads(f.read_text())["answers"]:
            for k in a.get("links", []):
                conf4[(a["id"], k["ticker"], k["direction"])] = float(k.get("confidence", 0))
    p4 = d4.proposer_links()
    fan4 = pd.Series([l["market"] for l in p4]).value_counts().to_dict()
    s4 = []
    for l in p4:
        v = r4.verdict(l, critic)
        dl = "up_on_yes" if l["direction"] > 0 else "down_on_yes"
        s4.append({"source": "S4 (open markets, Oct 2026)", "linker": "v1: two models agree" if v == "agreed" else "v0 only: text map, critic did not name it",
                   "market": l["market"], "question": l["question"], "ticker": l["ticker"], "direction": dl,
                   "confidence": conf4.get((l["market"], l["ticker"], dl), 0.0), "two_models": int(v == "agreed"), "links_on_question": fan4[l["market"]]})
    l5 = r5.merge_links()[0]
    fan5 = pd.Series([l["market"] for l in l5]).value_counts().to_dict()
    s5 = [{"source": "S5 (240 largest markets of the year)", "linker": "v1: two models agree", "market": l["market"], "question": l["question"],
           "ticker": l["ticker"], "direction": l["direction_label"], "confidence": min(l["confidence_a"], l["confidence_b"]), "two_models": 1,
           "links_on_question": fan5[l["market"]]} for l in l5]
    rows = frame(d4.CACHE, s4) + frame(r5.CACHE, s5)
    df = pd.DataFrame(rows)
    df["theme"] = df.question.map(g5.theme_of)
    df.to_csv(OUT / "benchmark.csv", index=False)

    def score(d: pd.DataFrame) -> dict:
        t = d[d.verdict != "untestable"]
        return {"links": int(len(d)), "testable": int(len(t)), "confirmed": int((t.verdict == "confirmed").sum()),
                "contradicted": int((t.verdict == "contradicted").sum()), "unproven": int((t.verdict == "unproven").sum()),
                "confirmed_share": float((t.verdict == "confirmed").mean()) if len(t) else float("nan"),
                "right_sign_share": float((t.gap_bp_per_point > 0).mean()) if len(t) else float("nan"),
                "median_t": float(t.gap_t.median()) if len(t) else float("nan")}

    table = [{"source": s, "linker": k, **score(d)} for (s, k), d in df.groupby(["source", "linker"])]
    v0 = df[df.source.str.startswith("S4")]
    table.append({"source": "S4 (open markets, Oct 2026)", "linker": "v0: the text map, every link", **score(v0)})
    by_theme = [{"theme": th, **score(d)} for th, d in df[df.linker.str.startswith("v1")].groupby("theme")]
    (OUT / "scores.json").write_text(json.dumps({"by_linker": table, "by_theme_v1": by_theme}, indent=1))
    pd.set_option("display.width", 220)
    print(pd.DataFrame(table).round(2).to_string(index=False))
    print(pd.DataFrame(by_theme).sort_values("testable", ascending=False).round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
