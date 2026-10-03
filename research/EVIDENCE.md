# PolyBridge evidence pack

For the partner writing the quant note (Sunday 2026-10-04). Written 2026-10-03. Every number below is copied from the file named next to it. Where a number is our own tally of a file (not printed in it), it is marked **(tally)**. If this page and a source file disagree, the source file wins; tell Theo.

**One-line verdict.** We found no prediction-market (PM) lead over equities during market hours, a mixed co-movement result when equities are closed, no executable options-versus-PM arbitrage, and a null 8-K parity result in-sample (out-of-sample not yet run). What we did build and measure is an execution and risk-control stack: a compiled library (1,278 presets) that decides in tens of nanoseconds, with an AI step that only picks from it. The product's value is execution and risk control, not alpha.

Contents: 1 8-K study, 2 lead-lag in market hours, 3 closed-market study, 4 options-arbitrage scan, 5 engine latency and library size, 6 AI fit replay scores, then what the evidence supports, then a 5-page note outline.

---

## 1. 8-K implied-move parity study (the confirmatory test)

- **Question.** After an 8-K filing, do the options under-price (H1, hedge side, protective put) or over-price (H2, opportunity side, cash-secured put) the move that follows, relative to ordinary days?
- **Method, one line.** Pre-registered (`research/HYPOTHESIS.md`, `research/HYPOTHESIS_TAGS.md`) before any event data was fetched; event-minus-placebo P&L edge with a 97.5% bootstrap CI at the 21-session, 42-session and expiry horizons; passes only if the CI excludes zero in the predicted direction at 2 or more of the 3 horizons and the parity ratio R differs from placebo in the predicted direction at the same horizons (`research/HYPOTHESIS.md` section 4).
- **Sample.** In-sample 2024-01-01 to 2025-12-31. H1: 36 events (18 in 2024, 18 in 2025). H2: 24 events (14, 10). Total events 60; 5 cross-family filings excluded; 120 placebo days per family (`research/results/in_sample/SUMMARY.md`).
- **Result.** Both NULL (`research/results/in_sample/hedge_verdict.txt`, `opportunity_verdict.txt`, both read `NULL`).

| | horizon | n events / placebo | edge | 97.5% CI |
|---|---|---|---|---|
| H1 | 21 | 32 / 106 | +0.0007 | [-0.0270, +0.0291] |
| H1 | 42 | 30 / 104 | +0.0049 | [-0.0451, +0.0577] |
| H1 | expiry | 28 / 95 | +0.0333 | [-0.0301, +0.1012] |
| H2 | 21 | 24 / 113 | +0.0009 | [-0.0068, +0.0089] |
| H2 | 42 | 24 / 111 | +0.0021 | [-0.0090, +0.0136] |
| H2 | expiry | 23 / 99 | +0.0092 | [-0.0036, +0.0234] |

  Edge is P&L per $1 of spot at entry; source table in `research/results/in_sample/SUMMARY.md`. Net edge after the pre-registered 5% premium haircut is small and positive (for example H1 at 21 sessions +0.0011, H2 at 21 sessions +0.0011), but the summary states none is a confirmatory test.
- **Atlas (exploratory, not a result).** 119 tags x 5 strategies x 3 horizons; 96,390 variants counted (`research/results/atlas/README.md`, `variants.txt`). Our tally of `atlas.csv`: 1,785 rows, 761 with a p-value (570 rows have zero events), 23 rows at BH q < 0.05 across 11 tags with 5 to 15 events each **(tally)**. With that many looks and samples that small, these are leads for a future study and carry no confirmatory weight (`research/HYPOTHESIS.md` section 5). Note: `in_sample/SUMMARY.md` still says "Atlas not run"; that line is stale, the atlas ran later (`research/results/RUN_LOG.md`, run 7).
- **Out-of-sample.** Window 2026-01-01 to 2026-08-31 is **not run** per `research/results/RUN_LOG.md`; it runs once after the method freeze (scheduled Sat 2026-10-03 13:00 ET). Result: **<fill in after the single post-freeze run, whatever it returns>**. No H1/H2 event in the out-of-sample window has been fetched or evaluated, and no out-of-sample 8-K result has been computed.
- **Supports.** Under the pre-registered rule neither hypothesis passes in-sample; no CI excludes zero at any headline horizon. We can say a null was reported as a null.
- **Does not support.** Any claim that 8-K tags predict option mispricing. Also does not prove absence of an effect: samples are 23 to 36 events per family, so the CIs are wide.
- **Caveats.** Static top-100 universe (survivorship), last-trade marks, spot inferred from the chain, conservative timing (all filings treated as public after the close). Disclosure: some in-sample exit and quote dates fall after 2025-12-31, inside the calendar span of the out-of-sample window; no 2026 event was fetched as an event (`in_sample/SUMMARY.md`, Disclosure). The Massive starter's out-of-sample cell was run on `cfo_appointment`, not an H1/H2 tag (`research/results/pipeline_check.md`). Other studies in this pack used 2026 market data that is not 8-K event data: the lead-lag study used equity minutes for the 2026 FOMC dates (2026-01-28, 2026-06-17, 2026-07-29), and the arb scan used option quotes for markets that resolved from 2026-08-15 (for example SPY>765 on 2026-08-31). None of it feeds the H1/H2 test, but do not write an absolute "no 2026 data was ever touched" claim in the note.

