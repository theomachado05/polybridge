import json
from pathlib import Path

R = Path(__file__).resolve().parent
src = json.loads((R / "polybridge_8k.ipynb").read_text())
cells = src["cells"]


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def reuse(i):
    c = json.loads(json.dumps(cells[i]))
    if c["cell_type"] == "code":
        c["outputs"], c["execution_count"] = [], None
    return c


INTRO = r"""
# Trade the 8-K · Does the option chain bend after a corporate headline?

**PolyBridge · Jacob Crainic and Theo Machado · Gator Quant Hacks 2026, Massive Challenge.** Built on the Massive starter
notebook: same endpoints, calendar, put-call-parity spot, five-strategy P&L engine, fixed horizons, expiry buckets and
placebo. The starter's code lives in `polybridge_research/` (each module names the starter section it comes from) so it is
unit-tested.

## Our thesis

PolyBridge starts from one premise: **the listed option chain is the professional price of an event.** In our main-track
study, on 4,561 fresh Polymarket stock markets, pre-registered and run once, the option-implied probability was a more
accurate forecast than the Polymarket price (Brier difference +0.0108, 95% CI +0.0064 to +0.0158), and the gap vanished
where professionals quote both sides. Thin retail books drift from the chain; a deep, dealer-quoted chain should not.

So we use the chain as the ruler, and a market maker's question follows: **where could the ruler itself bend?** Dealers
price an event from what they can see and hedge. Two kinds of 8-K break one of those:

- **H1 · risk that resolves slowly → protective put.** After `material_litigation`, `class_action_filing`,
  `regulatory_investigation`, `cybersecurity_incident`, `goodwill_impairment`, `asset_impairment` or
  `investment_impairment`, dealers mark implied volatility down once the headline passes, but the legal or accounting
  damage resolves over weeks. The chain should over-price the first day and under-price the follow-through, so a put
  bought after the filing is cheap.
- **H2 · demand that is one-sided → cash-secured put.** After `restructuring_plan`, `workforce_reduction`,
  `facility_closure` or `business_line_exit`, holders who must sit through the event buy puts, and dealers charge for
  demand they cannot offset (Gârleanu, Pedersen and Poteshman, 2009). Puts should be over-priced, so selling one earns
  more than on an ordinary day.

Each makes two predictions: a P&L edge for its strategy, and a sign on the parity ratio *R* = |realized move| ÷ implied
move (H1 above ordinary days, H2 below). Requiring both rules out a strategy that is merely long or short volatility in a
busy or calm year. **If the ruler is straight, both come back null with tight bounds**, and a holder can buy or sell
protection at the next close without paying for the headline. If either passes, the chain bends in a predictable place
and the strategy collects it.

**Pre-registration.** [HYPOTHESIS.md](HYPOTHESIS.md) and [HYPOTHESIS_TAGS.md](HYPOTHESIS_TAGS.md) were committed on
2 October 2026 before any 8-K event or option price was fetched. The out-of-sample window was run once after the method
freeze (git tag `method-freeze`). [FORECAST.md](FORECAST.md), our prediction for the out-of-sample and sealed windows,
was committed before either was run.

**Pass rule (fixed before results).** The 97.5% interval of the P&L edge (events minus ordinary days for the same names)
lies above zero at 2 or more of 21 sessions, 42 sessions and expiry, and *R* points the predicted way at those horizons.
Fewer than 2 testable headline horizons is reported as INSUFFICIENT. Entry is conservative: every filing is treated as
public after the close, so the trade enters at the close of the next session.

## How to run (judges)

1. Put `MASSIVE_API_KEY` in the environment or a `.env` file in this folder or a parent. Nothing else is needed.
2. `pip install -r requirements.txt` from this folder (it installs `polybridge_research` in editable mode). Opened outside
   the repo (Colab, a copied `.ipynb`), the first code cell installs the package from GitHub instead.
3. **Sealed window:** set `HOLDOUT_START`, `HOLDOUT_END` and `RUN_HOLDOUT = True` in the configuration cell, as in the
   starter, then run all cells. The last section runs the frozen pipeline on that window for both families and prints our
   committed forecast beside the verdict.

Run-all does the in-sample study, the out-of-sample re-run (`RUN_OOS`), the 2022 fresh year (`RUN_FRESH_2022`) and, when
flipped, the sealed window. From an empty cache expect roughly 10 to 20 minutes on a first run (tens of thousands of option
bars are fetched and cached in `.massive_cache/`); from a warm cache about a minute. Set `RUN_OOS = RUN_FRESH_2022 = False`
to run only the in-sample study and the sealed window.
"""

