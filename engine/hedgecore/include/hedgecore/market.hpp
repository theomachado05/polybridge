#pragma once
#include <array>
#include <cstdint>
#include <limits>
#include "hedgecore/types.hpp"

namespace hedgecore {

inline constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

enum class Venue : std::uint8_t { Poly = 0, Kalshi = 1 };
enum class Instrument : std::uint8_t { Equity = 0, PredYes = 1, PredNo = 2, Option = 3 };

struct BookLevel {
  double px = kNaN;
  double qty = kNaN;
};
constexpr int kDepth = 5;

struct MarketTick {
  std::int64_t ts_ns = 0;
  Venue venue = Venue::Poly;
  double yes_bid = kNaN, yes_ask = kNaN, no_bid = kNaN, no_ask = kNaN;
  BookLevel bids[kDepth], asks[kDepth];
  double p_other_venue = kNaN;
  double under_px = kNaN, under_bid = kNaN, under_ask = kNaN;
  double opt_mid = kNaN, opt_delta = kNaN, opt_iv = kNaN, opt_implied_prob = kNaN;
  double eightk_score = kNaN;
};

struct Intent {
  Action action = Action::Hold;
  Instrument instrument = Instrument::Equity;
  int side = 0;
  double qty = 0;
  double limit_px = kNaN;
  std::uint16_t reason = 0;
  double signal = kNaN;
  std::int64_t latency_ns = 0;
  Venue venue = Venue::Poly;
};

struct Position {
  double equity = 0, pred_yes = 0, pred_no = 0, option = 0;
  double shares_held = 0;
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

}
