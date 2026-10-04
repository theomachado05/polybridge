#include <gtest/gtest.h>
#include "hedgecore/blocks/execution.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hedgecore::blocks;
using hctest::NaN;

TEST(Execution, NoTradeBand) {
  NoTradeBand b{10};
  EXPECT_FALSE(b.pass(9));
  EXPECT_TRUE(b.pass(-10));
  EXPECT_FALSE((NoTradeBand{0}.pass(0)));
  EXPECT_FALSE(b.pass(NaN));
}

TEST(Execution, FeeGateBenefitVsCost) {
  FeeGate g{1.0};
  EXPECT_EQ(g.check(1.0, 1.0), Rc::None);
  EXPECT_EQ(g.check(0.99, 1.0), Rc::BelowFees);
  EXPECT_EQ((FeeGate{2.0}.check(1.5, 1.0)), Rc::BelowFees);
  EXPECT_EQ(g.check(NaN, 1.0), Rc::FeeUnknown);
  EXPECT_EQ(g.check(1.0, NaN), Rc::FeeUnknown);
}

TEST(Execution, SlicerPreservesSign) {
  Slicer s{100};
  bool sliced = false;
  EXPECT_DOUBLE_EQ(s.clip(-250, sliced), -100);
  EXPECT_TRUE(sliced);
  EXPECT_DOUBLE_EQ(s.clip(40, sliced), 40);
  EXPECT_FALSE(sliced);
  EXPECT_DOUBLE_EQ((Slicer{0}.clip(1e6, sliced)), 1e6);
}

TEST(Execution, PassiveAggressive) {
  PassiveAggressive pa{2.0};
  EXPECT_DOUBLE_EQ(pa.limit(+1, 99.9, 100.1, 1.0), 99.9);
  EXPECT_DOUBLE_EQ(pa.limit(-1, 99.9, 100.1, 1.0), 100.1);
  EXPECT_TRUE(std::isnan(pa.limit(-1, 99.9, 100.1, 2.5)));
  EXPECT_TRUE(std::isnan(pa.limit(+1, NaN, 100.1, 0.0)));
}

TEST(Execution, IcebergCap) {
  IcebergCap c{0.5};
  bool capped = false;
  EXPECT_DOUBLE_EQ(c.clip(300, 401, capped), 200);
  EXPECT_TRUE(capped);
  EXPECT_DOUBLE_EQ(c.clip(-100, 401, capped), -100);
  EXPECT_DOUBLE_EQ(c.clip(300, NaN, capped), 300);
  EXPECT_FALSE(capped);
}