## 2. Lead-lag during market hours

- **Question.** In stress events, does the PM move before the equity does?
- **Method, one line.** First significant move per series (k = 4 rolling sigma, 3-minute change, 5-minute persistence), lead in minutes, minute-level cross-correlation, pooled Granger and HAC regressions with event fixed effects; parameters fixed in `research/leadlag/METHOD.md` before data was fetched.
- **Sample.** 32 candidate events, 28 usable, 4 dropped; 20 events with a significant move in both series (`research/results/leadlag/SUMMARY.md`). 15 of the 28 are scheduled FOMC statements (the unselected part); 13 are curated from memory.
- **Result.**
  - PM first 9, simultaneous 2, equity first 9. Median lead -1.0 min, mean +3.0 min (positive = PM first). Exact sign test 9 of 18, p = 1.000.
  - Same direction in 14 of 20 events (8 of 9 PM-first events).
  - Pooled Granger (10 lags, event fixed effects): PM to equity F = 0.71 (p = 0.716); equity to PM F = 7.72 (p = 2.07e-12). Pre-set verdict: "points the other way".
  - HAC-robust: 0 of 4 Granger Wald tests significant at 5%. Regression A (PM to equity) cumulative response -0.083 (t = -1.21); Regression B (equity to PM) +0.203 (t = +2.29).
  - Sensitivity of the first-move rule: at k = 3, 27 events with both moves, PM first 7, equity first 18, median lead -15.0 min; at k = 5, 16 events, PM first 3, equity first 11. Widening the simultaneous band to 2 min gives PM first 9, simultaneous 5, equity first 6.
- **Supports.** A negative statement: no statistic in this study supports a PM lead in market hours. If anything the pooled tests lean toward equities leading the PM, weakly and not uniformly.
- **Does not support.** "Prediction markets move first." Also not proof that they never do: individual events exist where the PM was first (9 of 20), for example FOMC 2025-07-30 at +54 min, but 5 of those 9 have the first PM move before the event anchor, so they cannot be reactions to the event.
- **Caveats.** Events are not independent (the 2025 recession market appears in four tariff windows). PM history is at most one point per minute and stale in quiet minutes; the PM series is about 45 to 55 seconds staler than equity at each grid point, which biases leads against the PM (3 of the 9 equity-first events are at -2 min). Thin PM markets print isolated ticks that can pass the rule and bias toward "PM first". Equity moves are measured against SPY/ETF prices only; futures and options are not observed. Curated events were chosen from memory. The per-event HAC columns are oversized and not used. All in the Caveats section of `research/results/leadlag/SUMMARY.md`.

## 3. Closed-market lead study

