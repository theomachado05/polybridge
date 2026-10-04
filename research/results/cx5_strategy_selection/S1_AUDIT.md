# S1 strategy-selection audit

**S1 is defensible as a paper about cross-venue pricing and verification, but its
existing history does not establish an executable, funded Sharpe of 2–7.** The
primary modeled Sharpe is 7.163 at 1× costs and 4.859 at 2×. The pre-specified
PM-print-supported subset has modeled Sharpe 4.531 / 2.905. All four numbers
reproduce arithmetically; none verifies simultaneous fills, exact contract parity,
or a live-funded return. Current Anthropic rules explicitly break the assumed
payoff equality. A positive paper claim must remain conditional.

**Strongest positive claim:** the registered model identifies a small subset whose
Polymarket leg price and direction are corroborated by nearby public trades:
15 of 99 OOS entries on five pairs, with $47.50 modeled entry edge after assumed
fees, spreads and deadline carry; the independently modeled 2× run has nine of
38, with $32.28. This is evidence for investigating venue price fragmentation,
not $47.50 of realized profit or guaranteed arbitrage. S1 failed its registered
requirement that at least half of OOS entries have print support.

Audit time: 2026-10-04T04:33:51.788908+00:00. Existing S1 files read-only; current rule snapshots were supplied
by root. No network/data calls, protected forward files, sealed OOS or Git mutations.

## Arithmetic and funding interpretation

Recomputed from primary V0 / registered-quote rows in
[trades.csv](/Users/theomachado/gatorquant/research/results/s1_twin_spread/trades.csv),
[metrics.csv](/Users/theomachado/gatorquant/research/results/s1_twin_spread/metrics.csv)
and [equity_history.csv](/Users/theomachado/gatorquant/research/results/s1_twin_spread/equity_history.csv).
Edge = sum(verified quantity × edge per pair). Sharpe = mean(ΔP&L/$3,300) /
sample-standard-deviation(ΔP&L/$3,300) × sqrt(365), retaining every saved mark.

| OOS primary quantity | 1× costs | 2× costs |
|---|---:|---:|
| Modeled entries | 99 | 38 |
| Full modeled net mid P&L / Sharpe | $637.28 / 7.163 | $307.06 / 4.859 |
| PM-print-supported entries / distinct dates / pairs | 15 / 12 / 5 | 9 / 7 / 6 |
| Supported contract-pair quantity | 1,234.48875 | 418.360977 |
| Modeled entry collateral, scaled to printed size | $1,176.95 | $381.12 |
| Modeled entry edge | $47.50379 | $32.27648 |
| Supported modeled mid P&L / Sharpe | $65.67 / 4.531 | $40.62 / 2.905 |
| Largest two entries' share of modeled edge | 55.07% | 78.24% |
| Saved equity marks / actual calendar span | 74 / 73 days | 74 / 73 days |

The 74 marks include partial first/last calendar intervals. Supported equity is
retrospectively rescaled by print size, not a causal strategy that knew future prints. The 1× and 2× supported entry sets share only
**one** identical pair/direction/entry-time record. Double costs re-evaluate entries
and exits, so $32.28 is not a stress replay of the same 15 trades. Two 2× supported
quantities are below the stated PM five-share order minimum (4.125 Anthropic;
2.85507 Gemini October 31). Linear size scaling also retains fees computed for the
original 100-contract order rather than rerounding an actual smaller order.

The common $3,300 denominator is independently verified **as model arithmetic**.
A common executable funded daily Sharpe cannot be verified: historical PM bid/ask/
depth, synchronized second-leg size, actual fill/exit cash flows, per-venue free
cash and redemption delays are missing. IS/OOS restart flat is explicitly registered
in METHOD section 6; it is a separately restarted sleeve, not a continuous live
account. Five IS positions ($472.07) remain open at the 1× split. Current fees,
4.17% funding and a later spread calibration are applied through history; actual
transfer/gas and collateral-release delays are not charged. Do not relabel 4.531
as a verified trading Sharpe merely because it falls in the requested range.

## Concentration by pair and date

Independent grouping below is descriptive, not a new micro-market backtest.

