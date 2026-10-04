// Golden lock on the 17 families that existed before the micro families were added: preset counts, every preset's
// replay output and the default preset's intent stream must stay byte-identical. Doubles are written as hex floats
// (%a), so any change in any bit fails. Latency fields are left out (they are timings, not outputs).
// The file was recorded on the reference toolchain (Apple clang, arm64); other compilers may contract or round floating
// point differently in the last bit, so there the file check is skipped and CI's golden step (golden_dump built on the
// base commit and on the branch with the same compiler and flags, outputs diffed) is the byte-identity check.
// To regenerate after an intended change: HEDGECORE_WRITE_GOLDEN=1 ./hedgecore_tests --gtest_filter='Golden.*'
#include <gtest/gtest.h>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include "golden_render.hpp"

using namespace hedgecore;
using namespace hctest;

namespace {
const std::string kGolden = std::string(HEDGECORE_TEST_DIR) + "/golden/existing_families.txt";
}  // namespace

TEST(Golden, ExistingFamiliesAreByteIdentical) {
#if !(defined(__APPLE__) && defined(__aarch64__) && defined(__clang__))
  GTEST_SKIP() << "golden file is for Apple clang arm64; CI diffs golden_dump on base and branch instead";
#endif
  const std::string now = hcgolden::render();
  if (std::getenv("HEDGECORE_WRITE_GOLDEN")) {
    std::ofstream(kGolden, std::ios::binary) << now;
    GTEST_SKIP() << "wrote " << kGolden;
  }
  std::ifstream in(kGolden, std::ios::binary);
  ASSERT_TRUE(in.good()) << "missing " << kGolden;
  std::stringstream ss;
  ss << in.rdbuf();
  const std::string want = ss.str();
  if (want == now) return;
  std::istringstream a(want), b(now);
  std::string la, lb;
  for (int line = 1;; ++line) {
    const bool ga = static_cast<bool>(std::getline(a, la)), gb = static_cast<bool>(std::getline(b, lb));
    if (!ga && !gb) break;
    if (!ga || !gb || la != lb) FAIL() << "first difference at line " << line << "\n  golden: " << la << "\n  now:    " << lb;
  }
  FAIL() << "golden differs";
}

TEST(Golden, ExistingPresetCountsUnchanged) {
  const std::pair<const char*, std::size_t> want[] = {
      {"equity_delta_bridge", 108}, {"stress_lead_hedge", 81},  {"book_imbalance_hedge", 81},
      {"poly_kalshi_spread", 81},   {"no_bid_seller", 81},      {"fig_stress", 81},
      {"housing_rates", 81},        {"macro_fed_hedge", 81},    {"election_hedge", 81},
      {"tariff_trade_hedge", 81},   {"energy_geo_hedge", 81},   {"crypto_reg_hedge", 81},
      {"tech_reg_hedge", 81},       {"binary_vs_spread_arb", 36}, {"vol_vs_pm_move", 81},
      {"eightk_opportunity", 81},   {"closed_session_hedge", 108}};
  ASSERT_EQ(catalog().families.size(), 17u);
  for (std::size_t i = 0; i < 17; ++i) {
    EXPECT_STREQ(catalog().families[i].id, want[i].first);
    EXPECT_EQ(catalog().families[i].preset_count, want[i].second) << want[i].first;
  }
  EXPECT_EQ(catalog().total, 1386u);
}