CONFIG = r'''
# ---- Windows (same names as the starter). Judges: set the sealed dates and flip RUN_HOLDOUT. ----------
STUDY_START, STUDY_END = "2024-01-01", "2025-12-31"      # in-sample, where the hypotheses were tested
OOS_START, OOS_END = "2026-01-01", "2026-08-31"          # out-of-sample, frozen method, run once on 3 Oct 2026
HOLDOUT_START, HOLDOUT_END = "2023-06-01", "2023-08-31"  # sealed: judges change these and flip RUN_HOLDOUT
RUN_HOLDOUT = False

RUN_FRESH_2022 = True        # re-runs the 2022 fresh year (section 9), run once on 4 Oct 2026
RUN_OOS = True               # re-runs the frozen out-of-sample window with exits pinned to the freeze date (reproduces results/oos)
OOS_LAST_SESSION = "2026-10-02"   # the last session used for exits in the single out-of-sample run
MAX_WORKERS = 8

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from polybridge_research.analysis import (decay_table, difference_board, pass_check, robustness_table, sample_placebo,
                                         scoreboard, verdict)
from polybridge_research.atlas import count_variants
from polybridge_research.book import book_table
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.costs import cost_table
from polybridge_research.evaluate import evaluate
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study
from polybridge_research.pricing import price_events

for _name in ("STUDY_START", "STUDY_END", "OOS_START", "OOS_END", "HOLDOUT_START", "HOLDOUT_END"):
    pd.Timestamp(globals()[_name])      # raises on an impossible date such as "2024-06-31"
assert STUDY_START < STUDY_END and OOS_START < OOS_END and HOLDOUT_START < HOLDOUT_END

cfg = StudyConfig(study_start=STUDY_START, study_end=STUDY_END, oos_start=OOS_START, oos_end=OOS_END)
cfg.validate()
START, END = STUDY_START, STUDY_END
LAST_SESSION = "2026-10-02"   # exits pinned at the method freeze, so a later run reproduces these tables
'''

OOS = r'''
if RUN_OOS:
    OOS_LAST = pd.Timestamp(OOS_LAST_SESSION)
    oos = run_family_study(client, cal, cfg, cfg.oos_start, cfg.oos_end, OOS_LAST, user_agent=None, max_workers=MAX_WORKERS)
    print(f"Out-of-sample window {cfg.oos_start} -> {cfg.oos_end}; last session used for exits {OOS_LAST.date()} (pinned)")
    for fam in FAMILIES:
        chk = oos["checks"].get(fam)
        r_e, r_p = of_family(oos["results"], fam), of_family(oos["placebo_results"], fam)
        print(f"\n[{fam}] out-of-sample verdict: {verdict(chk)}")
        if len(r_e) and len(r_p):
            strat = chk["strategy"] if chk else None
            show(difference_board(r_e, r_p, cfg, level=cfg.confirmatory_level, strategies=[strat]),
                 f"[{fam}] {strat}: events minus ordinary days at every fixed horizon (97.5% CI; n < 5 has no interval)")
            show(decay_table(r_e, cfg), f"[{fam}] parity decay, out-of-sample events")
        ins = study["checks"].get(fam)
        if chk is not None and ins is not None:
            a = ins["pnl"][["horizon", "difference"]].rename(columns={"difference": "edge_in_sample"})
            b = chk["pnl"][["horizon", "n_a", "difference"]].rename(columns={"n_a": "n_oos", "difference": "edge_oos"})
            cmp_ = a.merge(b, on="horizon", how="left")
            cmp_["same_sign"] = np.sign(cmp_.edge_in_sample) == np.sign(cmp_.edge_oos)
            show(cmp_.set_index("horizon"), f"[{fam}] headline horizons: in-sample vs out-of-sample edge")
    book_report(oos, 8 / 12, "Out-of-sample Jan-Aug 2026")
else:
    print("Out-of-sample not run (RUN_OOS = False). The committed single run is in results/oos/SUMMARY.md.")
'''


