from __future__ import annotations

import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from polybridge_research.analysis import decay_table, difference_board, robustness_table, scoreboard, verdict
from polybridge_research.atlas import count_variants
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.costs import cost_summary, cost_table
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study
from polybridge_research.schema import STRATEGY_FOR_FAMILY, Family

OUT = Path("results/in_sample")
OUT.mkdir(parents=True, exist_ok=True)
t_start = time.time()


def log(msg):
    print(f"[{time.time() - t_start:7.0f}s] {msg}", flush=True)


cfg = StudyConfig()
cfg.validate()
client = MassiveClient(load_api_key(search_from=Path.cwd()))
cal = TradingCalendar()
last = cal.last_completed()
log(f"window {cfg.study_start} -> {cfg.study_end}; last completed session {last.date()}")
study = run_family_study(client, cal, cfg, cfg.study_start, cfg.study_end, last, user_agent=None, max_workers=8)
log("study done")

ev, res, pl, dropped = study["events"], study["results"], study["placebo_results"], study["dropped"]
order = [*cfg.horizons, "exp"]
hpos = lambda hs: [order.index(h) for h in hs]


def fam_of(df, fam):
    return df[df["family"] == fam] if len(df) and "family" in df else df.iloc[0:0]


if not ev.empty:
    (ev.assign(year=pd.to_datetime(ev["filing_date"]).dt.year).groupby(["family", "year"]).size()
     .rename("n_events").reset_index().to_csv(OUT / "events_summary.csv", index=False))
pd.DataFrame({"n_cross_family_filings_excluded": [len(study["excluded"])]}).to_csv(OUT / "excluded.csv", index=False)
(dropped.groupby("reason").size().rename("n").reset_index() if len(dropped)
 else pd.DataFrame(columns=["reason", "n"])).to_csv(OUT / "dropped_reasons.csv", index=False)
(study["placebo_dropped"].groupby(["family", "reason"]).size().rename("n").reset_index()
 if len(study["placebo_dropped"]) else pd.DataFrame(columns=["family", "reason", "n"])
 ).to_csv(OUT / "placebo_dropped_reasons.csv", index=False)
pd.DataFrame(list(study["timing_counts"].items()), columns=["timing", "n"]).to_csv(OUT / "timing_counts.csv", index=False)
(OUT / "variants.txt").write_text(f"{count_variants(cfg)}\n")
log("global tables written")

for fam, chk in study["checks"].items():
    strat = STRATEGY_FOR_FAMILY[Family(fam)]
    ev_r, pl_r = fam_of(res, fam), fam_of(pl, fam)
    log(f"[{fam}] exporting")
    diff = difference_board(ev_r, pl_r, cfg, level=cfg.confirmatory_level)
    diff.to_csv(OUT / f"{fam}_difference_975.csv", index=False)
    t = chk["pnl"][["horizon", "n_a", "n_b", "difference", "ci_lo", "ci_hi"]].rename(
        columns={"n_a": "n_events", "n_b": "n_placebo", "difference": "pnl_difference"})
    t = t.merge(chk["ratio"][["horizon", "difference"]].rename(columns={"difference": "ratio_difference"}),
                on="horizon", how="outer")
    t["pnl_ok"] = t["horizon"].isin(chk["horizons_pnl_ok"])
    t["ratio_ok"] = t["horizon"].isin(chk["horizons_ratio_ok"])
    t.to_csv(OUT / f"{fam}_pass_check.csv", index=False)
    (OUT / f"{fam}_verdict.txt").write_text(f"{verdict(chk)}\n")
    robustness_table(ev_r, pl_r, fam, cfg).to_csv(OUT / f"{fam}_robustness.csv", index=False)
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
    if summaries:
        pd.DataFrame(summaries).to_csv(OUT / f"{fam}_cost_summary.csv", index=False)
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
    ax.set_title(f"{fam}: {strat} mean P&L per $1 spot (95% CI)")
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
    ax.set_title(f"{fam}: mean parity ratio by horizon")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / f"{fam}_decay.png", dpi=120)
    plt.close(fig)
    log(f"[{fam}] verdict {verdict(chk)}")

log("export complete")
