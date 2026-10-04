# S11: questions that belong together are one book

Pre-registered Sat 2026-10-03, about 23:20 New York time, before any price of these markets is read by this study.
Every number below is fixed in [`config.py`](config.py). Changes after this commit go under "Amendments", dated.

## 0. The question

Some Polymarket questions are bound to each other by logic, so their prices must be consistent:

- **Strike ladder.** "Will WTI hit $105?" can never be more likely than "Will WTI hit $100?" in the same event. The
  mirror holds for "hit (LOW)" markets: $40 can never be more likely than $45.
- **Date ladder.** "Ceasefire by May 31?" can never be less likely than "Ceasefire by April 30?".
- **One-of-many set** (an event Polymarket runs as negRisk: exactly one member resolves YES). The YES prices sum to 1.

Two tests:

- **(a) Violations.** How often is a bundle inconsistent by more than the cost of trading every leg? How long does it
  last? Weekends against weekdays. Tonight's live books first; then one year of history.
- **(b) Propagation.** When one rung jumps 3+ points in 5 minutes, does its sibling follow late, so that the sibling
  can be traded?

What was already known (so nothing below is chosen after the fact on this data): S1 found same-question gaps between
venues real but tiny once print-checked; S3's three-way consistency rule never fired; S6 and S1 found that most
"prices" in thin markets are midpoints of empty books; S8 and S9 found a 2.6 to 3.3 point give-back that is the size of
a round trip. Nobody in this project has yet read a price of the bundles below.

## 1. Bundles (catalogue text only; `universe.py`, lists in `bundles.json` and `live_bundles.json`)

Built by rule from the catalogue record of each event. Every price field is dropped before anything is stored (the
code asserts it).

- **Same event.** Every leg of a bundle is a market of one event.
- **Date ladder.** Questions that are word for word the same once the last date phrase is replaced (`DATE_RE`:
  "April 30", "April 30, 2026", "end of June"), and whose wording is cumulative: the date follows "by" or "before".
  "On <date>" or "in <month>" questions are not ladders. The year missing from a phrase is the market's end-date year.
  Two rungs on one date: the ladder is dropped. Rungs ordered by date; each adjacent pair is (rich = earlier,
  cheap = later); P(rich) ≤ P(cheap).
- **Strike ladder.** Questions that are word for word the same once the one level ("$100", "$1B", "4.5%") is replaced;
  a question with two levels is not a rung (years are not levels). The wording must say the direction: up words
  ("(HIGH)", "↑", "above", "over", "more than", "at least", ">", "reach", "exceed") or down words ("(LOW)", "↓",
  "below", "under", "less than", "<", "dip to", "fall to"); both or neither: left out. Up: the higher level is the rich
  leg. Down: the lower level is the rich leg. Adjacent levels form the pairs.
  S9's 391 price markets are added with S9's own sign and level (their one-minute prices exist for **weekend windows
  only**); an S9 ladder that shares a leg with a ladder built from S5's events is replaced by the full-week one.
- **Rungs** must have a catalogue volume of $50,000 or more (as S9).
- **One-of-many set.** An event flagged negRisk with 2 to 30 markets that have an order book, and no ladder in it.
  Every member counts, whatever its volume. Sets with Polymarket's "augmented" flag (placeholders that are named
  later) are kept and reported apart, because buying every YES pays $1 only if the listed members cover every outcome.
- **History universe**: S9's ladders plus every event of S5's 892 ranked markets (`candidates.json`, `universe.json`),
  re-read whole from the catalogue by slug. **Live universe**: the 400 open events with the most 24-hour volume
  (event volume $100,000 or more), open markets only.

## 2. Costs and fills

- **Half-spread** per fill, by bundle kind (strike, date, one-of-many): the median over markets of each market's
  median half-spread in the first hour of this study's own live snapshots, markets with a mid between 10% and 90%,
  floored at 0.005 (half a one-cent tick). Fixed before any history is read.
