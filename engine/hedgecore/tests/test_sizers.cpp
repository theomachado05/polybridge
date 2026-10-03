#include <gtest/gtest.h>
#include "hedgecore/blocks/sizers.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore::blocks;
using hctest::NaN;

TEST(Sizers, DeltaBridgeRoundsAndRejectsNaN) {
  DeltaBridge s{0.5, 1000};
  EXPECT_DOUBLE_EQ(s.target(0.20), 100.0);
  EXPECT_DOUBLE_EQ(s.target(0.2031), 102.0);  // round(101.55)
  EXPECT_TRUE(std::isnan(s.target(NaN)));
  EXPECT_TRUE(std::isnan(s.target(1.2)));
}

TEST(Sizers, LinearExposureClamps) {
  LinearExposure s{2.0, 0.5, 0.8, 1000};
  EXPECT_DOUBLE_EQ(s.target(0.6), 200.0);  // 1000 * 2 * 0.1
  EXPECT_DOUBLE_EQ(s.target(0.4), 0.0);    // below neutral
  EXPECT_DOUBLE_EQ(s.target(0.99), 800.0); // capped at max_cov
  EXPECT_TRUE(std::isnan(s.target(NaN)));
}

TEST(Sizers, ConvexExposure) {
  ConvexExposure s{1.0, 2.0, 1000};
  EXPECT_DOUBLE_EQ(s.target(0.3), 90.0);
  EXPECT_DOUBLE_EQ((ConvexExposure{0.5, 0.5, 1000}.target(0.25)), 250.0);
}

TEST(Sizers, KellyCapped) {
  KellyCapped k{0.25, 1000};
  EXPECT_NEAR(k.fraction(0.6, 0.5), 0.2, 1e-12);
  EXPECT_DOUBLE_EQ(k.target(0.6, 0.5), 400.0);  // 0.2 * 1000 / 0.5
  EXPECT_DOUBLE_EQ(k.fraction(0.95, 0.5), 0.25);
  EXPECT_DOUBLE_EQ(k.fraction(0.4, 0.5), 0.0);  // no edge
  EXPECT_TRUE(std::isnan(k.target(NaN, 0.5)));
}

TEST(Sizers, VolTargetInverse) {
  VolTarget v{0.02, 0.25, 2.0};
  EXPECT_DOUBLE_EQ(v.scale(0.04), 0.5);
  EXPECT_DOUBLE_EQ(v.scale(0.001), 2.0);
  EXPECT_DOUBLE_EQ(v.scale(1.0), 0.25);
  EXPECT_TRUE(std::isnan(v.scale(NaN)));
}

TEST(Sizers, FixedNotional) {
  FixedNotional f{1000};
  EXPECT_DOUBLE_EQ(f.target(30.0), 33.0);
  EXPECT_DOUBLE_EQ(f.target(2.5, 100), 4.0);
  EXPECT_TRUE(std::isnan(f.target(NaN)));
  EXPECT_TRUE(std::isnan(f.target(0.0)));
}
