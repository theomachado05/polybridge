#include <gtest/gtest.h>
#include "hedgecore/blocks/tax.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hedgecore::blocks;
using hctest::kSec;

namespace {
constexpr std::int64_t kDay = 86'400 * kSec;
TaxLotSelector three_long_lots(int mode) {
  TaxLotSelector s;
  s.mode = mode;
  s.apply_fill(100, 50.0, 0);           // oldest, long-term by day 400
  s.apply_fill(100, 70.0, 100 * kDay);
  s.apply_fill(100, 60.0, 200 * kDay);
  return s;
}
}  // namespace

TEST(Tax, FifoConsumesOldest) {
  auto s = three_long_lots(TaxLotSelector::FIFO);
  const Realized r = s.apply_fill(-100, 65.0, 400 * kDay);
  EXPECT_DOUBLE_EQ(r.long_term, 1500.0);  // (65 - 50) * 100, held 400 days
  EXPECT_DOUBLE_EQ(r.short_term, 0.0);
  EXPECT_EQ(r.closed_dir, +1);
  EXPECT_DOUBLE_EQ(s.open_qty(), 200.0);
}

TEST(Tax, HifoConsumesHighestCost) {
  auto s = three_long_lots(TaxLotSelector::HIFO);
  const Realized r = s.apply_fill(-150, 65.0, 300 * kDay);
  EXPECT_DOUBLE_EQ(r.short_term, (65.0 - 70.0) * 100 + (65.0 - 60.0) * 50);  // -250
  EXPECT_DOUBLE_EQ(r.long_term, 0.0);
}

TEST(Tax, LongTermFirst) {
  auto s = three_long_lots(TaxLotSelector::LongTermFirst);
  const Realized r = s.apply_fill(-100, 65.0, 400 * kDay);  // only the day-0 lot is long-term
  EXPECT_DOUBLE_EQ(r.long_term, 1500.0);
}

TEST(Tax, CrossingZeroOpensOppositeLot) {
  TaxLotSelector s;
  s.apply_fill(100, 10.0, 0);
  const Realized r = s.apply_fill(-150, 12.0, kDay);
  EXPECT_DOUBLE_EQ(r.short_term, 200.0);
  EXPECT_DOUBLE_EQ(s.open_qty(), -50.0);
  const Realized r2 = s.apply_fill(50, 11.0, 2 * kDay);  // cover the short at a gain of 1/share
  EXPECT_EQ(r2.closed_dir, -1);
  EXPECT_DOUBLE_EQ(r2.short_term, 50.0);
}

TEST(Tax, WashSaleBlocksRebuyWithin30Days) {
  TaxLotSelector s;
  WashSaleGuard g;
  s.apply_fill(100, 50.0, 0);
  const Realized loss = s.apply_fill(-100, 45.0, 10 * kDay);
  g.record(loss, 10 * kDay);
  EXPECT_FALSE(g.allows(+1, 20 * kDay));  // re-buy blocked
  EXPECT_TRUE(g.allows(-1, 20 * kDay));   // opening a short is not a re-buy
  EXPECT_TRUE(g.allows(+1, 40 * kDay));
  WashSaleGuard off;
  off.enabled = false;
  off.record(loss, 10 * kDay);
  EXPECT_TRUE(off.allows(+1, 11 * kDay));
}

TEST(Tax, GainDoesNotArmWashSale) {
  TaxLotSelector s;
  WashSaleGuard g;
  s.apply_fill(100, 50.0, 0);
  g.record(s.apply_fill(-100, 55.0, kDay), kDay);
  EXPECT_TRUE(g.allows(+1, 2 * kDay));
}

TEST(Tax, CapacityMergesWithoutAllocation) {
  TaxLotSelector s;
  for (int i = 0; i < 40; ++i) s.apply_fill(1, 10.0 + i, i * kSec);
  EXPECT_EQ(s.n, TaxLotSelector::kCap);
  EXPECT_DOUBLE_EQ(s.open_qty(), 40.0);
}