R_PASS = r"""
**Reading, in-sample 2024–2025 (the committed run; a judge's window prints its own numbers above).** Both hypotheses are
**NULL** in-sample, while on a fresh year no study had touched (2022, section 9) H1 met both pass conditions at 21 sessions,
+4.30% of the stock price over ordinary days [+0.54, +7.93] on 12 events, but not at 42 sessions or expiry. In-sample no
headline interval excludes zero: H1's protective-put edge is +0.07% of the stock price at 21 sessions
[−2.70, +2.91], +0.49% at 42 and +3.33% at expiry; H2's cash-secured-put edge is +0.09% [−0.68, +0.89], +0.21% and +0.92%.
*R* did move the predicted way at all three headline horizons for H1 and at 21 and 42 for H2, so the direction of each
mechanism shows up, but not its size. **What the nulls bound:** the chain did not under-price post-headline protection by
more than about 3% of the stock price (H1), nor over-price restructuring puts by more than about 0.9% (H2).
"""

R_DECAY = r"""
**Reading: the shape of the ruler.** For H1 the chain priced the first session generously and the follow-through cheaply,
as H1 says: *R* is 0.68 one session after the filing against 0.99 on ordinary days, and 1.36 at 42 sessions against 1.15.
Both gaps sit inside the events' 95% band, so with about 30 events the bend is not distinguishable from a straight ruler.
H2 hugs the ordinary-day line at every horizon (0.77 to 1.11 against 0.86 to 1.01).
"""

R_SENS = r"""
**Reading.** At 21 sessions with the tradeable entry, the H2 edge is positive in 9 of 9 cells of expiry bucket × OTM
distance (+0.08% to +1.24%) and H1 in 7 of 9 (−0.67% to +0.68%). The cells share events, so this shows a stable sign, not
nine results. By category (the exploratory per-tag atlas, at most 15 events a tag against a shared placebo), no H1 tag has
an interval above zero; `restructuring_plan` × cash-secured put is positive at 21, 42 sessions and expiry (+2.57%
[+0.95, +4.51] at expiry, 14 events, q = 0.014). That is a lead for a new pre-registered test, not a result.
"""

R_COST = r"""
**Reading, in basis points.** A 5% premium haircut each way costs 28–29 bp of the stock price at 21 sessions; real
half-spreads where quotes exist are 26–29 bp. Net of the haircut the edge over ordinary days is about +11 bp for both
families, inside the noise. The median put traded 34 (H1) and 49 (H2) contracts on the entry day: at 10% participation a
desk fills 3 to 5 contracts an event, about $0.1 million of stock notional, on roughly 1.3 H1 and 1.0 H2 events a month.
Even a real edge would be a cost statement for a hedger, not a strategy with capacity.
"""

R_OOS = r"""
**Reading, out-of-sample January–August 2026.** H1 is **INSUFFICIENT** (3 events). H2 is **NULL with its sign reversed**:
−2.15% [−7.59, +2.03] at 21 sessions and −1.38% at 42, against +0.09% and +0.21% in-sample. The decay table shows why:
in 2026 restructuring filings moved 2.2 to 2.5 times the implied move in the first week (interval above 1 at 3 and 5
sessions, 7 events). That is the one place the ruler visibly bent, and it bent the opposite way to H2: the chain
under-priced the first week. Our forecast had "no pass" and the H2 count right, and missed the H1 count, the interval
widths and all three signs it could score.
"""


