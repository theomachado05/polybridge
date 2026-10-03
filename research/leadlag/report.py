"""Pooled tests, CSV writers and SUMMARY.md (METHOD.md sections 6-7)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import PARAMS, RESULTS_DIR, SENSITIVITY_K
from .events import Event
from .pipeline import EventResult
from .stats import binom_two_sided, distributed_lag, granger


def _hm(t) -> str:
    return "none" if t is None or pd.isna(t) else pd.Timestamp(t).strftime("%H:%M")


def _iso(t) -> str:
    return "" if t is None or pd.isna(t) else pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rel(t, anchor) -> str:
    """Minutes from the scheduled/news anchor to a move time ('n/a' if either is missing)."""
    if t is None or pd.isna(t) or anchor is None or pd.isna(anchor):
        return "n/a"
    return f"{(pd.Timestamp(t) - pd.Timestamp(anchor)).total_seconds() / 60:+.0f}"


def _rel_val(t, anchor):
    if t is None or pd.isna(t) or anchor is None or pd.isna(anchor):
        return None
    return (pd.Timestamp(t) - pd.Timestamp(anchor)).total_seconds() / 60


def _session(t) -> str:
    """'RTH' if the time falls in the regular 09:30-16:00 ET session, else 'ext' (pre/after-hours); '' if no time."""
    if t is None or pd.isna(t):
        return ""
    et = pd.Timestamp(t).tz_convert("America/New_York")
    mins = et.hour * 60 + et.minute
    return "RTH" if 9 * 60 + 30 <= mins < 16 * 60 else "ext"


# ------------------------------------------------------------------ pooled tests


def pooled_tests(usable: list[EventResult], p=PARAMS) -> dict:
    subsets = {
        "all usable": usable,
        "FOMC (scheduled)": [r for r in usable if r.event.family == "fomc"],
        "curated": [r for r in usable if r.event.selection == "curated"],
    }
    out: dict = {"subsets": {}}
    for name, rs in subsets.items():
        frames = {r.event.id: r.primary.frame for r in rs}
        if len(frames) < 3:
            out["subsets"][name] = None
            continue
        A, a = distributed_lag(frames, "x", "ys", p.reg_lags, p.hac_lags)
        B, b = distributed_lag(frames, "ys", "x", p.reg_lags, p.hac_lags)
        g = {}
        for pp in (p.granger_p, p.granger_p_robust):
            g[("pm_to_eq", pp)] = granger(frames, "x", "ys", pp, p.hac_lags)
            g[("eq_to_pm", pp)] = granger(frames, "ys", "x", pp, p.hac_lags)
        out["subsets"][name] = dict(A=(A, a), B=(B, b), granger=g, n_events=len(frames))
    # leave-one-event-out on the cumulative PM->equity response
    frames_all = {r.event.id: r.primary.frame for r in usable}
    loo = []
    if len(frames_all) >= 5:
        for eid in frames_all:
            sub = {k: v for k, v in frames_all.items() if k != eid}
            _, st = distributed_lag(sub, "x", "ys", p.reg_lags, p.hac_lags)
            loo.append((eid, st["cum"], st["cum_t"]))
    out["loo"] = loo
    # Exploratory robustness (Amendment 2): sign-free per-event Granger tests, p = granger_p, both directions
    per = []
    for r in usable:
        fr = {r.event.id: r.primary.frame}
        try:
            fwd, rev = granger(fr, "x", "ys", p.granger_p, p.hac_lags), granger(fr, "ys", "x", p.granger_p, p.hac_lags)
        except Exception:  # noqa: BLE001  (too few rows)
            continue
        per.append(dict(event_id=r.event.id, pm_to_eq_F=fwd["F"], pm_to_eq_p=fwd["F_p"], pm_to_eq_hac_p=fwd["hac_wald_p"],
                        eq_to_pm_F=rev["F"], eq_to_pm_p=rev["F_p"], eq_to_pm_hac_p=rev["hac_wald_p"], n=fwd["n"]))
    out["per_event_granger"] = pd.DataFrame(per)
    return out


def verdict(tests: dict, p=PARAMS) -> tuple[str, str]:
    """Apply the decision rule written in METHOD.md section 6."""
    s = tests["subsets"].get("all usable")
    if not s:
        return "no verdict", "Too few usable events for a pooled test."
    ga, gb = s["granger"][("pm_to_eq", p.granger_p)], s["granger"][("eq_to_pm", p.granger_p)]
    sa, sb = ga["F_p"] < 0.05, gb["F_p"] < 0.05
    desc = (f"Granger F (p={p.granger_p}, event fixed effects): PM to equity F={ga['F']:.2f} (p={ga['F_p']:.3g}); "
            f"equity to PM F={gb['F']:.2f} (p={gb['F_p']:.3g}).")
    if sa and (not sb or gb["F"] < ga["F"]):
        v, t = "supports PM leading", desc + " PM to equity is significant and the reverse is absent or weaker."
    elif sa and sb:
        v, t = "mixed", desc + " Both directions are significant and the reverse is at least as strong."
    elif sb and not sa:
        v, t = "points the other way", desc + " Only equity to PM is significant."
    else:
        v, t = "no evidence", desc + " Neither direction is significant at 5%."
    return v, t


def hac_evidence(tests: dict, p=PARAMS) -> dict:
    """Every HAC-based statistic declared in METHOD.md section 6, with flags for which are significant.

    Items: Granger HAC Wald (both directions, both p) on all usable events; Regression A/B joint Wald and cumulative
    response t in every subset. Each item records direction, whether it is significant at 5% (Wald p < 0.05 or
    |cumulative t| > 1.96), and the sign of the relevant cumulative response where one exists.
    """
    items = []
    s_all = tests["subsets"].get("all usable")
    if s_all:
        for pp in (p.granger_p, p.granger_p_robust):
            for d, lab in (("pm_to_eq", "PM to equity"), ("eq_to_pm", "equity to PM")):
                g = s_all["granger"][(d, pp)]
                items.append(dict(dir=d, kind="granger", label=f"all usable, Granger HAC Wald p={pp}, {lab}", p=g["hac_wald_p"],
                                  sig=g["hac_wald_p"] < 0.05, cum=None))
    for name, s in tests["subsets"].items():
        if not s:
            continue
        for d, key, lab in (("pm_to_eq", "A", "Reg A (PM to equity)"), ("eq_to_pm", "B", "Reg B (equity to PM)")):
            st = s[key][1]
            items.append(dict(dir=d, kind="wald", label=f"{name}, {lab} joint Wald", p=st["wald_p"], t=st["cum_t"], sig=st["wald_p"] < 0.05, cum=st["cum"]))
            items.append(dict(dir=d, kind="cum", label=f"{name}, {lab} cumulative response", p=None, t=st["cum_t"], sig=abs(st["cum_t"]) > 1.96, cum=st["cum"]))
    return dict(items=items)


def robust_reading(tests: dict, p=PARAMS) -> tuple[str, str]:
    """HAC reading over all pre-declared HAC statistics: (robustness line, plain-reading line)."""
    ev = hac_evidence(tests, p)
    items = ev["items"]
    s = tests["subsets"].get("all usable")
    if not s or not items:
        return "", ""
    parts = []
    for pp in (p.granger_p, p.granger_p_robust):
        a, b = s["granger"][("pm_to_eq", pp)], s["granger"][("eq_to_pm", pp)]
        parts.append(f"p={pp}: PM to equity p={a['hac_wald_p']:.3f}, equity to PM p={b['hac_wald_p']:.3f}")
    g_sig = [i for i in items if i["kind"] == "granger" and i["sig"]]
    a_all, b_all = s["A"][1], s["B"][1]
    rob = ("HAC-robust statistics (Newey-West, 30 lags), all pre-declared in METHOD.md section 6. "
           f"Granger HAC Wald, all usable events ({'; '.join(parts)}): {len(g_sig)} of 4 significant at 5%. "
           f"All usable events, Regression A (PM to equity): cumulative response {a_all['cum']:+.3f} (t={a_all['cum_t']:+.2f}), joint Wald p={_fmt_p(a_all['wald_p'])}; "
           f"Regression B (equity to PM): cumulative response {b_all['cum']:+.3f} (t={b_all['cum_t']:+.2f}), joint Wald p={_fmt_p(b_all['wald_p'])}.")
    sub_bits = []
    for name, st in tests["subsets"].items():
        if name == "all usable" or not st:
            continue
        a, b = st["A"][1], st["B"][1]
        sub_bits.append(f"{name}: Reg A Wald p={_fmt_p(a['wald_p'])} (cumulative {a['cum']:+.3f}, t={a['cum_t']:+.2f}), "
                        f"Reg B Wald p={_fmt_p(b['wald_p'])} (cumulative {b['cum']:+.3f}, t={b['cum_t']:+.2f})")
    if sub_bits:
        rob += " Subsets, " + "; ".join(sub_bits) + "."
    # plain reading, built from the flags
    pm_sig = [i for i in items if i["dir"] == "pm_to_eq" and i["sig"]]
    pm_sig_pos = [i for i in pm_sig if i["cum"] is None or i["cum"] > 0]
    eq_sig = [i for i in items if i["dir"] == "eq_to_pm" and i["sig"]]
    if pm_sig_pos:
        plain = ("Plain reading: at least one HAC statistic in the PM-to-equity direction is significant with a positive (expected-direction) "
                 "cumulative response (" + "; ".join(i["label"] for i in pm_sig_pos) + "), so the evidence is mixed rather than absent; read the table.")
    else:
        pm_w = [i for i in pm_sig if i["kind"] == "wald"]
        plain = "Plain reading: **no HAC statistic supports prediction markets leading equities**. "
        if pm_w:
            plain += ("The PM-to-equity joint Wald tests that are significant (" + "; ".join(
                f"{i['label']}, p={_fmt_p(i['p'])}, cumulative response {i['cum']:+.3f} with t={i['t']:+.2f}" for i in pm_w) +
                ") do not show a positive, expected-direction response; the lag pattern is not the one a PM lead would produce. ")
        if eq_sig:
            plain += ("In the other direction some HAC statistics are significant: " + "; ".join(
                f"{i['label']} ({'p=' + _fmt_p(i['p']) if i['p'] is not None else 't=' + format(i['t'], '+.2f')})" for i in eq_sig) +
                ". So the data are more consistent with equities leading the PM than the reverse, but the HAC Granger tests are not significant at 5%, "
                "so this is weak and not uniform across tests. ")
        else:
            plain += "No equity-to-PM HAC statistic is significant either. "
        plain += ("The 30-lag HAC Wald tests can be oversized (as found per event, see below), so even these significant joint tests deserve caution. "
                  "The classical F is also unreliable here because PM changes are jumpy.")
    return rob, plain


# ------------------------------------------------------------------ CSVs


def _events_metrics(results: list[EventResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        ev = r.event
        for tkr, ir in r.instruments.items():
            row = dict(
                event_id=ev.id, event=ev.name, date=ev.date, family=ev.family, selection=ev.selection, usable=r.usable,
                primary=ir.primary, ticker=tkr, expected_sign=ev.expected_sign, market=ev.market_slug,
                window_start_utc=_iso(ev.start), window_end_utc=_iso(ev.end), anchor_utc=_iso(ev.anchor),
                pm_points_in_window=r.pm_points, pm_changed_minutes=r.pm_changes,
                pm_move_utc=_iso(r.pm_move.time) if r.pm_move else "", pm_move_delta_pp=r.pm_move.delta if r.pm_move else np.nan,
                pm_move_z=r.pm_move.z if r.pm_move else np.nan,
                eq_move_utc=_iso(ir.eq_move.time) if ir.eq_move else "", eq_move_delta_bp=ir.eq_move.delta if ir.eq_move else np.nan,
                eq_move_z=ir.eq_move.z if ir.eq_move else np.nan,
                lead_minutes=ir.lead if ir.lead is not None else np.nan, lead_class=ir.lead_cls,
                moves_concordant=(np.sign(r.pm_move.delta * ev.expected_sign) == np.sign(ir.eq_move.delta)) if (r.pm_move and ir.eq_move) else np.nan,
                xcorr_peak_lag=ir.xc.peak_lag if ir.xc.peak_lag is not None else np.nan,
                xcorr_peak_rho=ir.xc.peak_rho if ir.xc.peak_rho is not None else np.nan, xcorr_n=ir.xc.n,
                xcorr_significant=ir.xc.significant, pm_lead_mass=ir.xc.pm_lead_mass, eq_lead_mass=ir.xc.eq_lead_mass,
                eq_valid_frac=ir.eq_valid_frac, eq_bar_coverage=ir.eq_cov,
                drop_reason="; ".join(r.drop_reasons),
            )
            for k in SENSITIVITY_K:
                t, lead = ir.sens[k]
                row[f"k{k:g}_eq_move_utc"] = _iso(t)
                row[f"k{k:g}_lead_minutes"] = lead if lead is not None else np.nan
            row.update({f"k{k:g}_pm_move_utc": _iso(r.sens_pm[k].time) if r.sens_pm[k] else "" for k in SENSITIVITY_K})
            rows.append(row)
    return pd.DataFrame(rows)


def write_csvs(results: list[EventResult], failed: list[tuple[Event, str]], tests: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "data").mkdir(exist_ok=True)
    m = _events_metrics(results)
    m.to_csv(RESULTS_DIR / "events_metrics.csv", index=False)
    # cross-correlation curves (primary instrument, usable events)
    xr = []
    for r in results:
        if r.usable:
            t = r.primary.xc.table.copy()
            t.insert(0, "event_id", r.event.id)
            t.insert(1, "ticker", r.primary.ticker)
            xr.append(t)
    if xr:
        pd.concat(xr).to_csv(RESULTS_DIR / "xcorr_by_event.csv", index=False)
    # aligned minute data (primary instrument; whole fetch range incl. warm-up)
    for r in results:
        if r.usable:
            r.primary.frame.rename_axis("minute_end_utc").to_csv(RESULTS_DIR / "data" / f"{r.event.id}__{r.primary.ticker}.csv")
    # dropped
    dropped = [dict(event_id=r.event.id, event=r.event.name, date=r.event.date, market=r.event.market_slug,
                    reason="; ".join(r.drop_reasons)) for r in results if not r.usable]
    dropped += [dict(event_id=e.id, event=e.name, date=e.date, market=e.market_slug, reason=why) for e, why in failed]
    pd.DataFrame(dropped, columns=["event_id", "event", "date", "market", "reason"]).to_csv(RESULTS_DIR / "dropped.csv", index=False)
    # regressions and tests
    lag_rows, test_rows = [], []
    for name, s in tests["subsets"].items():
        if not s:
            continue
        for label, (fit, st) in (("A_pm_leads_equity", s["A"]), ("B_equity_leads_pm", s["B"])):
            for i, (b, se) in enumerate(zip(fit.beta, fit.se), start=1):
                lag_rows.append(dict(subset=name, regression=label, lag=i, beta=b, hac_se=se, t=b / se if se > 0 else np.nan))
            test_rows.append(dict(subset=name, test=f"{label}: joint Wald all {len(fit.beta)} lags", stat=st["wald"], p=st["wald_p"],
                                  cumulative=st["cum"], cumulative_se=st["cum_se"], cumulative_t=st["cum_t"], n=st["n"], events=st["events"]))
        for (direction, pp), g in s["granger"].items():
            test_rows.append(dict(subset=name, test=f"Granger {direction} p={pp}: F", stat=g["F"], p=g["F_p"], cumulative=g["other_sum"],
                                  cumulative_se=np.nan, cumulative_t=np.nan, n=g["n"], events=g["events"]))
            test_rows.append(dict(subset=name, test=f"Granger {direction} p={pp}: HAC Wald", stat=g["hac_wald"], p=g["hac_wald_p"],
                                  cumulative=g["other_sum"], cumulative_se=np.nan, cumulative_t=np.nan, n=g["n"], events=g["events"]))
    pd.DataFrame(lag_rows).to_csv(RESULTS_DIR / "regression_lags.csv", index=False)
    pd.DataFrame(test_rows).to_csv(RESULTS_DIR / "pooled_tests.csv", index=False)
    if len(tests.get("per_event_granger", [])):
        tests["per_event_granger"].to_csv(RESULTS_DIR / "granger_per_event.csv", index=False)
    if tests["loo"]:
        pd.DataFrame(tests["loo"], columns=["left_out_event", "cumulative_beta", "cumulative_t"]).to_csv(
            RESULTS_DIR / "leave_one_out.csv", index=False)


# ------------------------------------------------------------------ SUMMARY.md


def _fmt_p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def write_summary(results: list[EventResult], failed: list[tuple[Event, str]], tests: dict) -> None:
    usable = [r for r in results if r.usable]
    dropped = [(r.event, "; ".join(r.drop_reasons)) for r in results if not r.usable] + [(e, w) for e, w in failed]
    both = [r for r in usable if r.primary.lead is not None]
    pm_first = [r for r in both if r.primary.lead_cls == "PM first"]
    eq_first = [r for r in both if r.primary.lead_cls == "equity first"]
    simul = [r for r in both if r.primary.lead_cls == "simultaneous"]
    no_det = [r for r in usable if r.primary.lead is None]
    verd, vtext = verdict(tests)
    n_dec = len(pm_first) + len(eq_first)
    sign_p = binom_two_sided(len(pm_first), n_dec) if n_dec else float("nan")
    leads = np.array([r.primary.lead for r in both], dtype=float)
    L = []
    L.append("# Lead-lag evidence: do prediction markets move before equities in stress?\n")
    L.append("Case studies plus a pooled time-series test. **Supporting evidence, not proof.** Parameters were fixed in "
             "[METHOD.md](../../leadlag/METHOD.md) and committed before any data was fetched.\n")
    L.append("## Headline\n")
    L.append(f"- Events: {len(results) + len(failed)} candidates, **{len(usable)} usable**, {len(dropped)} dropped (reasons below).")
    if both:
        L.append(f"- Where both series had a significant move ({len(both)} events): **PM first {len(pm_first)}, simultaneous (within 1 min) {len(simul)}, "
                 f"equity first {len(eq_first)}**. Median lead {np.median(leads):+.1f} min, mean {leads.mean():+.1f} min (positive = PM first).")
    if both:
        conc = lambda rs: sum(1 for r in rs if np.sign(r.pm_move.delta * r.event.expected_sign) == np.sign(r.primary.eq_move.delta))
        L.append(f"- Descriptive only: the first PM move and the first equity move went in the same (pre-set, oriented) direction in "
                 f"{conc(both)} of {len(both)} events ({conc(pm_first)} of {len(pm_first)} PM-first events). A PM-first event whose first PM move "
                 f"points the other way may be a stray tick rather than a lead (or the pre-set sign may be wrong, or the market may be reacting to something else).")
    if n_dec:
        L.append(f"- Exact two-sided sign test, PM first vs equity first ({len(pm_first)} of {n_dec}): p = {_fmt_p(sign_p)}.")
    L.append(f"- No significant move detected in one of the two series: {len(no_det)} usable events (lead not defined, still in the pooled test).")
    L.append(f"- Pooled test verdict (rule fixed in advance, classical F): **{verd}**. {vtext}")
    rob, plain = robust_reading(tests)
    if rob:
        L.append(f"- Robustness: {rob}")
        L.append(f"- {plain}")
    pe = tests.get("per_event_granger")
    if pe is not None and len(pe):
        m = len(pe)
        chi_f = -2 * np.log(pe["pm_to_eq_p"].clip(lower=1e-300)).sum()
        chi_r = -2 * np.log(pe["eq_to_pm_p"].clip(lower=1e-300)).sum()
        from .stats import chi2_sf
        L.append(f"- Exploratory, sign-free, added after the first run (METHOD.md Amendment 2): per-event Granger tests (p={PARAMS.granger_p}, classical F, 5% level) are significant "
                 f"PM to equity in {int((pe['pm_to_eq_p'] < 0.05).sum())} of {m} events and equity to PM in {int((pe['eq_to_pm_p'] < 0.05).sum())} of {m} (about {0.05 * m:.1f} expected by chance if the classical F were correctly sized, which it likely is not here); "
                 f"(the per-event HAC Wald columns in `granger_per_event.csv` are not used: with about 200 rows, 20 regressors and 30 HAC lags they are badly oversized, "
                 f"{int((pe['pm_to_eq_hac_p'] < 0.05).sum())} of {m} events 'significant' PM to equity, which is not credible). "
                 f"Fisher-combined p (classical F) = {_fmt_p(chi2_sf(chi_f, 2 * m))} (PM to equity) and {_fmt_p(chi2_sf(chi_r, 2 * m))} (equity to PM); "
                 f"Fisher's method is driven by the few smallest p-values, so read it with the counts.")
    L.append("")
    L.append("## Event table (primary instrument per event)\n")
    L.append("Lead = equity first-move time minus PM first-move time, in minutes; positive means the prediction market moved first. "
             "xcorr lag = peak of the 1-minute-change cross-correlation (positive = PM leads), with rho in brackets; `*` marks |rho| > 2/sqrt(n). "
             "Descriptive columns (not part of the pre-set rule): `PM vs anchor` and `Eq vs anchor` are each first move minus the event anchor time in `events.yaml` "
             "(statement time or news time), in minutes, so a negative value means the first move came before the event; `Eq session` is RTH (regular hours, "
             "09:30-16:00 ET) or ext (pre/after-hours) at the equity move time.\n")
    L.append("| Event | Date | Instr. | PM move (UTC) | Equity move (UTC) | Lead (min) | Class | PM vs anchor (min) | Eq vs anchor (min) | Eq session | xcorr lag [rho] | Chart |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in usable:
        ir, ev = r.primary, r.event
        lead = "n/a" if ir.lead is None else f"{ir.lead:+.0f}"
        xl = "n/a" if ir.xc.peak_lag is None else f"{ir.xc.peak_lag:+d} [{ir.xc.peak_rho:+.2f}{'*' if ir.xc.significant else ''}]"
        L.append(f"| {ev.name} | {ev.date} | {ir.ticker} | {_hm(r.pm_move.time if r.pm_move else None)} | {_hm(ir.eq_move.time if ir.eq_move else None)} "
                 f"| {lead} | {ir.lead_cls} | {_rel(r.pm_move.time if r.pm_move else None, ev.anchor)} "
                 f"| {_rel(ir.eq_move.time if ir.eq_move else None, ev.anchor)} | {_session(ir.eq_move.time if ir.eq_move else None) or 'n/a'} "
                 f"| {xl} | [png](charts/{ev.id}.png) |")
    L.append("")
    # moves that predate the event anchor, and equity moves in extended hours
    def _pre(rs, which):
        n = 0
        for r in rs:
            mv = r.pm_move if which == "pm" else r.primary.eq_move
            v = _rel_val(mv.time if mv else None, r.event.anchor)
            n += v is not None and v < 0
        return n
    eq_ext = sum(1 for r in eq_first if _session(r.primary.eq_move.time) == "ext")
    L.append(f"Anchor check (descriptive): of the {len(pm_first)} PM-first events, {_pre(pm_first, 'pm')} have the first PM move before the event anchor "
             f"(so it cannot be a reaction to the event); of the {len(eq_first)} equity-first events, {_pre(eq_first, 'eq')} have the first equity move "
             f"before the anchor and {eq_ext} {'falls' if eq_ext == 1 else 'fall'} in extended hours. A move before the anchor is not information about the event, so the lead count "
             f"for those events says little about who reacts first to news. Equity moves in extended hours, or right at the 16:00 ET close or the "
             f"04:00/20:00 ET session seams, can reflect thin trading or the session boundary rather than the event.\n")
    L.append("## Events where equities moved first (kept, as required)\n")
    if eq_first:
        for r in sorted(eq_first, key=lambda r: r.primary.lead):
            ir = r.primary
            L.append(f"- **{r.event.name}** ({r.event.date}, {ir.ticker}): equity moved at {_hm(ir.eq_move.time)}Z, PM at {_hm(r.pm_move.time)}Z, lead {ir.lead:+.0f} min.")
    else:
        L.append("- None.")
    L.append("")
    L.append("## Simultaneous (within 1 minute)\n")
    L.append("\n".join(f"- {r.event.name} ({r.event.date}): lead {r.primary.lead:+.0f} min" for r in simul) or "- None.")
    L.append("")
    L.append("## No significant move in one series\n")
    if no_det:
        for r in no_det:
            ir = r.primary
            miss = []
            if r.pm_move is None:
                miss.append("PM")
            if ir.eq_move is None:
                miss.append(ir.ticker)
            L.append(f"- {r.event.name} ({r.event.date}): no significant move in {' and '.join(miss)}.")
    else:
        L.append("- None.")
    L.append("")
    L.append("## Pooled time-series tests\n")
    L.append("Primary instrument of each usable event, z-scaled per event, PM oriented by the pre-set expected sign, event fixed effects, "
             "per-event Newey-West (30 lags). Regression A: equity return on PM changes lagged 1..30. Regression B: the reverse. "
             "Granger F tests use own lags plus the other series' lags.\n")
    L.append("| Subset | Events | Rows | Reg A: cum. response (t) | Reg A Wald p | Reg B: cum. response (t) | Reg B Wald p | Granger PM to eq (p=10) F [p] | Granger eq to PM (p=10) F [p] | Granger PM to eq (p=30) F [p] | Granger eq to PM (p=30) F [p] |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, s in tests["subsets"].items():
        if not s:
            L.append(f"| {name} | <3 | | | | | | | | | |")
            continue
        a, b, g = s["A"][1], s["B"][1], s["granger"]
        def gc(d, pp):
            x = g[(d, pp)]
            return f"{x['F']:.2f} [{_fmt_p(x['F_p'])}]"
        L.append(f"| {name} | {s['n_events']} | {a['n']} | {a['cum']:+.3f} ({a['cum_t']:+.2f}) | {_fmt_p(a['wald_p'])} | {b['cum']:+.3f} ({b['cum_t']:+.2f}) | {_fmt_p(b['wald_p'])} "
                 f"| {gc('pm_to_eq', PARAMS.granger_p)} | {gc('eq_to_pm', PARAMS.granger_p)} | {gc('pm_to_eq', PARAMS.granger_p_robust)} | {gc('eq_to_pm', PARAMS.granger_p_robust)} |")
    L.append("")
    s = tests["subsets"].get("all usable")
    if s:
        fa, sta = s["A"]
        fb, stb = s["B"]
        ta, tb = fa.t, fb.t
        ia, ib = int(np.nanargmax(np.abs(ta))), int(np.nanargmax(np.abs(tb)))
        L.append(f"- Regression A (all usable): largest |t| at lag {ia + 1} min (beta {fa.beta[ia]:+.3f}, t {ta[ia]:+.2f}); "
                 f"lags with |t| > 2: {int((np.abs(ta) > 2).sum())} of {len(ta)}. All 30 coefficients: `regression_lags.csv`.")
        L.append(f"- Regression B (all usable): largest |t| at lag {ib + 1} min (beta {fb.beta[ib]:+.3f}, t {tb[ib]:+.2f}); "
                 f"lags with |t| > 2: {int((np.abs(tb) > 2).sum())} of {len(tb)}.")
        L.append("- A positive coefficient means: when the prediction market moved in the equity-bullish direction, the equity rose over the following minutes (units: equity z per PM z).")
    if tests["loo"]:
        cums = [c for _, c, _ in tests["loo"]]
        lo, hi = min(tests["loo"], key=lambda r: r[1]), max(tests["loo"], key=lambda r: r[1])
        L.append(f"- Leave-one-event-out, Regression A cumulative response: range {lo[1]:+.3f} (without {lo[0]}) to {hi[1]:+.3f} (without {hi[0]}); "
                 f"{sum(c > 0 for c in cums)} of {len(cums)} are positive.")
    L.append("")
    L.append("## Sensitivity of the first-move rule (primary instrument; headline uses k = 4)\n")
    L.append("| k | events with both moves | PM first | simultaneous | equity first | median lead (min) |")
    L.append("|---|---|---|---|---|---|")
    from .detect import lead_class
    for k in (SENSITIVITY_K[0], PARAMS.k, SENSITIVITY_K[1]):
        if k == PARAMS.k:
            leads_k = [r.primary.lead for r in usable if r.primary.lead is not None]
        else:
            leads_k = [r.primary.sens[k][1] for r in usable if r.primary.sens[k][1] is not None]
        cls = [lead_class(v) for v in leads_k]
        med = f"{np.median(leads_k):+.1f}" if leads_k else "n/a"
        L.append(f"| {k:g} | {len(leads_k)} | {cls.count('PM first')} | {cls.count('simultaneous')} | {cls.count('equity first')} | {med} |")
    L.append("")
    from dataclasses import replace
    p2 = replace(PARAMS, sim_tol=2)
    lead_all = [r.primary.lead for r in usable if r.primary.lead is not None]
    c1 = [lead_class(v) for v in lead_all]
    c2 = [lead_class(v, p2) for v in lead_all]
    L.append("## Sensitivity of the simultaneity band (k = 4; descriptive, not headline)\n")
    L.append("The CLOB points are snapshots stamped a few seconds after the minute, while an equity bar closed at :59 of the same minute, so the PM series is on "
             "average about 45-55 seconds staler than equity at each grid point (METHOD.md Amendment 3). Widening the simultaneous band from 1 to 2 minutes shows how much "
             "of the 'equity first' count could come from that phase offset.\n")
    L.append("| simultaneous band | events with both moves | PM first | simultaneous | equity first |")
    L.append("|---|---|---|---|---|")
    L.append(f"| within 1 min (headline) | {len(c1)} | {c1.count('PM first')} | {c1.count('simultaneous')} | {c1.count('equity first')} |")
    L.append(f"| within 2 min | {len(c2)} | {c2.count('PM first')} | {c2.count('simultaneous')} | {c2.count('equity first')} |")
    L.append("")
    L.append("## Dropped events\n")
    L.append("\n".join(f"- **{e.name}** ({e.date}, `{e.market_slug}`): {why}" for e, why in dropped) or "- None.")
    L.append("")
    L.append("## Not in the candidate list, and why\n")
    L.append("- 8-K disclosures and any 2026 option data: out of scope for this study (the 8-K study's sealed window); none fetched.")
    L.append("- Events where the important PM move happened while US equities were closed (election results after 01:00 UTC on 2024-11-06, the Sunday-night Senate vote that ended the Nov 2025 shutdown, Israel's strike on Iran on 2025-06-13, the weekend US strikes of Jun 2025): a window with no equity prices cannot say who moved first. The election event covers the after-hours session only.")
    L.append("- 2025-01-27 DeepSeek sell-off, 2025-10-10 China tariff threat, 2025-11-05 Supreme Court tariff argument, regional-bank stress of Oct 2025 and Mar 2023: no suitable high-volume Polymarket market with a clear sign was found by search.")
    L.append("- CPI and jobs-report days: the sign of the equity response to a data surprise is ambiguous in advance (bad news can be dovish), so no sign could be pre-registered.")
    L.append("")
    L.append("## Caveats\n")
    L.append("- Events are not independent: the 2025 recession market appears in four tariff windows, the Russia-Ukraine ceasefire market twice, and consecutive FOMC markets overlap. Fixed effects and per-event HAC handle serial correlation within an event, not dependence across events.")
    L.append("- PM history is one point per minute at most, stale in quiet minutes, and moves in 0.1 to 1 point ticks. Detection times are coarse, and PM-to-equity correlations are biased toward zero.")
    L.append("- Thin PM markets print isolated 1 to 2 point ticks that can pass the first-move rule without any news behind them, which can bias the first-move lead toward 'PM first'. The concordance line, the cross-correlation and the pooled regression are less exposed to this than the lead count; the sensitivity table shows the effect of a stricter k.")
    n_m2 = sum(1 for r in eq_first if r.primary.lead <= -2 and r.primary.lead > -3)
    L.append(f"- Sampling phase: cached CLOB points are snapshots stamped about 4-17 seconds past each minute; they are assigned to the next minute-end grid point, while the equity value at that grid point includes trades up to :59. So the PM series is about 45-55 seconds staler than equity on average. This is not look-ahead, but it biases first-move leads against the PM ({n_m2} of the {len(eq_first)} 'equity first' events are at -2 minutes). See the simultaneity-band table and METHOD.md Amendment 3.")
    L.append("- Several first moves are unrelated to the event: some PM moves precede the scheduled anchor (a market cannot be reacting to a statement that has not happened), and some equity moves sit in after-hours trading, for example the SPY move in the 2026-01-28 FOMC event that falls about two hours after the statement and after the 16:00 ET close. The `vs anchor` and `Eq session` columns and the anchor check line make this visible; the pre-set rule does not filter on it.")
    L.append("- Equity ETF prices in these windows are also driven by futures and options that this study does not observe. 'Equity moved first' means first relative to the PM series only.")
    L.append("- The curated events were chosen from memory of famous dates; the scheduled FOMC set is the unselected part of the sample and is reported separately.")
    L.append("- The first-move rule (k = 4, 3-minute change, 5-minute persistence) is a convention. See the sensitivity table for how much the counts move.")
    L.append("")
    L.append("## Files\n")
    L.append("`events_metrics.csv` (every event and mapped instrument), `xcorr_by_event.csv`, `regression_lags.csv`, `pooled_tests.csv`, "
             "`leave_one_out.csv`, `dropped.csv`, `data/` (aligned minute series), `charts/` (one PNG per usable event), `RUN_LOG.md`.")
    (RESULTS_DIR / "SUMMARY.md").write_text("\n".join(L) + "\n")
