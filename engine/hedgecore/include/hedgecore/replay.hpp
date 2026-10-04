#pragma once
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
  std::size_t n_orders = 0;
  std::size_t n_fills = 0;
  std::size_t n_rejected = 0;
  double pnl = 0;
  double fees = 0;
  double max_dd = 0;
  double hedge_var_reduction = kNaN;
  double hedge_var_reduction_vs_static = kNaN;
  double avg_hedge_ratio = kNaN;
  double turnover = 0;
  std::int64_t p50_ns = 0, p99_ns = 0;
  std::size_t preset_index = 0;
  Params params{};
};

ReplayStats replay_algo(AnyAlgo& algo, const Position& pos, std::span<const MarketTick> ticks,
                        const FeeModel& fees = {});
ReplayStats replay(std::string_view family, const Params& params, const Position& pos,
                   std::span<const MarketTick> ticks, const FeeModel& fees = {});
std::vector<ReplayStats> replay_grid(std::string_view family, const Position& pos, std::span<const MarketTick> ticks,
                                     const FeeModel& fees = {});

double touch_price(Instrument inst, int side, Venue venue, const MarketTick& t, const FeeModel& fees) noexcept;
double mark_price(Instrument inst, Venue venue, const MarketTick& t) noexcept;

}