- **Fee**: each market's own feeSchedule, `rate × (p(1−p))^exponent` per contract, taker only, paid on every fill.
- **Live**: real best bid and ask, and the book's depth.
- **History**: one-minute mid (Polymarket's price history), moved against us by the half-spread, plus the fee. A mid
  older than 30 minutes does not count. **Print check** on every leg of every entry (`s6_monday_fade.run.verify`):
  a public print within 10 minutes at a price at least as good, in the right direction (a YES sale needs a taker who
  sold YES at or above our price). Only the latest 20,000 prints of a market are served, so older entries are
  "uncheckable"; reported as such.
- Every result at **1× and 2×** the half-spread and fee. Costs reported in points (cents per contract) and in bp of
  the capital the trade ties up.

## 3. Part (a): violations

- **Monotone pair** (rich A, cheap B). At cost multiplier c, a violation is
  `(mid_A − c·h − c·fee_A) − (mid_B + c·h + c·fee_B) > 0`: selling A (buying NO on A) and buying B locks that in,
  because long B plus NO on A pays at least $1 whatever happens. Capital per contract: `(1 − bid_A) + ask_B`.
- **One-of-many set** with n members. Buy every YES when `Σ(mid + c·h + c·fee) < 1`; buy every NO when
  `Σ(mid − c·h − c·fee) > 1` (n NOs pay n − 1). A minute counts only when every member has a fresh mid; a member
  already resolved counts at its result.
- **Episode**: consecutive minutes in violation; a gap of under an hour joins two. Reported: count, size, duration
  (minutes until the violation beyond costs is gone, and until the mid gap itself closes), weekend against weekday
  (weekend = Friday 17:00 to Sunday 18:00 New York time; rate per 1,000 bundle-hours observed).
- **The trade**: at the first minute of an episode, sell the rich leg and buy the cheap leg, 100 contracts a leg
  (one-of-many: 100 of every member). Hold until the mid gap closes (rich mid ≤ cheap mid; one-of-many: the sum
  crosses 1), unwinding at mid with the half-spread and fee again; or to resolution, settled at each market's result
  (no spread, no fee). A market not resolved by the end of the history is marked at its last mid, crossing the exit
  costs. Variant **H**: always hold to resolution. Cap: at most 10 new trades a day, largest violation first; one open
  trade per bundle.
- **Live** (`live.py`): every 3 minutes until Sun 2026-10-04 07:00 New York time, `POST /books` for every leg of every
  live bundle, stored in `.cache/live/`. At each snapshot every bundle is checked at the real best bid and ask, walking
  the depth while each extra contract still locks in money after both fees. Reported: snapshots, bundles, violations
  that are **arbitrages** (money locked in for at least 1 contract), the dollars locked in, the size, and how many
  consecutive snapshots each lasted. Polymarket's minimum order (5 contracts) is reported against the size.

## 4. Part (b): propagation (monotone pairs only)

- **Jump**: a rung's mid moves 3+ points between minute t − 5 and t, both mids fresh; one jump per rung per hour.
- **Sibling**: each adjacent rung of the same ladder. Its move from t to t + 5, 15, 30, 60 minutes, signed by the jump
  (positive = follows). Also its move over the jump's own 5 minutes. Interval by bootstrap over New York dates.
  One-of-many sets are left out: the sibling's expected direction is not fixed.
- **The trade P0 (primary)**: one minute after the jump is seen (t + 1), trade the sibling in the jump's direction at
  mid ± half-spread + fee; exit 60 minutes later the same way. Sibling mid between 3% and 97% at entry. Cap: 10 new
  trades a day, largest jumps first. Variant **P1**: only siblings that moved less than half the jump during the jump's
  5 minutes (the "laggard" filter). Both at 1× and 2× costs. Print check on the entry.

## 5. In-sample and out-of-sample

The history window is 2025-10-01 to 2026-10-03. Out-of-sample is the most recent 20% by date: from **2026-07-22**
(New York). Intervals: bootstrap over New York dates (2,000 draws), since several bundles on one date are one bet.

## 6. Success (all must hold)

- **Violations, history**: print-verified violation trades at 1× costs net positive per trade, date-bootstrap 95%
  interval above 0 in-sample, positive out-of-sample, at least 30 out-of-sample trades on 5+ dates.
- **Propagation**: P0 at 1× costs has an interval above 0 in-sample, a positive mean out-of-sample on 30+ trades and
  5+ dates, and is positive at 2× costs over the whole sample.
- **Live**: no pass/fail line; counts, dollars locked in and size are the result.
- A Sharpe above 3 is hunted for a bug before it is reported. Every variant is reported.

## 7. Data

- One-minute mids: S5's cache (148 markets) and S9's cache (weekend windows) are reused; the rest are pulled with
  `s1_twin_spread.data.pm_history` at 2.5 requests a second at most, from 2025-10-01 or the market's start to its end
  or 2026-10-03, every date and strike ladder leg first, then one-of-many sets whole, largest event first, 2,500
  markets at most. Results (resolved YES or NO) are read from the catalogue after closing.
- Prints: `s1_twin_spread.data.pm_trades`, two pages (20,000 prints) per market, only for legs of trades.

## Amendments

**1. Sat 2026-10-03 23:00 New York time: the year of a date without one.** The first live snapshot (22:51) showed a
"violation" of 10 points on "Iran leadership change by June 30, 2027?" against "... by December 31?". It was a bug in
the bundle rule, not a mispricing: a date phrase without a year took the year of the market's end date, and an end date
of 2027-01-01 04:59 UTC (midnight New York) made "December 31" into 2027-12-31, out of order. Rule now: if the phrase has
no year and the date it gives falls more than 7 days after the market's end date, the year before is used. Both lists
were rebuilt (the live list is re-read, so its events are those open at 23:00); the 22:51 snapshot is discarded
(`.cache/live_v0/`). No history price had been read. History list: 100 date ladders (was 99), 50 strike, 83 one-of-many.

**2. Sat 2026-10-03 23:20 New York time: fewer one-of-many histories.** The price-history server served about 1.3
requests a second in the first 20 minutes (52 markets), shared with the other sessions. All 2,341 planned markets would
take about 4 hours. The cap on new pulls is cut from 2,500 to 1,400 markets: every date and strike ladder leg (883
markets, about 4,400 requests) is kept; one-of-many sets are pulled whole, largest event first, until the cap. The rule
that picks the sets is unchanged. No history price had been read by the analysis.
