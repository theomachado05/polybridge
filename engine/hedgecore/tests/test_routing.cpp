#include <gtest/gtest.h>
#include "hedgecore/blocks/routing.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hedgecore::blocks;
using namespace hctest;

TEST(Routing, BuyYesGoesToCheaperVenue) {
  VenueRouter r;  // Poly taker 0, Kalshi 0.07 p(1-p), other half-spread 0.01
  MarketTick t = pm(kSec, 0.50, 0.02);  // Poly ask 0.52
  t.venue = Venue::Poly;
  t.p_other_venue = 0.45;  // Kalshi ask est 0.46 + 0.07*0.46*0.54 = 0.4774
  Route x = r.route(+1, Instrument::PredYes, t);
  EXPECT_EQ(x.venue, Venue::Kalshi);
  EXPECT_EQ(x.reason, Rc::RoutedKalshi);
  EXPECT_NEAR(x.px, 0.46, 1e-12);
  EXPECT_NEAR(x.all_in, 0.46 + 0.07 * 0.46 * 0.54, 1e-12);
  t.p_other_venue = 0.50;  // Kalshi est 0.51 + fee 0.0175 > 0.52
  EXPECT_EQ(r.route(+1, Instrument::PredYes, t).venue, Venue::Poly);
}

TEST(Routing, SellNoUsesNoBidAndDerivedOtherPrice) {
  VenueRouter r;
  MarketTick t = pm(kSec, 0.40);
  t.no_bid = 0.55; t.no_ask = 0.58;
  t.p_other_venue = 0.38;  // other NO mid 0.62, sell est 0.61 minus Kalshi fee
  Route x = r.route(-1, Instrument::PredNo, t);
  EXPECT_EQ(x.venue, Venue::Kalshi);
  EXPECT_NEAR(x.all_in, 0.61 - 0.07 * 0.61 * 0.39, 1e-12);
}

TEST(Routing, MissingQuotes) {
  VenueRouter r;
  MarketTick t;  // nothing quoted
  EXPECT_EQ(r.route(+1, Instrument::PredYes, t).reason, Rc::NoRoute);
  t.p_other_venue = 0.3;  // only the other venue is known
  EXPECT_EQ(r.route(+1, Instrument::PredYes, t).venue, Venue::Kalshi);
}
