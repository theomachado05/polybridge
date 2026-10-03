"""CSV, charts and SUMMARY.md for the closed-market study. Every sentence of numbers is generated from `res`."""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .analysis import usable  # noqa: E402
from .config import PARAMS, RESULTS_DIR  # noqa: E402

BLUE, ORANGE, GREY, INK = "#0072B2", "#D55E00", "#9AA0A6", "#222222"
MARKET_COLOR = {"recession": BLUE, "election": ORANGE}
MARKET_LABEL = {"recession": "US recession 2025 market (Yes = bearish)", "election": "Trump 2024 election market (Yes = bullish)"}


def _f(x, nd=1, plus=False):
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{x:+.{nd}f}" if plus else f"{x:.{nd}f}"


def _p(x):
    if x is None or not np.isfinite(x):
        return "n/a"
    return "<0.001" if x < 0.001 else f"{x:.3f}"


def _t1s(t) -> str:
    return f"{t['k']} of {t['n']} agree ({_f(100 * t['rate'], 0) if t['n'] else 'n/a'}%), p = {_p(t['p'])}"


def event_table(rows: pd.DataFrame) -> pd.DataFrame:
    ev = rows[rows["news"]].copy()
    th = PARAMS.theta_pp

    def agree(r):
        if r["reason"]:
            return "excluded"
        if abs(r["dpm_o_pp"]) < th:
            return "PM move below 1 pp"
        if r["gap_bp"] == 0:
            return "gap is zero"
        return "yes" if np.sign(r["dpm_o_pp"]) == np.sign(r["gap_bp"]) else "no"

    ev["agree"] = ev.apply(agree, axis=1)
    cols = ["event", "name", "family", "closure", "open_day", "kind", "market", "news_et", "precision", "pm_close", "pm_open", "dpm_pp",
            "dpm_o_pp", "gap_bp", "ret30_bp", "resid_bp", "dpm_early_o_pp", "gap_qqq_bp", "agree", "reason"]
    return ev[[c for c in cols if c in ev]].reset_index(drop=True)


# -------------------------------------------------------------------- charts


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.axhline(0, color=INK, linewidth=0.6)
    ax.axvline(0, color=INK, linewidth=0.6)


