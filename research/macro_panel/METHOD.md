# Overnight-gap relation on a rule-selected US macro panel (pre-registered)

**Background.** In the closed-market study (`research/leadlag_closed/`, `research/results/leadlag_closed/SUMMARY.md`), across 380 closures of two markets (Trump-wins and US recession 2025), the Polymarket (PM) move while the US equity session was closed went with the next SPY opening gap: +7.52 bp of gap per pp of oriented PM move, permutation p 0.001. On 10 rule-selected new markets, 8 of them geopolitical, the pooled slope was +0.63 bp per pp, date-permutation p 0.126 (`research/results/leadlag_replication/SUMMARY.md`). With one observation per closure date that panel gave p 0.034, outside its criterion. The expected-gap model held out of sample only on the US-recession market (`research/results/gap_model/SUMMARY.md`). The replication rule excluded Fed and macro-print markets as sign-ambiguous, so it could not say whether the relation lives in US macro markets.

**This study** asks one primary question and one secondary question.

- **Primary (T3, power).** On a larger panel of US macro and economic markets (recession, Fed path, inflation, unemployment, GDP), chosen by a fixed volume and keyword rule, does the oriented PM move over a closure go with the next SPY opening gap, over closures from 2023-01-01 to 2025-12-31?
- **Secondary (T1, labelled secondary).** Is the slope on this macro panel larger than the slope on the geopolitical markets of `leadlag_replication`?

It is confirmatory. The selection rule, the sign rule, the measures, the tests and the pass rule are fixed in this file. This file and `config.py` are committed in one commit **before any data is fetched for this study**: no gamma metadata, no PM price and no equity bar. The selection rule runs at fetch time, after this commit. Anything changed later goes under "Amendments" with the reason. One run produces the result, and the result is reported whatever it shows.

## 0. What was looked at before this commit

- No gamma query, no PM price and no equity bar for this study. The keyword lists below were written from the question formats the author remembers from Polymarket, not from a listing.
- The author knows the results of `leadlag_closed`, `leadlag_replication`, `gap_model`, `closed_hedge` and `open_options` as summarized in `research/EVIDENCE.md`, and the frozen candidate list of `leadlag_replication/markets.json` (its METHOD appendix), which contains no Fed, inflation, unemployment or GDP market because its rule excluded them.
- For the power calculation only, the standard deviations of the oriented PM move and of the SPY gap were computed from the committed result tables `research/results/leadlag_closed/closures_all.csv` and `research/results/leadlag_replication/results.csv` (oriented move sd 1.63 pp on the 380 closures, 4.52 pp on the 1,211 replication rows; gap sd 60 and 64 bp). No slope was recomputed.

## 1. Window and instruments

- **Study window:** closures whose start (close) day is in **2023-01-01 to 2025-12-30** and whose open day is on or before **2025-12-31**. Nothing dated 2026 is requested; the 2026-01-01 to 2026-08-31 window is sealed for the 8-K study, and `research/results/oos` is not touched.
- **Instrument:** SPY only.
- **Equity data:** Massive 1-minute aggregates, adjusted, extended hours included, fetched in calendar-month chunks with `leadlag_closed.data.fetch_equity_range`, exactly as in `leadlag_closed` and `leadlag_replication`.
- **PM data:** CLOB `prices-history?market=<Yes token>&startTs&endTs&fidelity=1`, one request per closure covering `[nominal 16:00 close - 5 h, 09:30 open + 30 min]`, with `leadlag.data.fetch_pm_history`.

## 2. Market selection rule (fixed, run at fetch time)

