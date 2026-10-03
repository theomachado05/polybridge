# Closed-market mode: stocks close, prediction markets don't

Plan for Sat 2026-10-03 12:30 ET to Sun 10:00 ET. Approved by Theo at about 12:30.
It builds on spec v4 (`docs/superpowers/specs/2026-10-03-polybridge-v4-design.md`) and on the research finding: across 380 unselected closures, the prediction-market move while equities are closed predicted the SPY open gap (+7.52 bp per point, HC3 t 2.58, permutation p 0.001).

## Product behaviour

While US equities are closed (overnight, weekend, holiday) and the prediction market trades:

1. **Session clock.** Classify every moment as regular, pre-market, after-hours, overnight, weekend or holiday, using the NYSE calendar including early closes.
   - Replays use the tick's own time, so a replayed Saturday behaves like a Saturday.
2. **Closure tracker.** Track the PM move since the last regular close.
3. **Expected open gap.** Expected gap = rate × PM move (in points).
   - The rate is per market, estimated from that market's own past closures. If there are too few, use the pooled rate with a wide band.
   - Always show the band and the number of closures behind it.
4. **Hedge A: 24/7 PM hedge.** Hedge with the prediction-market contract itself: buy the adverse YES, sized to offset the expected equity loss.
   - Fills are simulated (no Polymarket trading account); the label says so.
   - **Handoff at the open:** unwind the PM leg and move the hedge into the equity.
5. **Hedge B: staged session orders.** Equity hedge orders queued for the next tradable session.
   - Pre-market at 4:00 ET if the broker supports extended hours (checked against the Webull docs and the key); otherwise the 09:30 open.
   - The user approves the staged plan before it can execute.
   - Orders are cancelled or resized if the PM reverts.
6. **Opportunity at the open (options).**
   - At Friday's close, snapshot the option-implied probability for threshold markets.
   - At the Monday open, compare it with the PM probability. If options have not caught up, stage an option trade for 09:30 (simulated fills).
   - This is shown only where the research below supports it, and labelled as an estimate otherwise.
7. **Safety stays the same:**
   - Nothing runs without approval.
   - Coverage caps apply across PM and equity legs combined.
   - Every decision has a reason code.

## Research (pre-registered: each METHOD.md is committed before any data is fetched)

| ID | Question | Primary test | Success criterion (fixed before data) |
|---|---|---|---|
| R1 | Does closed-market hedging reduce the loss at the open? | Over every closure in the 380-closure panel plus the replication panel: equity P&L at the open with hedge A, hedge B, no hedge, and a static-size control | Variance of the open-gap P&L lower with A/B than with no hedge and than with the static control; bootstrap CI excludes 0 |
| R2 | Is the expected-gap model accurate out of sample? | Per-market rate fitted on earlier closures, tested on later ones | Out-of-sample sign accuracy > 50% (binomial p < 0.05) and slope of realized on predicted > 0 |
| R3 | Do options catch up at the Monday open? | Friday-close option-implied probability vs weekend PM move vs Monday-open option-implied probability, on threshold markets with listed options | Monday-open option repricing explains less than all of the PM move (a gap remains), CI reported. A null means no Opportunity claim |

Already running (from the reframe wave): the overnight-gap replication on new markets, the walk-forward fit test, and the single 8-K OOS run.

## Platform tasks

| ID | Task | Area |
|---|---|---|
| P1 | Session clock + closure tracker + expected-gap service + API fields (bridge summary `session`, `closure`, `expected_gap`) | backend |
| P2 | C++ family `closed_session_hedge` (hedge A sizing on the PredYes leg; handoff at the open) + a test that it does not allocate + a bench entry | engine |
| P3 | Staged-order book: model, approve and cancel endpoints, execution at session start through the broker, extended-hours flag, revert/resize rule | backend |
| P4 | Opportunity at the open: Friday option snapshot store, Monday comparison, staged option trade | backend/options |
| P5 | Wire P1–P4 into bridges, with replay on tick time and a recorded weekend replay for the demo (a real weekend with a large PM move) | backend |
| W1 | Webull key arrives → live sandbox smoke test: account, positions, place and cancel an equity order, extended-hours support, options support | backend/broker |

## UI tasks (in the design's language)

| ID | Task |
|---|---|
| U1 | Bridge: closed-market state ("Market closed · reopens Mon 09:30 ET / pre-market 04:00"), session pill in the nav |
| U2 | Weekend panel: PM move since close, expected gap with band and n closures, hedge A position, staged orders list with an Approve plan button, handoff timeline |
| U3 | Portfolio: weekend exposure per holding (expected gap × position), hedged vs unhedged |
| U4 | Build: "Weekend mode" when the market is closed, with copy explaining why the PM leg is used |
| U5 | Opportunity at open card (only when R3 or the live data supports it) |

## Timeline

| Time (ET) | Research | Platform | UI | Theo |
|---|---|---|---|---|
| 12:30–15:00 | R1–R3 pre-registered and run; replication, walk-forward and 8-K OOS finish | P1 + P2 + P3 + P4 in parallel; W1 when the key lands | — | Webull key, other keys, try `make dev` |
| 15:00–17:00 | Write-ups | P5 integration + weekend replay | U1–U5 | Review the story; partner starts the note |
| 17:00 | Check-in: results, merge to main | | | |
| 17:00–21:00 | Notebook section for the closed-market tests | e2e weekend scenario; whole-branch review and fixes | Polish | Rehearse with a timer |
| Sun 08:00–10:00 | — | Wi-Fi-off rehearsal | — | Devpost submit by 10:00 |
