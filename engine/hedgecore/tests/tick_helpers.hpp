#pragma once
#include <cmath>
#include <cstdint>
#include <limits>
#include "hedgecore/market.hpp"
#include "hedgecore/util.hpp"

namespace hctest {
using namespace hedgecore;
inline constexpr std::int64_t kSec = 1'000'000'000;
inline constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

inline MarketTick pm(std::int64_t ts, double p, double hs = 0.005, double u = 100.0, double uhs = 0.01) {
  MarketTick t;
  t.ts_ns = ts;
  t.yes_bid = p - hs;
  t.yes_ask = p + hs;
  t.under_px = u;
  t.under_bid = u - uhs;
  t.under_ask = u + uhs;
  return t;
}
inline MarketTick with_book(MarketTick t, double bid_qty, double ask_qty, int levels = 5) {
  for (int i = 0; i < levels; ++i) {
    t.bids[i] = {t.yes_bid - 0.01 * i, bid_qty};
    t.asks[i] = {t.yes_ask + 0.01 * i, ask_qty};
  }
  return t;
}
}
