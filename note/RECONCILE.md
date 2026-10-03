# Reconciliation: note/WRITEUP.md and note/PITCH.md against the committed results

For Jacob. Written 2026-10-03 (Sat) by Theo's session. Your files were not edited; this is a list of suggested changes. "W" is `note/WRITEUP.md`, "P" is `note/PITCH.md`, and "L" is a line number. The story is A: **evidence-gated 24/7 hedging**. PolyBridge checks each market's signal out of sample before that signal can act on a position. Closed-market mode exists because stocks close and prediction markets don't. Significant findings are stated with their scope, and the 8-K study is the rigorous "what didn't work". Every number comes from `research/EVIDENCE.md` or the file named.

**Checked and correct (no change needed):**
- Every in-sample edge, CI and R value in W L35-41 matches `research/results/in_sample/*_difference_975.csv` and `*_decay_*.csv`.
- The two small differences are listed in section 2.
- The 30-day placebo gap (W L23) matches `research/polybridge_research/config.py` (`placebo_gap_days: int = 30`).
- The 5 cross-family exclusions (W L19) match.
- 24 to 36 events per family (W L54) matches the totals.

## 1. Placeholders to fill (out-of-sample numbers)

| Location | Current text | Issue | Suggested replacement (source) |
|---|---|---|---|
| W L42 | `\| Out-of-sample \| [OOS] \| [OOS] \| [OOS] \| [OOS] \|` | The OOS numbers are committed. A single row cannot hold them, because n differs by horizon and H1 has no edge. | Delete the row and add this table under it (`research/results/oos/SUMMARY.md`):<br>**Out of sample, 2026-01-01 to 2026-08-31, frozen 3 Oct 13:00 ET, run once.**<br>\| Horizon \| H1 n (events / ordinary) \| H1 edge \| H2 n \| H2 edge [97.5% CI] \| H2 R, events / ordinary \|<br>\| 21 \| 3 / 107 \| not computable (n < 5) \| 7 / 90 \| −0.0215 [−0.0759, +0.0203] \| 1.57 / 1.10 \|<br>\| 42 \| 3 / 81 \| not computable \| 7 / 68 \| −0.0138 [−0.0729, +0.0260] \| 1.17 / 0.90 \|<br>\| Expiry \| 1 / 65 \| not computable \| 4 / 51 \| not computable \| 0.79 / 1.11 \|<br>Then: "H1 is INSUFFICIENT: 3 events, below the 5 an interval needs. H2 is NULL, and its edge has the opposite sign to in-sample (+0.0009, +0.0021) at both computable horizons. Its R is above ordinary days at 21 and 42 sessions, which is the opposite of H2's premise, on 6 to 7 events." |
| W L31 | "Neither hypothesis passes in-sample." | The OOS verdict is missing. | "Neither hypothesis passes, in-sample (2024-25, NULL for both) or out of sample (2026-01 to 08: H1 INSUFFICIENT on 3 events, H2 NULL with the sign reversed)." (`in_sample/*_verdict.txt`, `oos/SUMMARY.md`, `research/HYPOTHESIS.md` change log 2026-10-03) |
| W L17 | "...run once after the method freeze on 3 October." | The required OOS-run disclosure is missing. | Append: "The single run (13:00 ET, tag `method-freeze` on 344de99) used a branch that did not yet contain the robustness additions (company-clustered bootstrap, H1 put-leg edge, INSUFFICIENT label). They leave the pass rule unchanged. Applying the INSUFFICIENT rule to the saved output relabels H1 from NULL to INSUFFICIENT. H2 stays NULL." (`research/HYPOTHESIS.md` change log, last entry) |
| W L54 | "...A PASS on the sealed window would contradict our forecast." | The forecast can now be scored on the OOS window. | Append: "On the OOS window the forecast had the verdicts' direction right (no pass) and the event count and H2 sign wrong. H1 had 3 events, not about 11. H2's edge was negative at 21 and 42 sessions, where we forecast positive with probability 0.60. Section 5 of `note/RECONCILE.md` has the details." (`research/FORECAST.md`, `oos/SUMMARY.md`) |

## 2. Numbers that differ

