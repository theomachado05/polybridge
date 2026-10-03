# Lead-lag method (pre-registered)

Question: in stress and news events, do prediction-market (PM) prices move before equity prices?
Status of the evidence: **case studies plus a pooled time-series test. Supporting evidence, not proof of causation.**

This file was written and committed **before any price series was fetched or any statistic was computed**. Every parameter below is fixed. If a parameter is changed later, the change goes in the "Amendments" section at the bottom with the reason, and the original value stays visible in git history.

## 1. Events (`events.yaml`)

- 32 candidate events: 17 **scheduled** FOMC statements (every meeting from 2024-09-18 to 2026-09-16, selected by calendar, not by outcome) and 15 **curated** stress or news events (list in `events.yaml`).
- Honest note on selection: the curated events were picked from the author's memory of well-known dates (election night, Liberation Day tariffs and the Apr 9 pause, TikTok ruling, Warsh nomination, and so on). The author knew roughly what happened on those days, but no price series had been looked at. Windows are wide on purpose so the date, not the minute, is the only thing chosen in advance.
- For each event: PM market (slug, condition id, **Yes** token id), window `[start, end)` in UTC, mapped instruments, `expected_sign`, and a one-line rationale.
- `expected_sign` is the sign of the equity move that the PM Yes-price rising should go with (+1 bullish for the primary instrument, -1 bearish). It was written from economic reasoning before looking at data. It is used to orient PM changes in the pooled test. For FOMC events the PM is the "No change" market for the **next** meeting (a rise means fewer cuts, hawkish, sign -1), because the same-meeting market is already near 0 or 1 at the statement.
- **Primary instrument = first in each event's `instruments` list.** All headline numbers use the primary instrument only. Other mapped instruments are computed and written to the CSVs but never chosen after the fact.
- Windows always sit inside the extended equity session (04:00-20:00 ET, the span of the Massive minute bars). A window where equities are closed cannot say anything about who moved first. Events whose important PM move happened while equities were closed (for example the Sunday-night shutdown vote of Nov 2025, the 2024 election results after 01:00 UTC, the Israel strike on Iran of Jun 2025) were left out for that reason, and the election event covers only the after-hours session.

## 2. Data

- PM: CLOB `prices-history?market=<token>&startTs&endTs&fidelity=1` (Yes token). At most one point per minute, not tick data.
- Equities: Massive `/v2/aggs/ticker/<T>/range/1/minute/<from>/<to>` (adjusted, extended hours included), via the existing client and its on-disk cache.
- Fetch range per event: `[window_start - 180 min, window_end]`. The 180-minute warm-up is used for rolling sigma and for lag construction only.
- No 8-K disclosure data and no option data are fetched.

## 3. Alignment

- 1-minute grid labelled by the **end** of the minute (UTC).
- Equity price at grid time g = close of the bar that started at g - 1 min. PM price at g = last CLOB point with timestamp <= g, carried forward. So both series use only information available at g.
- Equity is valid only between the first and last bar of each trading session in the fetch (forward-filled inside the session, never across the overnight gap). PM is valid from its first observation onward.
- Changes: equity `x_t = 1e4 * (ln P_t - ln P_{t-1})` (basis points per minute). PM `y_t = 100 * (p_t - p_{t-1})` (percentage points per minute). A change is missing if either price is invalid, which removes the overnight gap return.
- Oriented PM change: `y*_t = expected_sign * y_t`. A positive `y*` means "PM moved in the equity-bullish direction".

## 4. First significant move

For each series (equity x, PM y, with the PM change kept raw because the first-move time does not depend on orientation):

- `w = 3` minutes. `D_t` = sum of the last 3 one-minute changes (change in level over 3 minutes).
- `sigma_t` = standard deviation of one-minute changes over the trailing `L = 120` valid minutes ending at `t - 1` (at least 30 required), with floors: equity **0.5 bp/min**, PM **0.25 pp/min**.
- Significant at `t` if `|D_t| > k * sigma_t * sqrt(w)` with **`k = 4`**.
- Persistence (rejects flickers): the level at `t + 5` must be on the same side of the level at `t - 3` as `D_t`, by at least half of `|D_t|`. A candidate with fewer than 5 valid minutes after it is rejected.
- Search runs over `t in [window_start, window_end)`; the first minute that passes is the move time. It is the **detection** time (end of the 3-minute change window) for both series, so the lead is not biased by the detector.
- `lead_minutes = t_equity - t_pm`. **Positive means PM first.** Classification: `PM first` if lead > 1, `simultaneous` if |lead| <= 1, `equity first` if lead < -1. If a series has no significant move the lead is NA and the event is listed as such.
- Sensitivity only (not headline): `k = 3` and `k = 5`.
- Equity-first events stay in every table and are listed in their own section of the summary.

## 5. Cross-correlation lag

- Series: `x_t` and `y*_t` (minute changes) restricted to window minutes where both are valid. Need n >= 60.
- `rho(l) = corr(x_t, y*_{t-l})` for `l = -30..+30`. Positive `l` means PM leads.
- Peak lag = `argmax_l |rho(l)|` (ties go to the smaller `|l|`). Also reported: the peak value with its sign and whether `|rho| > 2/sqrt(n)`.
- Lead-mass summary: mean `rho` over `l = 1..10` (PM leads) against `l = -10..-1` (equity leads).

## 6. Pooled time-series test

