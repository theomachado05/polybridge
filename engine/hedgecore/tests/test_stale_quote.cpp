#include <gtest/gtest.h>
#include <cmath>
#include "hedgecore/stale_quote.hpp"

using namespace hedgecore;

TEST(StaleQuote, BuysYesWhenAskBelowReferenceByTau) {
  StaleQuoteParams p;
  const auto d = stale_quote(0.38, 100, 0.40, 50, 0.46, p);
  EXPECT_EQ(d.side, StaleSide::BuyYes);
  EXPECT_NEAR(d.edge_pt, 6.0, 1e-9);
  EXPECT_NEAR(d.net_edge_pt, 6.0 - 100 * 0.04 * 0.4 * 0.6, 1e-9);
  EXPECT_DOUBLE_EQ(d.price, 0.40);
  EXPECT_DOUBLE_EQ(d.size, 50);
}

TEST(StaleQuote, BuysNoWhenBidAboveReferenceByTau) {
  StaleQuoteParams p;
  p.fees_enabled = false;
  const auto d = stale_quote(0.60, 30, 0.62, 10, 0.55, p);
  EXPECT_EQ(d.side, StaleSide::BuyNo);
  EXPECT_NEAR(d.edge_pt, 5.0, 1e-9);
  EXPECT_NEAR(d.net_edge_pt, 5.0, 1e-9);
  EXPECT_NEAR(d.price, 0.40, 1e-12);
  EXPECT_DOUBLE_EQ(d.size, 30);
}

TEST(StaleQuote, NoneInsideBandOrInvalid) {
  StaleQuoteParams p;
  EXPECT_EQ(stale_quote(0.48, 10, 0.52, 10, 0.50, p).side, StaleSide::None);
  EXPECT_EQ(stale_quote(0.10, 10, 0.20, 0, 0.50, p).side, StaleSide::None);
  EXPECT_EQ(stale_quote(0.10, 10, 0.20, 10, NAN, p).side, StaleSide::None);
  EXPECT_EQ(stale_quote(0.10, 10, 0.20, 10, 0.99, p).side, StaleSide::None);
}
