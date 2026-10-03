# Confirmatory replication of the overnight-gap finding (pre-registered)

**The finding under test.** In the closed-market study (`research/leadlag_closed/`, results in `research/results/leadlag_closed/SUMMARY.md`), across 380 unselected closures of two markets (Trump-wins, 2024-04-01 to 2024-11-04; US recession 2025, 2025-01-10 to 2025-12-30), the Polymarket (PM) move while the US equity session was closed went with the SPY opening gap: slope +7.52 bp of gap per pp of PM move, HC3 t +2.58, permutation p 0.001. In the 149 closures where the PM moved at least 1 pp, 89 had the same sign (60%, p 0.021).

**This study** asks whether that relation holds on **new markets chosen by a fixed rule**. It is confirmatory. The market rule, the sign rule, every measure, every test and the success criterion are fixed in this file. This file is committed **before any price series (PM or equity) is fetched for this study**. Anything changed later goes under "Amendments" with the reason, and the original stays in git history. One run produces the result, and the result is reported whatever it shows.

## 0. What was looked at before this commit

- **Gamma metadata only, no prices:** event and market slugs, question text, tags, lifetime volume, start, end and closed dates, token ids. The selection script (`select.py`) never prints or stores gamma's outcome prices, last-trade prices or price-change fields.
- **The rule was revised three times after reading candidate question texts. All three revisions were made before any price was seen:**
  1. A negation and conditional exclusion (`not`, `no`, `broken`, `if` and others) was added. Without it, "Israel x Iran ceasefire broken by December 31?" and "Next Israel x Hamas ceasefire not in 2024?" would have been signed as risk-on.
  2. A same-question-stem de-duplication was added. Without it, four overlapping Russia x Ukraine ceasefire markets took four of the top ten slots.
  3. The Politics tag was added to the pool. The brief says "policy", and shutdown and tariff markets sit under Politics, not Economy.
  
  Two threshold phrases (`greater than`, `fewer than`) and `nothing` were also added to the exclusion list. That removed two lower-ranked markets, "Nothing Ever Happens: Military Edition" and a tariff-rate threshold market. No revision used or could use any price.
- **The author knows the original study's result** (above) and, from memory, the rough path of 2024-2025 news. No price series of any market listed below has been looked at, in this study or before.
- No equity bar has been fetched for this study.

## 1. Window and instruments

- **Study window:** closures whose start (close) day is in **2024-01-01 to 2025-12-30**, with the next open on or before 2025-12-31. Nothing dated 2026 is requested, because the 2026-01-01 to 2026-08-31 window is sealed for the 8-K study.
- **Primary instrument:** SPY. **Secondary:** QQQ and IWM. A secondary result never replaces SPY in the headline.
- Equity data: Massive 1-minute aggregates, adjusted, extended hours included (`research/polybridge_research/massive.py` client, fetched in calendar-month chunks, as in `leadlag_closed`). PM data: CLOB `prices-history?market=<Yes token>&startTs&endTs&fidelity=1`, one request per closure covering `[nominal 16:00 close - 5 h, 09:30 open + 30 min]`.

## 2. Market selection rule (fixed)

1. **Pool:** every gamma event, closed or open, tagged Economy (100328), Geopolitics (100265), Economic Policy (101800) or Politics (2). The query takes the top 1,000 events by event volume for each tag and each of closed/open, then de-duplicates.
2. **Market eligibility:** a binary Yes/No market with an order book. The two original markets (`will-donald-trump-win-the-2024-us-presidential-election`, `us-recession-in-2025`) are excluded. The question must get a sign from the section 3 rule; a market the rule cannot sign is excluded. The market's life inside the study window must be at least **92 days (3 months)**. Life runs from gamma `startDate` (else `createdAt`) to `closedTime` if the market is closed, else to `endDate`.
3. **One market per event:** the event's highest-volume eligible market.
4. **No overlapping duplicates:** walk the list in order of lifetime volume (`volumeNum`). Drop a market if its question stem equals the stem of a market already kept and the two lives overlap in time. The stem is the lower-cased question with years, numbers, month names and the words *will, the, a, an, in, by, before, after, on, of, end, to, year, this* removed. The same question asked over non-overlapping years (for example "China invade Taiwan in 2024" and "by end of 2026") is kept, because those are separate data.
5. **N = 10.** Go down the ranking. Take a market if, among its closures in the window (section 4), **at least 40 have a PM quote at both ends** (section 5, rule 1). Stop after 10 markets qualify. This coverage check uses PM data only. In the code, no equity bar is fetched until the 10 markets are fixed.
6. **Frozen list:** `leadlag_replication/markets.json` holds the gamma snapshot of 2026-10-03 16:38:09 UTC (4,098 pool events, 45 eligible markets; sha256 `8c343ec07ee07940f62bc5f61f72a0cc55c1405164b509826baaf8996d2f8ee3`). The run reads this file and never re-ranks from live gamma, because the volumes of open markets keep changing. The ranking is reproduced in the Appendix.

