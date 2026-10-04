# S4: prediction-market odds against the equity they move (pre-registered)

**Question.** A prediction market about an event and a stock or ETF whose value depends on that event should move
together. They do not trade the same hours: Polymarket trades through nights and weekends, the equity does not. When
the odds move while the equity is closed, does the equity keep catching up after the open, enough to trade net of
costs? And in the other direction: when the equity moves during its session, do the odds catch up afterwards?

None of this is testable unless each question is tied to the right equity, in the right direction. So the study has
two parts: a **link agent** that decides which links are trusted, and a **backtest** that trades only those.

This file and `config.py` are committed **before any price is pulled for the test sample**. Every rule is fixed.
Changes go under "Amendments", dated. The run is reported whatever it shows.

## 0. What was known before this commit

- `backend/app/data/ai_map.json` (2026-10-03 01:22): 230 markets, 133 with at least one equity link, 404 links, 65
  tickers. Each link has a ticker, a direction (`up_on_yes` or `down_on_yes`) and an impact guess. It was written by
  a language model from the question text. **No link was ever checked against prices.**
- Earlier closure studies tied prediction markets to SPY, not to each question's own asset: the 380-closure relation
  did not replicate, and at the Monday open options had caught up 0.44 of the weekend move with nothing left after
  costs (`research/EVIDENCE.md`). The market-hours lead-lag study leaned toward equities moving first.
- **The motivating example, seen before this commit:** the Brazil first-round markets against EWZ, 18 sessions
  (2026-09-08 to 2026-10-02). Flávio Bolsonaro "most votes" went from 0.13 to 0.24 at the Friday close and to 0.40 by
  Saturday night; EWZ went from 38.62 to 38.21. Correlation of the overnight odds move with the EWZ gap +0.37; with
  the EWZ move after the open −0.17 (n = 18). The Brazil markets are therefore **kept out of the test** and shown
  separately as an illustration.
- **Not seen:** any price of any other linked market against its equity.

## 1. The link agent (three stages, in this order)

1. **Proposer (exists).** The links of `ai_map.json` as committed. Polymarket markets only (120 of the 133 linked
   markets); the 13 Kalshi ones are left out to keep one price source.
2. **Blind critic (new).** A second model reads only the question and a menu of the 65 tickers. It does not see the
   proposer's answer. For each question it names up to three tickers with a direction, or none, and classes the
   question as **event** (an outcome in the world that changes an asset's value) or **spot proxy** (the question is
   itself about the price of a traded asset: "Bitcoin above X", "oil above X"). A link is **agreed** when the critic
   independently names the same ticker with the same direction.
3. **Data gate (no model).** A link is **confirmed** on day `t` only if, on its own sessions strictly before `t`, the
   equity and the odds have moved together in the proposed direction: 30-minute bins of the regular session, the
   equity's excess return (bp) regressed through the origin on the direction-signed change in odds (pp), at least 60
   bins with a non-zero change in odds on at least 5 sessions, slope above zero, and a t-statistic of at least 2 with
   errors clustered by session. The slope is the link's **measured sensitivity** (bp per pp). It replaces the
   proposer's impact guess, which is not used anywhere.

A link is **trusted** on day `t` when it is agreed and confirmed. The gate walks forward: a link can become trusted
and can lose it.

## 2. Data

- **Window:** sessions from 2026-01-02 to 2026-10-02.
- **Odds:** Polymarket CLOB `prices-history`, 1-minute, over each market's life. The price at an instant is the last
  point at or before it, at most 30 minutes old; otherwise missing.
- **Equities:** Massive 1-minute bars (regular session) and daily bars, for the linked tickers and SPY.
- **Excess return:** the equity's return less `β ×` SPY's over the same interval. `β` is the OLS slope of daily
  close-to-close returns on SPY's over the 60 sessions before the day (at least 20, else 1).
- **Signed change in odds:** `x = direction × Δp`, in pp; positive means good for the equity.
- **Instants (New York):** close 16:00 (or the early close), signal 09:29, open 09:30.
- One signal per ticker per day: the mean of `x` over its trusted links with a fresh price.

## 3. S4a, the trade: the equity catches up after a closure

- **Signal:** `x_night`, the signed change in odds from the previous close to 09:29, over every closure (overnight,
  weekend, holiday).
- **Entry:** if `|x_night| ≥ 2 pp`, at the 09:30 open take the equity in the direction of `x_night`, $10,000, and the
  opposite `β × $10,000` of SPY. At most 10 tickers a day, largest `|x_night|` first.
- **Exit:** the 16:00 close (primary) or 10:00 (variant). No overnight position.
- **Capital base:** $100,000. Daily return = the day's net P&L ÷ $100,000.
- **Costs per side, bp of notional:** SPY leg 1; liquid ETFs and stocks above $50 billion market value 2; all other
  tickers 5. This is half the quoted spread plus commission and fees, as in `research/strategy_backtest/METHOD.md`
  section 5 (Interactive Brokers tiered commission, SEC and FINRA fees), widened because fills are at the open. The
  class of each ticker is fixed in `config.py`. 2× costs doubles every figure.
