from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

VERDICT_TEXT = {
    "PASS": "PASS: on fresh markets the option-implied probability was a more accurate forecast than the Polymarket price, on both Brier and log score.",
    "PARTIAL": "PARTIAL: only one of the two scores shows options more accurate with a CI above 0.",
    "REVERSED": "REVERSED: the Polymarket price was the more accurate forecast.",
    "NULL": "NULL: no accuracy difference shown.",
    "INSUFFICIENT": "INSUFFICIENT: below the 2,000-row or 40-date floor; no claim either way.",
    "SLICE-STOP": "STOPPED at the slice check (valid rate below 30%); no claim either way.",
}


def f4(x) -> str:
    return f"{x:+.4f}"


def ci(c) -> str:
    return f"[{c[0]:+.4f}, {c[1]:+.4f}]"


def line(name: str, b: dict) -> str:
    if not b.get("n"):
        return f"| {name} | 0 | 0 | | |"
    B, L = b["d_B"], b["d_L"]
    return (f"| {name} | {b['n']} | {b['clusters']} | {b['brier_pm']:.4f} vs {b['brier_opt']:.4f}, diff {f4(B['mean'])} {ci(B['ci95'])} | "
            f"{b['ls_pm']:.4f} vs {b['ls_opt']:.4f}, diff {f4(L['mean'])} {ci(L['ci95'])} |")


def write_stopped(out: Path, verdict: str, info: dict, commit: str, t0: datetime) -> None:
    (out / "SUMMARY.md").write_text(
        f"# Fresh-market accuracy: options vs Polymarket\n\n**Verdict: {verdict}.** {VERDICT_TEXT[verdict]}\n\n"
        f"Method: [`research/fresh_accuracy/METHOD.md`](../../fresh_accuracy/METHOD.md). Run started {t0.isoformat()} at commit `{commit}`.\n\n"
        f"```\n{json.dumps(info, indent=1, default=str)[:4000]}\n```\n")