## 3. Sign (orientation) rule (fixed, mechanical)

The sign comes from the lower-cased **question text** alone, matched on word boundaries (`select.classify`). It is set once per market.

1. **Exclusion list, checked first.** A match on any of these excludes the market as ambiguous:
   - **Monetary policy:** fed, fomc, federal reserve, interest rate(s), rate cut(s), rate hike(s), bps, powell. Why: when the odds of a cut rise, stocks can go either way, depending on whether the cause is a growth scare or dovish policy.
   - **Elections, people and offices:** elect\*, win(s), nominee, nominat\*, president, prime minister, approval, who, which, out as, resign\*, impeach\*, pardon\*, leader.
   - **The outcome itself or other asset prices:** s&p, spx, nasdaq, dow, stock(s), spy, ipo, market cap, largest company, bitcoin, btc, eth, ethereum, crypto\*, microstrategy, solana, gold, oil, price, treasury, yield(s).
   - **Macro prints:** inflation, cpi, gdp, unemployment, jobs, payroll(s).
   - **Counts and thresholds:** how many, how much, exactly, between, above, below, more than, less than, at least, greater than, fewer than, nothing, revenue, emergency, no change, sanction(s).
   - **Negated or conditional questions:** not, no, broken, break\*, collaps\*, fail\*, violat\*, surviv\*, if.
2. **Risk-on, Yes = good for US equities, sign +1:** ceasefire / cease-fire, truce, peace deal, peace agreement, trade deal, trade agreement, nuclear deal, "war end(s)", "end (of) the war", "end(s) the war".
3. **Risk-off, Yes = bad for US equities, sign -1:** recession, shutdown, default\*, invade\*, invasion, blockade\*, military, strike(s), airstrike(s), attack(s), declare(s) war, war with, go to war, at war, martial law, nuclear test/weapon/strike\*.
4. **Tariff questions:** a question with "tariff(s)" counts as risk-on if it also has an easing word (lower\*, reduc\*, cut\*, paus\*, remov\*, lift\*, exempt\*, deal, agreement, end(s) (the) tariff(s), suspend\*, drop\*, repeal\*). Otherwise it counts as risk-off.
5. A question that matches both sign lists, or neither, is excluded.

**Market class** (for a secondary split only): "US macro/policy" if the sign term is recession, shutdown, default or tariff. "Geopolitics" otherwise.

## 4. Closures

- **Closure:** the span from the end of the last regular-session (RTH, 09:30-16:00 ET) bar of one NYSE trading day to the 09:30 ET start of the next trading day. Calendar: `polybridge_research.calendar.TradingCalendar`. Types: `overnight` (consecutive days), `weekend` (Friday to Monday), `holiday` (any longer span). On early-close days the close is the end of the last RTH bar actually present.
- **Per market:** **every** closure whose nominal 16:00 ET close is at or after the market's start instant, whose 09:30 ET open is at or before the market's end instant, and that lies in the study window (section 1). Nothing else is removed. Scheduled 08:30 ET releases and all news stay in.

## 5. Measures (per market x closure)

- `pm_close`: the PM Yes price in pp, as of the closure start. It is the last CLOB point with timestamp at or before the end of the last RTH bar. `pm_open`: the same, as of 09:30:00 ET on the open day. Each needs a point within **30 minutes** before its instant, or the row is `no PM quote` (never imputed). Using only points at or before 09:30 means no look-ahead.
- `dpm = round(pm_open - pm_close, 9)` (pp). `x = sign * dpm`, the **oriented PM change**. A positive x means the PM moved in the equity-bullish direction.
- `gap_bp = 1e4 * (open / prev_close - 1)`. `open` is the open of the first RTH bar of the open day, which must start within 5 minutes of 09:30. `prev_close` is the close of the last RTH bar of the close day. The same is computed for QQQ and IWM.
- Usability: (1) a PM quote at both ends; (2) a gap. A failed fetch is recorded as `fetch failed` and the row is excluded, never imputed.