FRESH_MD = r"""
## 9 · A fresh year: 2022, run once (S27)

Pre-registered in `s27_liquid_8k/METHOD.md` (commit `41a04a6`) before any 2022 event or option price was pulled, and run once.
The frozen pipeline (same tags, timing and pass rule) on a year no study had used. The registered primary, a cut to the most
liquid option names, left 3 H1 and 1 H2 events (INSUFFICIENT); this section shows the full-year replication, which was
registered as its secondary analysis. The decomposition at the end splits the protective put into its stock and its put.
"""

FRESH = r'''
fresh = None if not RUN_FRESH_2022 else run_family_study(client, cal, cfg, "2022-01-01", "2022-12-31", pd.Timestamp("2026-10-02"), user_agent=None, max_workers=MAX_WORKERS)
for fam in (FAMILIES if fresh is not None else []):
    chk = fresh["checks"].get(fam)
    r_e, r_p = of_family(fresh["results"], fam), of_family(fresh["placebo_results"], fam)
    print(f"\n[{fam}] 2022 verdict: {verdict(chk)}; pass conditions met at: {sorted(set(chk['horizons_pnl_ok']) & set(chk['horizons_ratio_ok']), key=str) if chk else []}")
    if len(r_e) and len(r_p):
        show(difference_board(r_e, r_p, cfg, level=cfg.confirmatory_level, strategies=[chk["strategy"]]),
             f"[{fam}] {chk['strategy']}: events minus ordinary days at every fixed horizon, 2022 (97.5% CI)")
if fresh is None:
    print("2022 fresh year not run (RUN_FRESH_2022 = False); the committed run is in results/s27_liquid_8k/.")
h1 = lambda d: d[(d.family == "hedge") & (d.bucket == cfg.baseline_bucket) & (d.entry == "post") & (d.otm == cfg.otm_pct) & (d.horizon == 21)]
if fresh is not None:
  ev, pl = h1(fresh["results"]), h1(fresh["placebo_results"])
  show(pd.DataFrame({"filings": [ev.realized.mean(), (ev.realized < 0).mean(), (ev.protective_put - ev.stock).mean(), ev.protective_put.mean()],
                   "ordinary days": [pl.realized.mean(), (pl.realized < 0).mean(), (pl.protective_put - pl.stock).mean(), pl.protective_put.mean()]},
                  index=["stock return, 21 sessions", "share of stocks that fell", "put leg alone", "protective put"]).round(4),
     "H1 in 2022, decomposed: where the protective put's gain came from")
  book_report(fresh, 1.0, "Fresh year 2022")
'''

R_FRESH = r"""
**Reading.** On a fresh year, H1 met both pass conditions at 21 sessions: +4.30% over ordinary days [+0.54, +7.93] on 12
events, Sharpe 2.57 against −0.04 for the same put on ordinary days. It did not at 42 sessions or expiry, so the verdict is
NULL. The decomposition shows the gain is not H1's mechanism: after the bad news the stocks rose 6.1% in 21 sessions (only a
quarter fell) against 0.6% on ordinary days, while the put alone lost 1.8%. In a falling market the headline was oversold
and the put dear; the protective put earned through the stock it owns. That is a lead for a test of post-filing rebounds in
stress regimes. H2 in 2022 is NULL: +0.48% at 21 sessions [−1.72, +2.22].
"""

H3_MD = r"""
## 10 · H3: sell the put after bad-news filings (discovered on 2022)

Section 9's decomposition points at a different trade. In stress, bad news is oversold and puts are dear, so the trade
paid by both is to **sell** the put: after an H1 filing (the 7 frozen tags), sell the 5%-out-of-the-money 3–6 month put
at the close of the session after the filing (conservative timing), cash-secured, and hold it. The put seller is paid by
the rebound and by the premium. Edge = the same trade on ordinary days of the same companies; PASS if the 97.5% interval
lies above zero at 2 or more of 21 sessions, 42 sessions and expiry. **High fear**: the event's implied move at entry is
at least 14%, applied to events and ordinary days alike; all H1 events are reported as the secondary scope.

The rule was committed in `s28_sell_fear/METHOD.md` (commit `f9468bf`) before the high-fear filter touched any window.
**2022 formed the hypothesis, so its numbers are not evidence for it.** The confirmatory test is the sealed window below.
"""