| Kalshi pair | PM market ID | 1× supported entries / edge | 2× supported entries / edge |
|---|---|---:|---:|
| `KXFEDDECISION-26DEC-C25` | `3215006` | 0 / $0.00 | 1 / $0.66 |
| `KXGEMINI-GEM4-26DEC01` | `3669876` | 0 / $0.00 | 1 / $2.81 |
| `KXGEMINI-GEM4-26NOV01` | `3584362` | 1 / $1.11 | 1 / $0.13 |
| `KXGEMINI-GEM4-26OCT16` | `5084763` | 3 / $14.34 | 2 / $25.25 |
| `KXGEMINI-NEXTPRO-26NOV01` | `3667937` | 3 / $4.37 | 0 / $0.00 |
| `KXIPO-26-ANTHROPIC` | `676792` | 5 / $9.57 | 2 / $0.87 |
| `KXMACHADOVENEZUELA-26JUN29-JAN01` | `3187537` | 3 / $18.12 | 0 / $0.00 |
| `KXTRUMPAICZAR-26SEP-JCLA` | `5141824` | 0 / $0.00 | 2 / $2.56 |

At 1×, September 30 contributes $14.68612 (30.92%) and September 28 contributes
$14.53396 (30.60%): **61.51% from two dates**. At 2×, September 30 alone contributes
$25.25292 (78.24%), from two opposite-direction Gemini October-15 entries one hour
apart. The supported subset has 12 / 7 independent dates, not 15 / 9 independent
trials; its five/six pairs also contain correlated Gemini deadlines. No new
confidence claim or profitable-family Sharpe is inferred from these small clusters.

## What the print check actually establishes

[run.py:60](/Users/theomachado/gatorquant/research/s1_twin_spread/run.py:60) accepts a
print within **±600 seconds**, including prints after the modeled entry. Direction A
is PM YES + Kalshi NO: a YES BUY at or below the modeled YES ask qualifies.
Direction B is Kalshi YES + PM NO: a YES SELL at or above the modeled YES bid
qualifies. NO prints are converted using price 1-p and the opposite YES direction.
All qualifying sizes are summed and capped at 100 for each modeled entry; the PM
print proves neither a reservation nor Kalshi's simultaneous size. Inline checks confirmed the ±600-second boundary and direction conversions.
Original S1 print records are not cached, so trade identities and before/after
timing cannot be independently reconstructed from the summary CSV.

The registered quote-age allowance is 900 seconds; two consecutive one-minute
observations confirm entry. Among supported entries, Kalshi quote ages have median
60 seconds and maxima 600 / 480 seconds; PM points have median 46 seconds and
maxima 54 / 51 seconds. PM prices are minute-history points with a half-spread
estimated from October 3–4 live calibration books. These facts support a historical
price model; they do not establish second-by-second executable baskets. No protected
calibration/forward raw file was opened for this audit.

## Contract proof changes the strategy interpretation

The root-supplied [current rule snapshots](/Users/theomachado/gatorquant/research/results/cx5_strategy_selection/current_contract_metadata.json)
were observed at 2026-10-04 04:27 UTC. They are current text, **not historical
point-in-time rules**, and cannot retroactively establish what governed July–September
entries. They do invalidate calling today's entire manifest exact twins.

**Anthropic, PM 676792 / KXIPO-26-ANTHROPIC:** PM requires a completed IPO, including
first public stock sale by December 31. Kalshi can resolve YES when an S-1 becomes
effective, the offering is priced, or an exchange assigns a ticker, even if trading
starts later. Thus Kalshi YES / PM NO is an admissible state under current rules:
A (PM YES + Kalshi NO) can pay **$0**; B pays $2 in that state. B would need a full
one-way implication proof, including mergers, entity identity, geography, revisions
and exceptional payouts, before calling its floor guaranteed. Equal close timestamps
do not cure different predicates.