## 6. Tests

Rows are pooled across the 10 markets, one row per market x closure. The same closure date can appear for several markets with the same gap. The primary permutation therefore shuffles **closure dates**, not rows.

**Primary.**
- **S1, pooled slope.** OLS `gap_bp = a + b * x` on all usable rows, no threshold. Reported: `b` (bp per pp), **HC3 t**, R-squared, and the **permutation p-value**. The permutation runs 10,000 times with seed 20261003. Each time it permutes the map from closure date to SPY gap across the distinct usable dates, applies the same permutation to every market's rows and refits b. The test is two-sided on |b|, and p = (count + 1) / (10,000 + 1).
- **S2, sign test at 1 pp.** Among rows with `|x| >= 1.0 pp` (tolerance 1e-9) and `gap != 0`, count `sign(x) == sign(gap)`. Exact two-sided binomial against 0.5.

**Success criterion (fixed now, applied literally).**
- **"Replicates"** if all three hold: **b > 0**, **permutation p < 0.05** and **HC3 t > 2**.
- **"Partial"** if b > 0 and exactly one of the other two holds.
- **"Does not replicate"** otherwise.

The sign test S2 is reported next to the verdict, as agreeing or not (rate above 50% with p < 0.05), but it does not enter the verdict.

**Secondary (reported, not part of the verdict):**
- S1 and S2 with QQQ and IWM gaps.
- S2 at 0.5 and 2.0 pp.
- S1 with standard errors clustered by closure date.
- S1 with a row-level permutation.
- A **date-collapsed** regression: one observation per closure date, with the gap regressed on the mean x across the markets quoted that date (HC3, and a permutation over dates).
- Per-market b and S2.
- Leave-one-market-out b.
- The class split (US macro/policy vs geopolitics).
- Overnight vs weekend/holiday closures.
- The **fresh-date subset**: closures whose start day is outside both original panels (2024-04-01 to 2024-11-04 and 2025-01-10 to 2025-12-30). Only on these dates is the SPY gap itself new as well as the PM series.
- The original figures, side by side.

## 7. Outputs

`research/results/leadlag_replication/`:
- `SUMMARY.md`: headline numbers, verdict and caveats, all generated from the results.
- `results.csv`: every market x closure row.
- `chart.png`: scatter of gap against x, plus per-market slopes.
- `RUN_LOG.md`: commit, wall time, request counts, exit status.

Code: `research/leadlag_replication/`, reusing `leadlag.data.fetch_pm_history` and `leadlag_closed` closure, equity and statistics functions. Synthetic tests: `research/leadlag_replication/tests/`. The `MASSIVE_API_KEY` is read from the environment or `.env` and is never printed or written.

## 8. Caveats stated in advance

- **Futures proxy.** E-mini S&P 500 and Nasdaq futures trade almost around the clock, and SPY trades pre-market. By 09:30 the equity side has already priced most overnight news through futures, which this study does not observe; Massive equity bars only. A positive relation is therefore **co-movement over the closure**, both prices reacting to the same news. It does not show that the PM leads, and it is not a tradeable signal: the gap is not capturable once futures have moved. A futures-based test (PM move vs ES move over the same window, or the PM move up to time t vs the futures move after t) would be needed for a lead claim.
- **Same calendar as the original.** Most closures fall inside the original panels' dates. The PM series are new, but the SPY gaps on those dates are the same numbers the original used, so this is a replication of the PM-to-gap link on new PM data, not on new equity data. The fresh-date subset is the only part where both are new, and it is small.
- **The rule picks mostly geopolitical markets.** By volume, the eligible pool is dominated by ceasefire, invasion and military markets. Only a few are US macro/policy (shutdown, tariffs, recession). The original relation came mostly from a US recession market, where 70% of closures had the same sign, against 47% for the election market. The link from a geopolitical market to SPY is looser, which biases this test toward a null. Fed markets, the largest macro markets, are excluded because their sign is ambiguous. That is a deliberate cost.
- **Low-probability markets.** Many markets trade at 1-10%, so a 1 pp move is rare. S2 will have fewer rows than S1.
- **Shared dates.** Rows on the same date share one gap. The binomial test and HC3 t treat rows as independent and are optimistic. The date permutation, the date-clustered t and the date-collapsed regression address this.
- **Volume from a live snapshot.** Lifetime volume of still-open markets includes trading after 2025. The ranking is as of the frozen snapshot.
- **Reading of the result.** A replication would say that the PM closure move and the SPY gap move together beyond one or two hand-picked markets. A null on this pool would say the original relation does not carry over to high-volume geopolitical markets. That does not rule it out for US macro markets.