1. **Pool:** every gamma event, closed or open, returned by these queries, each taking the top **1,000 events by event volume** for closed and for open events: tag id 100328 (Economy) and 101800 (Economic Policy), and tag slugs `fed-rates`, `fed`, `inflation`, `economy`. Events are de-duplicated by id. A tag slug that returns nothing contributes nothing. The keyword rule of section 3 is the filter, so a broad pool only costs time.
2. **Market eligibility:** a binary Yes/No market with an order book; not one of the 12 markets already used (the 2 of `leadlag_closed`, the 10 selected by `leadlag_replication`, listed in `config.py`); the section 3 rule gives it a class and a sign; lifetime volume (`volumeNum`) of at least **$50,000**; and life inside the study window of at least **28 days**. Life runs from gamma `startDate` (else `createdAt`) to `closedTime` if closed, else `endDate`.
3. **One market per event:** the event's highest-volume eligible market. There is no question-stem de-duplication: per-meeting Fed markets and monthly print markets ask different questions about different dates, and overlapping markets on the same date are handled by clustering on closure date.
4. **Ranking and caps:** rank all eligible markets by lifetime volume. Walk the ranking. Take a market if its class has fewer than **10** markets taken and, among its closures in the window (section 4), **at least 15 have a PM quote at both ends** (section 5). Stop when every class has 10 or the ranking ends. At most **50** markets. The coverage check uses PM data only; no equity bar is fetched until the list is fixed.
5. **Frozen list:** the selection script writes `macro_panel/markets.json` with the snapshot time and the full eligible ranking. That file is committed before any PM price is fetched. The run reads it and never re-ranks from live gamma.

## 3. Class and sign rule (fixed, mechanical)

Matching is on the lower-cased question text with word boundaries (`macro_panel.select.classify`). The sign is +1 if Yes is good for US equities and -1 if Yes is bad.

1. **Exclusion list, checked first.** Any match excludes the market:
   - **Not US:** canada, canadian, uk, britain, british, england, euro\*, ecb, germany, german, japan\*, boj, china, chinese, india\*, australia\*, rba, boe, snb, swiss, mexic\*, brazil\*, turk\*, argentin\*, russia\*, korea\*, france, french, ital\*, spain, spanish, new zealand, rbnz.
   - **People, statements and offices:** say, says, said, mention\*, tweet\*, post\*, powell, chair, nominee, nominat\*, fire\*, resign\*, replace\*, elect\*, president, trump, biden, harris, who, which, approval.
   - **Asset prices:** s&p, spx, nasdaq, dow, stock(s), spy, bitcoin, btc, eth, ethereum, crypto\*, gold, oil, gas, price(s) (but not "price index"), treasury, yield(s), mortgage, dollar.
   - **Buckets, counts, holds and emergencies:** how many, how much, exactly, between, range, no change, unchanged, pause\*, hold, holds, maintain\*, emergency, and any numeric range such as "2.9-3.1" or "3 to 4".
   - **Negated or conditional questions:** not, no, never, if, unless, without.
2. **Class terms.** A question must match exactly one class:
   - **recession:** recession.
   - **fed:** fed, fomc, federal reserve, fed funds, interest rate(s), rate cut(s), rate hike(s).
   - **inflation:** inflation, cpi, pce, consumer price index.
   - **unemployment:** unemployment, jobless.
   - **gdp:** gdp.
   A question matching two classes or none is excluded.
3. **Direction.**
   - **recession:** no direction needed. Yes = recession, sign **-1**.
   - **fed:** down words cut\*, decrease\*, lower\*, reduc\*; up words hike\*, increase\*, raise\*. **A cut is equity-bullish, sign +1; a hike is equity-bearish, sign -1.** Both or neither: excluded. This sign is fixed now and applies to every cut size, including 50 bp or more.
   - **inflation, unemployment, gdp:** the direction comes from a threshold term only. Up: above, over, more than, greater than, at least, or more, or higher, exceed\*, and the symbols ≥, >=, >, or a number followed by "+". Down: below, under, less than, fewer than, or less, or lower, and the symbols ≤, <=, <. For gdp only, negative, contract\* and shrink\* also count as down. A plain "increase by 0.3%" with no threshold term is a bucket and is excluded. Both or neither: excluded.
   - **Valence:** higher inflation is bad (-1), higher unemployment is bad (-1), higher GDP is good (+1). The sign is valence times direction. So "CPI above 3%" is -1, "unemployment below 4%" is +1, "negative GDP growth" is -1.

Why these signs: in 2023 to 2025 the equity reaction to a hot inflation print or a hawkish repricing was mostly negative, and the reaction to a growth scare was negative. "Bad news is good news" for rate cuts is a known risk to the Fed and unemployment signs; it biases toward a null and is stated as a caveat, not handled by choosing signs after the data.

## 4. Closures

Same definitions as `leadlag_closed` and `leadlag_replication`, using `leadlag_closed.closures.build_closures` and `polybridge_research.calendar.TradingCalendar`.

