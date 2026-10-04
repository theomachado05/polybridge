# S17: is the first minute of the session still pricing the night? (pre-registered)

Written Sat 2026-10-03 near midnight New York time, at Theo's request ("add on, explore any possible edge"), as the
companion of S16 (options after a big overnight odds move). Committed with `config.py` **before any one-minute bar or
stock quote is pulled**. Changes go under "Amendments", dated.

## 0. What is known before this commit

- S4, S5, S14: the linked asset opens where the odds moved overnight (+6.88 bp per point, t = 6.01); from the open to
  the close nothing more (−0.55 bp per point, t = −0.74). All of that used five-minute bars and **the open price**;
  nobody has looked inside the first five minutes.
- S8: the odds give back 2.63 points after a 10+ point move; whether the asset confirmed the move in its first bar
  does not tell which odds moves reverse. S8 asked whether the **odds** follow the asset. Nobody has asked whether
  the **asset** follows the odds when it opened against them.
- S16 (pre-registered 23:34, running in parallel): the options on these assets, from 09:31. It does not measure the
  underlying inside the first minutes.
- I have seen no one-minute bar and no stock quote for any of these mornings.

## 1. Events (the same rule as S16 section 1, so the two studies line up)

Every row of `results/s8_open_referee/mornings.csv` with |x| ≥ 10 (main) or ≥ 5 (variant), x = the overnight odds
move in points (previous 16:00 to 09:29). Expanded to one observation per (ticker, day) from its signed ticker list;
several questions on one ticker-day: the largest |x| (ties: lowest market id). **Direction** d = sign(x) × the
ticker's sign in the link (+1: the asset should go up). Out-of-sample = sessions from **2026-06-22** (S16's split).

## 2. Prices

Massive one-minute aggregates (adjusted, regular session) for the ticker and SPY that day; the previous close from
the cached daily bars (`day_<T>.npz`, S4/S5 caches). Signed excess return of a window, in bp:
d × (r_ticker − β × r_SPY), β = S4's `engine.betas` (daily, before the day). A ticker-day without a bar starting by
09:32 is dropped and counted.

Windows: **gap** (previous close to the 09:30 open, the positive control), **open→09:31**, **09:31→09:35**,
**09:35→10:00**, **10:00→close**, and **09:31→close** (primary for F1). "09:31" is the close of the 09:30 bar.

## 3. Questions

- **F1, the first-minute thesis.** For each window, the mean signed excess return over events (date bootstrap, 2,000
  draws, seed 0) and the slope on |x| (bp per point; through-origin, errors clustered by date). Positive after the
  open = the open had not finished pricing the night (continuation); negative = it over-shot (reversal).
- **F2, catch-up.** "Unconfirmed" = signed gap ≤ 0 (the asset opened flat or against the odds). The signed 09:31→close
  return of unconfirmed against confirmed events, difference with a date-bootstrap interval. Catch-up = unconfirmed
  above zero and above confirmed.

## 4. Trades at real quotes (pre-registered; every one reported)

Entry at the 09:31 NBBO (buy at the ask, sell short at the bid), exit at the opposite side of the NBBO at the exit
instant. Quotes must be at most 120 s old, stamped after 09:30:00, spread ≤ 100 bp; else the trade is dropped and
counted. $10,000 a trade; no commission; 2× costs = every half-spread doubled. Costs are the quoted spreads
themselves, reported in bp.

| id | side | which events | exit |
|---|---|---|---|
| **T1 (primary)** | follow the odds | all | 10:00 |
| T1f | fade (mirror of T1) | all | 10:00 |
| T2 | follow | all | 15:55 |
| T3 | follow | unconfirmed only (F2) | 15:55 |

Each at 10+ (primary) and 5+ points: 8 trials.

**Pass** (per trade, at 10+ points), all of: at least 30 out-of-sample trades; out-of-sample mean net return above
zero with a date-bootstrap interval excluding zero (1×); out-of-sample above zero at 2×; in-sample above zero. A pass
in one of eight trials is a lead to replicate, not an edge.

**Book:** each day's return = mean of that day's trades; zero on sessions without one. Sharpe (daily, × √252), max
drawdown, worst month, turnover. Equity curve and drawdown of T1. Sharpe above 3 starts a bug hunt (quote times,
splits, a wrong previous close).

## 5. Exploratory (labelled, never a verdict)

F1's primary window and T1 broken out by theme (oil: USO, XLE, XOP and other energy tickers; rates: SHY, IEF, TLT;
everything else), by nights (after a weekend or holiday, or not) and the 12 largest |x| since 2026-07-01 (what the
asset did in each window).

## 6. Pull

Massive only, at 1.5 requests a second (S16 pulls at 2), cached in `s17_first_minute/.cache/`. Order: 10+ bars, 10+
quotes, 5+ bars, 5+ quotes. The pull stops at 04:30 Sunday whatever is done; anything cut is labelled incomplete.

## Amendments

**Amendment 1, Sun 2026-10-04 about 00:05 New York time, before any event's bars or quotes were pulled.** The previous
close comes from the same one-minute request as the day (one call from the previous session to the event day, close
of the last regular-session bar), not from the cached daily bars: the minute bars are split-adjusted at pull time and
the daily cache was pulled earlier, so mixing them could fake a gap. Betas still use the daily cache (returns only).
Before this, one format probe was made (USO, 2026-09-30, one minute-bar call and one quote): no return computed.
