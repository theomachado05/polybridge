from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds
from s4_linked_assets import data as d4
from s4_linked_assets import engine as en
from s5_big_moves import config as c5
from s5_big_moves import granular as g5
from s5_big_moves import run as r5

from . import scorer as sc
from .benchmark import OUT, link_stats, verdict

HERE = Path(__file__).resolve().parent / "heldout"
CACHE = r5.CACHE
ARMS = {"A, by question": ("A1", "A2"), "B, by event": ("B1", "B2")}
UTC = timezone.utc


def load(name: str) -> dict[str, dict]:
    d = json.loads((HERE / f"labels_{name}.json").read_text())
    return {a["id"]: {"family": a.get("family", "none"),
                      "links": {(l["ticker"], l["direction"]): float(l.get("confidence", 0)) for l in a.get("links", []) if l.get("ticker") in c5.MENU}}
            for a in d["answers"]}


def arm_links(arm: str) -> tuple[list[dict], dict]:
    uni = {m["id"]: m for m in json.loads((HERE / "universe.json").read_text())["markets"]}
    a, b = (load(n) for n in ARMS[arm])
    links, st = [], {"questions": 0, "both_event": 0, "agreed": 0, "named_by_one": 0, "markets_with_link": 0}
    for mid in a.keys() & b.keys():
        st["questions"] += 1
        both = a[mid]["family"] == "event" and b[mid]["family"] == "event"
        st["both_event"] += both
        agreed = set(a[mid]["links"]) & set(b[mid]["links"]) if both else set()
        st["agreed"] += len(agreed)
        st["named_by_one"] += len({t for t, _ in a[mid]["links"]} ^ {t for t, _ in b[mid]["links"]})
        st["markets_with_link"] += bool(agreed)
        for tk, dr in sorted(agreed):
            links.append({"source": "held-out", "linker": arm, "market": mid, "question": uni[mid]["question"], "ticker": tk, "direction": dr,
                          "confidence": min(a[mid]["links"][(tk, dr)], b[mid]["links"][(tk, dr)]), "two_models": 1, "links_on_question": len(agreed),
                          "token": uni[mid]["token"], "start": uni[mid]["start"], "end": uni[mid]["end"]})
    return links, st


def pull() -> None:
    links = [l for arm in ARMS for l in arm_links(arm)[0]]
    markets = {l["market"]: l for l in links}
    pt = ds.Throttle(5.0)
    win_a = datetime.fromisoformat(c5.WINDOW_START).replace(tzinfo=UTC) - timedelta(days=4)
    t0, fails = time.time(), []

    def job(m):
        f = CACHE / f"pm_{m['market'].split(':')[1]}.npz"
        if f.exists():
            return
        try:
            end = str(m["end"]).replace(" ", "T")
            end = end if "T" in end else end + "T00:00:00+00:00"
            b = min(ds._iso(end.replace("+00", "+00:00") if end.endswith("+00") else end) + timedelta(days=1), datetime.now(UTC))
            np.savez_compressed(f, **ds.pm_history({"token": m["token"]}, max(ds._iso(m["start"]), win_a).replace(second=0, microsecond=0), b, pt))
        except Exception as e:
            fails.append({"market": m["market"], "error": repr(e)[:160]})

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(job, markets.values()))
    s, base = d4._massive_session()
    for tk in sorted({l["ticker"] for l in links}):
        if not (CACHE / f"eq_{tk}.npz").exists():
            try:
                np.savez_compressed(CACHE / f"eq_{tk}.npz", **d4.equity_bars(s, base, tk, c5.WINDOW_START, c5.WINDOW_END))
                np.savez_compressed(CACHE / f"day_{tk}.npz", **d4.daily_bars(s, base, tk, r5.DAILY_START, c5.WINDOW_END))
            except Exception as e:
                fails.append({"ticker": tk, "error": repr(e)[:120].replace(s.headers["Authorization"], "<key>")})
    print(f"{time.time() - t0:.0f}s: {len(markets)} markets, {len({l['ticker'] for l in links})} tickers, failures {fails}")


def main() -> int:
    def npz(name):
        f = CACHE / name
        return dict(np.load(f)) if f.exists() else None

    spy_bars, spy_day = npz("eq_SPY.npz"), npz("day_SPY.npz")
    sess = en.sessions_from(spy_bars["t"])
    days = list(sess.day)
    spy_px = en.session_prices(spy_bars, sess)
    model = json.loads((OUT / "scorer.json").read_text())
    m = {"w": np.array([model["coefficients_standardised"]["intercept"]] + [model["coefficients_standardised"][k] for k in sc.FEATURES]),
         "mu": np.array(model["mean"]), "sd": np.array(model["sd"])}
    tk: dict[str, dict | None] = {}
    rows, stats = [], {}
    for arm in ARMS:
        links, st = arm_links(arm)
        stats[arm] = st
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
    df = pd.DataFrame(rows)
    df["theme"] = df.question.map(g5.theme_of)
    t = df[df.verdict != "untestable"].copy()
    t["score"] = sc.predict(m, sc.design(t)) if len(t) else []
    y = (t.verdict == "confirmed").to_numpy(float)

    def arm_score(d: pd.DataFrame) -> dict:
        tt = d[d.verdict != "untestable"]
        return {"links": int(len(d)), "testable": int(len(tt)), "confirmed": int((tt.verdict == "confirmed").sum()),
                "contradicted": int((tt.verdict == "contradicted").sum()),
                "confirmed_share": float((tt.verdict == "confirmed").mean()) if len(tt) else float("nan"),
                "right_sign_share": float((tt.gap_bp_per_point > 0).mean()) if len(tt) else float("nan"),
                "median_t": float(tt.gap_t.median()) if len(tt) else float("nan")}

    uniq = t.drop_duplicates(["market", "ticker", "direction"])
    yu = (uniq.verdict == "confirmed").to_numpy(float)
    out = {"arms": {arm: {**stats[arm], **arm_score(df[df.linker == arm])} for arm in ARMS},
           "scorer_on_held_out": {"links_scored": int(len(uniq)), "base_rate": float(yu.mean()) if len(uniq) else float("nan"),
                                  "auc": sc.auc(yu, uniq.score.to_numpy()) if len(uniq) else float("nan"),
                                  "confirmed_in_top_third": sc.top_third(yu, uniq.score.to_numpy()) if len(uniq) else float("nan"),
                                  "confirmed_in_bottom_third": float(yu[np.argsort(uniq.score.to_numpy())[: max(1, len(uniq) // 3)]].mean()) if len(uniq) else float("nan")}}
    df.merge(t[["linker", "market", "ticker", "direction", "score"]], on=["linker", "market", "ticker", "direction"], how="left").to_csv(OUT / "heldout_links.csv", index=False)
    (OUT / "heldout.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 70)
    print(t.sort_values("score", ascending=False)[["linker", "question", "ticker", "direction", "days", "gap_bp_per_point", "gap_t", "verdict", "score"]].round(2).head(40).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(pull() if "pull" in sys.argv else main())
