# CX2: merger equity and a failure event contract

Pre-registration written 2026-10-04 UTC, before this study reads any price or outcome series. Only this package and its result folder are owned. The parent session commits the freeze and sends FREEZE_ACK. No historical pull, price read, outcome read or test runs occur before that acknowledgement.

## Question and the important limit

Can a publicly traded cash acquisition target plus a contract paying on the matched deal's failure reduce the cost of downside protection or improve returns after realistic costs, relative to unhedged target ownership and target plus a listed put?

A stock plus a binary failure payout is not a riskless merger arbitrage. A failed target has a distribution of prices, including losses below any chosen planning reference. An announcement contract is not a completion contract. A deadline contract may pay on delayed completion without the deal failing. Revised cash consideration, dividends, competing buyers, partial acquisitions and option adjustments matter. We will retain these distinct states rather than forcing every observation into success at the offer price and failure at one fixed price.

## Information known before prices

The assignment and research/PARALLEL_BRIEF.md state that earlier linked-asset studies found price links but no established tradable profit after execution costs. Those aggregate descriptions were already supplied; no prior study result table or underlying price series has been read here. Existing histories are exposed exploratory data, not a virgin out-of-sample sample.

Metadata-only inspection on 2026-10-04 found 892 entries in research/s5_big_moves/candidates.json. Six corporate acquisition questions are potentially relevant: Nebius Group (694936), GameStop/eBay (2154920), Perplexity AI (700396), Viking Therapeutics (694938), GitLab (694940), and BP (694937). Greenland questions are sovereign transactions and are excluded. Perplexity is a private target and cannot match a listed target equity. The eBay twin question says "announce acquisition" on Kalshi, while the Polymarket title merely says "acquire": titles are insufficient to establish exact settlement equivalence. No Kalshi API will be used.

The existing S4 and S5 equity cache filenames contain none of NBIS, EBAY, VKTX, GTLB or BP. Their Polymarket histories, if any, are mids; they cannot establish executable prices or capacity by themselves. S7's package has no local cache directory contents. Options code exists but fetching Massive data, reading credentials, or touching shared infrastructure is outside this assignment. Catalog selection may favor active/high-volume markets and is not a complete historical merger universe. No test prices or outcomes were inspected for these findings.

## Discovery and inclusion, fixed now

Start with the above local catalogs, with exact rule text retrieved for those six questions after freeze. Also allow a small named public discovery pass for historically documented cash deals: Microsoft/Activision (ATVI), JetBlue/Spirit (SAVE), Kroger/Albertsons (ACI), Nippon Steel/US Steel (X), and Skydance/Paramount (PARA). The names are selected from public prior knowledge before contract or price retrieval; inclusion requires independent verification of the cash structure and public announcement date. Stock or mixed consideration, nonlisted targets, announcement-only contracts, open rumor markets without a signed agreement, and unmatched buyer/target or contract dates are excluded from a performance sample. Skydance/Paramount is a mechanics audit candidate and must not be assumed a simple all-cash offer.

Every discovered market receives an audit row, including rejected markets. Contract outcomes/prices are prohibited from influencing inclusion. An eligible deal requires:

1. A publicly listed target, signed definitive agreement, independently sourced public as-of announcement timestamp, cash consideration per target share, distribution adjustments and agreement termination/completion mechanics.
2. Full historical contract rules and amendments with timestamps. A "No" token must pay for noncompletion of that exact agreement by its stated deadline. Approval, announcement, any-buyer or ownership-transfer wording that does not match is rejected. A late close remains a separate state in the evaluator even for an otherwise useful timed hedge.
3. Equity quotes and unadjusted daily marks plus cash distributions and delisting cash consideration. Raw quote prices must correspond to the correct share units. Listed put contract deliverable and OCC corporate-action terms must be known through termination.
4. Contemporaneous event bid/ask and sizes or mids with pre-stated adverse half-spread and public print verification. Prints alone do not prove all order-book depth; quote-only history is flagged and no capacity claim made from midpoint history. No stale fill over 60 seconds for event/equity or 30 seconds for options.
5. A trailing 20 equity-session preannouncement standalone-price reference, quotes for a listed put and expiry after the event deadline, and all portfolio daily marks. Failure-price evidence must be empirical actual prices after documented broken deals, not a hand-selected planning price.

If these do not exist, the performance result is NOT_TESTABLE or INSUFFICIENT. A reusable evaluator and synthetic mechanics tests remain deliverables, with fixtures clearly identified as fixtures.

