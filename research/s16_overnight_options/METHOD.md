# S16: after a big overnight move in the odds, are options on the linked asset mispriced in the first minutes of the session? (pre-registered)

**Question (Theo's).** Prediction markets trade all night. Listed options do not: they stop at 16:00 and reopen at
09:30. Nine studies show that the linked stock or ETF opens where the odds moved overnight, and that the stock does
not keep moving after the open. No study has looked at the **options** on those linked assets after the open. The
hypothesis: it is impossible that the whole overnight move is perfectly priced into the options in the first moments
of the session. This study tests whether those options are mispriced in the first minutes after a big overnight odds
move, and how fast they finish repricing.

This file and `config.py` are committed **before any option quote is pulled for S16**. Every rule is fixed. Changes go
under "Amendments", dated. The run is reported whatever it shows. Written Sat 2026-10-03, about 23:55 New York time.

## 0. What was known before this commit

- **S4, S5, S14** (`results/s4_linked_assets`, `s5_big_moves`, `s14_link_ceiling`): the linked stock opens where the
  odds moved overnight (+6.88 bp per point of odds, t = 6.01; +137 bp after moves of 10+ points). The gap is complete
  at the open and at 08:00 pre-market. After the open: −0.55 bp per point (t = −0.74). S14: this holds under four
  definitions of the signal and under the most favourable choice of links (hindsight-picked links: −2.04 bp per point
  out-of-sample, t = −0.59). S4 and S5 traded **shares** only.
- **S7** (`results/s7_weekend_straddle`): Friday straddles (a call and a put at the same strike: gains from a large
  move in either direction) on tickers with a live event lost 17.7% of the premium, the same as ordinary weekends
  (−17.6%); mid to mid −1.0% against −2.0%. Options were not cheap on Friday.
- **R3** (`results/open_options`): on megacap and SPY threshold markets, by 09:45 options had repriced 0.44 of
  Polymarket's closure move and did not move further toward it afterwards (−0.59 point [−2.43, +0.88], n = 1,123).
  The first 15 minutes, and the linked-asset universe, were never tested.
- **S8** (`results/s8_open_referee`): after an overnight move of 10+ points the odds themselves give back 2.63 points.
- **Counts made from odds and the calendar only, no option price** (this session and the coordinating session):
  `results/s8_open_referee/mornings.csv` has 667 market-mornings with an overnight move of 5+ points; 233 with 10+
  points on 109 dates. Expanded to one row per ticker and day: **300 ticker-days at 10+ points** on 109 dates and 30
  tickers (118 after a weekend or holiday; USO 54, XLE 53, XOP 17); 808 at 5+ points on 200 dates. The most recent
  20% of the 109 main dates start on **2026-06-22** (22 dates, 54 ticker-days before any drop). Brazil: 13 mornings
  with a 5+ point move in the three first-round questions (12 of them in "Flávio Bolsonaro second place"). Fed
  questions (35 of them): 88 market-mornings of 5+ points on 62 dates.
- **Not seen by anyone:** any option price for any of these mornings, and the option spread in the first minutes.

## 1. Events

- **Main sample.** Every row of `mornings.csv` with |x| ≥ 10, where x is the overnight move in the odds in points
  (previous close 16:00 to 09:29, New York time). The signed ticker list is expanded to one observation per (ticker,
  day). If several questions hit one ticker on one day, the one with the largest |x| is kept (ties: lowest market id).
  **Direction** for the ticker = sign(x) × the ticker's sign in the link (+1: the asset should open up).
- A ticker-day is dropped, and counted by reason, when: no five-minute bar starts within 10 minutes of 09:30; no call
  is listed with an expiry in the window of section 3; or one of the four primary quotes (call and put at 09:35 and at
  15:55) is not valid. When a primary quote is invalid no other instant is requested for that ticker-day.

## 2. Controls

For each event: the **same ticker**, a session within **30 trading days** (either side) that is quiet for that
ticker, the nearest in trading days (ties: the earlier one), each session used once per ticker (S7's matching; events
are served in date order). **Quiet** = no question linked to that ticker (`s8_open_referee.run.links()`, plus the
case file's own questions for the case files) has an overnight move of 2 points or more, measured as in S8 from the
S5 and S4 one-minute odds caches (a reading older than 30 minutes is missing and counts as no move), and the session
is not an event day of that ticker at 5+ points. No new Polymarket data is pulled. The control uses the same contract
rules on its own day. Its "directional" option is the same side (call or put) as its event's.

## 3. Contracts

- **Expiry:** the nearest listed expiry at least 7 and at most 45 calendar days after the morning.
- **Strike:** the listed strike nearest the underlying's first regular-session price that day (the open of the
  five-minute bar that starts at 09:30, from the cached `eq_<TICKER>.npz`; XLF is not cached and its bars are pulled
  from Massive). Standard contracts only (100 shares).
- The same call and the same put are tracked all day.

## 4. Instants and quotes (New York time)

Previous session 15:55 (events only, to save requests); then 09:31, 09:35, 09:45, 10:00, 10:30 and 15:55.
The quote is the last NBBO at or before the instant (Massive `/v3/quotes`). It is valid only if bid > 0 and
ask ≥ bid, and: for a morning instant, stamped at or after 09:30:00 that day and at most 15 minutes old; for a 15:55
instant, at most 10 minutes old (S7's two limits). Bid, ask, sizes and the quote's time are stored for every instant.
**The spread at every instant, as a share of the mid premium, is a result in its own right** and is reported for
events and controls.

## 5. The three hypotheses, each with its own pass/fail line

| | Trade | Says |
|---|---|---|
| **H-dir** | buy the option in the direction of the odds move (call if up, put if down) at the 09:35 ask, sell at the 15:55 bid | Theo's literal claim: the move is not fully priced at 09:35 |
| **H-slow** | buy the straddle at the 09:35 ask of each leg, sell at the 15:55 bid of each leg | options are too cheap at the open |
| **H-rich** | sell the straddle at the 09:35 bid of each leg, buy it back at the 15:55 ask of each leg | options over-react at the open |

- **Return** = P&L ÷ the entry premium at the price traded (the ask paid for a purchase, the bid received for a sale;
  for H-rich this is a return on premium, not on margin). Reported **mid to mid** (no cost) and **at real bid/ask**
  with $0.65 per contract per leg each way. **2× costs:** every half-spread and every commission doubled.
- For the two straddle hypotheses: **event minus matched control**, on pairs where both have valid quotes.
- **Pass** (per hypothesis, primary variant V0), all of: (a) at least 30 out-of-sample trades; (b) out-of-sample mean
  net return above zero at real bid/ask with a date-bootstrap 95% interval that excludes zero; (c) out-of-sample mean
  above zero at 2× costs; (d) in-sample mean net return above zero. Otherwise the summary says exactly which line
  failed, including "too few observations".
- For H-slow and H-rich the summary also says whether event minus control is above zero with an interval that
  excludes zero. A pass without that is a statement about buying or selling options at 09:35 in general, not about the
  odds move, and is labelled so.
- **A pass on one of three hypotheses is a lead that needs replication, not an edge.** H-slow and H-rich are mirror
  trades; at most one of them can pass.

## 6. Variants (the complete list; all reported for the three hypotheses)

| id | entry | exit | odds move | nights |
|---|---|---|---|---|
| **V0, primary** | 09:35 | 15:55 | 10+ | all |
| V1 | 09:31 | 15:55 | 10+ | all |
| V2 | 09:35 | 10:30 | 10+ | all |
| V3 | 09:35 | 15:55 | 5+ | all |
| V4 | 09:35 | 15:55 | 10+ | after a weekend or holiday only |

15 trials (3 hypotheses × 5 variants), each at mid, 1× and 2× costs.

## 7. The speed curve (the direct answer to "priced in the first second")

For event and control mornings: the mean **mid-to-mid** return of the straddle, and of the directional option, from
each of 09:31, 09:35, 09:45, 10:00 and 10:30 to 15:55, with date-bootstrap 95% intervals, and event minus control on
matched pairs. A chart of both. If options are fully priced at once, event minus control is about zero from every
instant. Also reported for events: the change of the straddle's and the directional option's mid from the previous
15:55 to 09:31 (how much of the repricing happened while the market was shut).

## 8. Split, accounting, inference

- **Out-of-sample** = the most recent 20% of the 109 main-sample event dates: sessions from **2026-06-22** (fixed
  from the odds, before any quote). The same date splits every variant and the controls (a control belongs to its
  event's segment). Nothing is fitted.
- **Intervals:** bootstrap over dates, 2,000 draws, seed 0 (several tickers on one date are one bet; a control is
  carried by its event's date).
- **Book:** each day's return is the mean return of that day's trades (equal premium in each); a session with no
  trade returns zero. Sharpe on daily returns over every session of the window, × √252; maximum drawdown and worst
  month on the cumulative sum; equity curve and drawdown for the three trades.
- **Costs** as a share of premium and in bp of the underlying's price, source: the quoted spreads themselves.
- **Capacity:** the size quoted at the entry price and the day's volume of each entry leg.
- A Sharpe above 3 starts a bug hunt before anything is reported: strike uses the 09:30 price only; entry quotes are
  stamped at or after 09:30 and at or before the entry instant; the exit is at the opposite side of the quote; put-call
  parity at 09:35 is checked against the underlying's 09:35 price to catch a wrong contract or a split.

## 9. Named case files (exploratory, reported separately; none of them is the test)

- **Brazil.** The three first-round questions in S4's cache (`polymarket:4037599` Lula most votes, EWZ sign −1;
  `polymarket:4037600` Flávio Bolsonaro most votes, +1; `polymarket:1365861` Flávio Bolsonaro second place, +1; signs
  are S4's proposer links, and one of S4's three critics gave the opposite sign for the third) against **EWZ** options,
  every morning with an overnight move of 5+ points, all instants, with controls. 13 mornings: too few for a verdict.
- **Oil.** The USO, XLE and XOP ticker-days of the main sample, broken out.
- **Fed and banks.** Every date on which a Fed question (question text matching `\bfed\b|interest rates` among the
  linked questions) moved 5+ points overnight: straddles only on **TLT, KRE and XLF**, 09:35 to 15:55, with controls
  that are quiet for the Fed questions and for the ticker's own links.
- **The 12 largest moves since 2026-07-01:** the 12 main-sample ticker-days from 2026-07-01 with the largest |x|
  (ties: earlier date, then ticker), with what the options did that morning.

## 10. The pull, and what happens if time runs out

Massive only. One worker, at most 2 requests a second, cached to `s16_overnight_options/.cache/` (one small line per
quote), resumable. No call to Polymarket or Kalshi. The count of `fetch failed` lines in `research/forward/recorder.log`
is read before the pull and every 50 requests; if it grows by more than 5 the pull drops to 1 request a second. The
recorder is never stopped, restarted or written next to.

The result is due at 02:30. The pull is ordered in tiers and **stops at 01:50 New York time whatever is done**:

1. main-sample events and their controls, all instants;
2. Brazil events and controls, all instants;
3. the day's volume of the two entry legs of each main-sample event with valid primary quotes (most recent first);
4. Fed-and-banks events and controls, the 09:35 and 15:55 quotes only (seeded random order);
5. the extra events of V3 (5 ≤ |x| < 10) and their controls, the 09:35 and 15:55 quotes only (seeded random order).

The verdict is given only if tier 1 is complete. A tier the stop cuts part-way is reported on what was pulled, with
its count, and labelled incomplete (the random order makes that a random subsample); a tier never reached is reported
as "not run". At 2 requests a second tier 1 alone is about 70 minutes, so tier 5 is not expected to finish.

If the option-quote endpoint does not serve these tickers or dates, the study stops and reports the exact error. No
modelled price is substituted for a quote.

## 11. Forward test (rules fixed now, not run tonight)

The market metadata on disk (`s4_linked_assets/.cache/pull_meta.json`, `s11_bundles/live_bundles.json`) gives the
three Brazil first-round questions an end date of 2026-10-05T03:59:00Z, which is Sunday 2026-10-04 23:59 New York
time. That is consistent with a first round on Sunday 2026-10-04; the metadata does not state the election date
itself. Rules for the next session after the questions' end (expected Monday 2026-10-05), to be run by someone else:

- x = each question's odds at 09:29 on that session minus its odds at the previous session's 16:00 (Fri 2026-10-02),
  in points; take the question with the largest |x|; direction = sign(x) × its EWZ sign of section 9. Trade only if
  |x| ≥ 5.
- EWZ contract by section 3 (first expiry at least 7 days out, strike nearest the 09:30 price).
- The same three trades at the 09:35 quote, out at the 15:55 quote, 1 contract each, costs as section 5; also record
  the quotes at 09:31, 09:45, 10:00 and 10:30 and the previous 15:55.
- One observation is an anecdote, not a test. It is to be reported as a single row next to this study's Brazil case
  file and counted in no significance statement.

## 12. Caveats known in advance

- An option bought at 09:35 and sold at 15:55 pays the day's time decay and two spreads. Buying is expected to lose
  on ordinary days and selling to earn a little before the cost of the spread; the control shows by how much.
- Spreads in the first minutes are wide. A mid price at 09:31 may not be a price anyone could trade.
- A control is matched on ticker and date only, not on the day of the week; 118 of the 300 events follow a weekend.
- One theme (Iran and oil) holds 124 of the 300 main ticker-days, so the result leans on USO, XLE and XOP.
- Bond, currency and single-country ETFs have thin options; many of their ticker-days will be dropped.
- The links are model judgements, and most of these markets had resolved when they were linked (S5 amendment 1).
- Three hypotheses and five variants are 15 looks at one sample.

## Outputs

`research/results/s16_overnight_options/`: `SUMMARY.md`, `metrics.csv`, `trades.csv`, `speed_curve.csv`,
`speed_curve.png`, `spreads.csv`, `equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

None.
