from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def pt(m: dict, key: str = "mean", ci: str = "ci") -> str:
    return f"{100 * m[key]:+.2f} pt [{100 * m[ci][0]:+.2f}, {100 * m[ci][1]:+.2f}]"


def sh(m: dict) -> str:
    return f"{m['value']:.2f} [{m['ci'][0]:.2f}, {m['ci'][1]:.2f}]"


def sl(m: dict) -> str:
    return f"{m['beta']:.2f} [{m['ci'][0]:.2f}, {m['ci'][1]:.2f}]"


def sc(m: dict, k: str) -> str:
    return f"{m[k]['pm']:.4f} vs {m[k]['opt']:.4f}, diff {m[k]['d']['mean']:+.4f} [{m[k]['d']['ci'][0]:+.4f}, {m[k]['d']['ci'][1]:+.4f}]"


def chart(a: dict, path: Path) -> None:
    keys = [("R", "PM gives back"), ("F", "options catch up"), ("L", "left at the close")]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    names = ["closure gap G"] + [n for _, n in keys]
    vals = [100 * a["G"]["mean"]] + [100 * a[k]["mean"] for k, _ in keys]
    los = [100 * a["G"]["ci"][0]] + [100 * a[k]["ci"][0] for k, _ in keys]
    his = [100 * a["G"]["ci"][1]] + [100 * a[k]["ci"][1] for k, _ in keys]
    err = [[v - lo for v, lo in zip(vals, los)], [hi - v for v, hi in zip(vals, his)]]
    ax.bar(names, vals, color=["#555555", "#D55E00", "#0072B2", "#999999"], yerr=err, capsize=4)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("probability points (signed by PM move)")
    ax.set_title(f"Where the Monday-open gap goes (n={a['n']}, {a['clusters']} closures)", fontsize=10)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def summary(st: dict, meta: dict) -> str:
    a, va = st["decomposition"], st["verdict_a"]
    po, pc = st["open_pair"], st["close_pair"]
    L = ["# T4: overshoot or slow options at the Monday open?\n",
         f"Run {meta['run_utc']}. Pre-registered method: [`research/overshoot/METHOD.md`](../../overshoot/METHOD.md) "
         f"(committed in `{meta['method_commit']}` before any statistic was computed). Numbers: [`stats.json`](stats.json). "
         "Chart: [`decomposition.png`](decomposition.png). Log: [`RUN_LOG.md`](RUN_LOG.md).\n",
         "**This is a pre-registered re-analysis of R3's already-seen rows (`research/results/open_options/events.csv`). "
         "It is not confirmatory.** No new data was fetched.\n",
         "## Answer\n",
         f"Sample: {st['n_events']} R3 events from {st['clusters_events']} closures; decomposition sample (PM at 16:00 and "
         f"options at 15:55 both present) {a.get('n', 0)} events from {a.get('clusters', 0)} closures. Intervals are 95% "
         "closure-cluster bootstrap (10,000 draws).\n"]
    if a.get("n", 0):
        L += [f"**(a) Decomposition verdict: {va['label']}** ({va['persists_label']}).\n",
              f"- Closure gap G (PM move minus option move, signed by the PM move): {pt(a['G'])}.",
              f"- PM gives back after the open (by 16:00): {pt(a['R'])}; share of G {sh(a['share_R'])}.",
              f"- Options catch up after 09:45 (by 15:55): {pt(a['F'])}; share of G {sh(a['share_F'])}.",
              f"- Left at the end of the reopening day: {pt(a['L'])}; share of G {sh(a['share_L'])}.",
              f"- Catch-up slope at 09:45 on the PM closure move: {sl(a['beta_open'])}; on the PM move that survives to 16:00: "
              f"{sl(a['beta_perm'])}; options' full-day move on the PM's full-day move: {sl(a['beta_eod'])}.\n"]
    if po.get("n", 0):
        L += [f"**(b) Forecast verdict at the open: {st['verdict_open']}**; at the prior close: {st['verdict_close']}.\n",
              f"- Open pair (PM 09:30 vs options 09:45, n={po['n']}, {po['clusters']} closures), PM vs options, diff = PM minus "
              f"options (positive = options better): Brier {sc(po, 'brier')}; log score {sc(po, 'log')}.",
              f"- Close pair (PM at the close vs options 15:55, n={pc['n']}): Brier {sc(pc, 'brier')}; log score {sc(pc, 'log')}.\n"]
    L += ["## Secondary (reported, not used for the verdicts)\n",
          "Decomposition variants:\n",
          "| sample | events | closures | G | PM gives back | options catch up | left | share given back |",
          "|---|---|---|---|---|---|---|---|"]
    rows = {"primary": a, **st["secondary_a"]}
    for name, s in rows.items():
        if s.get("n", 0):
            L.append(f"| {name} | {s['n']} | {s['clusters']} | {pt(s['G'])} | {pt(s['R'])} | {pt(s['F'])} | {pt(s['L'])} | {sh(s['share_R'])} |")
        else:
            L.append(f"| {name} | 0 | 0 | | | | | |")
    if a.get("n", 0):
        L += ["", "Equal weight per closure (primary decomposition): " + "; ".join(
            f"{k} {pt(a[k], 'cw_mean', 'cw_ci')}" for k in ("G", "R", "F", "L")) + ".\n"]
    L += ["Forecast variants (diff = PM minus options, positive = options better):\n",
          "| pair | events | closures | Brier PM vs options, diff [CI] | log score PM vs options, diff [CI] |",
          "|---|---|---|---|---|"]
    for name, s in {"open pair (primary)": po, "close pair": pc, **st["secondary_b"]}.items():
        if s.get("n", 0):
            L.append(f"| {name} | {s['n']} | {s['clusters']} | {sc(s, 'brier')} | {sc(s, 'log')} |")
    if po.get("n", 0):
        L += ["", f"Equal weight per closure, open pair: Brier diff {po['brier']['d']['cw_mean']:+.4f} "
              f"[{po['brier']['d']['cw_ci'][0]:+.4f}, {po['brier']['d']['cw_ci'][1]:+.4f}]; log diff "
              f"{po['log']['d']['cw_mean']:+.4f} [{po['log']['d']['cw_ci'][0]:+.4f}, {po['log']['d']['cw_ci'][1]:+.4f}].\n"]
    cc, en = st["closure_change"], st["encompassing"]
    if cc.get("n", 0):
        L.append(f"Change in the options' forecasting edge over the closure (open-pair diff minus close-pair diff, n={cc['n']}): "
                 f"Brier {cc['brier']['mean']:+.4f} [{cc['brier']['ci'][0]:+.4f}, {cc['brier']['ci'][1]:+.4f}]; log "
                 f"{cc['log']['mean']:+.4f} [{cc['log']['ci'][0]:+.4f}, {cc['log']['ci'][1]:+.4f}].\n")
    if en.get("n", 0):
        L.append(f"Does the PM add anything beyond the options? Linear probability of YES on both prices (n={en['n']}): "
                 f"PM at 09:30 coefficient {en['b1']:+.2f} [{en['b1_ci'][0]:+.2f}, {en['b1_ci'][1]:+.2f}], options at 09:45 "
                 f"{en['b2']:+.2f} [{en['b2_ci'][0]:+.2f}, {en['b2_ci'][1]:+.2f}]. "
                 + ("The PM adds information beyond the options (lower bound above 0)." if en["pm_adds"]
                    else "The PM is not shown to add information beyond the options.") + "\n")
    L += ["## Caveats\n",
          "- Re-analysis of rows whose R3 summary was read before this method was written; the signs of the PM give-back "
          "and the option follow-through were known. Not confirmatory.",
          "- Overshoot and noise are not separated: Polymarket per-minute prices can be thin-book midpoints, and R3 kept only "
          "PM moves of 3 points or more, so part of any give-back is mechanical regression to the mean. 'Gives back' means "
          "only that the PM moved back toward its Friday price. The trade-print subset is the partial check.",
          "- The only later horizon is the end of the reopening day; weekly and month-end contracts resolve later.",
          "- Options are measured at 09:45, the PM at 09:30; the same-instant rows handle that.",
          "- Outcomes are shared within a closure and underlying, so the effective sample is nearer the number of closures; "
          "the bootstrap resamples closures.",
          "- The call spread approximates the digital and settles on a slightly different print than the PM."]
    return "\n".join(L) + "\n"