- **Question.** When news breaks while the US equity session is closed (nights, weekends, holidays), does the PM move from the last close to the next open predict the SPY opening gap?
- **Method, one line.** Sign test and slope of SPY gap on oriented PM change over each closure, plus a 380-closure placebo panel and a pairing placebo; rules fixed in `research/leadlag_closed/METHOD.md` before any event-window price was fetched.
- **Sample.** 17 pre-registered news closures, 17 usable (13 use the recession market, 4 the Trump-wins market); 380 placebo closures (`research/results/leadlag_closed/SUMMARY.md`). Event types: weekend 11, overnight 5, holiday 1.
- **Result.** Pre-set verdict: **mixed** (sign test not met; slope met; pairing placebo not met).
  - Same sign in 11 of 15 closures with a PM move of at least 1 pp (73%, exact p = 0.118); at a 2 pp threshold 9 of 10 (90%, p = 0.021).
  - Slope +10.43 bp of gap per pp (HC3 t = +0.84, R-squared 0.381, permutation p = 0.005); Spearman rho +0.73.
  - Placebo closures show the same relation: 89 of 149 agree (60%, p = 0.021), slope +7.52 bp per pp (permutation p = 0.001). News closures show no extra response: interaction +2.91 bp per pp (HC3 t = +0.23).
  - Pairing placebo: 7.8 agreeing events on average versus 11 observed (p = 0.075).
  - Timing test (T4): the PM move up to 08:00 ET does not predict the SPY move from 08:00 ET to the open (7 of 16 agree, slope +0.62 bp per pp, permutation p = 0.278).
- **Supports.** The PM price is a live read of event risk that moves with the equity gap when equities are closed. Mixed, leaning positive on co-movement only.
- **Does not support.** A tradeable lead or a head start. A relation also appears with no flagged news, news closures show no extra response, and the timing test is null.
- **Caveats.** Events chosen in hindsight (large gaps by construction); events share two markets; 17 events is little power; equities are not literally closed (SPY trades pre/post-market, futures nearly 24 hours); the market-to-news mapping is loose; a 1 pp move means different things at 3% and at 50%. Median absolute SPY gap: events 94 bp, placebo 28 bp. See Caveats in the source.

## 4. Options-arbitrage scan (PM probability versus option-implied probability)

- **Question.** Do listed PM threshold markets ("NVDA above $K on date") disagree with the probability implied by call spreads from Massive quotes by more than costs?
- **Method, one line.** Pre-registered scan (`research/arb/METHOD.md`); gap net of fees and an assumed PM spread; a trade-print verification step (amendment 3) that promotes a candidate only if a public print within 10 minutes shows a price at least as good as breakeven. Nothing was traded.
- **Sample.** Run 2026-10-03 (Saturday, options closed); resolved markets 2026-08-15 to 2026-10-12. Polymarket 9,814 markets seen, 3,136 "close above $K" thresholds; Kalshi S&P 500 and Nasdaq-100 16:00 ET markets (`research/results/arb/SUMMARY.md`).
- **Result.** **5 verified gaps, 0 executable.**
  - Cost screen alone passes 224 resolved Polymarket rows (111 events); only 5 of 224 have a trade print at the needed price. Those 5 are 4 distinct (underlying, date, strike) gaps, each a single print of 5 to 100 shares; one contract hedges 200 to 500 PM shares in these rows; 1 is flagged `coarse`.
  - Resolved Kalshi (real bid/ask): 500 clean scored rows, 0 at `gap_net`.
  - Calibration (descriptive): mean Brier(PM) minus Brier(options) = +0.0045 over 3,261 rows in 340 events, event-cluster bootstrap 95% interval [+0.0033, +0.0081]; positive means the PM mid was farther from the realised result than the options-implied probability.
- **Supports.** The honest count of executable arbitrage found is zero. The PM mid was not a better probability estimate than options, and slightly worse on this sample.
- **Does not support.** "The scan found money." Also not a statistical claim: no significance test is claimed.
- **Caveats.** An earlier version of the report claimed one verified gap (NVDA > $215); that was a timezone bug, fixed and documented in the source (section "Correction"). The resolved Polymarket spread is assumed (0.050, median of 154 live books), not observed; the call-spread hedge is not riskless inside the strike strip (up to 0.5 per share); rows are not independent; live rows are weekend-stale; the thin-market PM mid handicaps it in the Brier comparison.

## 5. Engine latency and library size

