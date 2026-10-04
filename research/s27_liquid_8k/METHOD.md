# S27: the pre-registered 8-K hypotheses on liquid option names, on 2022 (never used)

Committed before any 2022 option price or 8-K event is pulled by this study (a 2-minute data check fetched one AAPL
chain, its bars and the 2022 restructuring-plan filing count only). The judges' sealed window may fall in 2023, so 2022
is used. Nothing in 2022 has been looked at by any study.

## What is fixed (unchanged from HYPOTHESIS.md / HYPOTHESIS_TAGS.md)
H1 (protective put) and H2 (cash-secured put), the 11 tags, the cross-family exclusion, conservative timing, the
3-6-month bucket, 5% OTM, entry "post", the 120-day placebo per family and the pass rule: the 97.5% interval of the
event-minus-placebo P&L edge above zero at 2 or more of 21 sessions, 42 sessions and expiry, with the parity ratio moving
the predicted way there.

## What is new: the liquidity filter (known before entry, independent of any outcome)
Liquidity of an event or placebo day = volume of its ATM call plus ATM put (3-6m bucket) on the pre-event session t_pre.
**Liquid** = in the top 20% of that measure among all priced events and placebo days of the same family in the window.
The filter is applied to events and placebo days alike.

## Analyses, all reported
- **Primary:** H1 and H2 on liquid events against liquid placebo days, 2022, pass rule as above.
- **Secondary:** H1 and H2 on all 2022 events (a fresh replication of the frozen study).
- Sharpe (gross, 21 sessions, per-trade, annualized by the window's trade rate) for every row.