Sample: primary instrument of every usable event, rows `t in [window_start, window_end)`. Series are scaled per event to z-units (divide by that event's standard deviation over warm-up plus window) so volatile events do not dominate. PM is oriented by `expected_sign`.

- **Regression A (PM leads equity):** `x_{e,t} = a_e + sum_{l=1..30} b_l * y*_{e,t-l} + u`. Event fixed effects by within-event demeaning. Standard errors: Newey-West / Bartlett kernel, **30 lags**, computed inside each event and summed across events (no cross-event lags), with small-sample factor `N/(N-K)`. Reported: each `b_l` with t-stat, `sum b_l` (cumulative response) with its HAC SE, and the joint Wald test of all 30 `b_l = 0` (chi-square, 30 df).
- **Regression B (equity leads PM):** the same with roles swapped: `y*_{e,t} = a_e + sum_{l=1..30} c_l * x_{e,t-l} + u`.
- **Granger-style F tests, both directions**, with event fixed effects: restricted model = own lags only, unrestricted = own lags plus the other series' lags. **p = 10 is the primary** (reported in the headline); p = 30 is a pre-declared robustness check. The F statistic uses df `(p, N - 2p - E)` (E events). A HAC Wald version of the same restriction is reported next to it.
- **Subsets** (all pre-declared): all usable events; scheduled FOMC only; curated only. **Robustness**: leave-one-event-out range of `sum b_l` in Regression A.
- **Headline decision rule (written now, applied later).** The headline is the two primary Granger F tests (p = 10, all usable events), each judged at 5% with no multiplicity adjustment. "Supports PM leading" requires the PM-to-equity test to be significant and the equity-to-PM test either not significant or clearly weaker (smaller F). Anything else is reported as "no evidence" or "mixed" in the words of the result. Case-level lead counts (section 4) are descriptive, not tests, except a two-sided exact binomial sign test of PM first vs equity first among events where both series moved and the lead is not "simultaneous".

## 7. Usability rules (an event is dropped if it fails; the reason is recorded)

1. PM history: at least 30 CLOB points in the window and at least 10 window minutes with a nonzero PM change. Otherwise `no minute history` or `PM too flat`.
2. Equity primary: bars cover at least 70% of valid window minutes, and at least 80% of the window minutes are valid. Otherwise `thin equity data`.
3. At least 60 minutes where both changes are valid. Otherwise `too little overlap`.
4. Both HTTP fetches succeed. Otherwise `fetch failed` with the error.

An event with no significant move in one series is **kept** (usable for xcorr and the regression); only its lead is NA.

## 8. Caveats stated in advance

- Several events share a PM market (the 2025 recession market appears four times, Russia-Ukraine twice) and several FOMC markets are related, so events are not independent. Event fixed effects and per-event HAC handle serial correlation inside an event, not dependence across events.
- PM one-minute history is stale in quiet minutes and moves in 0.1-1 pp ticks. This lowers measured PM-to-equity correlation and makes first-move times coarse.
- Equity ETFs trade on futures and options-driven price discovery that this study cannot see. Equities "moving first" or "second" is relative to the PM series only.
- Sampling phase (see Amendment 3): CLOB points are snapshots a few seconds past each minute and are assigned to the next minute-end grid point, while the equity grid value includes trades to :59, so PM is on average about 45-55 seconds staler than equity. This biases first-move leads against the PM.
- Event-time detection with k = 4 on very different volatility regimes is a rule, not a truth. The sensitivity run exists to show how much the answer depends on it.

## Amendments

1. **Net-displacement condition in the first-move rule (section 4).** Found by a synthetic unit test (a one-minute spike that reverts) **before any real price series was fetched**: the reverse leg of a spike looked "persistent" because its 3-minute base sat inside the spike. The rule now also requires the level at `t` to differ from the level at `t - 2w` (6 minutes back) in the same direction by at least half of `|D_t|`. No other parameter changed. The code constant is `persist_frac = 0.5` for both persistence checks.
2. **Exploratory additions after the first full run (headline rule unchanged).** The first full run showed a large gap between the classical Granger F for equity-to-PM (p about 2e-12) and its HAC Wald version (p about 0.07). Because of that gap, the summary now (a) states the HAC-robust reading next to the pre-set verdict, (b) adds sign-free per-event Granger tests (p = 10, both directions, count of events significant at 5% and Fisher-combined p), because the pooled regressions assume the pre-set sign is right for every event. These are labelled exploratory in `SUMMARY.md`. The decision rule in section 6 was not changed and its verdict is still printed first.
3. **Sampling-phase caveat and descriptive additions (headline rule unchanged; added after the first run, in response to review).** Cached CLOB points are snapshots stamped about 4-17 s past each minute. `ceil()` assigns them to the next minute-end, while the equity value at that grid point includes trades up to :59, so the PM series is about 45-55 s staler than equity on average. This is not look-ahead, but it biases leads against the PM; with `sim_tol = 1`, three of the nine 'equity first' events sit at exactly -2 minutes. No parameter was changed. `SUMMARY.md` now carries (a) a descriptive sensitivity row with `sim_tol = 2`, (b) descriptive columns for each first move relative to the event anchor and the equity session (RTH or extended hours) with a count of moves that precede the anchor, and (c) a plain-reading line built from every HAC statistic declared in section 6 (Granger HAC Wald, Regression A/B joint Wald and cumulative t, all subsets) rather than from the Granger HAC Wald alone. The headline decision rule (section 6) and the first-move rule (section 4) are untouched.
