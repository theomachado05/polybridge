# S19: does the price-market premium replicate on crypto? (pre-registered)

**Question.** S18 found, at prices that traded, that buyers of YES in Polymarket's price markets on oil, metals, the
S&P 500 and stocks lost 8.87 points per contract held to the result, and that sellers at the bid earned +3.63 after
fees over the year but nothing in the most recent 20% of events, so it did not pass. One year of one family of
markets cannot say whether that is a premium or a good year. Polymarket has run the same product on Bitcoin,
Ethereum, Solana and XRP since October 2024 ("What price will Bitcoin hit in October?"). Different assets, twice the
history, more events. Does the same test pass there?

This file, `config.py`, `universe.py` and `universe.json` are committed **before any trade print of these markets is
pulled**. Every rule is fixed. Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- S18's result (`research/results/s18_price_market_calibration/SUMMARY.md`), including where it was largest
  (contracts traded between 50% and 75%) and that prices at 2 to 10% showed nothing.
- **From the catalogue only** (`universe.py`): 1,000 crypto price events, 653 of them daily and left out; 336 weekly
  or longer events with 4,039 eligible markets; 1,265 markets drawn at random, four per event (seed 0): 354
  Bitcoin, 351 Ethereum, 307 Solana, 253 XRP; listed from 2024-10-01 to 2026-10-03. 291 of the 1,265 resolved YES.
- A probe of the data API on one Bitcoin market, to learn that it can be asked for prints above a cash size (it
  can): the number of rows and their dates were read, no price.
- **Not seen:** any price or print of these markets set against a result.

## 1. Markets

`universe.json`: events whose title is "What price will Bitcoin / Ethereum / Solana / XRP hit ...", as returned by
the fixed catalogue searches, **leaving out the daily ones** ("... hit on March 9?"), which are a different product.
From each event, four markets drawn at random (numpy generator, seed 0) among those that have a result and at least
$5,000 traded. An **event** is one bet.

## 2. Prints

For each market, the public trade prints of **at least $50 of cash** from its listing time to **48 hours** later.
(The $50 floor lets the data API reach the first days of busy markets, which it cannot do unfiltered; S18 had no
floor.) The data API reports the taker's side. A print on the NO token at price q is read as a YES price of 1 − q
with the side reversed, as in S18.

## 3. The test (S18's, unchanged)

- **Sellers' test.** Prints in which the taker **sold** YES (hit a bid). Per market, the size-weighted mean of those
  prices, `ps`, and the P&L per contract of selling there and holding to the result: `ps` − the market's taker fee
  at `ps` − result. One observation per market. Mean with a 95% interval resampling events.
- **Buyers' test.** Prints in which the taker **bought** YES: the size-weighted mean `pb`, and the P&L of buying
  there: result − `pb` − fee.
- **Segments:** events in the order of their listing; out-of-sample is the most recent 20% of events.
- Also reported, same statistics: each asset; each horizon (monthly or longer, weekly, other range); each bucket of
  traded price (2 to 10%, 10 to 25%, 25 to 50%, 50 to 75%, 75 to 90%, 90 to 98%); listings up to 2025-12-31 against
  2026.

## 4. Success criterion (fixed now, the reading S18 used)

**The premium replicates only if all four hold:** the sellers' mean P&L is above zero with the interval excluding
zero over the whole sample; it is above zero in-sample; it is above zero out-of-sample; and it is above zero with
the fee doubled. If they hold, the sellers' trade is reported as passing **on a second, independent family of
markets**, with its book: up to 100 contracts per market and never more than the printed size, P&L booked in the
month of the result, capital base the largest capital locked at one time, Sharpe on monthly returns, maximum
drawdown, worst month, turnover, costs, capacity from the printed sizes. If they do not hold, S18's premium is not
supported outside its own year and family, and that is said.

## 5. Caveats known in advance

- Crypto never shuts, so this says nothing about weekends. It tests the premium, not the closed-market idea.
- Prints under $50 are not seen. Small buyers are the ones most likely to overpay; leaving them out can only make
  the buyers' loss look smaller.
- A market that is hit inside its first 48 hours contributes prints near 100% after the hit; their P&L is near zero.
- Selling these markets is selling insurance against large moves. Two years of crypto contain several.
- Four markets per event, not all: a sample, drawn before any print was seen.

## Outputs

`research/results/s19_crypto_price_markets/`: `SUMMARY.md`, `tests.csv`, `markets.csv`, `book.csv`,
`equity_curve.png`, `drawdown.png`, `capacity.md`, `RUN_LOG.md`.

## Amendments

None.
