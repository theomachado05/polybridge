#pragma once
#include <cstdint>
#include <string>

namespace hedgecore {

// A hedge the user approved in the PolyBridge UI. hedgecore never sizes anything without one.
struct HedgeSpec {
  std::string ticker;
  double shares_held = 0;                         // N, the long position being protected
  double target_coverage = 0.5;                   // c in [0, 1]
  double band_shares = 10;                        // trade only if |h* - h| >= band
  double max_hedge_shares = 0;                    // risk cap; 0 means shares_held
  std::int64_t max_staleness_ns = 2'000'000'000;  // ticks older than this are ignored
  double sigma_k = 2.0;                           // SigmaGate threshold in std devs of dp
  double sigma_alpha = 0.05;                      // EWMA weight for dp^2
  double gap_per_share = 0;                       // J, $ of hedge benefit per share per unit of dp; fee gate active when > 0
  double fee_per_share = 0.0035;                  // $/share commission
  double half_spread = 0.0;                       // $/share
  double min_benefit_ratio = 1.0;                 // trade only if benefit >= cost * ratio
};

struct Tick {
  std::int64_t ts_ns;  // venue timestamp
  double p;            // market probability of the event, in [0, 1]
};

enum class Action : std::uint8_t { Hold, Order };
enum class Reason : std::uint8_t { Invalid, Stale, BelowSigma, InsideBand, Rebalance, RiskCapped, BelowFees };

struct Decision {
  Action action;
  Reason reason;
  double order_qty;       // > 0 adds to the short hedge, < 0 reduces it
  double target_hedge;
  double current_hedge;
  std::int64_t latency_ns;
};

const char* to_string(Reason r) noexcept;

}  // namespace hedgecore
