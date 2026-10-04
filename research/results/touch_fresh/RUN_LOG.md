# touch_fresh run log (times New York)

- 01:47 worktree `r/touch-fresh` from origin/main (3c1a88a). Catalogue scan of closed `hit-price` events (metadata only, `outcomePrices` dropped).
- 01:54 pre-registration committed (`e236e24`): METHOD.md, config.py, universe.py, universe.json. Metadata count: 32 markets in 4 events under S21's eligibility rules (INSUFFICIENT against 30 on 15); 142 markets in 85 events in sample R (no event floor).
- 01:55 pull started (`touch_fresh.pull`): data API prints and gamma results per market, Massive option legs, underlying NBBO and daily bars. One worker, at most 2 Massive requests a second.
- 01:58 forward protocol committed (`dcffa67`) while the pull ran, before any result was read.
- 02:03 pull finished: 852 Massive requests in 459 s, 0 errors. Anchored 141 of 142 (1: no usable pair of leg quotes). The recorder log is not present in this worktree (count -1).
- 02:04 pull and run code committed (`a47d08f`); `touch_fresh.run` run once. No rule, threshold or sample changed after it.
- Data gaps found after the run, not repaired: 2026-06-19 (Juneteenth) is a market holiday and S21's parser takes it as the window's last session for the "Week of June 15" events, so the daily close is missing for 2 markets (both in B0); their hedge exits at the level (both resolved YES) and they drop out of the exposure regression. 89 of 142 markets printed nothing in their first weekend (every print was served; no request failed).
