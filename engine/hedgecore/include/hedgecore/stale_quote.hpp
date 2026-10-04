#pragma once
#include <cmath>
#include <limits>

namespace hedgecore {

enum class StaleSide : int { None = 0, BuyYes = 1, BuyNo = 2 };

struct StaleQuoteParams {
  double tau = 0.05;
  double fee_rate = 0.04;
  double fee_exp = 1.0;
  bool fees_enabled = true;
  double p_min = 0.03;
  double p_max = 0.97;
};

struct StaleQuoteDecision {
  StaleSide side = StaleSide::None;
  double edge_pt = 0.0;
  double net_edge_pt = 0.0;
  double price = std::numeric_limits<double>::quiet_NaN();
  double size = 0.0;
};

double poly_taker_fee(double px, const StaleQuoteParams& p) noexcept;

StaleQuoteDecision stale_quote(double best_bid, double bid_size, double best_ask, double ask_size, double p_ref,
                               const StaleQuoteParams& p) noexcept;

}
