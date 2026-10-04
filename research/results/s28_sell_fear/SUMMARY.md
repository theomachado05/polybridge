# S28 (H3): sell the put after bad-news filings when fear is high

Method committed `f9468bf` (05:16:05) before the high-fear filter touched any window. Run once on the three windows we have.

| Window | Scope | Verdict | 21 sessions | 42 sessions | Sharpe at 21, events vs ordinary days |
|---|---|---|---|---|---|
| 2022 (discovery) | high fear, 7 events | PASS shape | +2.17% [+0.28, +3.83] | +2.63% [+0.37, +4.88] | 3.56 vs 0.29 |
| 2022 (discovery) | all H1, 12 events | PASS shape | +1.73% [+0.33, +3.11] | +2.25% [+0.51, +4.06] | 3.34 vs 0.11 |
| 2024-25 (seen) | high fear, 8 events | NULL | −1.38% [−5.61, +2.02] | −2.12% [−7.27, +2.37] | −0.07 vs 0.69 |
| 2024-25 (seen) | all H1, 33 events | NULL | +0.03% [−1.17, +1.12] | −0.18% [−1.76, +1.43] | 0.57 vs 0.51 |
| 2026 (seen) | high fear / all | INSUFFICIENT | 1 and 3 events | | |

2022 formed the hypothesis, so its PASS is not evidence. The stock-level fear filter did not carry to 2024-25: high-fear
filings in a calm market did not rebound (−1.38% at 21 sessions on 8 events). What separated 2022 looks like market-wide
stress, not a stock's own implied move, and that condition has not been defined or tested. The judges' sealed window is
H3's first confirmatory test; no further condition is added here.