- **Question.** How big is the compiled library, and how long does a decision take?
- **Method, one line.** `hedgecore_bench`: 1,000,000 synthetic ticks per family, default preset, single thread, `-O3`; plus `replay_grid` over 20,000 ticks (`engine/hedgecore/BENCH.md`).
- **Sample / machine.** Apple M5, Apple clang 17.0.0, 2026-10-03, synthetic deterministic tape (LCG seed 42), not recorded market data.
- **Result.**
  - Library: **16 families, 1,278 presets, 37 blocks** (`docs/library.md`, from `engine/hedgecore/manifest.json`). The design handoff quotes "~1,284"; the library reports 1,278, so say 1,278 (`docs/demo.md` section 5).
  - `on_tick` batch mean 27.1 to 34.6 ns across the 16 families, including its own latency stamp (two clock reads, about 15 ns). Decision logic alone (`step()` mean) 4.2 to 22.9 ns. Worst per-call p99.9 458 ns; worst 64-block p99.9 83 ns per call (`BENCH.md`).
  - `replay_grid`: all 1,278 presets over 20,000 ticks in 1.68 s, 1.521e+07 preset-ticks per second, one thread.
- **Supports.** A decision costs well under a microsecond, about four orders of magnitude below the 1 ms scale of a network round trip (`BENCH.md` summary). Scoring the whole library once is cheap enough to tune per market.
- **Does not support.** An end-to-end latency claim, any profitability claim, or "faster than competitors". It measures `on_tick` only.
- **Caveats.** Synthetic tape; `poly_kalshi_spread` emitted 8 orders and `eightk_opportunity` 1, so those mostly time the no-trade path; not network, JSON or Python overhead; one machine, one run, one thread; only default presets are timed. The bridge screen's per-tick latency (`docs/demo.md` section 5) is a different, end-to-end-in-process measurement; do not mix the two.

## 6. AI fit replay scores (IN-SAMPLE replay, not a forecast)

- **Question.** Can the pipeline classify a PM market, pick a family and preset from the library, and score it on the market's own history?
- **Method, one line.** `scripts/precompute_fits.py`: classify (keyword rules), shortlist families, build ticks from each market's real price history aligned to Massive bars, `replay_grid`, pick the preset with the best score (hedge families: `hedge_var_reduction`); `docs/library.md` section "How the AI picks and tunes".
- **Sample.** 133 markets (120 Polymarket, 13 Kalshi; our count of the keys **(tally)**), generated 2026-10-03T08:52:52+00:00, provider `rules` (no Gemini), ticks source `live_history` for all 133, 1,000 shares held; 122 scored, 11 unscored (`backend/app/data/fits.json`, `backend/data_logs/precompute_fits.log`).
- **Result.** 122 fitted. Families chosen: `equity_delta_bridge` 64, `tech_reg_hedge` 15, `fig_stress` 14, `crypto_reg_hedge` 12, `energy_geo_hedge` 11, `election_hedge` 4, `stress_lead_hedge` 1, `tariff_trade_hedge` 1; 11 unsupported. Event classes: crypto 47, geopolitics_energy 24, macro_fed 14, tech_regulation 12, company_specific 12, elections 11, unsupported 11, corporate_8k 1, tariffs_trade 1. Scores (our tally of the 122 scored fits **(tally)**): min 0.028, median 0.766, max 1.000; 23 are at or above 0.99.
- **Supports.** The pipeline ran end to end over 133 real markets with no timeouts, none falling back to replay and none without history (log summary); it was run online (`offline=False`). For a given market it selects a preset whose replay cut the variance of the held stock's P&L by the stated fraction on that same history.
- **Does not support.** That the preset will reduce risk going forward, that a PM predicts the stock, or that the family choice is meaningful: the score is measured on the same history the preset was tuned on (in-sample, selection over up to 1,278 presets), and the picker maximises it. The ticker-to-market mapping is an AI estimate, not a measurement.
- **Caveats.** Scores near 1.0 (23 at or above 0.99) have not been audited; the replay uses hourly or daily equity bars (`backend/app/pipeline/ticks.py`), so the hedge-variance measure rests on few equity changes. Treat the top of the range with suspicion and do not quote a headline score. Classification is keyword rules and some picks look loose (for example "Will Anthropic announce bankruptcy by December 31, 2027?" is classed company_specific and mapped to AMZN). Polymarket history is mid-price only, spread and depth unknown and left empty; no out-of-sample test of the fits exists.

---

## What the evidence supports (conservative)