H3 = r'''
import sys
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))     # s28_sell_fear lives next to this notebook in research/
try:
    from s28_sell_fear.run import high_fear, h3
except ImportError:
    high_fear = h3 = None
    print("s28_sell_fear not found (notebook opened outside the repo); the committed H3 run is in results/s28_sell_fear/SUMMARY.md.")


def h3_rows(st, years, window):
    """H3 on one study: all H1 events and the high-fear subset, cash-secured put minus ordinary days."""
    ev, pl = of_family(st["results"], "hedge"), of_family(st["placebo_results"], "hedge")
    rows = []
    for scope in ("all H1", "high fear"):
        a, b = (ev, pl) if scope == "all H1" or not len(ev) or not len(pl) else (high_fear(ev), high_fear(pl))
        d, v, ok, n, s_ev, s_pl = h3(a, b, cfg, years)
        row = {"window": window, "scope": scope, "verdict": v, "events_21": n}
        for hz in (21, 42):
            x = d[d.horizon == hz] if len(d) else d
            if not len(x) or pd.isna(x.difference.iloc[0]):
                row[f"edge_{hz}"] = "too few events"
            elif pd.isna(x.ci_lo.iloc[0]):
                row[f"edge_{hz}"] = f"{100 * x.difference.iloc[0]:+.2f}% (no interval)"
            else:
                row[f"edge_{hz}"] = f"{100 * x.difference.iloc[0]:+.2f}% [{100 * x.ci_lo.iloc[0]:+.2f}, {100 * x.ci_hi.iloc[0]:+.2f}]"
        row["sharpe_21_events_vs_ordinary"] = f"{s_ev:.2f} vs {s_pl:.2f}"
        rows.append(row)
    return rows


if h3 is not None:
    if fresh is None:
        print("2022 not run (RUN_FRESH_2022 = False); showing 2024-25 and 2026 only. The committed 2022 run is in results/s28_sell_fear/.")
    h3_tab = []
    for st, yrs, name in ((fresh, 1.0, "2022 (discovery)"), (study, 2.0, "2024-25 (seen)"),
                          (globals().get("oos") if RUN_OOS else None, 8 / 12, "2026 (seen)")):
        if st is not None:
            h3_tab += h3_rows(st, yrs, name)
    h3_tab = pd.DataFrame(h3_tab)
    with pd.option_context("display.width", 200, "display.max_colwidth", 40):
        print("H3: cash-secured put after H1 filings minus ordinary days (97.5% CI; Sharpe at 21 sessions, annualised)")
        print(h3_tab.to_string(index=False))
'''

R_H3 = r"""
**Reading.** On 2022, where H3 was discovered, it shows the pass shape: all 12 H1 events +1.73% [+0.33, +3.11] at 21
sessions and +2.25% [+0.51, +4.06] at 42, Sharpe 3.34 against 0.11 on ordinary days; the 7 high-fear events +2.17% and
+2.63%, Sharpe 3.56. That is the discovery, not evidence. On 2024–25 (seen, calm) H3 is **NULL**: all H1 +0.03% at 21
sessions, and high fear −1.38% [−5.61, +2.02] on 8 events. **The stock-level fear filter failed**: high-fear filings in a
calm market did not rebound. What separated 2022 looks like market-wide stress, and that condition has not been defined or
tested; no condition is added after the fact. 2026 is INSUFFICIENT (1 and 3 events). The sealed window is H3's
confirmatory test.

2023 out-of-sample: see results/s28_sell_fear/oos_2023-01-01_2023-12-31.json
"""