| Location | Current text | Issue | Suggested replacement (source) |
|---|---|---|---|
| W L38, 39, 41 (bold H1 rows) | 21: [−0.026, +0.029]; 42: [−0.045, +0.060]; expiry: [−0.029, +0.100] | These come from `hedge_difference_975.csv`. The verdict and EVIDENCE use the pass-check CIs, which differ in the third decimal (shared RNG stream, `in_sample/SUMMARY.md` "Notes"). | 21: [−0.027, +0.029]; 42: [−0.045, +0.058]; expiry: [−0.030, +0.101] (`in_sample/hedge_pass_check.csv`). The H2 bold rows already match. |
| W L37 | H2 10-session edge "+0.001" | 0.00045 rounds to +0.000. | "+0.000 [−0.006, +0.008]" (`opportunity_difference_975.csv`, cash_secured_put, 10) |
| W L50, P L18 | "34 contracts (H1) and 49 (H2)" / "34 to 49 contracts traded on the entry day" | The source value is median leg volume, 33.5 and 48.5, and the source does not say "entry day". | "median option leg volume 33.5 (H1) and 48.5 (H2) contracts" (`in_sample/*_cost_summary.csv`) |
| W L50 | "the edges move by less than 0.3% of spot" | This is true but loose. The haircut moves the edge by at most 0.0004. The 0.3% figure is the half-spread cost. | "The 5% haircut moves the edge by at most 0.04% of spot (net edge 1x: H1 +0.0011 / +0.0052 / +0.0336, H2 +0.0011 / +0.0024 / +0.0095); the quoted half-spread costs about 0.0029 per $1 of spot at 21 sessions." (`in_sample/SUMMARY.md` costs) |
| W L9, L11 | "bought / sold at the filing close" | This conflicts with W L19 (entry at the close of the next session, conservative timing). | "at the close of the session after the filing" (`research/HYPOTHESIS.md` §3, change log 2026-10-02) |
| P L17 | "The atlas has q-values of 0.01." | The minimum q is 0.0136. | "The lowest atlas q is 0.014: 23 rows at q < 0.05 across 11 tags, 5 to 15 events each, out of 96,390 variants." (`research/results/atlas/atlas.csv` (tally), `atlas/README.md`) |

## 3. Claims that conflict with story A or with the evidence