- **Closure:** from the end of the last regular-session (09:30-16:00 ET) bar of one NYSE trading day to 09:30 ET on the next trading day. Types: overnight, weekend, holiday. On early-close days the close is the end of the last RTH bar actually present.
- **Per market:** every closure in the study window whose nominal 16:00 ET close is at or after the market's start and whose 09:30 ET open is at or before the market's end. Nothing else is removed; scheduled 08:30 ET releases (CPI, jobs, GDP) stay in, because they are where macro markets move.
- For the PM coverage check, which runs before any equity bar, the close instant is 13:00 ET on the known early-close days (2023-07-03, 2023-11-24, 2024-07-03, 2024-11-29, 2024-12-24, 2025-07-03, 2025-11-28, 2025-12-24) and 16:00 ET otherwise.

## 5. Measures (per market x closure)

Identical to `leadlag_replication` section 5.

- `pm_close`: the last CLOB point at or before the end of the last RTH bar, in pp; `pm_open`: the last point at or before 09:30:00 ET on the open day. Each needs a point within 30 minutes before its instant, or the row is `no PM quote` (never imputed).
- `x = sign * round(pm_open - pm_close, 9)`, the oriented PM change in pp. Positive x means the PM moved in the equity-bullish direction.
- `gap_bp = 1e4 * (open / prev_close - 1)`, with `open` the open of the first RTH bar of the open day (starting within 5 minutes of 09:30) and `prev_close` the close of the last RTH bar of the close day.
- A row is usable if it has a PM quote at both ends and a gap. A failed fetch is recorded as `fetch failed` and excluded.

## 6. Tests

### Primary (T3): pooled slope on the macro panel

OLS `gap_bp = a + b * x` on all usable rows of the macro panel, no threshold, one row per market x closure. Reported: b (bp per pp), the **t-statistic with standard errors clustered by closure date** (CR1 small-sample factor, `leadlag_replication.stats.cluster_t`), a 95% interval b ± 1.96 se, and the **date-level permutation p**: 10,000 permutations with seed 20261003 of the map from closure date to SPY gap across the distinct usable dates, applied to every market's rows, two-sided on |b|, p = (count + 1) / (10,000 + 1) (`leadlag_replication.stats.date_perm_slope`). HC3 t is reported next to it.

**Pass rule (fixed now, applied literally; same style as `leadlag_replication` with the clustered t in place of HC3 t):**
- **"Holds"** if all three: **b > 0**, **date-permutation p < 0.05**, **date-clustered t > 2**.
- **"Partial"** if b > 0 and exactly one of the other two holds.
- **"Does not hold"** otherwise.

### Secondary (T1): macro minus geopolitics

The geopolitical rows are the usable rows of `research/results/leadlag_replication/results.csv` with `cls == "geopolitics"` (8 markets, read as committed, not refetched). Stack them with the macro rows and fit `gap_bp = a + c * macro + b_geo * x + d * (x * macro)` by OLS with standard errors clustered by closure date (shared dates fall in one cluster). **d = b_macro - b_geo** is the contrast. Reported: d, its clustered se, a 95% interval d ± 1.96 se. "Macro slope larger" if the interval is above 0, "smaller" if below 0, "no difference shown" otherwise. This is secondary and does not change the primary verdict. Caveat: the geopolitical panel covers 2024-2025 only.

### Other secondary results (reported, not in the verdict)

- One observation per closure date: gap on the mean x across the macro markets quoted that date (HC3 t and date permutation).
- Sign test at 1 pp: among rows with |x| >= 1 pp and gap != 0, share with sign(x) = sign(gap), exact binomial, plus a date-permutation p.
- Per-class slope with clustered t, per-market slope, leave-one-class-out slope.
- Fresh dates: closures starting in 2023, outside the windows of every earlier closed-market study, where both the PM series and the SPY gaps are new.
- Overnight vs weekend/holiday closures.

## 7. Expected n and power (stated before data)