CONCLUSION = r"""
## What this says about the thesis

**The ruler held, and one fresh year shows where it slips.** On 2022, run once, H1 beat ordinary days by +4.30% at
21 sessions [+0.54, +7.93], meeting both pass conditions at that horizon, though the gain came from stocks rebounding after
the news rather than from cheap puts (section 9). Otherwise the option chain at the 100 largest US stocks priced the move
about right: within roughly 3% of the stock price for post-headline protection and 0.9% for restructuring
puts over 2024–2025, and too few or too noisy events since. The mechanisms left traces in the right direction (H1's decay
shape, H2's stable sensitivity sign), but not edges a desk could trade after costs and at this capacity.
H3 is the conditional trade (sell the put after bad-news filings in market stress): discovered on 2022 with Sharpe 3.34,
flat in calm 2024–25, and tested independently on the sealed window.

That is the result PolyBridge's premise needs. We use the chain as the reference price for thinner markets, and this study
finds no headline-driven bend large enough to matter. The one bend we saw, restructurings in 2026 moving far more than
priced in their first week, is the next pre-registered test, together with `restructuring_plan` alone and H2 entry a few
sessions after the filing, on a window with the power to detect a 0.5% edge.
"""

HOLDOUT_MD = r"""
## Sealed window · judges only

Set `HOLDOUT_START`, `HOLDOUT_END` and `RUN_HOLDOUT = True` in the configuration cell and run all cells. This cell runs
the frozen pipeline (same tags, same pass rule, same conservative timing) on that window for both families. Horizons that
have not resolved by today are absent rather than guessed.

**What we predicted** ([FORECAST.md](FORECAST.md), committed before any window outside 2024–2025 was run): a 3-month window
gives about 4 H1 and 3 H2 events, too few for an interval, so INSUFFICIENT for both; 4–5 months NULL or INSUFFICIENT;
6 months or more NULL for both. A PASS would contradict the forecast and we would call it a surprise, not a confirmation.

**H3 is tested here too** (section 10, rule committed in `s28_sell_fear/METHOD.md`, `f9468bf`): the cash-secured put
after H1 filings, high-fear events and all H1 events, against ordinary days. This is its first confirmatory test.
Forecast: a calm window gives few high-fear events and a null (or INSUFFICIENT); a stressed window should show the edge at
21 and 42 sessions.
"""

HOLDOUT = r'''
FORECAST = [(3.5, "INSUFFICIENT", "INSUFFICIENT"), (5.5, "NULL or INSUFFICIENT", "INSUFFICIENT"),
            (12.5, "NULL", "NULL"), (float("inf"), "NULL", "NULL")]


def forecast_for(start, end):
    months = (pd.Timestamp(end) - pd.Timestamp(start)).days / 30.44
    h1, h2 = next((a, b) for m, a, b in FORECAST if months <= m)
    return months, {"hedge": h1, "opportunity": h2}


if RUN_HOLDOUT:
    LAST_H = cal.last_completed()
    holdout = run_family_study(client, cal, cfg, HOLDOUT_START, HOLDOUT_END, LAST_H, user_agent=None, max_workers=MAX_WORKERS)
    months, fc = forecast_for(HOLDOUT_START, HOLDOUT_END)
    print(f"Sealed window {HOLDOUT_START} -> {HOLDOUT_END} ({months:.1f} months); exits up to {LAST_H.date()}")
    rows = []
    for fam in FAMILIES:
        chk = holdout["checks"].get(fam)
        r_e, r_p = of_family(holdout["results"], fam), of_family(holdout["placebo_results"], fam)
        sb = scoreboard(r_e, cfg, strategies=["stock"], horizons=[21]) if len(r_e) else None
        n_ev = int(sb["n"].sum()) if sb is not None and len(sb) else 0
        rows.append({"family": fam, "events_at_21": n_ev, "verdict": verdict(chk), "our_forecast": fc[fam]})
        if len(r_e) and len(r_p):
            strat = chk["strategy"] if chk else None
            show(difference_board(r_e, r_p, cfg, level=cfg.confirmatory_level, strategies=[strat]),
                 f"[{fam}] {strat}: events minus ordinary days at every fixed horizon (97.5% CI)")
            show(scoreboard(r_e, cfg), f"[{fam}] all five strategies, events (95% CI)")
            de = decay_table(r_e, cfg)
            show(de, f"[{fam}] parity decay, sealed-window events")
            de_in = decay[fam][0]
            if len(de) and len(de_in):
                fig, ax = plt.subplots(figsize=(6, 3.2))
                order = [*cfg.horizons, "exp"]
                for tbl, label, colr in ((de_in, "in-sample events", "tab:red"), (de, "sealed-window events", "tab:green"),
                                         (decay[fam][1], "in-sample ordinary days", "tab:gray")):
                    t = tbl.dropna(subset=["mean_ratio"])
                    ax.plot([order.index(h) for h in t.index], t["mean_ratio"], "o-", label=label, color=colr)
                ax.axhline(1, color="k", lw=0.6)
                ax.set_xticks(range(len(order)), [str(h) for h in order])
                ax.set_xlabel("sessions after the filing"); ax.set_ylabel("|realized| / implied")
                ax.set_title(f"[{fam}] parity decay"); ax.legend(fontsize=8)
                plt.show()
        else:
            print(f"[{fam}] no priced events or no placebo in this window")
    if h3 is not None:
        h3_hold = pd.DataFrame(h3_rows(holdout, months / 12, f"sealed {HOLDOUT_START}..{HOLDOUT_END}"))
        with pd.option_context("display.width", 200, "display.max_colwidth", 40):
            print("H3 on the sealed window: cash-secured put after H1 filings minus ordinary days (97.5% CI)")
            print(h3_hold.to_string(index=False))
        for r in h3_hold.to_dict("records"):
            rows.append({"family": f"H3 {r['scope']} (cash_secured_put)", "events_at_21": r["events_21"], "verdict": r["verdict"],
                         "our_forecast": "NULL or INSUFFICIENT if calm; edge at 21 and 42 if stressed"})
    show(pd.DataFrame(rows).set_index("family"), "Sealed window: verdict against our committed forecast")
    book_report(holdout, months / 12, f"Sealed window {HOLDOUT_START} to {HOLDOUT_END}")
else:
    print(f"Sealed window {HOLDOUT_START}..{HOLDOUT_END} not run. Judges: set RUN_HOLDOUT = True.")
'''

