# S14: is the missing edge a link problem, a signal problem, or neither? (pre-registered diagnostic)

**Question (Theo's).** Eight studies found a real relation between prediction-market odds and linked assets, and no
trade that pays. Is that because the links between questions and assets are wrong, because the signal is measured
badly, or because the information is already in the price when the asset can be traded?

Each explanation predicts something different, and the cached S4 and S5 data can tell them apart:

- **If the links are the bottleneck,** some links carry a move *after the open* and others do not, and a better
  linker could find them. Then (C1) the links that showed the strongest after-open relation in the first 80% of the
  sessions should keep it in the last 20%, and (C2) more links should show a strong after-open relation than chance
  alone produces.
- **If the signal is measured badly,** a different definition of the odds move should show an after-open relation
  that the plain one misses (C3).
- **If neither,** the opening gap carries the whole relation under every link choice and every definition.

This file and `config.py` are committed **before any of these quantities is computed**. This is a diagnostic, not a
strategy: no trade, no P&L. Every rule is fixed; the result is reported whatever it shows.

## 0. What was known before this commit

- Pooled over all links: the opening gap responds to the overnight odds move (+6.88 bp per point, t = 6.01, S5); the
  move after the open does not (−0.55, t = −0.74). On links that pass S4's walk-forward gate the trade lost money.
- The link benchmark: about 40% of testable links are confirmed on the gap; oil 88%, Fed 13%, US politics 0%.
- **Not seen:** the after-open relation link by link; whether hindsight-chosen links persist; any alternative
  definition of the odds move.

## 1. Data

The 254 links of S8 (S5's agreed links and S4's agreed event links, SPY links dropped), the cached one-minute odds
and five-minute bars, 253 sessions from 2025-10-01 to 2026-10-02. For each link and session, as in S5: `x` = the odds
move from the previous close to 09:29 in points, signed by the link direction; `gap` = the asset's move from the
previous close to the open in excess of β × SPY, in bp; `after` = its excess move from the open to the close.
In-sample = the first 80% of sessions; out-of-sample = the last 20%.

## 2. Tests

**Per-link statistic.** For a link with at least 30 sessions on which the odds moved (`x ≠ 0`) in the sample used:
the through-origin slope of the outcome on `x` and its t with heteroskedasticity-robust errors.

- **C1, the oracle link.** Using in-sample sessions only, pick the links whose after-open t is at least +2
  ("continuation") or at most −2 ("reversal"). This is the best selection a linker could make for the trade, made
  with hindsight. Then, out-of-sample only: the pooled slope of `after` on `x` for each group, errors clustered by
  date; and the combined slope with reversal links' `x` flipped. Persistence means a combined slope above zero with
  t ≥ 2. Also reported: the same for the top and bottom tenth of links by in-sample after-open t.
- **C2, more strong links than chance?** Over the whole sample: the share of links with after-open |t| ≥ 2, and the
  mean |t| of the top tenth. The same two numbers under 500 shuffles of each link's `x` across its own sessions (the
  shuffle keeps each link's odds moves and each asset's returns and breaks only their pairing). Reported with the
  share of shuffles that reach the observed value. **Positive control:** the same for the gap, where the relation is
  known to exist: share of links with gap t ≥ 2 against its shuffle distribution.
- **C3, other definitions of the signal.** Pooled slopes, errors clustered by date, of the gap and of the after-open
  move on four definitions of the overnight odds move:
  1. points, previous close to 09:29 (the one used everywhere so far);
  2. log-odds: the change in ln(p / (1 − p)) over the same span, with p clipped to 1% and 99%;
  3. the early part of the night only: previous close to 08:00, in points;
  4. the late part only: 08:00 to 09:29, in points (news the pre-market has had the least time to absorb).
  Each also on weekends only. With eight after-open slopes, a definition counts as showing something only at |t| ≥ 3.

## 3. How the answer is read (fixed now)

- **"The links are the bottleneck"** needs C1's combined out-of-sample slope above zero with t ≥ 2, or C2's observed
  after-open share beyond 95% of the shuffles.
- **"The signal is measured badly"** needs an after-open slope with |t| ≥ 3 under definitions 2, 3 or 4.
- **Otherwise the answer is "neither":** the relation is real (the positive control must show it) and it is in the
  price at the open whatever the link and whatever the definition.

## Outputs

`research/results/s14_link_ceiling/`: `SUMMARY.md`, `tests.csv`, `links.csv`, `RUN_LOG.md`.

## Amendments

None.