- **Expected n.** Up to 50 markets. Fed per-meeting and monthly CPI markets live 1 to 3 months (about 20 to 60 closures each); recession and annual markets live a year (about 250). Expected about **2,000 usable rows over about 500 to 650 closure dates**. The actual counts go in SUMMARY.md.
- **Power** for the clustered slope test at alpha 0.05 two-sided, residual sd 65 bp:
  - Scenario A, oriented-move sd 4.5 pp (as on the replication panel) and a clustering variance factor of 1.21 (the HC3-to-clustered ratio seen there): se 0.36 bp per pp, minimum detectable effect at 80% power **1.0 bp per pp**. Power is 1.00 against +7.52 (original), 1.00 against +1.9 (the original divided by 4 for winner's curse), 0.43 against +0.63 (replication).
  - Scenario B, oriented-move sd 1.6 pp (as on the original 380 closures) and a clustering factor of 2.0 (more markets per date): se 1.29, MDE **3.6 bp per pp**. Power 1.00 against +7.52, 0.32 against +1.9, 0.08 against +0.63.
  - **Reading.** The test is sure to detect an effect as large as the original. Against a discounted effect it is well powered only if macro markets move as much as the replication markets did. A null with an interval that excludes about +2 bp per pp would rule out the original effect size on macro markets; a null with a wide interval would only say the panel was too quiet.
- **Null-proofing note.** The variation is the overnight news flow that moves both prices; the design measures co-movement over the closure, not a causal effect or a lead. The kill test is the first row count after the PM coverage stage: if fewer than 500 usable rows remain, power falls below Scenario B and the run still goes ahead and is reported as underpowered.

## 8. Outputs

`research/results/macro_panel/`: `SUMMARY.md` (generated from the results), `results.csv` (every market x closure row), `coverage.csv` (the selection walk), `tests.json`, `chart.png`, `RUN_LOG.md`, and `.done`, written after the single full run; `run.py` refuses a second fetch-and-analyse run while `.done` exists. Code in `research/macro_panel/`, tests on synthetic data in `research/macro_panel/tests/`. The `MASSIVE_API_KEY` is read from the environment or `research/.env` and never printed or written.

Run: `cd research && .venv/bin/python -m macro_panel.run`. It selects (if `markets.json` is absent, then stops so the list can be committed), runs the PM coverage walk, and stops with exit 2 before any equity request if the key is missing.

## 9. Caveats stated in advance

- **Futures.** ES and NQ futures trade overnight and SPY trades pre-market; a positive slope is co-movement over the closure, not a lead or a tradeable signal.
- **Sign risk.** The Fed and unemployment signs can flip under "bad news is good news". The fixed signs bias toward a null if that regime dominates.
- **Shared dates.** Many macro markets quote on the same date and share one gap. The clustered t and the date permutation are the primary inference for that reason.
- **Old histories.** CLOB minute histories for markets that resolved in 2023 may be missing; such markets fail the coverage check and the walk moves on.
- **Live volumes.** Volumes of still-open markets include trading after 2025; the ranking is as of the snapshot.

## Amendments

**Amendment 1 (informational, no rule changed; written after the gamma snapshot and the PM coverage walk, before any equity bar was requested).** The frozen snapshot (`markets.json`, 2026-10-03 21:50:41 UTC, 1,312 pool events) has 70 eligible markets: fed 35, inflation 19, gdp 10, recession 3, unemployment 3. The coverage walk selected **36 markets** (fed 10, inflation 10, gdp 10, recession 3, unemployment 3) with **2,612 market x closure rows, 2,609 quoted at both ends, over 354 closure dates from 2024-08-02 to 2025-12-30** (`research/results/macro_panel/coverage.csv`). The two 2023 markets in the ranking sit below the point where the fed cap filled, so **no closure from 2023 is in the panel and the "fresh 2023 dates" secondary result is empty**. The rule picks the highest-volume Fed markets, which are tail outcomes (50+ bp cuts, 25+ bp hikes) that trade near 0; that is the rule applied literally and is not changed. Power recomputed for the realized n, same assumptions as section 7: scenario A se 0.31, MDE 0.9 bp per pp, power 1.00 / 1.00 / 0.53 against +7.52 / +1.9 / +0.63; scenario B se 1.12, MDE 3.1, power 1.00 / 0.39 / 0.09; a one-observation-per-date bound (354 dates, mean-move sd 1.6 pp) se 2.16, MDE 6.0, power 0.94 / 0.14 / 0.06. Fewer dates than the 500 to 650 expected; the kill threshold of 500 usable rows is passed.
