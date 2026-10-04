#include "hedgecore/stale_quote.hpp"

namespace hedgecore {

double poly_taker_fee(double px, const StaleQuoteParams& p) noexcept {
  if (!p.fees_enabled || !(px > 0.0 && px < 1.0)) return 0.0;
  return p.fee_rate * std::pow(px * (1.0 - px), p.fee_exp);
}

StaleQuoteDecision stale_quote(double best_bid, double bid_size, double best_ask, double ask_size, double p_ref,
                               const StaleQuoteParams& p) noexcept {
  StaleQuoteDecision d;
  if (!(p_ref >= p.p_min - 1e-12 && p_ref <= p.p_max + 1e-12)) return d;
  const bool ask_ok = best_ask > 0.0 && best_ask < 1.0 && ask_size > 0.0;
  const bool bid_ok = best_bid > 0.0 && best_bid < 1.0 && bid_size > 0.0;
  const double e_yes = ask_ok ? p_ref - best_ask : -1.0;
  const double e_no = bid_ok ? best_bid - p_ref : -1.0;
  const double cut = p.tau - 1e-12;
  if (e_yes >= cut && e_yes >= e_no) {
    d.side = StaleSide::BuyYes;
    d.price = best_ask;
    d.size = ask_size;
    d.edge_pt = 100.0 * e_yes;
    d.net_edge_pt = 100.0 * (e_yes - poly_taker_fee(best_ask, p));
  } else if (e_no >= cut) {
    d.side = StaleSide::BuyNo;
    d.price = 1.0 - best_bid;
    d.size = bid_size;
    d.edge_pt = 100.0 * e_no;
    d.net_edge_pt = 100.0 * (e_no - poly_taker_fee(d.price, p));
  }
  return d;
}

}  // namespace hedgecore
