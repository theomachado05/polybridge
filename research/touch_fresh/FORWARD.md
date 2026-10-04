# touch_fresh forward test: the S21 seller rule on "will it hit" markets listed from 2026-10-05

Committed Sun 2026-10-04 with `forward_config.py` and `forward.py`, before any market it covers exists and whatever the
historical run (`METHOD.md`) shows. Changes go under "Amendments", dated, never rewritten.

## Markets

Every stock and S&P 500 "will it hit $X" market under Polymarket's `hit-price` tag whose listing time (`startDate`) is at
or after 2026-10-05 00:00 New York, chosen by `touch_fresh.universe`'s title rules (asset class, exclusion lists, S21's
parser), with a window that ends after its first weekend's Friday. A market enters the book only if its traded volume is
at least $10,000 at the Sunday 20:00 snapshot (read before any result; no event floor). One entry per market, on its
first weekend.

## The rule, per market, in real time

1. **Friday 15:55 New York** (12:55 on a half session): catalogue snapshot; for each eligible market, S21's option anchor
   with the matched horizon exactly as `METHOD.md` section 3: the listed expiry nearest the window's last session day
   (either side, within 45 days, ties to the later), the bracketing vertical spread from Massive NBBO quotes,
   `p_T` = its finish-beyond probability, and the central anchor
   `touch = min(1, 2 Φ(−Φ⁻¹(1 − p_T) √(T/τ)))`, T and τ in calendar days from the anchor day to the expiry and to the
   window's last session day. The underlying's NBBO is recorded at the same instant.
2. **Friday 20:00 to Sunday 20:00:** the taker prints (data API). `sell_price` = size-weighted YES price of takers who sold
   YES. Size-weighted price of all prints outside 2% to 98%: out.
3. **Trade:** sell YES at `sell_price` when `100 × (sell_price − touch) ≥ 5`. Hold to the result. P&L per contract
   `100 × (sell_price − fee − result)`, the market's own fee schedule at 1× and 2×.

Every stage is logged append-only (`forward_log/`) with its UTC time before the next stage starts, so the anchor is on
record before the prints and both before the result.

## Pass rule

Evaluated once, when at least 30 B0 markets in 15 events have resolved, or on 2027-06-30, whichever comes first. **Pass:**
the event-clustered bootstrap 95% interval (2,000 draws, seed 0) of mean P&L per contract lies above zero at fee 1× and at
fee 2×. Fewer than 30 markets or 15 events by 2027-06-30: INSUFFICIENT. Otherwise FAIL. Also reported, no pass line: the
unfiltered seller book, the delta-hedged B0 of `METHOD.md` section 3, the regression on the underlying's directional move,
and B0 by weekly and monthly events.

## Runner

`python -m touch_fresh.forward snapshot` (Friday 15:55), `prints` (Sunday after 20:00), `evaluate` (any time; prints the
verdict only once the minimum is met or the date has passed). The stub reuses `touch_fresh.universe`, `touch_fresh.pull`
and `touch_fresh.run` unchanged.

## Amendments
