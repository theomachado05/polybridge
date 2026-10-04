# S24: the ladder trade on fresh ladders

Pre-registered Sun 2026-10-04, about 02:00 New York time, before any print or price of these markets is pulled.
Every number below is fixed in [`config.py`](config.py). Changes after this commit go under "Amendments", dated.

## 0. The question

A ladder is a set of questions that logic puts in order. "US strikes Iran by Jan 15" can never be worth more than
"... by Jan 16". "Bitcoin above $120,000" can never be worth more than "Bitcoin above $110,000" on the same day.
When public trade prints show the ladder out of order, sell the rich rung and buy the cheap one, and hold both to the
result.

**Does that trade hold on ladders S11 never used, with at least 30 out-of-sample trades, and how much money does it
carry?**

## 1. What is already known

Everything in S11's summary (`research/results/s11_bundles/SUMMARY.md`, commit `94becab`):

- S11's print-verified ladder trade earned **+3.89 points per trade** at 1× costs (95% interval over dates
  [+2.49, +5.43]), Sharpe 4.64, on 99 trades on 71 dates, and +4.34 [+2.62, +6.20] at 2× costs.
- Out-of-sample it was +3.24 [+0.62, +7.09], but on **11 trades**, against the 30 its rule required. Not a pass.
- At 100 contracts a leg the year made **$385** ($214 of it locked in at entry). At the full printed size the entry
  edge was up to $7,962 (an upper bound: a few very large prints, and both legs assumed filled together).
- **Most mid-price violations were not real**: 965 of 1,425 had no print at the price, 361 could not be checked.
  This is why S24 detects from prints, never from mids.
- The verified trades **clustered in fast news**: Iran strikes, Hormuz, Venezuela, the silver and oil spikes.
- **Each leg's print was within 10 minutes**, so the two legs were not proven at the same instant.
- **4 S11 trades broke the ladder's order at the result** (the earlier date resolved YES and the later one NO), all
  unverified or uncheckable. Rungs that look the same can have different creation windows or resolution sources.
- **Tonight's live books** (real bid and ask, after fees) showed 2 arbitrages worth $0.14.
- Held to the result, the pair cannot lose more than its entry cost if the ladder's order holds.

S11 is the only result in the project that is positive in-sample, out-of-sample and at doubled costs at prices that
traded. Its weakness is the count. No print or price of any market in the two sets below has been seen by anyone in
this project: S11's markets, and every market another study has cached, are removed by rule (section 2).

## 2. The lists (catalogue text and metadata only; `universe.py`, list in `ladders.json`)

Built by S11's own rules (`s11_bundles.universe.date_ladders` and `strike_ladders`, imported, not copied), within one
event, from the question text. Every price field of the catalogue record is dropped before anything is stored (the
code asserts it). Date ladders and strike ladders only. No one-of-many sets.