INSTALL = r"""
# Inside the repo, `pip install -r requirements.txt` has already installed polybridge_research. Opened on its own
# (Colab, a copied .ipynb), install it from the public repo. No other setup is needed beyond MASSIVE_API_KEY.
try:
    import polybridge_research  # noqa: F401
except ImportError:
    %pip install -q "git+https://github.com/theomachado05/polybridge.git#subdirectory=research"
"""

BOARD = r"""
# Table 1 of the write-up: the registered strategy alone, events minus ordinary days at every fixed horizon.
for fam in FAMILIES:
    chk = study["checks"].get(fam)
    r_e, r_p = of_family(study["results"], fam), of_family(study["placebo_results"], fam)
    if chk is None or not len(r_e) or not len(r_p):
        print(f"[{fam}] no events or no placebo in this window")
        continue
    show(difference_board(r_e, r_p, cfg, level=cfg.confirmatory_level, strategies=[chk["strategy"]]),
         f"[{fam}] {chk['strategy']}: events minus ordinary days at every fixed horizon (97.5% CI)")
"""

BOOK_FN = r"""
STRATEGY_OF = {"hedge": "protective_put", "opportunity": "cash_secured_put"}


def book_report(st, years, label):
    # Each registered rule run as a book: one $1-notional trade per filing at 21 sessions, net of the 5% haircut.
    tab, lists = book_table(st, cfg, STRATEGY_OF, years)
    keep = ["trades", "trades_per_year", "mean_net_pct", "hit_rate", "annual_return_pct", "annual_vol_pct", "sharpe_net",
            "max_drawdown_pct", "worst_trade_pct", "avg_open_positions", "turnover_x_per_year"]
    show(tab[[c for c in keep if c in tab]].round(2),
         f"{label}: the book, net of a 5% premium haircut each way (percent of one trade's stock notional). Ordinary days "
         "are a 120-day sample per family, annualised at the filings' trade rate: compare Sharpe and mean, not trade count or drawdown.")
    fig, ax = plt.subplots(figsize=(7, 3))
    for fam, colr in (("hedge", "tab:red"), ("opportunity", "tab:blue")):
        t = lists[(fam, "filings")]
        if len(t):
            ax.step(pd.to_datetime(t.exit_date), 100 * t.net.cumsum(), where="post", color=colr,
                    label=f"{fam}: {STRATEGY_OF[fam]} ({len(t)} trades)")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_ylabel("cumulative net P&L, % of one trade"); ax.set_title(f"{label}: equity curve of the registered rules")
    ax.legend(fontsize=8); plt.show()
    return tab, lists
"""