## Amendments

(none)

## Appendix: frozen ranking (gamma snapshot 2026-10-03 16:38:09 UTC)

Ranks 1-10 are the intended sample if each passes the 40-closure PM coverage check. Otherwise the next ranks are taken in order (section 2, rule 5). Volume is lifetime USD in millions. Life is from start to end/closed (UTC dates).

| Rank | Market slug | Question | Sign | Volume ($M) | Life |
|---|---|---|---|---|---|
| 1 | `russia-x-ukraine-ceasefire-in-2025` | Russia x Ukraine ceasefire in 2025? | +1 | 73.75 | 2024-12-29 to 2026-01-01 |
| 2 | `us-government-shutdown-before-2025` | Will there be a US Government shutdown? | -1 | 53.50 | 2024-09-03 to 2024-12-25 |
| 3 | `us-x-venezuela-military-engagement-by-december-31-391-819-722-945-174-285-817-971-353-859-836-598-255-382-192-983` | US x Venezuela military engagement by December 31? | -1 | 51.07 | 2025-09-05 to 2026-01-05 |
| 4 | `will-china-invade-taiwan-before-2027` | Will China invade Taiwan by end of 2026? | -1 | 43.28 | 2025-07-24 to 2027-01-01 |
| 5 | `will-israel-invade-syria-in-2024` | Will Israel invade Syria in 2024? | -1 | 16.82 | 2024-09-13 to 2024-12-21 |
| 6 | `israel-x-hamas-ceasefire-before-july-2025` | Israel x Hamas ceasefire before July? | +1 | 6.11 | 2025-03-19 to 2025-07-01 |
| 7 | `will-china-invade-taiwan-in-2024` | Will China invade Taiwan in 2024? | -1 | 5.67 | 2024-01-15 to 2025-01-01 |
| 8 | `will-the-supreme-court-rule-in-favor-of-trumps-tariffs` | Supreme Court rules in favor of Trump's tariffs? | -1 | 4.76 | 2025-09-02 to 2026-02-20 |
| 9 | `will-a-nuclear-weapon-detonate-in-2024` | Will a nuclear weapon detonate in 2024? | -1 | 4.74 | 2024-07-01 to 2025-01-01 |
| 10 | `israel-x-hamas-ceasefire-in-2024` | Israel x Hamas ceasefire in 2024? | +1 | 3.95 | 2024-08-07 to 2025-01-01 |
| 11 | `will-russia-invade-a-nato-country-by-june-30-2026` | Will Russia invade a NATO country by June 30, 2026? | -1 | 3.65 | 2025-09-23 to 2026-07-01 |
| 12 | `us-government-shutdown-in-2025` | US government shutdown in 2025? | -1 | 3.51 | 2025-01-09 to 2025-10-01 |
| 13 | `us-strikes-yemen-by-december-31` | US strikes Yemen by December 31? | -1 | 3.35 | 2025-09-26 to 2026-01-05 |
| 14 | `nuclear-weapon-detonation-in-2025` | Nuclear weapon detonation in 2025? | -1 | 2.90 | 2024-12-29 to 2026-01-01 |
| 15 | `us-x-iran-nuclear-deal-in-2025` | US-Iran nuclear deal in 2025? | +1 | 2.80 | 2025-02-05 to 2026-01-01 |
| 16 | `will-the-us-invade-venezuela-in-2025` | Will the U.S. invade Venezuela by December 31, 2025? | -1 | 2.76 | 2025-09-06 to 2026-01-01 |
| 17 | `ukraine-signs-peace-deal-with-russia-in-2025` | Ukraine signs peace deal with Russia in 2025? | +1 | 2.61 | 2025-08-12 to 2026-01-01 |
| 18 | `us-recession-by-end-of-2026` | US recession by end of 2026? | -1 | 2.24 | 2025-09-29 to 2027-01-31 |
| 19 | `will-china-blockade-taiwan-by-june-30` | Will China blockade Taiwan by June 30? | -1 | 2.11 | 2025-09-19 to 2026-07-01 |
| 20 | `will-china-invades-taiwan-before-gta-vi-716-644` | Will China invades Taiwan before GTA VI? | -1 | 1.94 | 2025-05-02 to 2026-08-01 |
| 21 | `will-the-us-officially-declare-war-on-iran-in-2025` | Will the US officially declare war on Iran in 2025? | -1 | 1.73 | 2025-06-22 to 2026-01-01 |
| 22 | `israel-strikes-iran-before-2026` | Israel strikes Iran before 2026? | -1 | 1.71 | 2025-06-25 to 2026-01-01 |
| 23 | `china-x-taiwan-military-clash-by-december-31` | China x Taiwan military clash by December 31? | -1 | 1.37 | 2025-01-30 to 2026-01-01 |
| 24 | `will-north-korea-invade-south-korea-in-2024` | Will North Korea invade South Korea in 2024? | -1 | 1.27 | 2024-01-08 to 2025-01-01 |
| 25 | `another-us-military-action-against-iran-before-2026` | Another US military action against Iran before 2026? | -1 | 1.19 | 2025-06-26 to 2026-01-01 |
| 26 | `israel-military-action-against-iran-by-end-of-2024` | Israel military action against Iran by end of 2024? | -1 | 0.93 | 2024-06-01 to 2024-10-26 |
| 27 | `us-recession-in-2024-1` | U.S. Recession in 2024? | -1 | 0.88 | 2024-08-05 to 2025-01-01 |
| 28 | `will-the-us-invade-iran-in-2025` | Will the U.S. invade Iran in 2025? | -1 | 0.85 | 2025-06-18 to 2026-01-01 |
| 29 | `nato-x-russia-military-clash-in-2025` | NATO x Russia military clash in 2025? | -1 | 0.63 | 2025-09-23 to 2026-01-01 |
| 30 | `will-the-eu-impose-new-tariffs-on-us-goods-in-2025` | Will the EU impose new tariffs on US goods in 2025? | -1 | 0.61 | 2025-07-23 to 2025-12-02 |
| 31 | `us-x-russia-nuclear-deal-by-december-31` | U.S. x Russia Nuclear deal by December 31? | +1 | 0.49 | 2025-08-14 to 2026-01-01 |
| 32 | `next-israel-x-hamas-ceasefire-in-december` | Next Israel x Hamas ceasefire in December? | +1 | 0.43 | 2024-08-29 to 2025-01-01 |
| 33 | `us-x-russia-military-clash-by-december-31` | US x Russia military clash by December 31? | -1 | 0.42 | 2025-05-28 to 2026-01-01 |
| 34 | `will-north-korea-invade-south-korea-in-2025` | Will North Korea invade South Korea in 2025? | -1 | 0.36 | 2025-01-30 to 2026-01-01 |
| 35 | `north-korea-x-south-korea-military-clash-by-december-31` | North Korea x South Korea military clash by December 31? | -1 | 0.31 | 2025-01-30 to 2026-01-01 |
| 36 | `israel-x-turkey-military-clash-by` | Israel x Turkey military clash in 2025? | -1 | 0.28 | 2025-04-01 to 2026-01-01 |
| 37 | `china-x-philippines-military-clash-by-december-31` | China x Philippines military clash by December 31? | -1 | 0.25 | 2025-01-30 to 2026-01-01 |
| 38 | `russian-strike-on-poland-by-december-31` | Russian strike on Poland by December 31? | -1 | 0.19 | 2025-09-26 to 2026-01-01 |
| 39 | `us-agrees-to-a-new-trade-deal-with-south-korea` | U.S. agrees to a new trade deal with "South Korea"? | +1 | 0.17 | 2025-07-25 to 2026-01-01 |
| 40 | `east-coast-port-strike-in-january` | East coast port strike in January? | -1 | 0.16 | 2024-10-23 to 2025-02-01 |
| 41 | `us-defaults-on-debt-in-2025` | US defaults on debt in 2025? | -1 | 0.14 | 2025-04-08 to 2026-01-01 |
| 42 | `will-a-nuclear-weapon-detonate-by-june-30-2024` | Will a nuclear weapon detonate by June 30, 2024? | -1 | 0.09 | 2023-12-28 to 2024-07-01 |
| 43 | `china-x-india-military-clash-by-december-31` | China x India military clash by December 31? | -1 | 0.07 | 2025-01-30 to 2026-01-01 |
| 44 | `will-trump-impose-large-tariffs-in-2025` | Will Trump impose large tariffs in 2025? | -1 | 0.03 | 2025-04-11 to 2025-07-30 |
| 45 | `canada-recession-in-2025` | Canada recession in 2025? | -1 | 0.03 | 2025-09-11 to 2026-01-06 |
