#pragma once
// Replay harness (for tuning, spec §3.3). Fills marketable orders at the touch (ask to buy, bid to sell) plus the
// FeeModel fee; a passive limit rests one tick and fills at its limit only if the next tick trades through it.
// hedge_var_reduction = 1 - var(hedged P&L changes) / var(unhedged P&L changes) of the user's shares_held, over ticks
// where under_px is known; NaN when shares_held <= 0 or there is no underlying price.
// hedge_var_reduction rewards ANY short of the underlying, signal or not: a static short of a fraction h of the shares
// scores 1 - (1 - h)^2 even when the PM series is constant. Read it next to avg_hedge_ratio (the mean short hedge as
// a fraction of shares_held over the scored intervals) and hedge_var_reduction_vs_static = 1 - var(hedged) /
// var(unhedged * (1 - avg_hedge_ratio)): the variance cut beyond what a static hedge of the same average size gives,
// i.e. what the PM signal adds (0 for a static hedge, negative when timing hurts; NaN when avg_hedge_ratio == 1).
// Equity orders with no live quote (under_bid / under_ask NaN, so priced off under_px, a bar close) are rejected out
// of the US regular session and until under_px has changed inside the session: a stale close is not a fill price.
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>
#include <vector>
#include "hedgecore/fees.hpp"
#include "hedgecore/library.hpp"
#include "hedgecore/market.hpp"

namespace hedgecore {

struct ReplayStats {
  std::size_t n_ticks = 0;
  std::size_t n_orders = 0;    // Order intents emitted
  std::size_t n_fills = 0;
  std::size_t n_rejected = 0;  // marketable orders with no price to fill at, or unfilled passive orders
  double pnl = 0;              // algo P&L net of fees, marked at the last known prices
  double fees = 0;
  double max_dd = 0;           // of the algo's mark-to-market equity
  double hedge_var_reduction = kNaN;
  double hedge_var_reduction_vs_static = kNaN;
  double avg_hedge_ratio = kNaN;
  double turnover = 0;         // sum of |qty| * px * multiplier
  std::int64_t p50_ns = 0, p99_ns = 0;  // on_tick latency, measured per tick around the call
  std::size_t preset_index = 0;
  Params params{};
};

ReplayStats replay_algo(AnyAlgo& algo, const Position& pos, std::span<const MarketTick> ticks,
                        const FeeModel& fees = {});
ReplayStats replay(std::string_view family, const Params& params, const Position& pos,
                   std::span<const MarketTick> ticks, const FeeModel& fees = {});
std::vector<ReplayStats> replay_grid(std::string_view family, const Position& pos, std::span<const MarketTick> ticks,
                                     const FeeModel& fees = {});

// Fill price at the touch for a marketable order; NaN when the tick has no price for that leg.
double touch_price(Instrument inst, int side, Venue venue, const MarketTick& t, const FeeModel& fees) noexcept;
// Mark price for valuing an open position; NaN when unknown.
double mark_price(Instrument inst, Venue venue, const MarketTick& t) noexcept;

}  // namespace hedgecore
