"""S5, descriptive: which questions are tied to which instruments, and is the link itself the weak point?
Per theme and per link: the opening-gap relation, what follows after the open, and the big-move nights.
Same links and cached data as S5; nothing new is pulled. Exploratory.

Run from `research/`:  python -m s5_big_moves.granular
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from s4_linked_assets import engine as en

from .run import CACHE, RESULTS, merge_links

# First match wins. Themes are for reading the results; no rule uses them.
THEMES = (
    ("Fed chair", ("fed chair", "powell out", "nominate")),
    ("Fed rate decision", ("fed ", "interest rates", "rate cuts")),
    ("Iran, Hormuz and oil", ("iran", "hormuz", "khamenei", "kharg")),
    ("Russia-Ukraine ceasefire", ("russia", "ukraine")),
    ("China and Taiwan", ("china", "taiwan")),
    ("Bitcoin holders", ("microstrategy", "satoshi", "bitcoin")),
    ("Venezuela", ("venezuela", "maduro")),
    ("US politics and shutdown", ("shutdown", "trump out", "recession", "starmer")),
    ("Single company", ("tesla", "tiktok", "microsoft")),
)


def theme_of(question: str) -> str:
    q = question.lower()
    for name, words in THEMES:
        if any(w in q for w in words):
            return name
    return "Other"


def build() -> pd.DataFrame:
    links, _ = merge_links()

    def npz(name):
        f = CACHE / name
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
        if a is None or pm is None or len(pm["t"]) == 0:
            continue
        ld = en.link_days(pm["t"], pm["p"].astype(float), l["direction"], sess, a["px"], spy_px, a["beta"])
        ok = np.isfinite(ld.x_night) & np.isfinite(ld.e_gap)
        rows.append(pd.DataFrame({"day": np.array(days)[ok], "market": l["market"], "question": l["question"], "theme": theme_of(l["question"]),
                                  "ticker": l["ticker"], "direction": l["direction_label"], "x": ld.x_night[ok], "gap": ld.e_gap[ok],
                                  "after": ld.e_day[ok]}))
    return pd.concat(rows, ignore_index=True)


def stats(d: pd.DataFrame) -> dict:
    g = en.clustered_slope(d.x.to_numpy(), d.gap.to_numpy(), d.day.to_numpy())
    a = en.clustered_slope(d.x.to_numpy(), d.after.to_numpy(), d.day.to_numpy())
    big = d[d.x.abs() >= 10]
    sg, sa = (np.sign(big.x) * big.gap).to_numpy(), (np.sign(big.x) * big.after).to_numpy()
    bg = en.date_bootstrap({k: list(sg[big.day.to_numpy() == k]) for k in big.day.unique()}) if len(big) else (np.nan,) * 3
    ok = np.isfinite(sa)
    ba = en.date_bootstrap({k: list(sa[ok][big.day.to_numpy()[ok] == k]) for k in big.day.unique()}) if len(big) else (np.nan,) * 3
    return {"link_days": int(len(d)), "dates": int(d.day.nunique()), "gap_bp_per_point": g["slope"], "gap_t": g["t"],
            "after_open_bp_per_point": a["slope"], "after_open_t": a["t"], "big_nights": int(len(big)), "big_dates": int(big.day.nunique()),
            "big_gap_bp": bg[0], "big_gap_lo": bg[1], "big_gap_hi": bg[2], "big_gap_same_sign": float(np.mean(sg > 0)) if len(big) else np.nan,
            "big_after_bp": ba[0], "big_after_lo": ba[1], "big_after_hi": ba[2]}


def main() -> int:
    df = build()
    themes = []
    for th, d in df.groupby("theme"):
        tks = d.groupby("ticker").size().sort_values(ascending=False)
        themes.append({"theme": th, "questions": int(d.market.nunique()), "links": int(d[["market", "ticker"]].drop_duplicates().shape[0]),
                       "tickers": ", ".join(tks.index), **stats(d)})
    themes.sort(key=lambda r: -r["link_days"])
    per_tk = []
    for (th, t, dr), d in df.groupby(["theme", "ticker", "direction"]):
        per_tk.append({"theme": th, "ticker": t, "direction": dr, "questions": int(d.market.nunique()), **stats(d)})
    links = []
    for (m, t), d in df.groupby(["market", "ticker"]):
        links.append({"question": d.question.iloc[0], "theme": d.theme.iloc[0], "ticker": t, "direction": d.direction.iloc[0], **stats(d)})
    lk = pd.DataFrame(links)
    enough = lk[(lk.link_days >= 30) & np.isfinite(lk.gap_t)]
    check = {"links_with_30_days": int(len(enough)), "gap_slope_positive": int((enough.gap_bp_per_point > 0).sum()),
             "right_and_significant": int((enough.gap_t >= 2).sum()), "wrong_and_significant": int((enough.gap_t <= -2).sum())}
    # the degenerate SPY links, the weight of the largest theme, and the trade by theme
    def fit(d, y="gap"):
        c = en.clustered_slope(d.x.to_numpy(), d[y].to_numpy(), d.day.to_numpy())
        return {"slope": c["slope"], "t": c["t"], "n": c["n"]}

    ns = df[df.ticker != "SPY"]
    top = themes[int(np.argmax([t["big_nights"] for t in themes]))]["theme"]
    tr = pd.read_csv(RESULTS / "trades.csv")
    pz = tr[(tr.variant == "V0") & (tr.cost_mult == 1.0)].copy()
    pz["theme"] = pz.question.map(theme_of)

    def bm(d):
        m = en.date_bootstrap({k: list(d.net_bp[d.day == k]) for k in d.day.unique()})
        return {"trades": int(len(d)), "dates": int(d.day.nunique()), "mean_net_bp": m[0], "ci_lo": m[1], "ci_hi": m[2],
                "mean_gross_bp": float(d.gross_bp.mean()) if len(d) else float("nan"), "hit": float((d.net_bp > 0).mean()) if len(d) else float("nan")}

    extra = {"link_check": check, "spy_link_days": int((df.ticker == "SPY").sum()), "spy_weight": float((df[df.ticker == "SPY"].x ** 2).sum() / (df.x ** 2).sum()),
             "p1_all": fit(df), "p1_without_spy": fit(ns), "after_without_spy": fit(ns, "after"), "largest_theme": top,
             "largest_theme_share_of_big_nights": float(len(ns[(ns.theme == top) & (ns.x.abs() >= 10)]) / max(len(ns[ns.x.abs() >= 10]), 1)),
             "p1_largest_theme": fit(ns[ns.theme == top]), "after_largest_theme": fit(ns[ns.theme == top], "after"),
             "p1_without_largest_theme": fit(ns[ns.theme != top]), "after_without_largest_theme": fit(ns[ns.theme != top], "after"),
             "p2_all": bm(pz), "p2_without_spy": bm(pz[pz.ticker != "SPY"]), "p2_spy_trades": int((pz.ticker == "SPY").sum()),
             "p2_by_theme": {th: bm(d) for th, d in pz[pz.ticker != "SPY"].groupby("theme")}}
    import json
    (RESULTS / "granular.json").write_text(json.dumps(extra, indent=1))
    pd.DataFrame(themes).to_csv(RESULTS / "themes.csv", index=False)
    pd.DataFrame(per_tk).to_csv(RESULTS / "theme_tickers.csv", index=False)
    lk.sort_values(["theme", "question", "ticker"]).to_csv(RESULTS / "links_detail.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60); pd.set_option("display.max_rows", 200)
    print(pd.DataFrame(themes)[["theme", "questions", "links", "tickers", "link_days", "gap_bp_per_point", "gap_t", "after_open_bp_per_point", "after_open_t",
                                "big_nights", "big_dates", "big_gap_bp", "big_gap_same_sign", "big_after_bp", "big_after_lo", "big_after_hi"]].round(2).to_string(index=False))
    print(check)
    t = pd.DataFrame(per_tk).sort_values(["theme", "link_days"], ascending=[True, False])
    print(t[["theme", "ticker", "direction", "questions", "link_days", "gap_bp_per_point", "gap_t", "after_open_bp_per_point", "after_open_t", "big_nights",
             "big_gap_bp", "big_after_bp"]].round(2).to_string(index=False))
    wrong = enough[enough.gap_t <= -2].sort_values("gap_t")
    print("links whose data contradict the direction (t <= -2):")
    print(wrong[["question", "ticker", "direction", "link_days", "gap_bp_per_point", "gap_t"]].round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
