#pragma once
// Hot-path types shared by every block, algo family, the replay harness and the Python binding (spec v4 §3.3).
// NaN means "field not available". No block ever treats a missing field as 0.
#include <array>
#include <cstdint>
#include <limits>
#include "hedgecore/types.hpp"  // Action { Hold, Order }

namespace hedgecore {

inline constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

enum class Venue : std::uint8_t { Poly = 0, Kalshi = 1 };
enum class Instrument : std::uint8_t { Equity = 0, PredYes = 1, PredNo = 2, Option = 3 };

struct BookLevel {
  double px = kNaN;
  double qty = kNaN;
};
constexpr int kDepth = 5;

struct MarketTick {  // NaN = field not available (the default for every field)
  std::int64_t ts_ns = 0;
  Venue venue = Venue::Poly;
  double yes_bid = kNaN, yes_ask = kNaN, no_bid = kNaN, no_ask = kNaN;
  BookLevel bids[kDepth], asks[kDepth];  // YES book, best first
  double p_other_venue = kNaN;           // other venue's YES mid
  double under_px = kNaN, under_bid = kNaN, under_ask = kNaN;  // equity/ETF
  double opt_mid = kNaN, opt_delta = kNaN, opt_iv = kNaN, opt_implied_prob = kNaN;
  double eightk_score = kNaN;  // [-1, 1], 0 = none
};

struct Intent {
  Action action = Action::Hold;  // Hold | Order
  Instrument instrument = Instrument::Equity;
  int side = 0;          // +1 buy, -1 sell
  double qty = 0;        // > 0 on an Order
  double limit_px = kNaN;  // NaN = marketable
  std::uint16_t reason = 0;  // block-level reason code, see reasons.hpp
  double signal = kNaN;      // the value that triggered it (for the UI log)
  std::int64_t latency_ns = 0;
  // Addition to the §3.3 contract (trailing, defaulted): execution venue of a prediction-market leg as chosen by
  // the VenueRouter block. Ignored for Equity and Option intents.
  Venue venue = Venue::Poly;
};

struct Position {
  double equity = 0, pred_yes = 0, pred_no = 0, option = 0;  // signed; a short equity hedge is negative
  double shares_held = 0;  // the user's long underlying that a hedge family protects (never traded by an algo)
};

constexpr int kMaxParams = 8;
struct Params {
  std::array<double, kMaxParams> v{};
};

constexpr const char* to_string(Venue v) noexcept { return v == Venue::Poly ? "poly" : "kalshi"; }
constexpr const char* to_string(Instrument i) noexcept {
  switch (i) {
    case Instrument::Equity: return "equity";
    case Instrument::PredYes: return "pred_yes";
    case Instrument::PredNo: return "pred_no";
    case Instrument::Option: return "option";
  }
  return "unknown";
}

}  // namespace hedgecore