- **Capacity:** the position against the dollar volume of the equity's first regular minute and first 30 minutes on
  signal days; capacity is the size at 5% of the median first-30-minute volume.

## 4. S4b, described not traded: the odds catch up after the equity moves

- For each trusted link and session: the equity's excess return over the session (open to close), and the signed
  change in odds over the following closure (close to next 09:29) and over the following 24 hours.
- Reported: the pooled through-origin slope and its interval, clustered by date, and the sign agreement.
- It is **not** turned into a P&L. Historical Polymarket prices are not executable prices (S1 showed how an assumed
  spread manufactures profit). A positive result here says where to point the live recorder next.

## 5. Variants (the complete list)

| id | links traded | families | exit |
|---|---|---|---|
| **V0, primary** | trusted (agreed and confirmed) | event | close |
| V1 | trusted | event | 10:00 |
| V2 | agreed only (no data gate) | event | close |
| V3 | trusted | event and spot proxy | close |
| V4 | every proposer link, unchecked | event and spot proxy | close |

V4 is the backtest without the link agent. The gap between V4 and V0 is what the agent is worth. Each variant is run
at 1× and 2× costs.

## 6. Segments, metrics, inference

- **Out-of-sample:** the most recent 20% of the sessions in the window. In-sample: the rest. The gate walks forward
  through both and never uses a day's own data or later data.
- **Per segment and variant:** trades, tickers, days with a trade, net P&L, mean net return per trade in bp, hit
  rate, Sharpe (daily returns on the $100,000 base, 252 days), maximum drawdown, worst month, turnover, costs in bp.
- **Inference:** mean net return per trade with a 95% bootstrap interval resampling **dates** (positions of one day
  share the market's move). The deflated Sharpe ratio uses 5 trials.
- **Also reported, not tradable:** the slope of the equity's excess gap on `x_night` (does the open line up with the
  odds), pooled and per family.
- A Sharpe above 3 starts the bug hunt before anything is reported: the signal uses nothing after 09:29; fills are
  the bar prices that printed; `β` and the gate use earlier days only; costs on both legs and both sides.

## 7. Success criterion (primary V0, fixed now)

A pass needs all of: at least 30 out-of-sample trades on at least 10 dates and 5 tickers; out-of-sample mean net
return per trade above zero with a date-bootstrap 95% interval excluding zero at 1× costs; still above zero at 2×
costs; in-sample mean net return per trade above zero. Anything else is a null or "too few observations" and is
reported as that.

## 8. Caveats known in advance

- The links come from language models. Agreement between two models is not truth; the data gate is the check, and it
  needs history that young markets do not have.
- Many linked markets are weeks old, so the trusted set may be small.
- Several markets link to one ticker and several tickers move together; inference is by date for that reason.
- Fills at the first regular bar's open stand for the opening auction. Slippage there is covered only by the cost
  figures.
- Spot-proxy questions restate a price that the equity market can see directly; they are kept out of the primary.

## Outputs

`research/results/s4_linked_assets/`: `SUMMARY.md`, `metrics.csv`, `equity_curve.png`, `drawdown.png`, `trades.csv`,
`capacity.md`, `RUN_LOG.md`, `links.csv` (every link with its three verdicts).

## Amendments

**Amendment 1, 2026-10-04 00:25 UTC, before any test-sample price was pulled: 5-minute equity bars.** Section 2 says
1-minute equity bars. One-minute bars for 66 tickers over nine months would not fit on the disk that is left.
Five-minute regular-session bars are used instead. Nothing in the rules changes: the open is the open of the 09:30
bar, the 10:00 exit is the close of the 09:55 bar, the 30-minute gate bins are six bars. The capacity figure of
section 3 uses the first five minutes instead of the first minute. Polymarket odds stay at 1 minute.

**Amendment 2, 2026-10-04 00:33 UTC, after the S4 run: an exploratory follow-up, S4c (pre-market).** The run showed
that the linked equity's opening gap lines up with the overnight move in odds and that nothing follows after 09:30.
The open question is whether the equity already reflects the odds *before* the open, in the pre-market, where it can
be traded. S4c was designed after seeing the S4 result, so it is **exploratory** and is not part of the success
criterion of section 7. Its rules, fixed before its data is pulled:
- **Entry:** the open of the first 5-minute pre-market bar starting between 08:00 and 08:30 New York time (no bar, no
  trade). **Signal:** the signed move in odds from the previous close to 07:59, `|x| ≥ 2 pp`, one signal per ticker,
  at most 10 a day. **Exit:** the 09:30 open. Beta hedge with SPY over the same interval.
- **Links:** reported for the agreed event links (the trusted set proved too small to say anything) and for the
  trusted event links.
- **Costs per side:** entry in the pre-market at 5 bp (liquid), 15 bp (other), 2 bp (SPY); exit at the open at the
  section 3 figures. These are assumptions: pre-market spreads are several times the regular session's. 2× doubles them.
- **Also reported:** the slope of the equity's excess move on the odds move, split into previous close to 08:00 and
  08:00 to the open; and the same for weekend closures alone.
