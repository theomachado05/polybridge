# Manual settlement check: 20 random pairs (seed 2026, `config.MANUAL_SAMPLE_SEED`)

Drawn from every classified pair of both universes (S11 then fresh, the order of `settlement_check.csv`), under the rule
as amended (amendment 4). Each pair's two full gamma descriptions, start dates and sources were read by hand.

| # | Universe | Pair (rich / cheap) | Rule | Hand | Note |
|---|---|---|---|---|---|
| 1 | S11 | Iran closes its airspace by May 27 / May 31 | nested | nested | "by the listed date, 11:59 PM ET", identical text |
| 2 | S11 | US strikes Iran by March 11 / March 12, 2026 | nested | nested | window from "this market's creation"; rungs created 1.6 s apart |
| 3 | fresh | Gaza "Board of Peace" by January 31 / March 31 | nested | nested | only the date differs |
| 4 | fresh | Solstice token by Dec 31 2025 / Mar 31 2026 | nested | nested | "date specified in the title" |
| 5 | fresh | GPT-5.6 released by July 24 / July 31, 2026 | nested | nested | "by the specified date (ET)" |
| 6 | fresh | US-Canada tariff agreement by Aug 31 / Sep 30 | not nested (texts differ) | nested | only difference besides the date is "cancelled" vs "canceled" |
| 7 | S11 | Gemini 3.0 released by Nov 15 / Nov 22 | nested | nested | resolves on the release date |
| 8 | S11 | Silver (SI) HIGH $120 / $110 by end of January | nested | nested | CME settlement, "the listed price", same source |
| 9 | fresh | Houthi strike on Israel by Mar 31 / Apr 15, 2026 | not nested (creation) | not nested | window from creation; cheap rung created 21 days later |
| 10 | fresh | Military action against Iran ends by Apr 28 / Apr 29 | nested | nested | Iran Standard Time in both; identical text |
| 11 | fresh | SpaceX IPO by June 15 / June 30, 2026 | nested | nested | identical text |
| 12 | S11 | Russia captures Kostyantynivka by Sep 30 / Dec 31, 2026 | not nested (texts differ) | nested | the rich rung adds a persistence requirement, so it is stricter: rich YES still implies cheap YES |
| 13 | fresh | Bitcoin all time high by Jun 30 / Sep 30, 2026 | nested | nested | both windows start 16 Dec '25 10:30 |
| 14 | fresh | Russia captures all of Huliaipole by Jun 30 / Sep 30 | nested | nested | only the date differs |
| 15 | fresh | DeepSeek V4 released by Mar 31 / Apr 15 | not nested (texts differ) | not nested | the later rung excludes "V4-Lite"-type releases the earlier rung would count |
| 16 | fresh | STRC hit $100 by Sep 30 / Dec 31 | nested | nested | window from creation; rungs created 2 s apart |
| 17 | fresh | Pump.fun airdrop by Jul 31 / Aug 31 | nested | nested | only the date differs |
| 18 | fresh | Fomo token by Mar 31 / Jun 30 2026 | nested | nested | "date specified in the title" |
| 19 | fresh | Arc token by Jun 30 / Sep 30 2026 | nested | nested | "date specified in the title" |
| 20 | fresh | Japanese snap election called by Jan 31 / Jun 30, 2026 | not nested (texts differ) | nested | windows Jan 14 to Jan 31 and Nov 10 to Jun 30: the later window covers the earlier |

Agreement 17 of 20. All 3 disagreements are pairs the rule excludes that a reader would call nested (spelling variant,
a stricter rich rung, a wider cheap window). No pair the rule calls nested was found not nested by hand. The rule errs
toward exclusion, which can only shrink the replay's sample, never add a pair that can lose by its written terms.
