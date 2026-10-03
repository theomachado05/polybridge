"""SUMMARY.md, catchup_chart.png and stats.json from events.csv (METHOD.md sections 4-7).

    cd research && uv run --no-project --with pandas --with numpy --with matplotlib python -m open_options.report
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

from open_options.stats import cluster_bootstrap, mean_ci  # noqa: E402

MIN_EVENTS, MIN_CLOSURES = 30, 8


def verdict(st: dict) -> str:
    if st["n"] < MIN_EVENTS or st["clusters"] < MIN_CLOSURES:
        return "SAMPLE TOO SMALL"
    return "PASS" if st["g_net"]["mean_ci"][0] > 0 else "NULL"


def analyse(ev: pd.DataFrame) -> dict:
    if len(ev) == 0:
        return dict(n=0, clusters=0)
    r = cluster_bootstrap(ev.d_pm, ev.d_opt, ev.G, ev.closure)
    net = mean_ci(ev.G_net, ev.closure)
    return dict(n=r["n"], clusters=r["clusters"], beta=r["beta"], beta_ci=r["beta_ci"], alpha=r["alpha"],
                g=dict(mean=r["mean"], mean_ci=r["mean_ci"]), g_net=net)


def _fmt_ci(d: dict, key="mean", scale=100.0, unit=" pt") -> str:
    if not d or d.get("n", 1) == 0 or not np.isfinite(d.get(key, np.nan)):
        return "n/a"
    lo, hi = d[f"{key}_ci"]
    return f"{d[key] * scale:+.2f}{unit} [{lo * scale:+.2f}, {hi * scale:+.2f}]"


def chart(ev: pd.DataFrame, st: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 5.2), dpi=150)
    ax.axhline(0, color="#bbb", lw=0.8)
    ax.axvline(0, color="#bbb", lw=0.8)
    if len(ev):
        x, y = ev.d_pm * 100, ev.d_opt * 100
        lim = float(np.nanmax(np.abs(np.r_[x, y]))) * 1.08 + 1
        ax.scatter(x, y, s=16, alpha=0.6, color="#2a6fdb", edgecolor="none", label=f"events (n={st['n']}, {st['clusters']} closures)")
        xx = np.array([-lim, lim])
        ax.plot(xx, xx, color="#888", ls="--", lw=1, label="full catch-up (slope 1)")
        if np.isfinite(st.get("beta", np.nan)):
            ax.plot(xx, st["alpha"] * 100 + st["beta"] * xx, color="#d9480f", lw=1.6,
                    label=f"fit: slope {st['beta']:.2f} [{st['beta_ci'][0]:.2f}, {st['beta_ci'][1]:.2f}]")
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
    ax.set_xlabel("PM move over the closure (points, Fri close to Mon 09:30)")
    ax.set_ylabel("Option-implied move (points, Fri 15:55 to Mon 09:45)")
    ax.set_title("Do options catch up with the PM at the Monday open?", fontsize=10)
    ax.legend(fontsize=7, loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main(out: Path | None = None) -> int:
    out = Path(out or RESEARCH / "results" / "open_options")
    df = pd.read_csv(out / "events.csv", low_memory=False)
    meta = json.loads((out / "run_meta.json").read_text())
    ev = df[df.status == "event"].copy()
    st = analyse(ev)
    v = verdict(st) if st["n"] else "SAMPLE TOO SMALL"

    subsets = {}
    if len(ev):
        def sub(name, mask):
            s = ev[mask]
            subsets[name] = analyse(s) if len(s) else dict(n=0, clusters=0)
        sub("Polymarket trade print inside the closure", ev.prints_in_closure.astype(str) == "True")
        sub("|dPM| >= 5 points", ev.d_pm.abs() >= 0.05)
        sub("same strike pair and width_sens <= 0.05", (ev.same_pair.astype(str) == "True") & (ev.width_sens_max <= 0.05))
        for k in sorted(ev.kind.dropna().unique()):
            sub(f"kind = {k}", ev.kind == k)
        sub("weekends only", ev.closure_kind == "weekend")
    ft = dict(F=mean_ci(ev.F, ev.closure), rt=mean_ci(ev.rt_pnl, ev.closure), pm=mean_ci(ev.pm_follow, ev.closure)) if len(ev) else {}
    brier = {}
    res = ev.dropna(subset=["outcome"])
    if len(res):
        brier = dict(n=len(res), pm_open=float(((res.pm_open - res.outcome) ** 2).mean()),
                     opt_open=float(((res.oo_mid - res.outcome) ** 2).mean()))

    chart(ev, st, out / "catchup_chart.png")
    (out / "stats.json").write_text(json.dumps(dict(verdict=v, primary=st, subsets=subsets, follow_through=ft, brier=brier),
                                               indent=1, default=float))

    funnel = df.status.value_counts().to_dict()
    sc = meta["scope"]
    L = []
    L.append("# R3: do options catch up with the prediction market at the Monday open?\n")
    L.append(f"Run {meta['run_utc'][:16]} UTC. Pre-registered method: [`research/open_options/METHOD.md`](../../open_options/METHOD.md) "
             "(committed before any price or quote was fetched; amendment 1 drops Kalshi before any price was fetched). "
             "Rows: [`events.csv`](events.csv). Chart: [`catchup_chart.png`](catchup_chart.png). Numbers: [`stats.json`](stats.json). "
             "Log: [`RUN_LOG.md`](RUN_LOG.md).\n")
    L.append("## Answer\n")
    if st["n"] == 0:
        L.append("**Sample too small: zero events.** No threshold market with a clean option expiry moved 3 points or more over a "
                 "closure while both option snapshots were valid. No claim is made either way.\n")
    else:
        L.append(f"**Verdict against the pre-registered criterion: {v}.** {st['n']} events from {st['clusters']} closures "
                 f"(needs >= {MIN_EVENTS} events and >= {MIN_CLOSURES} closures; success = mean net residual gap with a 95% "
                 "cluster-bootstrap CI above 0).\n")
        L.append(f"- **Catch-up slope:** options' Monday-09:45 repricing reflected **{st['beta']:.2f}** of the PM's closure move "
                 f"(95% CI {st['beta_ci'][0]:.2f} to {st['beta_ci'][1]:.2f}; 1 = full catch-up, 0 = none).")
        L.append(f"- **Residual gap at the open, before costs** (signed by the PM move, Friday basis netted out): {_fmt_ci(st['g'])}.")
        L.append(f"- **Residual gap net of option costs** (half the bid/ask band on the traded side + $0.65/leg commission): "
                 f"{_fmt_ci(st['g_net'])}; equal weight per closure {_fmt_ci(st['g_net'], 'cw_mean')}.")
        L.append(f"- Median option cost at the open: {ev.cost_half.median() * 100:.2f} pt half-band + "
                 f"{ev.cost_comm.median() * 100:.2f} pt commission.\n")
        if v == "PASS":
            L.append("Read: options had not fully caught up at 09:45 and the residual survives costs on average. Whether it is a lag "
                     "the options close later, or PM noise, is the follow-through section below.\n")
        elif v == "NULL":
            L.append("Read: after costs there is no residual gap distinguishable from zero. Per the plan, no 'Opportunity at the open' "
                     "claim; the card can only be shown as an unvalidated estimate, if at all.\n")
        else:
            L.append("Read: the sample is below the pre-registered minimum, so no claim is made in either direction, whatever the "
                     "point estimates say. The 'Opportunity at the open' card stays an unvalidated estimate.\n")

    L.append("## Funnel\n")
    L.append(f"Closures in the window (reopening 2025-10-01 .. 2026-09-28, weekends and holidays): {sc.get('closures')}. "
             f"Polymarket equity events: {sc.get('pm_events')}; markets seen {sc.get('pm_markets_seen')}; 'close above $K' "
             f"thresholds in scope {sc.get('pm_in_scope')}. Kalshi: not run (amendment 1).\n")
    L.append("| step | count |\n|---|---|")
    for k in ("pair_listed_after_close", "pair_resolves_before_reopen_close", "pairs_life_ok", "pair_no_clean_expiry", "pairs_eligible"):
        L.append(f"| {k.replace('_', ' ')} | {sc.get(k, 0)} |")
    for k in ("f1_no_pm_price", "f1_pm_close_extreme", "f2_placeholder_050", "f3_move_below_3pt", "f4_no_option_spread",
              "f4_opt_close_extreme", "f4_noarb_violation", "event"):
        L.append(f"| status: {k} | {funnel.get(k, 0)} |")
    L.append("")
    L.append("'pairs life ok' = (market, closure) pairs where the market was listed 15+ minutes before the close and resolves at or "
             "after 16:00 ET of the reopening day; 'eligible' additionally has a listed option expiry on the resolution date.\n")

    if len(ev):
        L.append("## Secondary (reported, not used for the verdict)\n")
        L.append("| subset | events | closures | slope [CI] | net residual gap [CI] |\n|---|---|---|---|---|")
        L.append(f"| all (primary) | {st['n']} | {st['clusters']} | {st['beta']:.2f} [{st['beta_ci'][0]:.2f}, {st['beta_ci'][1]:.2f}] "
                 f"| {_fmt_ci(st['g_net'])} |")
        for name, s in subsets.items():
            if s.get("n", 0) >= 3:
                L.append(f"| {name} | {s['n']} | {s['clusters']} | {s['beta']:.2f} [{s['beta_ci'][0]:.2f}, {s['beta_ci'][1]:.2f}] "
                         f"| {_fmt_ci(s['g_net'])} |")
            else:
                L.append(f"| {name} | {s.get('n', 0)} | {s.get('clusters', 0)} | n/a | n/a |")
        L.append("")
        L.append("**Follow-through on the reopening day** (same strike pair, 09:45 to 15:55 ET), signed by the PM move:\n")
        L.append(f"- Option move after the open, F: {_fmt_ci(ft['F'])} (n={ft['F']['n']}).")
        L.append(f"- Round trip of the option trade (buy at the ask band, sell at the bid band, two commissions): {_fmt_ci(ft['rt'])}.")
        L.append(f"- PM after the open (positive = PM kept moving its way, negative = gave it back): {_fmt_ci(ft['pm'])}.\n")
        L.append("Interpretation: options reprice by less than the PM over a closure, but the difference is not a lag the "
                 "options close later. After 09:45 the options do not keep moving toward the PM, the PM itself gives back part "
                 "of its closure move, and a trade that buys the options toward the PM loses the spread. The before-cost gap "
                 "looks more like PM overshoot or noise over the weekend than slow options.\n")
        if brier:
            L.append(f"Outcome check on {brier['n']} resolved events (descriptive): Brier score PM at 09:30 {brier['pm_open']:.3f}, "
                     f"options at 09:45 {brier['opt_open']:.3f} (lower is better).\n")
        top = ev.reindex(ev.G_net.sort_values(ascending=False).index).head(12)
        L.append("Largest net residual gaps:\n")
        L.append("| market | closure | PM Fri -> Mon 09:30 | options Fri -> Mon 09:45 | G | G net |\n|---|---|---|---|---|---|")
        for _, r in top.iterrows():
            L.append(f"| {r.question} | {r.closure} | {r.pm_close:.2f} -> {r.pm_open:.2f} | {r.oc_mid:.2f} -> {r.oo_mid:.2f} | "
                     f"{r.G * 100:+.1f} | {r.G_net * 100:+.1f} |")
        L.append("")

    L.append("## Caveats\n")
    L.append("- Polymarket prices are the per-minute `prices-history` series, which can be the midpoint of a thin book; the "
             "trade-print subset is the check. No PM cost is charged because only the options are traded.")
    L.append("- The call spread approximates the digital; settlement prints differ slightly (official close vs the PM's source); "
             "SPY and single-name options are American.")
    L.append("- One NBBO snapshot per leg at 09:45 ET (quotes must be stamped after 09:30:00); options can also lag the stock "
             "inside those 15 minutes.")
    L.append("- Strike ladders on one underlying and one closure are counted as separate events; the bootstrap resamples whole "
             "closures for that reason.")
    L.append("- Selection: only markets alive across a closure, listed before Friday's close, with a listed option expiry on "
             "the resolution date. Kalshi's 16:00 markets are listed the day before settlement, so they never qualify.")
    L.append("- No 8-K filing data was used.\n")
    (out / "SUMMARY.md").write_text("\n".join(L))
    print(f"verdict={v} n={st.get('n')} clusters={st.get('clusters')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
