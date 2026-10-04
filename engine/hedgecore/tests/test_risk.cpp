#include <gtest/gtest.h>
#include "hedgecore/blocks/risk.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hedgecore::blocks;
using hctest::NaN;
using hctest::kSec;

TEST(Risk, PositionCap) {
  PositionCap c{500};
  bool capped = false;
  EXPECT_DOUBLE_EQ(c.clamp(700, capped), 500);
  EXPECT_TRUE(capped);
  EXPECT_DOUBLE_EQ(c.clamp(-700, capped), -500);
  EXPECT_DOUBLE_EQ(c.clamp(300, capped), 300);
  EXPECT_FALSE(capped);
}

TEST(Risk, NotionalCapAndUnknownPrice) {
  NotionalCap c{10'000};
  bool capped = false;
  EXPECT_DOUBLE_EQ(c.clamp(200, 75.0, 1.0, capped), 133);
  EXPECT_TRUE(capped);
  EXPECT_DOUBLE_EQ(c.clamp(5, 3.0, 100.0, capped), 5);
  EXPECT_TRUE(std::isnan(c.clamp(10, NaN, 1.0, capped)));
  EXPECT_DOUBLE_EQ((NotionalCap{0}.clamp(1e9, NaN, 1.0, capped)), 1e9);
}

TEST(Risk, DrawdownKillLatches) {
  DrawdownKill k{100};
  EXPECT_FALSE(k.update(0));
  EXPECT_FALSE(k.update(250));
  EXPECT_FALSE(k.update(150));
  EXPECT_FALSE(k.update(NaN));
  EXPECT_TRUE(k.update(149));
  EXPECT_TRUE(k.update(1000));
}

TEST(Risk, GapFlipKill) {
  GapFlipKill k{0.01};
  EXPECT_FALSE(k.update(-0.5));
  k.arm(0.03);
  EXPECT_FALSE(k.update(0.0));
  EXPECT_FALSE(k.update(-0.01));
  EXPECT_FALSE(k.update(NaN));
  EXPECT_TRUE(k.update(-0.011));
}

TEST(Risk, DailyLossCapResetsEachDay) {
  DailyLossCap c{50};
  const std::int64_t day = 86'400 * kSec;
  EXPECT_FALSE(c.update(day + 1, 1000));
  EXPECT_FALSE(c.update(day + 2, 960));
  EXPECT_TRUE(c.update(day + 3, 949));
  EXPECT_TRUE(c.update(day + 4, 1000));
  EXPECT_FALSE(c.update(2 * day + 1, 949));
}
