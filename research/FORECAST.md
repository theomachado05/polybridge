# PolyBridge · Forecast for the out-of-sample and sealed windows

**Committed:** 2026-10-03, before the method freeze (13:00 ET) and before the out-of-sample window or any sealed
window was run. The git timestamp is the proof. Everything below is derived from the committed in-sample results
in `results/in_sample/` and from event rates; no 2026 or pre-2024 H1/H2 data was looked at.

## How the numbers are derived

- **Event rate.** In-sample (24 months), the events with a 21-session P&L were 32 for H1 and 24 for H2, so about
  **1.3 H1 events and 1.0 H2 event per month** reach the headline test.
- **Interval width.** A 97.5% interval narrows with the square root of the number of events. In-sample half-widths
  were 0.028 / 0.051 / 0.066 (H1 at 21, 42, expiry) and 0.008 / 0.011 / 0.014 (H2), so a window with n events has a
  half-width of about (in-sample half-width) × √(in-sample n ÷ n).
- **Minimum for a test.** The notebook needs 5 events and 5 placebo days for an interval. A hypothesis with fewer than
  2 testable headline horizons is reported as **INSUFFICIENT**, not NULL.

## Out-of-sample window, 2026-01-01 to 2026-08-31 (run once, after the freeze)

Exits are cut at the pinned last session (early October 2026), so later horizons lose the latest events.

| Family | Horizon | Expected n | Expected 97.5% half-width | Forecast |
|---|---|---|---|---|
| H1 hedge | 21 | about 11 | about 0.05 | NULL; no sign forecast (in-sample edge +0.0007) |
| H1 hedge | 42 | about 9 | about 0.09 | NULL |
| H1 hedge | expiry | about 6 | about 0.14 | NULL or no interval |
| H2 opportunity | 21 | about 8 | about 0.014 | NULL; edge positive |
| H2 opportunity | 42 | about 7 | about 0.021 | NULL; edge positive |
| H2 opportunity | expiry | about 5 | about 0.03 | no interval likely |

**Verdicts we expect:** H1 NULL, H2 NULL. The chance of either passing is below 5%: a pass needs an edge larger than
the half-widths above, and the in-sample edges were 0.001 to 0.009.

## Sealed window

We do not know the judges' window. The starter's default is 2023-06-01 to 2023-08-31 (3 months).

| Window length (months, all horizons resolved) | Expected n, H1 / H2 | Forecast verdict, H1 / H2 |
|---|---|---|
| 3 (starter default) | about 4 / 3 | INSUFFICIENT / INSUFFICIENT |
| 4 to 5 | about 5–7 / 4–5 | NULL or INSUFFICIENT / INSUFFICIENT |
| 6 to 12 | about 8–16 / 6–12 | NULL / NULL |
| over 12 | over 16 / over 12 | NULL / NULL |

A PASS on any sealed window would contradict this forecast, and we would report it as a surprise, not a confirmation.

## Signs we commit to

Each is a statement about the point estimate, with the probability we put on it. We will score these on every window
large enough to compute them.

| # | Statement | In-sample basis | Probability |
|---|---|---|---|
| 1 | H2 cash-secured-put edge over ordinary days is positive at 21 and 42 sessions | +0.0009, +0.0021; positive in all 18 sensitivity cells (correlated cells, not 18 pieces of evidence) | 0.60 |
| 2 | H1 parity ratio at 42 sessions is above the placebo's | +0.21 | 0.60 |
| 3 | H1 parity ratio one session after the filing is below the placebo's (the chain prices the first move generously) | events 0.68 vs placebo about 1.0 | 0.65 |
| 4 | Company-clustered intervals are wider than the iid ones at every headline horizon with n ≥ 5 | repeated filers in both families | 0.80 |

## What would make us wrong

- A regime with many more H1 filings (a litigation or cyber wave) raises n and could make an interval exclude zero.
- 2023 sits before the in-sample window; event mix and option liquidity may differ.
- The static `TOP_100` list includes companies that were not top-100 in 2023, which changes who files.