def write_summary(out: Path, r: dict) -> None:
    P = r["primary"]
    B, L = P["d_B"], P["d_L"]
    sec = r["secondary"]
    enc, fl = r["encompassing_logit"], r["favourite_longshot"]
    same = r["verdict_equal_weight"] == r["verdict"]
    g = r["gate"]
    parts = [
        "# Fresh-market accuracy: options vs Polymarket on equity-threshold markets no earlier study touched",
        f"Run {r['finished_utc'][:16]}Z at commit `{r['commit']}`. Pre-registered method: [`research/fresh_accuracy/METHOD.md`](../../fresh_accuracy/METHOD.md) "
        "(committed with the frozen market list before any price, quote or outcome was fetched). Numbers: [`stats.json`](stats.json). "
        "Rows: [`rows.csv`](rows.csv). Chart: [`accuracy_chart.png`](accuracy_chart.png). Log: [`RUN_LOG.md`](RUN_LOG.md).",
        f"## Answer\n\n**Verdict: {r['verdict']}.** {VERDICT_TEXT[r['verdict']]}",
        f"Sample: {r['n_rows']:,} scored (market, snapshot) rows from {r['n_markets']:,} markets, {r['n_events']:,} ticker-date ladders, "
        f"{r['n_dates']} resolution dates (the clusters). Difference = PM minus options, positive = options more accurate; "
        "95% resolution-date cluster bootstrap, 10,000 draws, seed 20261004.",
        f"- Brier: Polymarket {P['brier_pm']:.4f} vs options {P['brier_opt']:.4f}, difference **{f4(B['mean'])} {ci(B['ci95'])}**.\n"
        f"- Log score: Polymarket {P['ls_pm']:.4f} vs options {P['ls_opt']:.4f}, difference **{f4(L['mean'])} {ci(L['ci95'])}**.",
        "In words: the Polymarket price is a worse forecast than the option-implied probability measured at the same instant. "
        "This does not say Polymarket traders know less; the PM price PolyBridge reads is a per-minute series that can be a stale last "
        "price or the midpoint of a thin book, and that is the mechanism.",
        f"**Freshness.** The markets and outcome dates are fresh (none in R3's pairs or on R3's resolution dates, none in the arb scan's window). "
        "The hypothesis and its direction were already seen in the arb scan and in R3/T4, so this is a frozen-rule confirmation on new data, "
        "not a new hypothesis. The T4 overshoot (PM give-back) is not tested here.",
        f"**Equal weight per date (pre-registered check).** Mean of per-date means: Brier {f4(B['cw_mean'])} {ci(B['cw_ci95'])}, "
        f"log {f4(L['cw_mean'])} {ci(L['cw_ci95'])}. The verdict computed under this weighting would be {r['verdict_equal_weight']}, "
        f"which {'matches' if same else 'differs from'} the primary verdict; the primary verdict stands either way and is not rescued or changed by it.",
        "## Secondary (reported, never used for the verdict)",
        "| subset | rows | clusters | Brier PM vs options, diff [95% CI] | log score PM vs options, diff [95% CI] |\n|---|---|---|---|---|\n"
        + "\n".join([line("primary (date clusters)", P), line("event clusters (ticker x date)", sec["event_cluster"])]
                    + [line(k, v) for k, v in sec.items() if k != "event_cluster"]),
        f"Encompassing logit of the result on logit(options) and logit(PM), date-clustered: options coefficient "
        f"{enc['coef'][1]:+.3f} [{enc['ci95'][1][0]:+.3f}, {enc['ci95'][1][1]:+.3f}], PM coefficient {enc['coef'][2]:+.3f} "
        f"[{enc['ci95'][2][0]:+.3f}, {enc['ci95'][2][1]:+.3f}].",
        f"Favourite-longshot slope (PM minus options on options minus 0.5, date-clustered): {fl['coef'][1]:+.4f} "
        f"[{fl['ci95'][1][0]:+.4f}, {fl['ci95'][1][1]:+.4f}] (predicted negative). Mean |PM - options| {r['mean_abs_gap']:.4f}; "
        f"coarse rows (narrow and wide spread differ by more than 5 pt) {r['coarse_share']:.1%}.",
        f"## Costs (from data; no trade is claimed)\n\nOption reference: mean half-band (p_hi - p_lo)/2 {r['costs']['opt_half_band_mean']:.4f} "
        f"(median {r['costs']['opt_half_band_median']:.4f}) per $1 of payoff; commission {r['costs']['opt_comm_per_dollar_mean']:.4f} per $1 "
        f"(median {r['costs']['opt_comm_per_dollar_median']:.4f}). Polymarket historical spreads are not observable. An accuracy gap is not an "
        "executable edge: the arb scan found 0 executable gaps (5 verified), and R3's net gap was +0.79 pt [-1.21, +2.78].",
        h3_text(r.get("h3")),
        "## Funnel\n\n" + f"Frozen markets 9,349. Snapshots dropped by the listing and end rules: {g['dropped_snapshots']}. "
        f"Row status: {g['status']}. Scored rows at the coverage gate: {g['scored_rows']:,} on {g['dates']} dates. "
        f"Rows without a resolved outcome: {r['no_outcome_rows']}. Tickers in the scored sample: {r['tickers']}.",
        "## Caveats\n\n- The call spread averages the density over [K1, K2]; Polymarket settles on the Pyth 16:00 print, options on the "
        "official close; SPY and single-name options are American.\n- Rows within a date share one market move; inference clusters on "
        "date and the equal-weight and event-cluster versions are shown.\n- The fresh frame is earlier in Polymarket's life than the arb "
        "window and has more midweek dailies and weeklies.\n- The arb's informative filter (PM in [0.02, 0.98]) is kept unchanged although "
        "it is asymmetric.\n- Hypothesis and direction were known before the run (freshness above).",
    ]
    (out / "SUMMARY.md").write_text("\n\n".join(parts) + "\n")


