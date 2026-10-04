#pragma once
#include <cmath>
#include "hedgecore/fees.hpp"
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

struct Route {
  Venue venue = Venue::Poly;
  double px = kNaN;
  double all_in = kNaN;
  Rc reason = Rc::NoRoute;
};

struct VenueRouter {
  static constexpr const char* name = "VenueRouter";
  FeeModel fees{};

  Route route(int side, Instrument inst, const MarketTick& t) const noexcept {
    const Venue here = t.venue;
    const Venue other = here == Venue::Poly ? Venue::Kalshi : Venue::Poly;
    double px_here = kNaN;
    if (inst == Instrument::PredYes) px_here = side > 0 ? t.yes_ask : t.yes_bid;
    else if (inst == Instrument::PredNo) px_here = side > 0 ? t.no_ask : t.no_bid;
    double px_other = kNaN;
    if (prob(t.p_other_venue)) {
      const double m = inst == Instrument::PredYes ? t.p_other_venue : 1.0 - t.p_other_venue;
      px_other = m + side * fees.other_venue_half_spread;
      if (!prob(px_other)) px_other = kNaN;
    }
    if (!prob(px_here)) px_here = kNaN;
    const double ai_here = all_in(side, inst, here, px_here);
    const double ai_other = all_in(side, inst, other, px_other);
    const bool h = num(ai_here), o = num(ai_other);
    if (!h && !o) return {};
    const bool pick_other = o && (!h || (side > 0 ? ai_other < ai_here : ai_other > ai_here));
    const Venue v = pick_other ? other : here;
    return {v, pick_other ? px_other : px_here, pick_other ? ai_other : ai_here,
            v == Venue::Poly ? Rc::RoutedPoly : Rc::RoutedKalshi};
  }

 private:
  double all_in(int side, Instrument inst, Venue v, double px) const noexcept {
    if (!num(px)) return kNaN;
    const double f = fees.unit_fee(inst, v, px);
    return num(f) ? px + side * f : kNaN;
  }
};

}