| Cost run | Supported Anthropic entry UTC | Direction | Supported quantity | Modeled edge |
|---|---|---|---:|---:|
| 1× | 2026-07-22T23:52:00Z | A | 100 | $1.3948 |
| 1× | 2026-08-11T08:06:00Z | A | 100 | $1.8094 |
| 1× | 2026-09-06T17:16:00Z | A | 100 | $2.4428 |
| 1× | 2026-09-18T21:36:00Z | A | 10 | $0.1604 |
| 1× | 2026-09-26T14:52:00Z | B | 100 | $3.7612 |
| 2× | 2026-07-31T14:04:00Z | A | 4.125 | $0.0443 |
| 2× | 2026-09-27T22:13:00Z | B | 46 | $0.8222 |

There are **seven distinct primary supported entries** across both cost runs:
five at 1× and two at 2×. At 1×, four A entries account for **$5.80739**, or
12.23% of all supported modeled edge; one B entry accounts for
$3.76121. At 2×, one A entry accounts for $0.04428; one B for $0.82218.
Deleting A after reading current rules would be a new exploratory variant, not a
repair that validates the published historical Sharpe. The remaining pairs are not
certified by deleting this known mismatch.

**Gemini:** PM explicitly includes open rolling waitlists and a recognized successor
to Gemini 3; the current Kalshi text requires public release outside a closed beta,
allows a costly subscription, and names Gemini 4. These clauses do not establish
identical definitions. A differently named successor or a public waitlist without
model access needs an explicit outcome table and source interpretation. The fuzzy
manifest checks are candidate matching, not mathematical contract proof.

`close_time` may be a trading cutoff, whereas the full rules define the event's
qualification deadline; expiration/redemption is a third time. For October 31,
PM endDate is 2026-11-01 03:59Z and Kalshi close_time is 04:59Z. **If** those times
are operative qualification cutoffs, a qualifying release in the hour between them
can produce PM NO / Kalshi YES, making A pay $0 and B $2. The full rules and timezone
must decide whether that state actually exists. A one-day tolerance in the fuzzy
verifier must not be treated as exact equality.

## Prospective micro-market verification priorities — exploratory

Selection follows known history and is explicitly exploratory. Rank by a named
source/product, exact operative rules and shorter collateral lockup; do not optimize
family Sharpe or retrospectively delete losing/incompatible entries.

| Priority | PM market / Kalshi ticker | Economic and semantic rationale; evidence still missing |
|---|---|---|
| First AI verification target | 5084763 / KXGEMINI-GEM4-26OCT16 | Specific model, near-term October-15 horizon; metadata times both 2026-10-16 03:59Z. Still reconcile successor naming, waitlists, public access, announcement source and refunds. Matching clocks are insufficient. |
| Secondary AI | 3669876 / KXGEMINI-GEM4-26DEC01 | November-30 metadata times agree; obtain both full rule texts before certification. |
| AI stress cases | 3584362 / KXGEMINI-GEM4-26NOV01; 3667937 / KXGEMINI-NEXTPRO-26NOV01 | October-31 hour gap; Next Pro also needs the same market-creation baseline and preview-to-GA treatment. |
| IPO mechanism case | 676792 / KXIPO-26-ANTHROPIC | Current completion-versus-confirmation mismatch; investigate only a proven directional implication, not A as an exact twin. |
| Additional IPO rule audits | 676788 / KXIPO-26-ANYSPHERE; 3956999 / KXIPOOPENAI-27APR01 | Equal metadata dates, but test confirmation versus completion and exceptional outcomes; longer carry. |
| Semantic control | 2589811/2589813, 3215006/3215008, 3215011/3215013 | October/December/January FOMC pairs, mapped to KXFEDDECISION-26OCT/26DEC/27JAN-C25 or -H25. Named official source and discrete change; prove exact vs at-least 25bp, baseline and meeting identity. No superior-profit claim. |

Minimum evidence before any funded-profit or executable-Sharpe claim: full
versioned rules captured before entry; a certified payoff table for each direction;
causal synchronized direct token bid/ask depth and clock records; sequential
submission/fill/reject/unwind modeling; fee and minimum-size terms; per-venue cash,
actual release/dispute cash flows; and contiguous daily executable portfolio marks.
Existing S1 supports neither a riskless label nor a new winning micro-market
backtest. Its useful paper contribution is the measured gap between a high modeled
Sharpe, limited one-leg corroboration and contractual/execution certainty.
