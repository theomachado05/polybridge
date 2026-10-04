"""SUMMARY.md writers for arm K and arm M (METHOD.md section 7)."""
from __future__ import annotations

import math


def _f(v, nd=2, sign=True) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


def _p(v) -> str:
    if v is None or not math.isfinite(v):
        return "n/a"
    return "< 0.001" if v < 0.001 else f"{v:.3f}"


def test_line(label: str, r: dict) -> str:
    if not r or not math.isfinite(r.get("c", float("nan"))):
        return f"| {label} | {r.get('n', 0) if r else 0} | n/a | n/a | n/a | n/a | n/a | n/a |"
    return (f"| {label} | {r['n']} ({r['n_dates']} dates) | {_f(r['c'])} [{_f(r['c_lo'])}, {_f(r['c_hi'])}] | "
            f"{_f(r['c_t'])} | {_p(r['p_perm'])} | {_f(r['dr2'], 4)} [{_f(r['dr2_lo'], 4)}, {_f(r['dr2_hi'], 4)}] | "
            f"{_f(r['beta'], 3)} (R2 {_f(r['r2_reduced'], 3, False)}) | {_f(r['d'])} |")


HEADER = ("| test | n | c, bp per pp [95% cluster CI] | cluster t | Freedman-Lane p | dR2 [block bootstrap CI] | "
          "benchmark beta (reduced R2) | PM-only slope d |\n|---|---|---|---|---|---|---|---|")


def arm_k_summary(res: dict, commit: str) -> str:
    k = res["k_0800"]
    L = ["# T2 arm K: PM move to 08:00 ET versus the SPY pre-market move (keyless arm)", "",
         f"Secondary sensitivity S1 of [METHOD.md](../../../pm_vs_premarket/METHOD.md) with the SPY extended-hours benchmark, "
         f"computed only from committed columns of `research/results/leadlag_closed/closures_all.csv` (no network). "
         f"Code commit `{commit}`. This is not the primary test (09:25 ET, arm M).", "",
         "## Headline", "",
         f"- **Reading under the pass rule applied to this arm:** {res['k_0800_verdict']}.",
         f"- PM coefficient given the SPY move to 08:00: c = {_f(k.get('c'))} bp per pp "
         f"(95% cluster CI [{_f(k.get('c_lo'))}, {_f(k.get('c_hi'))}]; month-block bootstrap [{_f(k.get('c_boot_lo'))}, "
         f"{_f(k.get('c_boot_hi'))}]), cluster t {_f(k.get('c_t'))}, Freedman-Lane p {_p(k.get('p_perm', float('nan')))}, "
         f"n = {k.get('n')} closures.",
         f"- Incremental R-squared of the PM move: {_f(k.get('dr2'), 4)} (bootstrap CI [{_f(k.get('dr2_lo'), 4)}, "
         f"{_f(k.get('dr2_hi'), 4)}]); the SPY move to 08:00 alone has R-squared {_f(k.get('r2_reduced'), 3, False)}.",
         f"- Without the benchmark, the PM move to 08:00 has slope d = {_f(k.get('d'))} bp per pp (cluster t {_f(k.get('d_t'))}); "
         f"share absorbed by the benchmark 1 - c/d = {_f(k.get('absorbed'), 2, False)}.", "",
         "## Tests", "", HEADER,
         test_line("K: x to 08:00, SPY bench 08:00", k),
         test_line("S3: x full closure, SPY bench 08:00 (upper bound)", res["s3_0800"])]
    for m, r in res["by_market"].items():
        L.append(test_line(f"S4: {m}, x to 08:00", r))
    d = res["describe"]
    L += ["", "## Descriptives", "",
          f"n {d.get('n')}; SD of gap {_f(d.get('sd_g'), 1, False)} bp, of SPY move to 08:00 {_f(d.get('sd_b'), 1, False)} bp, "
          f"of the remainder 08:00 to open {_f(d.get('sd_r'), 1, False)} bp, of the PM move to 08:00 {_f(d.get('sd_x'), 2, False)} pp; "
          f"share of closures with a non-zero PM move by 08:00 {_f(d.get('share_x_nonzero'), 2, False)}; "
          f"correlation of PM move and SPY move {_f(k.get('corr_xb'), 3)}.",
          f"Rows: {res['n_rows']} placebo closures, {res['n_dropped']} without an SPY bar in [07:45, 08:00] ET or a PM price at 08:00.",
          "", "## Caveats", "",
          "- Already-seen panel (METHOD.md section 0). SPY pre-market at 08:00 is thin, which weakens the benchmark and "
          "favours finding a PM effect. S3 uses PM prices after 08:00 (including 08:30 releases) and is not a test of added information.",
          "- Two markets in disjoint years; serial dependence handled only by month blocks.", ""]
    return "\n".join(L)


def arm_m_summary(res: dict, commit: str) -> str:
    p = res["primary_0925"]
    L = ["# T2: does the PM move add information about the SPY open beyond the overnight benchmark?", "",
         f"Pre-registered in [METHOD.md](../../pm_vs_premarket/METHOD.md). Single run of arm M, code commit `{commit}`. "
         f"Benchmark chosen by the section 2 probe: **{res['benchmark']}** (probe: {'; '.join(res['probe_log'])}).", "",
         "## Headline", "",
         f"- **Verdict under the pre-set rule:** {res['verdict']}.",
         f"- PM coefficient given the benchmark move to 09:25 ET: c = {_f(p.get('c'))} bp per pp "
         f"(95% cluster CI [{_f(p.get('c_lo'))}, {_f(p.get('c_hi'))}]; bootstrap [{_f(p.get('c_boot_lo'))}, {_f(p.get('c_boot_hi'))}]), "
         f"cluster t {_f(p.get('c_t'))}, Freedman-Lane p {_p(p.get('p_perm', float('nan')))}, n = {p.get('n')}.",
         f"- Incremental R-squared {_f(p.get('dr2'), 4)} [{_f(p.get('dr2_lo'), 4)}, {_f(p.get('dr2_hi'), 4)}]; benchmark alone "
         f"R-squared {_f(p.get('r2_reduced'), 3, False)}; PM-only slope d = {_f(p.get('d'))}, absorbed {_f(p.get('absorbed'), 2, False)}.",
         "", "## Tests", "", HEADER]
    for label, key in res["table"]:
        L.append(test_line(label, res["tests"].get(key, {})))
    L += ["", "## Consistency with committed tables", "", res["consistency"], "",
          "## Caveats", "", "- Already-seen panels (METHOD.md section 0); see section 8 of METHOD.md.", ""]
    return "\n".join(L)