BOOK_MD = r"""
## 7b · The rules run as a book: equity curve, drawdown, turnover, Sharpe

One trade per filing at the registered cell (3–6 month expiry, entry at the close after the filing, 5% OTM, held
21 sessions), each $1 of stock notional, net of the 5% premium haircut each way. Each trade books on its exit date. Holds
overlap, so Sharpe is per trade annualised by the window's trade rate, not a daily-NAV figure. Turnover: each position
lives 21 sessions, so capital turns over 12 times a year, and the book holds on average `avg_open_positions` trades.
"""

R_BOOK = r"""
**Reading, in-sample 2024–2025.** H1's protective put: 32 trades, +1.81% net a trade, Sharpe 1.20 net, max drawdown
−9.6% of one trade's notional, about 1.3 positions open at a time. The same put bought on ordinary days, at the same trade
rate and net of the same haircut, had a Sharpe of 1.01. H2's cash-secured put: 24 trades, +0.54% net, Sharpe 1.41 net, max
drawdown −2.8%, against 0.74 on ordinary days. Both books made money in 2024–25 mostly because puts on large caps in a
rising market did; the filing's own contribution is the edge over ordinary days, which the pass rule tests and which is
not distinguishable from zero.
"""


new = [md(INTRO), code(INSTALL), code(CONFIG), reuse(2), code(BOOK_FN),
       md("## 1 · In-sample study, 2024-01-01 to 2025-12-31\n\nEvents by family, exclusions (cross-family filings are dropped from both tests) and drops before pricing."),
       reuse(3),
       md("## 2 · Scoreboards and the placebo gap at every fixed horizon\n\nAll five strategies for events and for ordinary days, then the event-minus-placebo edge with its interval."),
       reuse(4),
       md("**Table 1 of the write-up** (the registered strategy alone; the board above bootstraps all strategies with one generator, so its intervals differ in the last digit)."),
       code(BOARD),
       md("## 3 · The pre-registered pass check"), reuse(5),
       md(R_PASS),
       md("## 4 · Robustness (reported next to the pass rule, never instead of it)"), reuse(6),
       md("## 5 · The yardstick: parity decay (|realized| ÷ implied move)\n\nEntry on the pre-event session, so this is a statement about pricing, not a trade."),
       reuse(7), md(R_DECAY),
       md("## 6 · Parameter sensitivity\n\nThe starter's grid: expiry bucket × entry session × OTM distance, at 21 sessions."),
       reuse(8), md(R_SENS),
       md("## 7 · Trade specification: costs, liquidity, capacity\n\nA 5% premium haircut each way at 1× and 2×, and real half-spreads where quotes exist; median leg volume on the entry day."),
       reuse(9), md(R_COST),
       md(BOOK_MD), code("book_in, _ = book_report(study, 2.0, \"In-sample 2024-2025\")"), md(R_BOOK),
       md("## 8 · Out-of-sample, 2026-01-01 to 2026-08-31\n\nThe frozen pipeline, exits pinned to 2 October 2026 as in the single committed run (`results/oos/`)."),
       code(OOS), md(R_OOS),
       md(FRESH_MD), code(FRESH), md(R_FRESH),
       md(H3_MD), code(H3), md(R_H3),
       md(HOLDOUT_MD), code(HOLDOUT),
       md(CONCLUSION), reuse(14)]

for k, c in enumerate(new):
    c.setdefault("id", f"m8k-{k:02d}")
nb = {"cells": new, "metadata": src["metadata"], "nbformat": src["nbformat"], "nbformat_minor": src["nbformat_minor"]}
(R / "massive_8k.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
print("cells:", len(new))