- **Date ladder** (S11's rule). Questions that are word for word the same once the last date phrase is replaced, with
  the date after "by" or "before". Rich rung = the earlier date. Two rungs on one date: the ladder is dropped.
- **Strike ladder** (S11's rule). Questions that are word for word the same once the one level is replaced, with an up
  word or a down word (S11's lists). Up: the higher level is the rich rung. Down: the lower level is the rich rung.
- **Pairs**: neighbouring rungs of a ladder, as S11.

Two fresh sets, never mixed in one ladder:

- **Set (a): before S11's year.** Rungs listed (catalogue `startDate`, else `createdAt`) from 2024-01-01 to 2025-09-30,
  catalogue volume $50,000 or more (S11's floor).
- **Set (b): S11's year, below S11's floor.** Rungs listed from 2025-10-01 to 2026-10-03, volume at least $10,000 and
  under $50,000.

What S24 adds to S11's rules. All from text and metadata, all fixed before any print:

1. **Fresh only.** Every market in S11's two lists (`bundles.json`, 2,564 markets; `live_bundles.json`, 888) is
   removed before a ladder is built. So is every market whose prices or prints any other study of this project has
   cached (file names in the other studies' `.cache` folders), and every condition id that appears in another study's
   list. A ladder is then built from what is left; rungs that are no longer neighbours are still in logical order.
2. **Yes/No markets only.** The trade is written in YES terms, so a rung must have the outcomes "Yes" and "No".
3. **A strike ladder has one deadline.** S11's strike template drops the date phrase, so "reach $100 by June 30" and
   "reach $120 by December 31" would be one ladder. That pair has no logical order. Rungs are grouped by their date
   phrase first; S11's rule is applied inside each group.
4. **"Or lower" must agree with the direction.** S11 reads "reach 3.0% or lower" as an up ladder because of the word
   "reach"; the words after the level say down. A strike template whose "or lower / less / fewer / below / under" or
   "or higher / more / above / greater / over" contradicts S11's direction is left out. Found by reading every
   template shape of the list (text only) before this commit; it removed 1 ladder ("Will the Fed's lower bound reach
   ... or lower before 2027?"). No other shape read as out of order. No rung is a one-of-many (negRisk) market.

**Reading the catalogue.** `gamma-api.polymarket.com/events`, ordered by event volume, largest first, 100 a page, in
two queries by event start date: 2024-01-01 to 2025-09-30 and 2025-10-01 to 2026-10-03. Each event read is tested for
both sets. The catalogue serves no offset above about 2,000, so each query restarts below the last volume it reached.
Page caps: 60 pages for the first query, 380 for the second (set (a) fills its print budget from far fewer events).

**The lists as built** (Sun 01:49 to 01:57 New York time, 440 requests; `ladders.json`):

| Set | Events read | Ladders | Date | Strike | Rungs | Pairs | Events with a ladder |
|---|---|---|---|---|---|---|---|
| (a) listed 2024-01-01 to 2025-09-30, volume $50,000+ | 5,998 (down to an event volume of $289,305) | 214 | 35 | 179 | 918 | 704 | 183 |
| (b) listed 2025-10-01 to 2026-10-03, volume $10,000 to $50,000 | 37,988 (down to $169,507) | 1,309 | 126 | 1,183 | 5,231 | 3,922 | 1,128 |

Both queries stopped at their page cap, so smaller events were not read; that is a limit of the list, stated here.
Removed as already seen: 10,258 market ids and 5,681 condition ids (S11's lists and the other studies' caches and
lists). Most ladders are crypto price ladders ("Will the price of Bitcoin be above ... on ...?" and the same for other
coins); the rest are geopolitics, AI releases, stock closes, word counts and player statistics.

A first run of the catalogue reading (01:48, 44 requests) used plain offsets and stopped at 2,100 events a query,
because the catalogue serves no deeper offset. Its list was replaced. The page caps were chosen after it, from ladder
counts alone. Requests so far: 488 of 3,000 (4 probes, 44, 440).

## 3. Detection, from prints only

Prints: `data-api.polymarket.com/trades` with `market=<conditionId>`, `limit=10000`, `offset=0` and `10000`: S11's own
call. The API serves a market's latest 20,000 prints only. Each print has the taker's side.

- **YES terms, as S11.** A taker who buys NO at p sells YES at 1 − p. A taker who sells NO at p buys YES at 1 − p.
- **A match** is a taker SELL of YES on the rich rung at price a and a taker BUY of YES on the cheap rung at price b,
  **within 10 minutes of each other**, with `a − b > fee_rich(a) + fee_cheap(b)` (each market's own taker fee,
  `rate × (p(1−p))^exponent`, as S11). No mid price is used anywhere.
- Both prints must be **before either rung closed** (catalogue `closedTime`).
- Both fills must exist at 1× and at 2× costs: the sale print is at least 2.1 cents and the purchase print at most
  97.9 cents (fills are one or two cents worse and must stay between 0.1 and 99.9 cents).
- **One trade per pair per New York day: the first match to complete.** A match completes at its later print. The
  later print is matched with the most recent print of the other rung that qualifies with it. Several matches
  completing in the same second: the smallest time difference, then the largest gap, then the largest size.
- **Variant W120:** the same with the two prints within 2 minutes.

## 4. The trade and its costs

- Sell YES on the rich rung **one cent below** the sale print. Buy YES on the cheap rung **one cent above** the
  purchase print. Hold both to the result. Per contract: `P&L = (sell − fee) − (buy + fee) + result_cheap − result_rich`.
  If the ladder's order holds, `result_cheap − result_rich` is 0 or 1, never −1.
- A 1-cent or 2-cent gap passes detection and then loses up to a cent after the one-cent haircut on each side. That is
  the rule as given; those trades stay in.
- **Size**: the smaller of the two printed sizes, capped at 100 contracts (primary); uncapped (capacity variant).
- **Costs 1×**: both markets' own taker fees at the fill prices. **2×**: fees doubled and each price one further cent
  worse (sell two cents below, buy two cents above). The 2× row is the **same trades** at worse costs. (S11 re-detected
  at 2×, which kept only the larger violations; this is the stricter reading.)
- **A pair without both results** (a rung still open tonight) is booked at its entry edge alone: the least it pays if
  the ladder's order holds. It is carried, with its capital, to 2026-10-04. Reported with and without these pairs.
- **Capital**: a pair contract ties up `(1 − sell) + buy + fees`, about $1, from the entry date to the day the later
  rung closes.
- Costs are reported in points (cents per contract) and in bp of the capital tied up. Source: each market's
  `feeSchedule` in the catalogue; the one-cent haircut is the brief's.

## 5. In-sample and out-of-sample

- **The split (the pass test).** Within each set, the dates (New York) that have a primary trade are sorted; the most
  recent 20% of them, rounded up, are out-of-sample. Trade dates are not in the catalogue, so the cut cannot be fixed
  before the pull. It is computed from the dates alone by `run detect`, which reads no result, written to
  `results/s24_ladder_fresh/oos_cut.json` and committed **before** `run settle` computes any P&L. Pooled
  out-of-sample = both sets' out-of-sample trades. The 2-minute variant uses the same cut dates.
- **A second split fixed now, from the calendar alone** (reported next to the first, never the pass test): set (a)
  from 2025-05-26 (the last 20% of its listing window, and everything later); set (b) from 2026-07-22 (S11's cut).
- Intervals: bootstrap over New York dates (2,000 draws, seed 24). Several pairs on one date are one bet.

## 6. Pass (all four must hold, on the pooled primary trades)

The unit is S11's: net points per contract per trade, every trade weighted equally.

1. **In-sample**, 1× costs: net profit per trade above zero and the 95% interval excludes zero.
2. **Out-of-sample**, 1× costs: net profit per trade above zero and the 95% interval excludes zero.
3. **The same trades at 2× costs**, whole sample: net profit per trade above zero.
4. **At least 30 out-of-sample trades on 10 or more dates.**

The summary says exactly which line fails, if any. Each set is also reported against the same four lines.

**What a pass would prove.** With S11, it would be the project's first replicated result at traded prices: on ladders
nobody had looked at, public prints again showed ladders out of order by more than the fees and two cents, often
enough to count, in-sample and out-of-sample.

**What a pass would not prove.** (i) That both legs could be filled at the same moment: the two prints are up to 10
minutes apart (2 in the variant), and in fast news a price can move that far in that time, which looks like a
violation and is not one. (ii) That our order would have been filled: a print proves that one taker traded at that
price, not that a second order of our size would have. (iii) That it scales: the size is the smaller print. (iv) That
the money is worth the capital: about $1 a contract is locked until the result.

## 7. What is reported

Trades, dates, pairs, events. Profit per trade with its interval, in-sample, out-of-sample, whole sample, at 1× and
2×. Total P&L at the capped and the uncapped size. Capital locked and for how long. A Sharpe on daily P&L over every
calendar day, maximum drawdown, worst month. The share of trades that resolved with the ladder's order violated (it
should be zero; each case is read and explained). How many pairs could not be fully checked because only the latest
20,000 prints are served. Set (a) against set (b). Date ladders against strike ladders.

- **Daily P&L (primary)**: a trade's P&L is booked on the day the pair is settled; its capital is locked from entry to
  that day; the capital base is the most capital locked at once. Sharpe = mean daily return / its standard deviation
  × √365, over every calendar day from the first entry to the last day.
- **S11's convention** is reported next to it for comparison: P&L booked on the entry date, capital base = the most
  capital opened in one day.

**Every variant, fixed now:** primary (10 minutes, 100-contract cap, 1×); 2× costs; W120 (2 minutes); uncapped size;
trades with a positive entry edge after the haircut only ("locked at entry"); resolved pairs only; the calendar
split; S11's Sharpe convention; set (a) and set (b); date and strike ladders. Nothing else will be tried. Anything
looked at after the run goes under a heading that says so.

## 8. The pull

- **Polymarket only.** One worker, at most one request a second in all (`net.py`), cached in `.cache/`, resumable.
  No one-minute price histories. No Kalshi calls.
- **Budget: 3,000 requests in all**, the catalogue reading and four probes included. Prints: 2,400 at most.
- **Order, fixed here: largest event volume first** (ties: event slug, kind, template; the order of `ladders.json`).
  The two sets take turns, one ladder each. A ladder is pulled whole (every rung) or not at all. A set stops at the
  first ladder that might not fit in its 1,200 requests (two requests a rung not yet cached, the worst case). When
  both have stopped, what is left of the 2,400 is spent the same way, in turns.
- **Deadline:** no ladder is started after 03:40 New York time. Everything left out is reported.
- **Results** (YES or NO) are read from the catalogue after the prints, 60 markets a request.
- **The recorder.** `research/forward/recorder.log` is read, never written. The count of `fetch failed` lines is taken
  before the pull and every 20 requests. If it grows by more than 5, the pull pauses two minutes and goes on at one
  request every two seconds.
- Only prints of ladder rungs are kept (time, price, side, outcome, size).

## 9. A Sharpe above 3

A pair that cannot lose makes a high Sharpe by construction, and so does a bug. Before any such number is reported:
the trades are read one by one; each pair's wording is checked for a real logical order ("by" against "on", dates,
levels, directions, resolution windows); the two prints are checked against the stated sides (a taker sale of YES on
the rich rung, a taker purchase of YES on the cheap rung); no trade may use a print after a rung closed. A pair that
turns out not to be a ladder is a ladder-building error: it is reported, explained, and the result is shown with and
without it, under a heading that says it was looked at after the run.

## Amendments

None yet.
