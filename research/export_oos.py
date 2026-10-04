from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

OUT = Path("results/oos")
DONE = OUT / ".done"
IN_SAMPLE = Path("results/in_sample")
LAST_SESSION = "2026-10-02"

if DONE.exists():
    sys.exit(f"refusing to run: {DONE} exists; the out-of-sample window is run once (HYPOTHESIS.md §4).\n"
             f"{DONE.read_text()}")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from polybridge_research.analysis import decay_table, difference_board, scoreboard  # noqa: E402
from polybridge_research.atlas import count_variants  # noqa: E402
from polybridge_research.calendar import TradingCalendar  # noqa: E402
from polybridge_research.config import StudyConfig  # noqa: E402
from polybridge_research.costs import cost_summary, cost_table  # noqa: E402
from polybridge_research.massive import MassiveClient, load_api_key  # noqa: E402
from polybridge_research.pipeline import run_family_study  # noqa: E402
from polybridge_research.schema import STRATEGY_FOR_FAMILY, Family  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
t_start = time.time()
started = datetime.now().astimezone()


def log(msg):
    print(f"[{time.time() - t_start:7.0f}s] {msg}", flush=True)


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else str(v) for v in row) + " |"
              for row in df.itertuples(index=False)]
    return "\n".join(lines)


cfg = StudyConfig()
cfg.validate()
client = MassiveClient(load_api_key(search_from=Path.cwd()))
cal = TradingCalendar()
last = pd.Timestamp(LAST_SESSION)
log(f"OUT-OF-SAMPLE window {cfg.oos_start} -> {cfg.oos_end}; last session used for exits {last.date()} (pinned); "
    f"timing conservative (user_agent=None)")
study = run_family_study(client, cal, cfg, cfg.oos_start, cfg.oos_end, last, user_agent=None, max_workers=8)
DONE.write_text(f"out-of-sample study computed {datetime.now().astimezone().isoformat(timespec='seconds')}; "
                f"window {cfg.oos_start} -> {cfg.oos_end}; LAST_SESSION {LAST_SESSION}; started "
                f"{started.isoformat(timespec='seconds')}\n")
log("study done (.done written)")

ev, res, pl, dropped = study["events"], study["results"], study["placebo_results"], study["dropped"]
order = [*cfg.horizons, "exp"]
hpos = lambda hs: [order.index(h) for h in hs]  # noqa: E731


def fam_of(df, fam):
    return df[df["family"] == fam] if len(df) and "family" in df else df.iloc[0:0]


if not ev.empty:
    (ev.assign(month=pd.to_datetime(ev["filing_date"]).dt.strftime("%Y-%m")).groupby(["family", "month"]).size()
     .rename("n_events").reset_index().to_csv(OUT / "events_summary.csv", index=False))
else:
    pd.DataFrame(columns=["family", "month", "n_events"]).to_csv(OUT / "events_summary.csv", index=False)
pd.DataFrame({"n_cross_family_filings_excluded": [len(study["excluded"])]}).to_csv(OUT / "excluded.csv", index=False)
(dropped.groupby("reason").size().rename("n").reset_index() if len(dropped)
 else pd.DataFrame(columns=["reason", "n"])).to_csv(OUT / "dropped_reasons.csv", index=False)
(study["placebo_dropped"].groupby(["family", "reason"]).size().rename("n").reset_index()
 if len(study["placebo_dropped"]) else pd.DataFrame(columns=["family", "reason", "n"])
 ).to_csv(OUT / "placebo_dropped_reasons.csv", index=False)
pd.DataFrame(list(study["timing_counts"].items()), columns=["timing", "n"]).to_csv(OUT / "timing_counts.csv", index=False)
(OUT / "variants.txt").write_text(f"{count_variants(cfg)}\n")
log("global tables written")

