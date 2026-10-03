# Recorded sessions (Wi-Fi-free demos)

## Demo recordings at a glance

| File | Market (Polymarket id) -> ticker | Rows, span | p range | Fit on this replay (engine, 1,000 shares) | Replay speed |
|---|---|---|---|---|---|
| `another-fed-hike-2026-history.jsonl` (**default demo**) | Another Fed rate hike in 2026? (4620900) -> TLT, down on YES | 401 hourly, 2026-09-16 19:00Z to 2026-10-03 11:33Z | 0.705 to 0.92 | equity_delta_bridge #75, score_vs_static +0.257 (engine replay: 17 sends, 4 fills; a bridge trading at any hour: 4 orders, 3 at a 50% cap; with closed-market mode, the default: 3 and 3) | 21600x, about 67 s |
| `russia-eu-military-2026-history.jsonl` | Russia military action against an EU country by December 31, 2026? (4713962) -> ITA, up on YES | 347 hourly, 2026-09-19 01:00Z to 2026-10-03 11:33Z | 0.065 to 0.285 (opening print 0.485) | energy_geo_hedge #54, score_vs_static +0.508 (engine replay: 136 sends, 8 fills; a bridge trading at any hour: 31 orders, 17 at a 50% cap; with closed-market mode, the default: 9 and 5) | 18000x, about 69 s |
| `fed-hike-25bps-oct-2026-history.jsonl` | Will the Fed increase interest rates by 25 bps after the October 2026 meeting? (2589813) -> IWM | 721 hourly, 2026-09-02 to 2026-10-03 | 0.155 to 0.705 | IWM: equity_delta_bridge #15, score_vs_static -0.011 (no better than a static hedge; fits.json scores SPY at -0.004) | 36000x, about 72 s |
| `fed-hike-25bps-oct-2026.jsonl` | same Fed October market | 1200 one-second polls, 20 min | constant 0.175 | (quiet: one initial hedge) | real time |
| `us-recession-in-2025-weekend-2025-04-04.jsonl` (**closed-market mode**) | US recession in 2025? (516710, the one market whose expected-gap model is validated out of sample) -> SPY, down on YES | 799 five-minute points, Fri 2025-04-04 15:30 ET to Mon 2025-04-07 10:00 ET | 0.555 at the Friday close, 0.675 at the weekend high, 0.635 at the open | no fit (a resolved market); a bridge holds its equity algo for the 786 closed ticks, stages hedge B from the validated expected gap (peak -128.8 bp), and fills it at the first fresh pre-market print (Mon 04:05 ET, 488.45) | 3600x, about 67 s |
| `nvda-230-sep-2026-history.jsonl` (**Opportunity division**) | Will NVIDIA (NVDA) close above $230 end of September? (3961215, resolved NO) -> NVDA call spread 227.5/232.5, expiry 2026-09-30 | 353 hourly, 2026-09-16 04:00Z to 2026-09-30 20:00Z; 66 carry an options estimate | 0.005 to 0.76 (options-implied 0.11 to 0.71) | opportunity fit: binary_vs_spread_arb #6, score -0.956 (11 orders, -$276.15 net of fees, max drawdown $288.95: it loses money here); a bridge: the same 11 orders at recorded leg closes + a bridge-end close at the expiry settlement, -$294.77 | 21600x, about 59 s |

