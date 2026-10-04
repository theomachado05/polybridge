# Confirmation specification for the barrier-ticket hypothesis

Prepared October 4, 2026 ET after reading the historical results. This is a
prospective specification and has not yet been executed. It does not turn the
selected historical bucket into an independent test. Any implementation changes
must be dated before the new observations they evaluate.

**Hypothesis:** first-weekend, medium-priced barrier YES tickets contain a
seller premium large enough to survive executable entry costs, funding and
event-level losses. The null is no positive net risk-adjusted excess return.
Insurance risk compensation and quote/oracle artifacts are alternative explanations.

**Pilot:** monthly SPY ETF high/low tickets only; source-specific regular-session
barriers with full versioned rule text. SPX index, weekly SPY and commodity
tickets remain separate controls/sleeves. Build the prospective universe from
metadata without future outcomes. Include eventual losers, unresolved tickets,
delayed refunds and disputes. Exclude an already-triggered barrier using only
source observations known at the decision time.

**Clock:** identify the first eligible weekend using the exchange holiday
calendar; the research convention is 20:00 America/New_York on the last session
day. At that instant and during the following 48 hours, record every eligible
contract and both direct outcome-token books with exchange/receive timestamps,
sequence gaps, minimum order size, depth and the applicable fee version. Do not
substitute a subsequently computed weekend VWAP for a causal entry quote.

**Candidate entry rule for replay:** at the first synchronized valid observation
of an eligible ticket's first weekend, buy NO only if the executable YES-equivalent
sale price `1 - ask_NO` lies in [0.50, 0.75). Quotes must be at most one second
old in exchange and receive time, with positive actual depth and a confirmed
minimum-size order. Observe a second fresh snapshot at least one second later;
the rule must still hold and use the second book's depth/price. One entry per
contract; never reuse a future trade print to decide fill size. A missing or
failed fill stays missing/failed. This operational rule differs from the old
48-hour observational VWAP, so its performance is currently unknown.

Use a fixed paper capital base of $10,000. Limit total entry cost plus fees to
5% of initial capital per underlying/source/month event and 25% across the
pilot; use integer quantities meeting venue minimums. Allocate in timestamp
order, with market ID as a deterministic same-time tie-break. No same-day
ranking using future signal strength. Retain the order rejections/cash constraints
in the denominator. This budget is a proposed validation setting, not a capacity
estimate or a live allocation recommendation.

**Portfolio:** buy NO using funded cash, hold to actual redemption, charge fees
at entry, mark all open positions daily at executable liquidation prices, and
retain idle days. Track free cash, pending settlement, fee rounding and actual
collateral-release delays. Charge a recorded contemporaneous funding rate.
Stress the *same entries and quantities* with doubled fees and execution
slippage; report a separately labeled entry-reselected sensitivity if needed.

**Risk controls and comparison:** keep each month/source event as one correlated
exposure rather than treating its strikes as independent bets. Report loss by
event, signed barrier direction and underlying. Test the paper's unhedged rule
first. A separate frozen option-hedged variant must charge both hedge spreads,
commissions, financing and rebalancing, and distinguish payoff replication from
a statistical hedge. Capture the specified source feed and its outage fallback;
SPY option/stock prices are not automatically the same as Pyth's candle extrema.

**Confirmation:** no best-subset selection on new outcomes. Use at least 30
independent underlying/source/month events and 60 complete daily NAV observations
before a Sharpe screen. Target net daily annualized Sharpe at least 1.5, positive
same-cohort doubled-total-cost P&L, positive event-and-calendar-block uncertainty
bound, and positive result after removing the largest winning event. Report
all versions and benchmark returns regardless of outcome. The current 51-event
historical cohort is discovery data; the new pilot has none of those confirmed
observations yet. Stress rare correlated barrier hits separately from empirical
bootstrap intervals. No data period or simulated result should be invented to
meet the sample target.
A SPY-only monthly pilot accumulates one underlying/source/month cluster per
month: reaching 30 such clusters can take about 30 months. More strikes do not
shorten that clock. Earlier operational evidence can validate the recorder,
cash ledger and execution assumptions, but cannot satisfy this statistical target.

**AI/C++ handoff:** AI produces versioned contract manifests/model proposals and
offline replay checks. Deterministic C++ verifies token identities, source/time
state, quote freshness, depth, integer sizing and cash/risk limits, and records
decision-to-submit and submit-to-fill timings. Freeze the model and parameters
before each new validation window. Measure local computation latency separately
from end-to-end fills and P&L. A strategy configuration change must replay against
contract/cash fixtures before activation.

No recorder was started, protected observations read, live orders placed or
original studies edited for this selection audit. Confirming the proposed rule
requires new causal data; the historical transaction-cohort Sharpe alone cannot
provide that confirmation.