summary_sections, verdicts, comparisons = [], {}, {}
for fam in ("hedge", "opportunity"):
    strat = STRATEGY_FOR_FAMILY[Family(fam)]
    chk = study["checks"].get(fam)
    ev_r, pl_r = fam_of(res, fam), fam_of(pl, fam)
    log(f"[{fam}] exporting")
    if chk is None:
        verdicts[fam] = "NULL"
        (OUT / f"{fam}_verdict.txt").write_text("NULL\n")
        summary_sections.append(f"## {fam} ({strat}): NULL\n\nNo out-of-sample events for this family, so the "
                                f"pass rule cannot be met. Verdict as computed: NULL.")
        log(f"[{fam}] no events; verdict NULL")
        continue
    diff = difference_board(ev_r, pl_r, cfg, level=cfg.confirmatory_level)
    diff.to_csv(OUT / f"{fam}_difference_975.csv", index=False)
    t = chk["pnl"][["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]].rename(
        columns={"n_a": "n_events", "n_b": "n_placebo", "difference": "pnl_difference"})
    t = t.merge(chk["ratio"][["horizon", "difference"]].rename(columns={"difference": "ratio_difference"}),
                on="horizon", how="outer")
    t["pnl_ok"] = t["horizon"].isin(chk["horizons_pnl_ok"])
    t["ratio_ok"] = t["horizon"].isin(chk["horizons_ratio_ok"])
    t.to_csv(OUT / f"{fam}_pass_check.csv", index=False)
    verdict = "PASS" if chk["passed"] else "NULL"
    verdicts[fam] = verdict
    (OUT / f"{fam}_verdict.txt").write_text(f"{verdict}\n")
    de, dp = decay_table(ev_r, cfg), decay_table(pl_r, cfg)
    de.to_csv(OUT / f"{fam}_decay_events.csv")
    dp.to_csv(OUT / f"{fam}_decay_placebo.csv")
    r21, p21 = ev_r[ev_r.horizon == 21], pl_r[pl_r.horizon == 21]
    keys = ["bucket", "entry", "otm"]
    se = r21.groupby(keys)[strat].agg(n_events="count", mean_events="mean")
    sp = p21.groupby(keys)[strat].agg(n_placebo="count", mean_placebo="mean")
    sens = se.join(sp, how="outer")
    sens["edge"] = sens["mean_events"] - sens["mean_placebo"]
    sens.reset_index().to_csv(OUT / f"{fam}_sensitivity.csv", index=False)
    priced_f = [p for p in study["priced"] if str(getattr(p.family, "value", p.family)) == fam]
    pl_priced_f = [p for p in study["placebo_priced"] if str(getattr(p.family, "value", p.family)) == fam]
    summaries = []
    for h in (21, 42, "exp"):
        if ev_r.empty or not priced_f:
            continue
        try:
            ct = cost_table(ev_r, priced_f, strat, h, cfg, client=client)
        except Exception as e:
            print(f"cost_table with quotes failed ({type(e).__name__}); falling back to client=None", flush=True)
            ct = cost_table(ev_r, priced_f, strat, h, cfg, client=None)
        ct.drop(columns=["ticker", "event_date"]).to_csv(OUT / f"{fam}_costs_h{h}.csv", index=False)
        ct_pl = cost_table(pl_r, pl_priced_f, strat, h, cfg, client=None) if len(pl_r) and pl_priced_f else None
        summaries.append({"horizon": h, **cost_summary(ct, ct_pl)})
    cs = pd.DataFrame(summaries)
    if summaries:
        cs.to_csv(OUT / f"{fam}_cost_summary.csv", index=False)
    ins_path = IN_SAMPLE / f"{fam}_pass_check.csv"
    cmp_ = None
    if ins_path.exists():
        ins = pd.read_csv(ins_path)[["horizon", "n_events", "pnl_difference", "ratio_difference"]].rename(
            columns={"n_events": "n_events_in_sample", "pnl_difference": "edge_in_sample",
                     "ratio_difference": "ratio_diff_in_sample"})
        ins["horizon"] = ins["horizon"].astype(str)
        oo = t[["horizon", "n_events", "pnl_difference", "ratio_difference"]].rename(
            columns={"n_events": "n_events_oos", "pnl_difference": "edge_oos", "ratio_difference": "ratio_diff_oos"})
        oo = oo.assign(horizon=oo["horizon"].astype(str))
        cmp_ = ins.merge(oo, on="horizon", how="outer")
        cmp_["edge_same_sign"] = np.sign(cmp_.edge_in_sample) == np.sign(cmp_.edge_oos)
        cmp_["ratio_same_sign"] = np.sign(cmp_.ratio_diff_in_sample) == np.sign(cmp_.ratio_diff_oos)
        cmp_.to_csv(OUT / f"{fam}_in_sample_vs_oos.csv", index=False)
        comparisons[fam] = cmp_
    sb_e, sb_p = scoreboard(ev_r, cfg, strategies=[strat]), scoreboard(pl_r, cfg, strategies=[strat])
    fig, ax = plt.subplots(figsize=(6, 3.8))
    for sb, label, c in ((sb_e, "events", "tab:red"), (sb_p, "placebo", "tab:gray")):
        d = sb.dropna(subset=["mean"])
        if d.empty:
            continue
        x = hpos(d["horizon"])
        ax.plot(x, d["mean"], marker="o", color=c, label=label)
        ax.fill_between(x, d["ci_lo"], d["ci_hi"], color=c, alpha=0.2)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([*map(str, cfg.horizons), "exp"])
    ax.set_title(f"OOS {fam}: {strat} mean P&L per $1 spot (95% CI)")
    ax.set_xlabel("horizon (sessions)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / f"{fam}_scoreboard.png", dpi=120)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 3.8))
    for tbl, label, c in ((de, "events", "tab:red"), (dp, "placebo", "tab:gray")):
        d = tbl.dropna(subset=["mean_ratio"])
        if d.empty:
            continue
        x = hpos(d.index)
        ax.plot(x, d["mean_ratio"], marker="o", color=c, label=label)
        ax.fill_between(x, d["ci_lo"], d["ci_hi"], color=c, alpha=0.2)
    ax.axhline(1, color="k", lw=0.5, ls="--")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([*map(str, cfg.horizons), "exp"])
    ax.set_title(f"OOS {fam}: mean parity ratio by horizon")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / f"{fam}_decay.png", dpi=120)
    plt.close(fig)
    hyp = "H1 hedge, protective put" if fam == "hedge" else "H2 opportunity, cash-secured put"
    pc = t.copy()
    pc["97.5% CI"] = pc.apply(lambda r: f"[{r.ci_lo:+.4f}, {r.ci_hi:+.4f}]", axis=1)
    pc = pc.assign(edge=pc.pnl_difference.map(lambda v: f"{v:+.4f}"),
                   ratio_diff=pc.ratio_difference.map(lambda v: f"{v:+.3f}"),
                   n=pc.apply(lambda r: f"{r.n_events:.0f} / {r.n_placebo:.0f}", axis=1))
    sec = [f"## {hyp}: {verdict}",
           md(pc[["horizon", "n", "edge", "97.5% CI", "ratio_diff", "pnl_ok", "ratio_ok"]]),
           f"Rule 1 horizons (CI excludes zero, predicted direction): {chk['horizons_pnl_ok'] or 'none'}. "
           f"Rule 2 horizons (ratio difference has the predicted sign): {chk['horizons_ratio_ok'] or 'none'}. "
           f"Passing needs both at 2 or more headline horizons. Verdict as computed: {verdict}."]
    if cmp_ is not None:
        c2 = cmp_[["horizon", "n_events_in_sample", "edge_in_sample", "n_events_oos", "edge_oos",
                   "edge_same_sign", "ratio_diff_in_sample", "ratio_diff_oos", "ratio_same_sign"]].round(4)
        sec.append("In-sample (committed `results/in_sample/`) vs out-of-sample, headline horizons:\n\n" + md(c2))
    dd = de[["n", "mean_ratio", "ci_lo", "ci_hi"]].round(3).reset_index()
    dpp = dp[["n", "mean_ratio"]].round(3).reset_index().rename(columns={"n": "n_placebo",
                                                                          "mean_ratio": "mean_ratio_placebo"})
    sec.append("Parity decay (mean R, entry on the pre-event session, events with 95% CI; placebo mean):\n\n"
               + md(dd.merge(dpp, on="horizon", how="outer")))
    if not cs.empty:
        cols = [c for c in ("horizon", "n", "n_gross", "n_paired", "gross", "gross_paired", "spread_cost_paired",
                            "net_spread_paired", "net_haircut_1x", "net_haircut_2x", "net_edge_1x", "net_edge_2x")
                if c in cs]
        sec.append("Costs (mean P&L per $1 spot; net edge = events minus placebo after the 5% haircut, and at 2x):"
                   "\n\n" + md(cs[cols].round(4)))
    summary_sections.append("\n\n".join(sec))
    log(f"[{fam}] verdict {verdict}")

n_fam = (ev.groupby("family").size().to_dict() if not ev.empty else {})
pl_ev = study["placebo_events"]
n_pl = (pl_ev.groupby("family").size().to_dict() if len(pl_ev) and "family" in pl_ev else {})
drop_txt = ("; ".join(f"{r.reason}: {r.n}" for r in dropped.groupby("reason").size().rename("n").reset_index()
                      .itertuples()) if len(dropped) else "none")
pdrop = study["placebo_dropped"]
pdrop_txt = (", ".join(f"{f} {n}" for f, n in pdrop.groupby("family").size().items()) if len(pdrop) else "none")
head = [
    f"# Out-of-sample results, {cfg.oos_start} to {cfg.oos_end}",
    f"The single out-of-sample run of the pre-registered 8-K study (`research/HYPOTHESIS.md` §4), executed after the "
    f"method freeze (git tag `method-freeze`). Produced by `research/export_oos.py`; every number below is generated "
    f"from the computed tables, with no edits. Started {started.strftime('%Y-%m-%d %H:%M %Z')}.",
    f"Same `StudyConfig` as in-sample (baseline 3-6m expiry, 5% OTM, entry \"post\", 97.5% bootstrap CI, "
    f"{cfg.n_placebo} placebo days per family), conservative timing, last session used for exits pinned to "
    f"{LAST_SESSION}. Edge = event mean minus placebo mean, P&L per $1 of spot at entry.",
    "## Verdicts\n\n" + md(pd.DataFrame([{"hypothesis": "H1 hedge (protective put)", "oos_verdict": verdicts.get("hedge"),
                                           "in_sample_verdict": (IN_SAMPLE / "hedge_verdict.txt").read_text().strip()},
                                          {"hypothesis": "H2 opportunity (cash-secured put)",
                                           "oos_verdict": verdicts.get("opportunity"),
                                           "in_sample_verdict": (IN_SAMPLE / "opportunity_verdict.txt").read_text().strip()}])),
    "## Sample\n\n"
    f"- Events: hedge {n_fam.get('hedge', 0)}, opportunity {n_fam.get('opportunity', 0)} "
    f"(by month in `events_summary.csv`). Cross-family filings excluded: {len(study['excluded'])}.\n"
    f"- Event/bucket pricing drops: {drop_txt}.\n"
    f"- Timing: {dict(study['timing_counts'])}.\n"
    f"- Placebo days sampled: {n_pl}; placebo pricing drops (event/bucket pairs): {pdrop_txt}.\n"
    f"- Events late in the window have fewer completed exits by {LAST_SESSION} (42-session, 63-session and "
    f"expiry horizons), so n falls at longer horizons; the n per horizon is in every table.",
]
tail = ["## Notes",
        "- Pass rule as pre-registered (§4, with the 2026-10-02 clarification of rule 2): rule 1 needs the 97.5% CI of "
        "the event-minus-placebo edge to exclude zero in the predicted direction at 2 or more of 21, 42 and expiry; "
        "rule 2 needs the event-minus-placebo mean R to have the predicted sign (H1 > 0, H2 < 0) at those horizons.",
        "- Figures plot 95% bootstrap bands; the pass-rule CIs are 97.5%.",
        "- This window was run once. `.done` in this folder records the run; `export_oos.py` refuses to run again."]
(OUT / "SUMMARY.md").write_text("\n\n".join(head + summary_sections + tail) + "\n")
log("SUMMARY.md written")
log("export complete")