| Location | Current text | Issue | Suggested replacement (source) |
|---|---|---|---|
| W L1, L3 | Title "Do Options Price Slow 8-K News Correctly?..."; "Massive 'Trade the 8-K' challenge" | Under A, the main-track note's title is the product thesis, and these pages become its 8-K section. | Note title: "PolyBridge: Evidence-Gated 24/7 Hedging". Section heading (pages 1-2): "Part I · The 8-K test (Massive challenge): pre-registered, null in and out of sample". Keep the current file as the standalone Massive submission if one is needed. |
| W L46 | "For a portfolio manager this means post-headline insurance costs about what it is worth." | The result is in-sample only. The H1 bound is on stock plus put, not on the put price; the stock leg dominates (`research/HYPOTHESIS.md` change log 2026-10-03 (b)). | "In 2024-25 data, a stock-plus-put position after an H1 filing did no better or worse than on ordinary days by more than about 3% of spot at 21 sessions. Short puts after H2 filings were not overpriced by more than about 0.9%. Out of sample there were too few events to recheck this." (`in_sample/hedge_pass_check.csv`, `opportunity_pass_check.csv`, `oos/SUMMARY.md`) |
| W L48, P L7 | "The shape is the finding worth following." / Decay chart slide: "0.68 ... 1.36 at 42 sessions. That is our mechanism." | EVIDENCE says not to single out one horizon and to quote the decay only with its caveat. Under the gate, an in-sample shape that failed OOS is an unvalidated estimate. With n = 3, the OOS ratios point the other way. | "In-sample the H1 parity ratio was 0.68 at one session and 1.36 at 42 (ordinary days 0.92 to 1.15), the shape H1 describes, but the event CIs overlap placebo at every horizon. Out of sample (3 events, no CI) it went the other way: 1.86 vs 0.93 at one session, 0.61 vs 0.92 at 42. Not a finding." (`in_sample/SUMMARY.md` "Parity decay"; `oos/SUMMARY.md`; `research/EVIDENCE.md` style notes L189) |
| W L27, P L15 | "Robustness. A bootstrap that resamples whole companies, and for H1 the put's own P&L..." / "we report the put's own edge as a robustness check" | No number for either is committed. `research/results/in_sample/` has none, the notebook has no saved outputs, and the OOS run predates both. Also, both were added after the in-sample NULLs were seen. | Either commit the in-sample robustness output and cite it, or write: "Added after the in-sample NULLs were seen, as robustness only: a company-clustered bootstrap and the H1 put-leg edge (notebook cells in `research/polybridge_8k.ipynb`). Neither can turn a NULL into a PASS, and the OOS run predates both." (`research/HYPOTHESIS.md` change log 2026-10-03) |
| W L50, P L18 | "so capacity is a few contracts per event without moving the market" / "a few contracts per event" | EVIDENCE says no capacity or ADV analysis is in the pack, so do not claim one. | "Median leg volume was 33.5 and 48.5 contracts. We did no capacity analysis." (`research/EVIDENCE.md` L186) |
| W L58, P L11 | "buying protection at the close does not overpay, so a holder ... can buy it without waiting" / "Next test: H2 entry timing" | Under A, an 8-K signal that failed OOS does not act on positions. The product shows 8-K tags as untested (`backend/app/verdicts.py`, label `no_edge`, note "not tested"). The H2 lead also lost OOS (edge −0.0215 at 21 sessions). | "We would not trade either rule. PolyBridge lets a signal act on positions only after it passes a pre-registered out-of-sample test. Both 8-K families failed (H1 INSUFFICIENT, H2 NULL with the sign reversed), so 8-K tags are shown as untested and never size a hedge. H2 entry timing remains a candidate for a fresh pre-registered window. Out of sample the H2 short put lost to ordinary days." Pitch close: "Next: a fresh-sample test of the staged 09:30 hedge and of the expected gap on US macro markets, against a futures benchmark." (`oos/SUMMARY.md`; `research/EVIDENCE.md` outline p.5) |
| P L5, L6, L8 | Title line about 8-K; the two bets; "Both nulls ... insurance is not overpriced..." | The pitch is 8-K-first. Under A it leads with the product and the gate, and the 8-K test is one result. | 0:00 "Stocks close; prediction markets don't. PolyBridge hedges a stock book around the clock, and lets a market's signal touch a position only after it passes an out-of-sample test." 0:30 "Six pre-registered tests today. The four on new data failed or were NULL. The two that passed did so on an already-seen panel, with stated scope." 2:15 "The 8-K test by the book: committed before data, NULL in-sample; out of sample H1 had 3 events and H2 flipped sign. So 8-K tags never act." (`research/EVIDENCE.md` L18-29, L164) |
| P L7 (slot) | Decay chart | Replace this slide with a scoped finding that cleared its test. | "At the Monday open, options had repriced only 0.44 of the prediction market's closure move (CI 0.33 to 0.57; 1,535 events, 44 closures, fresh data). After costs it is NULL: information, not arbitrage." (`research/results/open_options/SUMMARY.md`; EVIDENCE Lead 1) |
| P L9 | Forecast slide | Keep it, and add the score. Saying "we were wrong" is strong evidence that the record is honest. | "We wrote down the OOS result before running it. We had no pass right. We got the event count (H1 3, not about 11) and H2's sign wrong." (section 5 below) |
| P L10 | Demo: "labels anything we have not tested as 'Not tested'" | Under A the closed-mode labels are "validated" and "unvalidated estimate" (`backend/app/closed/bridge_mode.py` L14-16). The pitch is on Sunday, and the Webull paper sandbox rejects every order outside 09:30-16:00 ET with HTTP 417 ("Orders cannot be placed at this time...", tested Sat 2026-10-03 14:50 ET, 1 share SPY limit $1). | "It's Sunday: stocks are shut, the prediction market is live. PolyBridge shows each market's signal as validated or as an unvalidated estimate, and stages the equity hedge for the 09:30 open. The broker refuses orders until then, which is exactly the design: the staged hedge is the one closed-market hedge that met its rule, fragile, +6.82% [+0.50, +13.54] over a same-size static hedge." (`research/results/closed_hedge/SUMMARY.md`; the 417 test is not yet in a committed file, so record it before quoting) |

**Inconsistencies in our own files (Theo to fix, not you).**
- The H1 OOS label differs between files. `research/EVIDENCE.md` L26 and L42 say "H1 NULL" and "stayed NULL". `research/EVIDENCE.md` L107 and the change log say INSUFFICIENT. `oos/SUMMARY.md` and `RUN_LOG.md` row 8 print the computed label NULL, from before the relabel.
- The note should say "H1 INSUFFICIENT (computed label NULL; relabelled by the pre-freeze INSUFFICIENT rule)".
- `in_sample/SUMMARY.md` still says "Out-of-sample window not run" and "Atlas not run". Both lines are stale.

## 4. Suggested 5-page main-track note (story A; your Massive section stays as pages 1-2)

The rubric has five criteria, each scored out of 10: Economic foundation, Innovation, Risk management, Liquidity and capital, and Performance and evidence.

