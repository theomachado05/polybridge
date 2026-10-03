# P2 options-anchored Polymarket taker: INSUFFICIENT

Verdict: **INSUFFICIENT**, so no claim either way. The pre-registered day-one kill test (METHOD.md section 7.1) stopped the run before the trade list was frozen. No outcome was ever fetched, so there is no P&L estimate, no CI and no sign.

## What the kill test saw (prices only)

| quantity | value |
|---|---|
| frozen universe | 2,617 markets, 86 resolution days, 449 ticker-days (`universe.csv`, sha256 `7f9bc214...`) |
| kill window | resolution dates 2026-01-20 to 2026-02-09: 135 markets, 14 days |
| taker prints inside the trading windows | 202 raw, 189 after per-minute thinning, in 82 of 135 markets |
| evaluated prints | 110 (94 with a usable spread, 16 failing the 0.20 band or the [0.03, 0.97] range, 0 without a valid spread) |
| primary trades (tau = 0.05) | 4 |
| projected over the window | 77.5 trades (rule: at least 100) on 43 days (rule: at least 30) |
| share of prints without a valid spread | 0% (rule: at most 30%), so the option measurement works |

Median evaluated print size: 35 shares. Over the 94 usable prints, the signed gap (option p_mid minus the PM price, in the direction of a trade toward the options) has a median of -0.8 pt and an interquartile range of -4.2 to +1.1 pt. Only 5 prints reached the 5 pt threshold, 10 reached 3 pt and 1 reached 10 pt (`chart.png`). In this window the printed PM prices mostly sat at or inside the option band, so the stale quotes that were assumed are rare.

## Reading

The binding constraint was the number of prints, which was the main risk named in advance. Early-2026 daily markets traded little: about 1.5 taker prints per market in the window before resolution. Few of those prints were far from the options.

The design assumed SPY daily markets from January. In the frozen universe they start on 2026-04-21 (682 of the 2,617 markets). Before 2026-02-11 the megacaps list only Friday expiries. So the kill window held only Friday megacap markets, and the projection scales that window by market count. It cannot account for SPY markets or for any growth in trading later in the year. That is a limit of the pre-registered projection. It does not give grounds to rerun or rescue this test. The run stopped exactly as METHOD.md says.

Fresh data still unseen: the outcomes of all 2,617 markets, and every print and quote for resolution dates from 2026-02-10 to 2026-08-14. A follow-up would need its own pre-registration, with a kill window that matches the universe's composition, for example April to August, when SPY markets exist. It would be a new study, not this one.

## Files

`universe.csv` (frozen universe and expiries), `kill_test.json`, `prints_evaluated.csv` (kill-window prints with same-instant option probability, no outcomes), `stats.json`, `chart.png` (prices only), `RUN_LOG.md`, `.done`.