## One frozen trading rule and comparators

One trade per eligible signed deal. Entry is the first regular US equity session at 15:45 New York at least one full session after the announcement, with all instruments executable and no known termination. No price-based search for a better entry. If quotes are missing that instant, skip the deal rather than shifting entry to a favorable later date.

Own 100 target shares. Select the listed put with first standard expiry strictly after the contract deadline and strike closest to 80% of the median of the last 20 unadjusted preannouncement equity closes, with lower strike breaking ties. This strike is a planning reference, not a forecast failure price or a stock floor. Event hedge quantity is floor(100 * max(cash consideration minus strike, 0)) "No" shares. No option or contract leverage and no equity short.

Compare:
- Target plus the frozen quantity of event "No" shares.
- The same 100 target shares unhedged, with the event premium left in cash (same initial capital).
- 100 target shares plus one put at the frozen strike and expiry; use the same starting portfolio capital, and report any extra premium funding explicitly. Also give equal-capital scaled comparisons, never equate binary and put protection as identical payoffs.

Maximum initial study capital $100,000. Equal capital among live deals with a maximum 10% capital in one deal; an order cannot exceed 1% of displayed executable depth or 1% of prior 20-session target share volume. Share and option units are rounded down. Event minimum size must be satisfied. Missing depth causes exclusion from a verified performance sample. Collateral and cash remain in NAV; every return uses whole-portfolio daily marked NAV rather than premiums or only deployed stock.

Exit at documented deal termination (next available regular quote), target cash conversion, or event deadline (next regular session), whichever happens first. For a deadline while the deal remains pending, liquidate the target and mark/settle the event independently; do not infer failure. A put still alive is liquidated at the executable bid. At completion, use cash consideration plus documented distribution and the OCC-adjusted put liquidation or terminal cash deliverable. No forward knowledge of completion/termination dates may enter an entry decision.

## Costs and funding

For the verified sample, equity and option buys use asks and sells bids; event buys asks and sells bids. Apply actual venue fee metadata valid at entry, option commission $0.65 per contract per side, and equity incremental commission $0 unless a documented fee applies. 2x costs double every measured implementation shortfall from midpoint plus explicit fees/commissions. Event midpoint fallback is audit-only unless adverse half-spread of 0.02 per leg plus entry public-print checks exists; it cannot create a verified capacity estimate. Report the assumption both as 2 event price points and as basis points of all initial portfolio capital.

Funding uses a frozen conservative 5% annual cash borrowing rate, ACT/365, on any borrowing; collateral is fully included in starting capital. Report zero cash interest in the primary conservative comparison. Show committed premium/collateral and maximum simultaneous capital demand. Separate empirical fill evidence from assumptions. No hardcoded fixed failure price is used to claim arbitrage.

## Inference and success, fixed now

Chronological split uses the most recent 20% of aligned equity sessions as recent validation. It is labeled exposed exploratory validation. Do not treat multiple observations from one deal as independent trades. Report deal count, independent entry dates and daily observation count separately. Bootstrap complete deal clusters for terminal-trade return uncertainty and blocks of five session dates for daily portfolio uncertainty, 2,000 resamples, seed 4202. If the number of independent deal clusters is under 10, no confidence/Sharpe claim is considered adequate.

Success requires at least 30 independent entry dates, at least 60 recent daily observations, recent annualized daily portfolio Sharpe >=1.5, positive net return at both 1x and 2x costs, positive lower 95% bootstrap bound for net terminal returns and recent daily return, and improvement against the exposure-matched unhedged comparator without one deal supplying over 25% of net profit. Report maximum drawdown, worst month, downside tails, turnover, largest position/profit concentration and verified capacity. Sharpe above 3 triggers a mechanics/timing audit before any report. No rule tuning follows observation of results. Only this one strategy rule is tested; all comparators and failed feasibility cases remain disclosed.

## Prospective backup

If historical aligned deal evidence is insufficient, produce an exact-contract watchlist and a normalized CSV input specification for prospective capture. After a signed eligible cash deal, record full rule versions, equity NBBO, event two-sided depth, put NBBO and deliverable, and distributions at the frozen entry time and daily mark times. No live trade is authorized by this study. No schedule, API credential or recorder is altered. We will explicitly list the missing inputs and estimate necessary observations without manufacturing an equity curve from illustrative states.

## Amendments

None at freeze.