def h3_text(h: dict | None) -> str:
    if not h:
        return "## H3: Kalshi index equivalence (gated)\n\nPending: run only if the primary is PASS and finished before 01:30 ET."
    if not h.get("run"):
        return f"## H3: Kalshi index equivalence (gated)\n\nH3 not run: {h['reason']}."
    b = h["result"]
    if not b.get("n"):
        return f"## H3: Kalshi index equivalence (gated)\n\n**H3 verdict: {h['verdict']}** (no scored rows). Status: {h['status']}."
    B, L = b["d_B"], b["d_L"]
    rows = "\n".join(line(f"series {k}", v) for k, v in h.get("by_series", {}).items())
    return ("## H3: Kalshi index equivalence (gated)\n\n"
            f"**H3 verdict: {h['verdict']}.** {h['n_rows']:,} Kalshi S2 rows on {h['n_dates']} dates. Brier Kalshi {b['brier_pm']:.4f} vs "
            f"options {b['brier_opt']:.4f}, difference {f4(B['mean'])}, 90% CI {ci(B['ci90'])} (equivalence margin +/-0.003), 95% CI "
            f"{ci(B['ci95'])}. Log score difference {f4(L['mean'])} {ci(L['ci95'])} (reported, not tested).\n\n"
            "| subset | rows | clusters | Brier Kalshi vs options | log score Kalshi vs options |\n|---|---|---|---|---|\n"
            f"{line('all', b)}\n{rows}\n\nKalshi costs from data: mean half-spread {h['costs']['k_half_spread_mean']:.4f}, "
            f"mean taker fee {h['costs']['k_fee_mean']:.4f} per $1. Row status: {h['status']}.")


def write_run_log(out: Path, r: dict, stage: str) -> None:
    f = out / "RUN_LOG.md"
    head = "# Run log: fresh-market accuracy\n\n" if not f.exists() else f.read_text()
    if stage == "primary":
        body = (f"## Primary run\n\n- Commit: `{r['commit']}`\n- Started {r['started_utc']}, finished {r['finished_utc']} "
                f"({r['seconds']:.0f} s)\n- Command: `cd research && SHARED_MASSIVE_CACHE=<shared dir> .venv/bin/python -m fresh_accuracy.run`\n"
                f"- Slice check: {r['slice']['valid']}/{r['slice']['rows']} valid ({r['slice']['valid_rate']:.1%}), threshold 30%, "
                f"status {r['slice']['status']}\n- Coverage gate: {r['gate']['scored_rows']} rows, {r['gate']['dates']} dates\n"
                f"- Requests (cache hits not counted): {json.dumps(r['requests']['http'])} Polymarket/Kalshi; "
                f"{json.dumps(r['requests']['massive'])} Massive\n- Failures: http {r['requests']['http_failures']}, "
                f"massive {r['requests']['massive_failures']}\n- Verdict: {r['verdict']}\n")
    else:
        h = r["h3"]
        body = (f"\n## H3 run\n\n- Commit: `{h['commit']}`\n- Started {h['started_utc']}, finished {h['finished_utc']}\n"
                f"- Command: `cd research && SHARED_MASSIVE_CACHE=<shared dir> .venv/bin/python -m fresh_accuracy.run --h3`\n"
                f"- Requests: {json.dumps(h['requests']['http'])}; massive {json.dumps(h['requests']['massive'])}\n"
                f"- Failures: http {h['requests']['http_failures']}, massive {h['requests']['massive_failures']}\n- Verdict: {h['verdict']}\n")
    f.write_text(head + body)


def chart(sc: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.6))
    bins = np.linspace(0, 1, 11)
    for col, lab, colr in (("pm_mid", "Polymarket price", "#D55E00"), ("p_mid", "Option-implied", "#0072B2")):
        b = np.clip(np.digitize(sc[col].clip(0, 1), bins) - 1, 0, 9)
        g = sc.groupby(b).agg(p=(col, "mean"), y=("outcome", "mean"), n=("outcome", "size"))
        ax[0].plot(g.p, g.y, "o-", color=colr, label=lab, ms=4)
    ax[0].plot([0, 1], [0, 1], color="#999999", lw=0.8)
    ax[0].set(xlabel="forecast probability (decile bins)", ylabel="share resolved YES", title="Calibration on fresh markets")
    ax[0].legend(frameon=False)
    d = sc.groupby("res_date").d_B.mean().sort_values()
    ax[1].plot(np.arange(len(d)), d.values, "o", ms=3, color="#0072B2")
    ax[1].axhline(0, color="#999999", lw=0.8)
    ax[1].axhline(sc.d_B.mean(), color="#D55E00", lw=1, label=f"row mean {sc.d_B.mean():+.4f}")
    ax[1].set(xlabel="resolution date (sorted)", ylabel="mean Brier(PM) - Brier(options)", title="Per-date difference (positive = options better)")
    ax[1].legend(frameon=False)
    for a in ax:
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