| Page | Section | Earns | Content |
|---|---|---|---|
| 0 (top of p.1, 4 lines) | Summary | Economic foundation | The thesis in one sentence. Then the principle (validate out of sample before acting). Then the record: six tests, four on new data failed or NULL, two passes with scope. |
| 1-2 | **Part I · The 8-K test (your W §1-5)** | Performance and evidence; Economic foundation | Your hypothesis, method and results, with section 1 filled and sections 2-3 applied. To fit: collapse sessions 1, 5, 10 and 63 into one sentence pointing to `in_sample/`, add the OOS table, and replace §5 with the gate sentence above. End with one bridge line: "That is why PolyBridge gates every signal." |
| 3 | Part II · Closed-market mode and the gate | Economic foundation; Innovation | Stocks close; prediction markets don't. The PM price and the option chain price the same risk. The gate: validated vs unvalidated estimate. The findings that cleared their tests, each with its scope in the same sentence: R3 catch-up 0.44 (NULL after costs); R2 expected gap on the recession market only (97 of 151; replication fails); R1 staged 09:30 hedge, fragile. The 380-closure relation is exploratory and did not replicate (EVIDENCE Lead 1-4). |
| 4 | Part III · Evidence table, risk and liquidity | Performance and evidence; Risk management; Liquidity and capital | The six-test table from EVIDENCE L22-29, each result once. Product implications: staged equity orders by default, PM-contract hedge opt-in, options-at-open research-only. Controls (`docs/library.md`). Liquidity numbers from EVIDENCE outline p.4, plus the Webull 417 (orders only in session, which is why hedges are staged). |
| 5 | Part IV · Limits, latency, next steps | Performance and evidence; Innovation | What didn't work: no market-hours lead (9 / 9 / 2), arbitrage 5 verified / 0 executable, AI fit fails walk-forward. Engine 27.1 to 34.6 ns per `on_tick` on synthetic tape. Not tested: futures and pre-market benchmarks, real fills. Next: fresh-sample tests of hedge B and of the US-macro expected gap. |

## 5. FORECAST.md vs the out-of-sample result

Sources: `research/FORECAST.md`, committed 11:00 before the 13:00 freeze; `research/results/oos/SUMMARY.md`.

| Forecast (FORECAST.md line) | Said | Actual | Verdict |
|---|---|---|---|
| H1 n at 21 / 42 / expiry (L23-25) | about 11 / 9 / 6 | 3 / 3 / 1 | **Wrong.** The event rate was about 0.4 a month against 1.3 forecast. |
| H2 n at 21 / 42 / expiry (L26-28) | about 8 / 7 / 5 | 7 / 7 / 4 | Right |
| H2 97.5% half-width at 21 / 42 (L26-27) | about 0.014 / 0.021 | 0.048 / 0.049 | **Wrong**, 2.4 to 3.4 times wider. Scaling by √n understated the OOS variance. |
| H1 verdict (L30) | NULL | INSUFFICIENT (computed NULL) | **Wrong label.** The cause is n, as the FORECAST's own INSUFFICIENT rule defines it. |
| H2 verdict (L30) | NULL | NULL | Right |
| Either passes (L30) | under 5% | neither passed | Right |
| H2 expiry (L28) | no interval likely | 4 events, no interval | Right |
| Sign #1: H2 edge positive at 21 and 42 (p 0.60) | positive | −0.0215, −0.0138 | **Wrong**, at both horizons |
| Sign #2: H1 R at 42 above placebo (p 0.60) | above | not scorable (n = 3 < 5). The descriptive point is 0.61 vs 0.92, the other way. | Not scorable |
| Sign #3: H1 R at 1 session below placebo (p 0.65) | below | not scorable (n = 3). The descriptive point is 1.86 vs 0.93, the other way. | Not scorable |
| Sign #4: clustered CIs wider than iid (p 0.80) | wider | not computed; the OOS run predates the clustered bootstrap | Not scorable |
| Sealed window (L37-44) | INSUFFICIENT at 3 months | not run | Pending |

**Score:**
- Verdicts: 3 of 4 right. Event counts: right for H2, wrong for H1. Signs: the one scorable sign was wrong.
- The H2 parity ratio (not a forecast item) was also opposite to H2's premise at 21 and 42 sessions (+0.468 and +0.272 above placebo), and in the predicted direction at expiry (−0.319).

## 6. Message to Jacob (paste-ready)

> Jacob, Theo picked story A for the main track: evidence-gated 24/7 hedging. Your 8-K write-up stays as pages 1-2, as the rigorous "what didn't work". I left a full diff of your WRITEUP and PITCH against the committed results in `note/RECONCILE.md`. The OOS numbers to fill are in section 1, and the 8-K claims that have to be scoped are in section 3. Can you also run a subagent-based research pass on the thesis tonight? Run one subagent per open question:
>
> 1. A fresh-sample test of the staged 09:30 hedge (R1 hedge B).
> 2. The expected gap on US macro markets only.
> 3. A futures and pre-market SPY benchmark for the closure move.
> 4. An adversarial reviewer that tries to break every number in `research/EVIDENCE.md`.
>
> Same rules as today: each subagent commits a METHOD.md before it fetches any data, runs once, and logs to RUN_LOG. Anything without a committed method is labelled exploratory. Do not re-run the 8-K OOS (`oos/.done`). Pitch is Sunday, while the market is closed. Webull paper rejects orders outside 09:30-16:00 ET (HTTP 417), so the demo shows staged orders, not fills.
