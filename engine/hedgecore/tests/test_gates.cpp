#include <gtest/gtest.h>
#include "hedgecore/blocks/gates.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hedgecore::blocks;
using namespace hctest;

TEST(Gates, StalenessAgeFutureAndBoundary) {
  Staleness g{2 * kSec};
  const MarketTick t = pm(10 * kSec, 0.5);
  EXPECT_TRUE(g.pass({t, 12 * kSec}));
  EXPECT_FALSE(g.pass({t, 13 * kSec}));
  EXPECT_FALSE(g.pass({t, 9 * kSec}));
}

TEST(Gates, SigmaWarmupPassesMissingDpFails) {
  Sigma g{2.0};
  const MarketTick t = pm(kSec, 0.5);
  EXPECT_TRUE(g.pass({t, kSec, 0.001, NaN}));
  EXPECT_FALSE(g.pass({t, kSec, NaN, 0.01}));
  EXPECT_TRUE(g.pass({t, kSec, 0.02, 0.01}));
  EXPECT_FALSE(g.pass({t, kSec, 0.019, 0.01}));
  EXPECT_TRUE((Sigma{0}.pass({t, kSec, NaN, NaN})));
}

TEST(Gates, SpreadFailsClosedWhenUnknown) {
  Spread g{0.02};
  EXPECT_TRUE(g.pass({pm(kSec, 0.5, 0.01), kSec}));
  EXPECT_FALSE(g.pass({pm(kSec, 0.5, 0.02), kSec}));
  MarketTick t = pm(kSec, 0.5, 0.005);
  t.yes_bid = NaN;
  EXPECT_FALSE(g.pass({t, kSec}));
}

TEST(Gates, DepthNeedsBothSides) {
  Depth g{250, 3};
  EXPECT_TRUE(g.pass({with_book(pm(kSec, 0.5), 100, 100), kSec}));
  EXPECT_FALSE(g.pass({with_book(pm(kSec, 0.5), 100, 50), kSec}));
  EXPECT_FALSE(g.pass({pm(kSec, 0.5), kSec}));
}

TEST(Gates, SessionHoursAndDst) {
  Session g{true};
  const auto at = [](int y, unsigned m, unsigned d, int h, int mi) {
    return (days_from_civil(y, m, d) * 86400 + h * 3600 + mi * 60) * kSec;
  };
  EXPECT_TRUE(g.pass({pm(at(2026, 10, 2, 13, 30), 0.5), 0}));
  EXPECT_FALSE(g.pass({pm(at(2026, 10, 2, 13, 29), 0.5), 0}));
  EXPECT_FALSE(g.pass({pm(at(2026, 10, 2, 20, 0), 0.5), 0}));
  EXPECT_FALSE(g.pass({pm(at(2026, 10, 3, 15, 0), 0.5), 0}));
  EXPECT_TRUE(g.pass({pm(at(2026, 12, 1, 14, 30), 0.5), 0}));
  EXPECT_FALSE(g.pass({pm(at(2026, 12, 1, 14, 29), 0.5), 0}));
  EXPECT_TRUE((Session{false}.pass({pm(at(2026, 10, 3, 3, 0), 0.5), 0})));
}

TEST(Gates, SessionClosedOnNyseHolidays) {
  const auto day = [](int y, unsigned m, unsigned d) { return days_from_civil(y, m, d); };
  for (auto d : {day(2026, 1, 1), day(2026, 1, 19), day(2026, 2, 16), day(2026, 4, 3), day(2026, 5, 25),
                 day(2026, 6, 19), day(2026, 7, 3), day(2026, 9, 7), day(2026, 11, 26), day(2026, 12, 25)})
    EXPECT_TRUE(nyse_holiday(d)) << d;
  EXPECT_TRUE(nyse_holiday(day(2027, 6, 18)));
  EXPECT_TRUE(nyse_holiday(day(2027, 12, 24)));
  EXPECT_TRUE(nyse_holiday(day(2023, 1, 2)));
  EXPECT_FALSE(nyse_holiday(day(2021, 12, 31)));
  EXPECT_FALSE(nyse_holiday(day(2021, 6, 18)));
  EXPECT_TRUE(nyse_holiday(day(2025, 4, 18)));
  for (auto d : {day(2026, 7, 2), day(2026, 11, 27), day(2026, 12, 24), day(2026, 10, 2)})
    EXPECT_FALSE(nyse_holiday(d)) << d;
  Session g{true};
  EXPECT_FALSE(g.pass({pm((day(2026, 11, 26) * 86400 + 15 * 3600) * kSec, 0.5), 0}));
  EXPECT_TRUE(g.pass({pm((day(2026, 11, 27) * 86400 + 15 * 3600) * kSec, 0.5), 0}));
}

TEST(Gates, CooldownAfterOrder) {
  Cooldown g{5 * kSec};
  const MarketTick t = pm(kSec, 0.5);
  EXPECT_TRUE(g.pass({t, 10 * kSec}));
  g.on_order(10 * kSec);
  EXPECT_FALSE(g.pass({t, 14 * kSec}));
  EXPECT_TRUE(g.pass({t, 15 * kSec}));
}

TEST(Gates, EventWindowOpensOnTrigger) {
  EventWindow g{10 * kSec, 0.5};
  EXPECT_FALSE(g.pass({pm(1 * kSec, 0.5), 0, NaN, NaN, 0.2}));
  EXPECT_TRUE(g.pass({pm(2 * kSec, 0.5), 0, NaN, NaN, -0.6}));
  EXPECT_TRUE(g.pass({pm(12 * kSec, 0.5), 0, NaN, NaN, NaN}));
  EXPECT_FALSE(g.pass({pm(13 * kSec, 0.5), 0, NaN, NaN, NaN}));
}

TEST(Gates, VariantChainReportsFirstFailure) {
  std::array<AnyGate, 3> gates{Staleness{2 * kSec}, Spread{0.02}, Cooldown{kSec}};
  Rc why = Rc::None;
  EXPECT_TRUE(run_gates(gates, {pm(kSec, 0.5, 0.005), kSec}, why));
  gates_on_order(gates, kSec);
  EXPECT_FALSE(run_gates(gates, {pm(kSec, 0.5, 0.05), kSec}, why));
  EXPECT_EQ(why, Rc::SpreadTooWide);
  EXPECT_FALSE(run_gates(gates, {pm(kSec, 0.5, 0.005), kSec + 1}, why));
  EXPECT_EQ(why, Rc::Cooldown);
}