1. **Supported, measured:** the compiled library exists (16 families, 1,278 presets, 37 blocks), decides in 27.1 to 34.6 ns per tick on the benchmark tape, and can score every preset on 20,000 ticks in 1.68 s.
2. **Mixed, co-movement only:** with equities closed, the PM move over the closure and the SPY opening gap are positively related (slope +10.43 bp per pp, permutation p = 0.005; 11 of 15 same sign, p = 0.118). The same relation shows in the 380 placebo closures, news closures show no extra response, and the PM move before 08:00 ET does not predict the rest of the gap. Read it as "the PM is a live public read of event risk when equities are shut", not as a lead.
3. **Not found:** a PM lead during market hours (PM first 9, equity first 9, sign test p = 1.000; pooled tests point the other way).
4. **Not found:** an executable PM versus options arbitrage (5 verified, 0 executable; each on a print of 5 to 100 shares).
5. **Null, in-sample:** the 8-K parity hypotheses H1 and H2. Out-of-sample is pending a single run.
6. **Not evidence of returns:** the AI fit scores. They are in-sample hedge-variance replays.

So: the product's value is **execution and risk control** (human approval gate, coverage cap, fee gate, a compiled and tested catalog, honest labels), not alpha. Do not write that prediction markets lead equities, that the fit predicts returns, or that the scan found arbitrage.

---

## Suggested 5-page quant note, mapped to the main-track rubric

Rubric: five criteria, each out of 10 (Economic foundation, Innovation, Risk management, Liquidity and capital, Performance and evidence), from `docs/win-plan.html` section 3. That table was written for the earlier 8-K hedge-overlay plan; its "our evidence" column predates v4, so rewrite each cell from this page.

| Page | Section | Rubric criterion it earns | Content (sources) |
|---|---|---|---|
| 1 | Summary and economic foundation | Economic foundation | The thesis in spec section 1 stated as a hypothesis to test, not a fact: PMs may reprice event risk faster than equities. Who is on the other side and why it would or would not persist. State up front that the tests below did not confirm a market-hours lead. |
| 2 | Method and framework | Innovation | PM price and option chain as two prices of the same event risk; pre-registration before data (HYPOTHESIS.md, METHOD.md files); the library-plus-AI design where the AI only picks from compiled, tested presets (`docs/library.md`). |
| 3 | Results: four studies | Performance and evidence | Section 1 table (H1/H2 null, variant count 96,390, OOS status), section 2 (9/9/2, sign test p = 1.000, pooled Granger), section 3 (slope, placebo, T4), section 4 (5 verified, 0 executable, Brier). One compact table, one sentence each on what it does not show. If the parity decay is shown, point to `in_sample/SUMMARY.md` "Parity decay" with the caveat "event CIs overlap placebo at every horizon; not a confirmatory test". |
| 4 | Risk management and liquidity | Risk management; Liquidity and capital | Controls that exist in the library: coverage cap, fee gate, no-trade band, drawdown kill, gap-flip kill, approval gate (`docs/library.md` blocks table; `docs/demo.md` Q&A). Liquidity: 8-K median leg volume 33.5 (H1) and 48.5 (H2); half-spread cost 0.0029 per $1 of spot at the 21-session horizon for both families (`in_sample/SUMMARY.md` cost table); arb scan PM prints of 5 to 100 shares versus 200 to 500 shares per contract. Honest gap: no capacity or ADV analysis and no Webull overlay backtest is in the evidence pack, so do not claim them. |
| 5 | Limits, latency, next steps | Performance and evidence (limits); Innovation | Engine latency with its synthetic-tape caveat (section 5). AI fit scores labelled in-sample (section 6). A short, plain list of what was not tested: tradeable intra-closure lead, out-of-sample for fits, real fills. Next study: a pre-registered closed-market test with intra-closure timing. |

Style notes: lead with the null results; the rubric note reads "a well-argued null result with a clear decay curve beats a lucky backtest" (`docs/win-plan.html`, note under the rubric, quoting the Massive brief). The parity decay result is in `research/results/in_sample/SUMMARY.md`, section "Parity decay"; quote it only with its caveat, "event CIs overlap placebo at every horizon; not a confirmatory test", and do not single out one horizon (for example hedge R 1.36 at 42 sessions). Cap conditions in the same rubric block: a score is capped at 4 if the work is not runnable, has lookahead, or is tuned on out-of-sample data, so describe the out-of-sample window only as frozen and run once. Put the out-of-sample number in once, in one place, after the freeze run.
