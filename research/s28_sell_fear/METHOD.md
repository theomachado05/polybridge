# S28 (H3): sell the put after bad-news filings when fear is high

Committed at the time of this commit, after the discovery check below and before the high-fear filter is applied to any
window, and before any sealed window is run.

## Where H3 comes from (discovery, 2022, already seen)
S27 ran the frozen study on 2022. Decomposing H1's protective put showed that after bad-news 8-Ks the stocks rose 6.1% in
21 sessions against 0.6% on ordinary days, while the bought put lost 1.8%: the headline was oversold and the put dear.
The trade that is paid by both is to SELL the put. Discovery check on 2022 (12 H1 events), cash-secured put, edge over
ordinary days: +1.73% at 21 sessions [+0.33, +3.11], +2.25% at 42 [+0.51, +4.06], −1.42% at expiry [−8.00, +3.90];
Sharpe at 21 sessions 3.34 against 0.11 on ordinary days. On 2024-25 (seen, calm) the same trade was flat: +0.03% at 21.
These numbers formed the hypothesis; they are not evidence for it.

## H3
After an H1 filing (the 7 frozen tags: material litigation, class actions, regulatory investigations, cyber incidents,
goodwill, asset and investment impairments), when fear is high, sell the 5%-out-of-the-money 3-6-month put at the close of
the session after the filing (conservative timing), cash-secured, and hold it. Mechanism: after bad news in a fearful
market, holders overpay for puts and the stock is oversold; the seller collects both.

**High fear (fixed now, from 2022 alone):** the event's implied move to expiry at entry (ATM straddle ÷ spot, the
starter's measure, known at entry) is at least 14%, about 2022's average for these events (14.6%). Ordinary days are
filtered the same way.

## Test and pass rule (same shape as the frozen study)
Edge = cash-secured put on high-fear H1 events minus the same trade on high-fear ordinary days of the same companies.
PASS if the 97.5% interval lies above zero at 2 or more of 21 sessions, 42 sessions and expiry. Fewer than 2 testable
horizons (5 events and 5 ordinary days each) is INSUFFICIENT. Unfiltered H3 (all H1 events) is reported as secondary.

## Where it is tested
- **Confirmatory: the judges' sealed window**, run by the notebook's sealed-window cell. Forecast: a calm window gives few
  high-fear events (INSUFFICIENT or NULL); a stressed window should show the edge at 21 and 42 sessions.
- Reported regardless, not confirmatory: 2024-25 and 2026 (seen data) with the filter applied.
