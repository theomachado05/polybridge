#pragma once
#include <cstdint>
#include <string>

namespace hedgecore {

struct HedgeSpec {
  std::string ticker;
  double shares_held = 0;
  double target_coverage = 0.5;
  double band_shares = 10;
  double max_hedge_shares = 0;
  std::int64_t max_staleness_ns = 2'000'000'000;
  double sigma_k = 2.0;
  double sigma_alpha = 0.05;
  double gap_per_share = 0;
  double fee_per_share = 0.0035;
  double half_spread = 0.0;
  double min_benefit_ratio = 1.0;
};

struct Tick {
  std::int64_t ts_ns;
  double p;
};

enum class Action : std::uint8_t { Hold, Order };
enum class Reason : std::uint8_t { Invalid, Stale, BelowSigma, InsideBand, Rebalance, RiskCapped, BelowFees };

struct Decision {
  Action action;
  Reason reason;
  double order_qty;
  double target_hedge;
  double current_hedge;
  std::int64_t latency_ns;
};

const char* to_string(Reason r) noexcept;

}