The two new files (recorded 2026-10-03 with `scripts/history_with_equity.py`) carry `{"ts_ns", "p", "under_px"}` per
row: `p` is the CLOB `prices-history` mid (hourly, `interval=1m&fidelity=60`; spread and depth unknown, never
invented) and `under_px` is the Massive hourly close of the last bar that had already ended at that time (no
look-ahead). Their YES token ids are in the `.meta.json` sidecars; `app/data/replay_index.json` points the fit's
offline fallback at them, and `app/data/equity_bars/TLT.json` / `ITA.json` hold the same bars for an offline fit.
"Fit on this replay" is `POST /pipeline/fit` with no network (ticks from the recording): the same pick and score as
`app/data/fits.json`. It is in-sample (tuned and scored on this history, the best of many presets), and these two
markets were chosen for the demo because they score near the top of the 122 scored markets (most add little: median
+0.0053, 36 at or below 0; see `docs/demo.md` section 5). A bridge on the replay makes
the same decisions as the engine for the same preset and the same fills (tick by tick, pinned for the default demo in
`tests/test_bridge_replay_parity.py`); only the order counts differ, because of the fill model. The engine replay's
order count is every send, and its fill model refuses an equity fill at a stale recorded close (outside regular hours,
or in a session before the price has changed), so the algo re-sends the same order on the next tick until a fill is
allowed: the TLT replay's 17 orders are 4 fills + 13 refused sends (11 = 2 + 9 at a 50% cap), ITA's 136 are 8 + 128
(101 = 4 + 97 at 50%). The bridge's SimBroker fills each market order at today's Massive quote (or the recorded price
offline) whenever it arrives, so every order fills once: 4 for TLT, 31 for ITA with no coverage cap, 3 and 17 at a 50%
cap (our 2026-10-03 runs, and what `Algo` decides on the same ticks when every order fills). Those counts are for a
bridge with `"session_hold": false`. By default a bridge now runs closed-market mode (`app/closed/bridge_mode.py`): its
equity algo is paused whenever the recorded time is outside the regular session (328 of TLT's 401 hourly ticks, 287 of
ITA's 347), so it trades only in regular hours: TLT 3 orders uncapped and 3 at a 50% cap (hedge 540 and 360 shares),
ITA 9 and 5 (885 and 438; 5 at 500 shares uncapped). No staged order is planned on them: their hourly points leave
no PM price within 30 minutes before the 16:00 close (the closure tracker's research anchor rule), so the tracker
reports NO_CLOSE_PRICE and no expected gap is shown (and their markets have no validated out-of-sample record: any gap
would be an unvalidated estimate). The closed-market recording below has 5-minute points for that reason. After the first refused
send the two hedge paths differ, so the in-sample score describes the engine replay's (session-respecting) fills, not
the bridge's. See `docs/contracts.md` ("Bridge vs engine replay").

    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py \
        --market another-fed-hike-2026=4620900 --equity TLT --out replays/another-fed-hike-2026-history.jsonl
    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py \
        --market russia-eu-military-2026=4713962 --equity ITA --out replays/russia-eu-military-2026-history.jsonl
    cd backend && uv run --env-file ../.env python scripts/record_equity_bars.py ITA --replay russia-eu-military-2026-history.jsonl

## nvda-230-sep-2026-history.jsonl (the Opportunity division)

"Will NVIDIA (NVDA) close above $230 end of September?" (Polymarket 3961215, about $6,000 traded, resolved NO: NVDA
closed at 228.38 on 2026-09-30, its official close). Recorded 2026-10-03 with options-implied history, so the Opportunity division
(`binary_vs_spread_arb`) can be fitted and bridged on a replay, offline:

    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py --options --since 2026-09-16 \
        --market nvda-230-sep-2026=3961215 --equity NVDA --out replays/nvda-230-sep-2026-history.jsonl

Each row is `{"ts_ns", "p", "under_px"}` (as for the files above: CLOB hourly mid, NVDA hourly close of the last
finished bar), plus, on 66 of the 353 rows, `opt_mid`, `opt_implied_prob`, `opt_iv` and `opt_legs`, and on the last
row the expiry settlement:

- **Structure** (sidecar `options`): the YES-equivalent call spread C(227.5) - C(232.5) at the 2026-09-30 expiry
  (`O:NVDA260930C00227500` long, `O:NVDA260930C00232500` short), chosen from Massive's contract listing as it stood
  on 2026-09-16, the replay's first day (point in time: Massive's `as_of`, so contracts listed later, whose strikes
  follow the later price path, are not candidates): the listed expiry nearest the resolution date and the tightest
  listed strikes around $230. No price is read to choose it.
- **Values**: the two legs' Massive hourly bar closes (77 and 79 bars; the Sep 30 contracts trade from Sep 16),
  each joined as of its bar END (no look-ahead), through `app.pipeline.options_join.option_columns`, the fit's own
  builder. `opt_mid` = the spread close-to-close, `opt_implied_prob` = `opt_mid / 5 / DF` (digital approximation),
  `opt_iv` = Black-Scholes inversion of the leg closes against NVDA's bar closes (paired within one bar interval),
  `opt_legs` = each leg's close (what a replay bridge prices the legs at). All are estimates from bar closes, not
  quotes.
- **Fresh-close rule** (the engine's rule for equity fills, applied to the option legs): option fields only inside
  the regular session (09:30-16:00 New York, trading days) and once both legs have printed that day, and only where
  the two legs closed within one bar interval of each other. 277 synced but off-session or stale hours were dropped;
  nights and weekends carry no estimate (NaN on replay), so no order is filled at a stale close. A bridge's end close
  is priced at the last recorded legs only when they are at most one bar older than the end of the replay; otherwise
  it is a rejected fill and the structure stays open in the summary.
- **Expiry settlement** (the last row, 16:00:20 New York on 2026-09-30, after the close): `opt_legs` = each leg's
  intrinsic value at NVDA's official close (Massive `/v1/open-close`, 228.38): C(227.5) = 0.88, C(232.5) = 0, so
  `opt_mid` = 0.88, with `opt_settlement` naming the close and its source. No `opt_implied_prob` / `opt_iv` there (a
  settlement value is not a quote, so no family opens a trade on it). The engine marks an open spread to it and a
  replay bridge closes at it (no spread, the simulator's per-contract fee). Without it the spread bought at 15:00 that
  day (mid 2.91) was marked (engine) and closed (bridge) at its 15:00 closes, hiding about $200 of loss.
- `--since 2026-09-16` drops the 303 rows before that day (the market opened 2026-08-28; the Sep 30 contracts trade
  from Sep 16) before the structure is chosen, so the listing is read as of the replay's first day. No 8-K data was
  fetched.

On this market the PM and the options agree closely: the median gap is under a point and the largest, on expiry day,
is 11.6 points. Fit (`POST /pipeline/fit`, division opportunity, NVDA, offline or online: online, the live history
has no option history because the contracts expired, so the fit replays this recording and says so): the top
opportunity pick is `no_bid_seller` #3 at +11.149, a prediction-market-only family whose replay sells NO at the
recorded mid (the spread is unknown, so its fills are optimistic) and which never runs on a bridge; the options
family is `binary_vs_spread_arb` #6 (entry gap 0.03, exit 0.02, 1 spread) at **-0.956**: 11 orders, -$276.15 net of
fees against a $288.95 max drawdown (#9, entry gap 0.05: 3 orders, all on expiry day, -$241.95, -0.959). In-sample
and best of 36 presets, and still negative: the demo shows the mechanism, not alpha. Most of the loss is the last
spread, bought at 15:00 on expiry day and worth 0.88 at the close. An approved proposal + `POST /bridges` on this
replay places the same 11 orders, each a two-leg combo filled by the SimBroker at the recorded closes +/- 2% (the real
spread is unknown), $0.65 per leg contract, and closes the last spread at the expiry settlement: -$294.77 over the six
round trips (#9: -$249.75; our 2026-10-03 run, pinned in `tests/test_opportunity_replay.py`;
`python3 scripts/e2e_demo.py --opportunity` drives it over HTTP).

## us-recession-in-2025-weekend-2025-04-04.jsonl (closed-market mode)

One real weekend for the closed-market demo, picked by a fixed rule (`scripts/record_weekend.py`; no price was looked
at to choose): among the markets `app/data/gap_evidence.json` marks validated (R2: the market's own out-of-sample
record passes; only "US recession in 2025", sign 64.2% of 151, slope +1.28), its weekend closures in
`research/results/leadlag_closed/closures_all.csv`, the largest adverse (equity-bearish) PM move: 2025-04-04 to
2025-04-07, YES 55.5 -> 63.5 at the research marks, SPY gap -322.7 bp, then +132.9 bp from 09:30 to 10:00 (the
"Liberation Day" tariff weekend; a hand-picked news closure in the research table, so it is not one of the closures R2
tested the rate on).

    cd backend && uv run --env-file ../.env python scripts/record_weekend.py

Each row is `{"ts_ns", "p", "under_px"}`: `p` is the CLOB `prices-history` mid at 5-minute fidelity over the window
(`startTs`/`endTs`), `under_px` the close of the last 5-minute Massive SPY bar that had already ended (extended hours
included; over the weekend it stays at Friday's last after-hours print, 505.50). The sidecar carries the rule and the
research row of the weekend (`weekend`). `app/data/replay_index.json` maps `polymarket:516710` and its YES token here.

What a bridge shows on it (`tests/test_closed_bridge.py`, `python3 scripts/e2e_demo.py --weekend`): Friday 16:00 the
session closes and the equity algo holds (786 of 799 ticks); the closure tracker follows the PM move since the close and
the expected gap is **validated** (own rate 10.73 bp/pp on 231 closures, 80% band; -128.8 bp at the weekend high); a
staged sell (hedge B) is planned, resized with the gap, and approved; the sandbox broker supports extended hours, so it
executes at the first fresh recorded price, Monday 04:05 ET pre-market (04:00 still shows Friday's 505.50); the
algo resumes at 09:30. With equity_delta_bridge (sigma_k 0) at 1,000 shares and a 50% cap: 278 shares hedged on Friday
afternoon carry over the weekend, the plan sells the remaining 222 at 488.45, and at the open the algo buys 182 back.
P&L from the Friday close (506.56) to Monday 10:00 (495.69), recorded prices: holding -$10,870; carried hedge
+$3,022; staged order -$1,607 (SPY rallied after the open: hedge B works by timing, not direction, and executes after
the gap); algo after the open +$1,179; hedged -$8,276, i.e. +$2,594 vs no hedge (the e2e prints the run's own
numbers). The demo shows the mechanism on one weekend; it is not evidence.

## fed-hike-25bps-oct-2026.jsonl

- Market: "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?" (Polymarket, resolved via gamma search)
- YES token id: `55159722761418013044126414276680602270318000841690689684819994448621694923050`
- Recorded: 2026-10-03 05:25:12Z to 05:45:11Z UTC (20 minutes), CLOB midpoint polled every 1 s
- Rows: 1200 ticks, 0 failed polls, one `{"ts_ns", "p"}` JSON object per line (51 KB)
- Note: the market was quiet during the window (midpoint constant at 0.175), so hedgecore sizes one initial hedge and then holds.

## fed-hike-25bps-oct-2026-history.jsonl (the previous default; now an alternative)

Historical replay (real Polymarket price history, time-compressed at replay). Same market and YES token as above.
721 hourly points (about 30 days, 2026-09-02 to 2026-10-03) from `clob.polymarket.com/prices-history`
(`interval=1w&fidelity=1` is rejected by the API, so the script falls back to `interval=1m&fidelity=60`).
p ranges 0.155 to 0.705 (the largest range among the Fed October 2026, Iran, and Russia/EU candidates checked;
tied with the "no change" market at 0.55). Regenerate:

    cd backend && uv run python scripts/history_to_replay.py --token-id <YES token id> --out replays/<slug>-history.jsonl

Setting: replay at 36000x (ten ticks per second, about 72 seconds for the month), via `POLYBRIDGE_REPLAY_SPEED=36000`.
(The default demo, `another-fed-hike-2026-history.jsonl`, plays at 21600x: six hourly points per second.)
This is safe because staleness is judged on the wall clock (ticks are stamped at delivery), not on the recorded 1 h gaps
(tested in `tests/test_bridges.py::test_high_speed_replay_of_hourly_history_is_never_stale`). Replayed ticks are stamped
with the current time, preserving spacing divided by the speed.

## Record another

    cd backend && uv run python scripts/record_ticks.py --token-id <YES token id> --out replays/<slug>.jsonl --minutes 20

Failed polls are skipped. Find a token id via `GET /markets/search?q=...` (`token_id` field).

## Replay

    POLYBRIDGE_REPLAY_PATH=replays/another-fed-hike-2026-history.jsonl POLYBRIDGE_REPLAY_SPEED=21600 uv run --group engine uvicorn app.main:app
    # approve a hedge proposal, then:
    curl -X POST localhost:8000/bridges -H 'content-type: application/json' \
      -d '{"proposal_id":"<id>","source":"replay","market":{"source":"polymarket","id":"4620900"},"gap_per_share":1.0}'
    curl -N localhost:8000/bridges/<bridge_id>/stream

Each recording has a sidecar `<file>.meta.json` (`{"source", "id", "token_id"}`) naming the market it records: both
Fed October files record `polymarket:2589813`, `another-fed-hike-2026-history.jsonl` records `polymarket:4620900` and
`russia-eu-military-2026-history.jsonl` records `polymarket:4713962`. A replay bridge for another market answers 422 instead of replaying this
history under that market's title. A file with no sidecar (market unknown) is replayed only when the request names it
(`"replay_file": "<file name>"`, or a market id equal to the file's stem). Add a sidecar next to any new recording.

Without `POLYBRIDGE_REPLAY_PATH`, `source: "replay"` looks for `replays/<market.id>.jsonl`. The same variable is the automatic
fallback when a live bridge loses its network connection. With the 1 s recording, leave `POLYBRIDGE_REPLAY_SPEED` unset (real time).