def chart_scatter(rows: pd.DataFrame, res: dict, path) -> None:
    ev, pl = usable(rows[rows["news"]]), usable(rows[~rows["news"]])
    fig, ax = plt.subplots(figsize=(9, 6), dpi=140)
    ax.scatter(pl["dpm_o_pp"], pl["gap_bp"], s=14, color=GREY, alpha=0.55, label=f"placebo closures, no flagged news (n={len(pl)})", linewidths=0)
    for m, s in ev.groupby("market"):
        ax.scatter(s["dpm_o_pp"], s["gap_bp"], s=60, color=MARKET_COLOR[m], label=f"news events, {MARKET_LABEL[m]} (n={len(s)})", edgecolors="white", linewidths=0.8, zorder=3)
    for _, r in ev.iterrows():
        ax.annotate(r["event"][:3], (r["dpm_o_pp"], r["gap_bp"]), xytext=(4, 4), textcoords="offset points", fontsize=7.5, color=INK)
    xs = np.linspace(min(ev["dpm_o_pp"].min(), pl["dpm_o_pp"].min()), max(ev["dpm_o_pp"].max(), pl["dpm_o_pp"].max()), 50) if len(ev) and len(pl) else []
    for sub, color, ls, nm in ((pl, GREY, "--", "placebo fit"), (ev, INK, "-", "event fit")):
        if len(sub) > 3 and sub["dpm_o_pp"].nunique() > 1:
            b, a = np.polyfit(sub["dpm_o_pp"], sub["gap_bp"], 1)
            ax.plot(xs, a + b * xs, color=color, linestyle=ls, linewidth=1.2, label=f"{nm}: {b:+.1f} bp per pp")
    ax.set_xlabel("PM change over the closure, oriented (pp; positive = equity-bullish direction)")
    ax.set_ylabel("SPY open gap vs previous close (bp)")
    ax.set_title("Does the closure move in the PM line up with the equity gap?", loc="left", fontsize=12, color=INK)
    _style(ax)
    ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def chart_events(rows: pd.DataFrame, path) -> None:
    ev = usable(rows[rows["news"]]).sort_values("closure").reset_index(drop=True)
    if ev.empty:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 0.42 * len(ev) + 1.8), dpi=140, sharey=True)
    y = np.arange(len(ev))[::-1]
    agree = np.sign(ev["dpm_o_pp"]) == np.sign(ev["gap_bp"])
    small = ev["dpm_o_pp"].abs() < PARAMS.theta_pp
    colors = [GREY if s else (BLUE if a else ORANGE) for a, s in zip(agree, small)]
    a1.barh(y, ev["dpm_o_pp"], color=colors)
    a2.barh(y, ev["gap_bp"], color=colors)
    labels = [f"{r['event'][:3]} {r['closure']} {r['kind'][:3]}" for _, r in ev.iterrows()]
    a1.set_yticks(y)
    a1.set_yticklabels(labels, fontsize=8)
    a1.set_xlabel("oriented PM change (pp)")
    a2.set_xlabel("SPY open gap (bp)")
    for ax in (a1, a2):
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.axvline(0, color=INK, linewidth=0.7)
        ax.grid(axis="x", alpha=0.25)
    fig.suptitle("News events: blue = same sign, orange = opposite, grey = PM move below 1 pp", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def chart_placebo(res: dict, path) -> None:
    p2 = res["p2"]
    if p2["k_obs"] is None:
        return
    ks = np.asarray(p2["k_draws"])
    fig, ax = plt.subplots(figsize=(7, 4), dpi=140)
    vals, counts = np.unique(ks, return_counts=True)
    ax.bar(vals, counts / len(ks), color=GREY, width=0.8, label="event PM moves paired with random placebo gaps")
    ax.axvline(p2["k_obs"], color=BLUE, linewidth=2, label=f"observed: {p2['k_obs']} of {p2['n']} agree")
    ax.set_xlabel(f"events whose PM move and gap have the same sign (of {p2['n']})")
    ax.set_ylabel("share of 10,000 draws")
    ax.set_title("Pairing placebo", loc="left", fontsize=12, color=INK)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ------------------------------------------------------------------- summary


def plain_reading(res: dict) -> list[str]:
    th = PARAMS.theta_pp
    t1, t2, p2 = res["t1_events"][th], res["t2_events"], res["p2"]
    out = []
    v = res["verdict"]
    out.append(f"Under the pre-set rule (METHOD.md section 4) the verdict is **{v}**.")
    d = res["verdict_detail"]
    out.append(f"The three conditions: sign test significant with agreement above 50% = {'met' if d['c1_sign_test'] else 'not met'}; "
               f"slope positive with permutation p < 0.05 = {'met' if d['c2_slope_perm'] else 'not met'}; "
               f"pairing placebo p < 0.05 = {'met' if d['c3_pairing_placebo'] else 'not met'}.")
    if t1["n"]:
        out.append(f"In the events, the PM and the equity gap pointed the same way in {t1['k']} of {t1['n']} closures where the PM moved at least 1 pp "
                   f"({_f(100 * t1['rate'], 0)}%, exact p = {_p(t1['p'])}). With so few events, even a clear tilt may fall short of significance; "
                   f"a count that high or low would be needed to reject 50/50 at n = {t1['n']}: at least {_needed(t1['n'])} agreeing or disagreeing.")
    if np.isfinite(t2["b"]):
        out.append(f"The slope is {_f(t2['b'], 2, True)} bp of gap per pp of PM change (HC3 t = {_f(t2['t'], 2, True)}, R-squared {_f(t2['r2'], 2)}, "
                   f"permutation p = {_p(t2['p_perm'])}, Spearman rho {_f(t2['rho'], 2, True)}).")
    pl = res["p1_t1"][th]
    pls = res["p1_t2"]
    if pl["n"]:
        out.append(f"On the placebo closures the same PM-vs-gap relation shows {pl['k']} of {pl['n']} agreeing ({_f(100 * pl['rate'], 0)}%, p = {_p(pl['p'])}) "
                   f"and a slope of {_f(pls['b'], 2, True)} bp per pp (permutation p = {_p(pls['p_perm'])}). "
                   + ("A relation of this kind in the unflagged closures means the PM-equity co-movement is not special to the selected news days."
                      if (pl["p"] < PARAMS.alpha or pls["p_perm"] < PARAMS.alpha) else
                      "No relation shows up in the unflagged closures, as expected if nothing happens when there is no news."))
    if p2["k_obs"] is not None:
        out.append(f"Pairing each event's PM move with a random placebo gap gives {_f(p2['k_draws_mean'], 1)} agreeing events on average against the observed {p2['k_obs']} "
                   f"(p = {_p(p2['p_k'])}); slope p = {_p(p2['p_slope'])}.")
    p3 = res["p3"]
    if np.isfinite(p3["d"]):
        out.append(f"The interaction term (extra response per pp on news closures) is {_f(p3['d'], 2, True)} bp per pp (HC3 t = {_f(p3['d_t'], 2, True)}); "
                   f"the baseline response over all closures is {_f(p3['b'], 2, True)} (t = {_f(p3['b_t'], 2, True)}).")
    # bottom line, assembled from the same numbers
    a = PARAMS.alpha
    general = pl["n"] and (pl["p"] < a or pls["p_perm"] < a)
    news_extra = np.isfinite(p3["d"]) and abs(p3["d_t"]) >= 2
    t4 = res["t4_events_t2"]
    parts = []
    if np.isfinite(t2["rho"]) and t2["p_rho"] < a:
        parts.append("the PM closure move and the equity gap are positively related across the selected news events (rank correlation significant)")
    else:
        parts.append("the PM closure move and the equity gap are not reliably related across the selected news events")
    parts.append("the same relation " + ("also appears in closures with no flagged news, and news closures do not show an extra response" if general and not news_extra
                                          else "also appears in closures with no flagged news" if general
                                          else "does not appear in closures with no flagged news"))
    if np.isfinite(t4["b"]):
        parts.append("the PM move up to 08:00 ET " + ("does not predict" if t4["p_perm"] >= a else "does predict") + " the SPY move from 08:00 ET to the open")
    out.append("**Bottom line:** " + "; ".join(parts) + ". This is co-movement over the closure, not by itself evidence that the PM leads equities.")
    return out


def _needed(n: int) -> int:
    from .stats import binom_two_sided
    for k in range(n // 2 + 1, n + 1):
        if binom_two_sided(k, n) < PARAMS.alpha:
            return k
    return n


def write_summary(rows: pd.DataFrame, res: dict, markets: dict, et: pd.DataFrame, path) -> None:
    th = PARAMS.theta_pp
    L: list[str] = []
    L.append("# Closed-market lead-lag: does a prediction-market move during a US equity closure predict the equity gap?\n")
    L.append("Narrow claim, tested after the wave-1 study found no PM lead during market hours: when news breaks while the regular equity session is "
             "closed (nights, weekends, holidays), the PM move from the last close to the next open predicts the SPY opening gap. "
             "Rules were fixed in [METHOD.md](../../leadlag_closed/METHOD.md) and committed before any event-window price was fetched. "
             "**Hindsight-selected case studies plus an unselected placebo panel: supporting evidence at best, not proof, and co-movement rather than a proven lead.**\n")
    L.append("## Headline\n")
    L.append(f"- Events: {res['n_events_total']} pre-registered news closures, **{res['n_events_usable']} usable** (PM quote and SPY bars at both ends). "
             f"Placebo closures: {res['n_placebo_usable']} usable of {res['n_placebo_total']} (every closure of two fixed date ranges, minus the event closures).")
    for s in plain_reading(res):
        L.append(f"- {s}")
    L.append("")
    L.append("## Event table\n")
    L.append("PM columns are the Yes-price in percentage points at the closure start and end; `oriented` multiplies the change by the market's pre-set sign "
             "(+1 Trump-wins market, -1 recession market) so that positive means the equity-bullish direction. Gaps are in basis points. "
             "`news ET` is approximate and decides only which closure the event belongs to.\n")
    L.append("| Event | Closure (close day to open day) | Type | Market | News ET (approx) | PM close | PM open | PM change | Oriented | SPY gap (bp) | SPY first 30 min (bp) | QQQ gap (bp) | Same sign? |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in et.iterrows():
        L.append(f"| {r['name']} | {r['closure']} to {r['open_day']} | {r['kind']} | {r['market']} | {str(r['news_et']).replace('T', ' ')} | "
                 f"{_f(r['pm_close'])} | {_f(r['pm_open'])} | {_f(r['dpm_pp'], 1, True)} | {_f(r['dpm_o_pp'], 1, True)} | {_f(r['gap_bp'], 0, True)} | "
                 f"{_f(r['ret30_bp'], 0, True)} | {_f(r.get('gap_qqq_bp'), 0, True)} | {r['agree']}{'; ' + r['reason'] if r['reason'] else ''} |")
    L.append("")
    L.append("![scatter](charts/scatter_gap_vs_pm.png)\n")
    L.append("![events](charts/events_pm_vs_gap.png)\n")
    L.append("## Tests on the news events (METHOD.md section 4)\n")
    L.append("**T1 sign agreement** (exact two-sided binomial against 50%; headline threshold 1.0 pp):\n")
    L.append("| Min PM move | Events | Agree | Rate | p |\n|---|---|---|---|---|")
    for k, t in res["t1_events"].items():
        L.append(f"| {k} pp{' (headline)' if k == th else ''} | {t['n']} | {t['k']} | {_f(100 * t['rate'], 0) if t['n'] else 'n/a'}% | {_p(t['p'])} |")
    L.append("")
    t2 = res["t2_events"]
    L.append(f"**T2 regression** `gap = a + b * oriented PM change`, n = {t2['n']}: b = {_f(t2['b'], 2, True)} bp per pp, HC3 t = {_f(t2['t'], 2, True)}, "
             f"R-squared = {_f(t2['r2'], 3)}, permutation p = {_p(t2['p_perm'])} (10,000 shuffles). Spearman rho = {_f(t2['rho'], 2, True)} (permutation p = {_p(t2['p_rho'])}).\n")
    t31, t32, t4a, t4b = res["t3_events_t1"], res["t3_events_t2"], res["t4_events_t1"], res["t4_events_t2"]
    lo = res.get("loo", {})
    if "full" in lo:
        s = (f"**Leverage check, exploratory (METHOD.md Amendment 2, added after the first run).** Leave-one-event-out slope: {_f(lo['min'], 1, True)} "
             f"(without {lo['min_drop'][:3]}) to {_f(lo['max'], 1, True)} (without {lo['max_drop'][:3]}), positive in {lo['n_positive']} of {lo['n']}.")
        ne = lo.get("no_election")
        if ne:
            s += (f" Only the {ne['n']} recession-market events: slope {_f(ne['b'], 2, True)} bp per pp (HC3 t = {_f(ne['t'], 2, True)}, permutation p = {_p(ne['p_perm'])}), "
                  f"Spearman rho {_f(ne['rho'], 2, True)} (p = {_p(ne['p_rho'])}). The election call (e04) is a very large, high-leverage point: it inflates the HC3 standard error "
                  "(hence the low HC3 t next to the small permutation p). It does not carry the slope, since dropping it makes the slope larger, not smaller; "
                  "the two markets simply have different bp-per-pp scales (a Trump-odds point and a recession-odds point are not the same unit of news).")
        L.append(s + "\n")
    L.append("Secondary (not part of the decision rule):\n")
    L.append(f"- **T3 first 30 minutes after the open**: sign agreement at 1 pp: {_t1s(t31[th])}. Slope {_f(t32['b'], 2, True)} bp per pp (t = {_f(t32['t'], 2, True)}, permutation p = {_p(t32['p_perm'])}, n = {t32['n']}). "
             f"Gap vs first-30-minute direction: the move continued the gap's direction in {res['gap_vs_ret30']['continue']} of {res['gap_vs_ret30']['n']} events.")
    L.append(f"- **T4 residual gap** (PM change up to 08:00 ET against the SPY move from 08:00 ET to the open): sign agreement {_t1s(t4a)}; slope {_f(t4b['b'], 2, True)} bp per pp (t = {_f(t4b['t'], 2, True)}, permutation p = {_p(t4b['p_perm'])}, n = {t4b['n']}). "
             "A slope near zero here would mean pre-market SPY had already absorbed the PM move by 08:00 ET.")
    for nm, lab in (("overnight", "overnight closures"), ("weekend_holiday", "weekend and holiday closures")):
        t, s = res[f"t1_{nm}"], res[f"t2_{nm}"]
        L.append(f"- Subset, {lab}: {_t1s(t)}; slope {_f(s['b'], 2, True)} bp per pp (permutation p = {_p(s['p_perm'])}, n = {s['n']}).")
    for nm in ("election", "recession"):
        L.append(f"- Subset, {nm} market: {_t1s(res[f't1_{nm}'])}.")
    L.append("")
    L.append("## Placebo (METHOD.md section 5)\n")
    L.append(f"Median absolute SPY gap: events {_f(res['median_abs_gap_events'], 0)} bp, placebo closures {_f(res['median_abs_gap_placebo'], 0)} bp. "
             f"Closure types, events: {res['mix_events']}; placebo: {res['mix_placebo']}.\n")
    L.append("**P1 the same tests on closures with no flagged news**\n")
    L.append("| Min PM move | Closures | Agree | Rate | p |\n|---|---|---|---|---|")
    for k, t in res["p1_t1"].items():
        L.append(f"| {k} pp{' (headline)' if k == th else ''} | {t['n']} | {t['k']} | {_f(100 * t['rate'], 0) if t['n'] else 'n/a'}% | {_p(t['p'])} |")
    pt = res["p1_t2"]
    L.append(f"\nSlope on all {pt['n']} placebo closures: b = {_f(pt['b'], 2, True)} bp per pp, HC3 t = {_f(pt['t'], 2, True)}, R-squared = {_f(pt['r2'], 3)}, permutation p = {_p(pt['p_perm'])}. "
             f"By panel at 1 pp: " + "; ".join(f"{m}: {_t1s(d['t1'])} (n closures {d['n']})" for m, d in res["p1_by_panel"].items()) + ".\n")
    p2 = res["p2"]
    if p2["k_obs"] is not None:
        L.append(f"**P2 pairing placebo** (events with PM move >= 1 pp, n = {p2['n']}): each event's PM move paired with the gap of a random placebo closure from the same panel, 10,000 draws. "
                 f"Observed agreeing events {p2['k_obs']} vs {_f(p2['k_draws_mean'], 1)} on average under pairing; p = {_p(p2['p_k'])}. "
                 f"Observed slope {_f(p2['slope_obs'], 2, True)} vs {_f(p2['slope_draws_mean'], 2, True)} on average; p = {_p(p2['p_slope'])}.\n")
        L.append("![placebo](charts/pairing_placebo.png)\n")
    p3 = res["p3"]
    L.append(f"**P3 interaction** (events plus placebo, n = {p3['n']}): `gap = a + b*dpm + c*news + d*dpm*news`; b = {_f(p3['b'], 2, True)} (t = {_f(p3['b_t'], 2, True)}), "
             f"d = {_f(p3['d'], 2, True)} (t = {_f(p3['d_t'], 2, True)}).\n")
    L.append("## Caveats\n")
    for c in (
        "**Hindsight selection.** The 17 events were chosen after the fact, knowing they were big news days. Large gaps are therefore likely by construction, and the sign agreement is a statement about these days, not about a forecast made in advance. The placebo panels are unselected and are the guard against this, not a cure.",
        "**Shared markets.** 13 events use the same recession market and 4 use the Trump market. Events are not independent draws; the binomial and slope p-values are somewhat too optimistic.",
        "**Co-movement, not lead.** PM change and gap cover the same window. A positive relation says they moved together over the closure, not that the PM moved first. Only the residual-gap test (T4) looks at timing.",
        "**Equities are not literally closed.** SPY trades after hours and pre-market, and futures trade almost around the clock. The gap is measured against regular-session prints. The PM is therefore not the only price during the closure.",
        "**Loose market-to-news fit and a fixed sign.** A recession market is an imperfect mirror of tariff, strike or shutdown news. Using one market and one sign per period was chosen to avoid picking favourable markets per event; it costs relevance, and the 2025-10-01 and 2025-11-09 shutdown events and the DeepSeek weekend fit especially loosely.",
        "**Level dependence.** A 1 pp PM move is large at 3% and small at 50%. The recession market fell toward the low single digits in late 2025, so late-2025 closures rarely pass the 1 pp threshold.",
        "**Small n.** The sign test has little power; a null does not show absence of an effect, and a significant result would be driven by few events.",
        "**Not tested.** A tradeable lead (a PM move at time t inside the closure predicting the *remaining* equity move) would need an intra-closure timing design; T4 is the closest piece here.",
        "**Placebo is not news-free.** Scheduled releases at 08:30 ET (CPI, jobs) and unflagged news sit in the placebo closures.",
    ):
        L.append(f"- {c}")
    L.append("")
    L.append("## Files\n")
    L.append("`closures_all.csv` (every closure: PM close/open, change, SPY gap, first-30-minute return, residual, QQQ gap, flags), `events.csv` (the table above), "
             "`tests.json` (every statistic), `charts/`, `RUN_LOG.md`. Code in `research/leadlag_closed/`, tests in `research/leadlag_closed/tests/`.")
    path.write_text("\n".join(L) + "\n")


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if k not in ("k_draws", "slope_draws")}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def write_all(rows: pd.DataFrame, res: dict, markets: dict, charts: bool = True, out_dir=None) -> None:
    out = out_dir or RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    et = event_table(rows)
    et.to_csv(out / "events.csv", index=False)
    (out / "tests.json").write_text(json.dumps(_jsonable(res), indent=2))
    if charts:
        (out / "charts").mkdir(exist_ok=True)
        chart_scatter(rows, res, out / "charts" / "scatter_gap_vs_pm.png")
        chart_events(rows, out / "charts" / "events_pm_vs_gap.png")
        chart_placebo(res, out / "charts" / "pairing_placebo.png")
    write_summary(rows, res, markets, et, out / "SUMMARY.md")
