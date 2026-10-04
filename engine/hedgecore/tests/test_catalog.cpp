#include <gtest/gtest.h>
#include <set>
#include <string>
#include "hedgecore/library.hpp"

using namespace hedgecore;

TEST(Catalog, AllSeventeenFamiliesInSpecOrder) {
  const auto& c = catalog();
  ASSERT_EQ(c.families.size(), 17u);
  const char* expected[] = {"equity_delta_bridge", "stress_lead_hedge", "book_imbalance_hedge", "poly_kalshi_spread",
                            "no_bid_seller",       "fig_stress",        "housing_rates",        "macro_fed_hedge",
                            "election_hedge",      "tariff_trade_hedge", "energy_geo_hedge",    "crypto_reg_hedge",
                            "tech_reg_hedge",      "binary_vs_spread_arb", "vol_vs_pm_move",    "eightk_opportunity",
                            "closed_session_hedge"};
  for (std::size_t i = 0; i < 17; ++i) EXPECT_STREQ(c.families[i].id, expected[i]);
}

TEST(Catalog, PresetTotalIsTheHonestSumNearDesignFigure) {
  const auto& c = catalog();
  std::size_t sum = 0;
  for (const auto& f : c.families) {
    EXPECT_EQ(f.preset_count, f.spec.preset_count());
    EXPECT_GE(f.spec.tuned_count(), 2) << f.id;
    EXPECT_LE(f.spec.tuned_count(), 5) << f.id;
    sum += f.preset_count;
  }
  EXPECT_EQ(c.total, sum);
  EXPECT_EQ(c.total, 1386u);
}

TEST(Catalog, PresetsAreDistinctAndInsideBounds) {
  for (const auto& f : catalog().families) {
    std::set<std::vector<double>> seen;
    for (std::size_t i = 0; i < f.preset_count; ++i) {
      const Params p = f.spec.preset(i);
      EXPECT_TRUE(f.spec.valid(p)) << f.id << " preset " << i;
      seen.insert(std::vector<double>(p.v.begin(), p.v.begin() + f.spec.n));
    }
    EXPECT_EQ(seen.size(), f.preset_count) << f.id;
    EXPECT_TRUE(f.spec.valid(f.spec.defaults())) << f.id;
    for (int k = 0; k < f.spec.n; ++k) {
      const auto& d = f.spec.defs[k];
      std::set<double> g(d.grid.begin(), d.grid.begin() + d.n_grid);
      EXPECT_EQ(static_cast<int>(g.size()), d.n_grid) << f.id << "." << d.name;
      EXPECT_TRUE(d.n_grid == 1 || (d.n_grid >= 3 && d.n_grid <= 6)) << f.id << "." << d.name;
    }
  }
}

TEST(Catalog, MetadataUsesKnownKinds) {
  const std::set<std::string> kinds{"signals", "gates", "sizers", "execution", "risk", "tax", "routing"};
  const std::set<std::string> ui{"Gate", "Reader", "Impact", "Execution", "Tax", "Routing"};
  std::set<std::string> ui_seen;
  for (const auto& f : catalog().families) {
    EXPECT_FALSE(f.event_classes.empty()) << f.id;
    EXPECT_FALSE(f.instruments.empty()) << f.id;
    EXPECT_TRUE(ui.count(f.ui_kind)) << f.id;
    for (const auto& b : f.blocks) {
      EXPECT_TRUE(kinds.count(b.kind)) << f.id << " " << b.kind;
      ui_seen.insert(ui_kind_of(b.kind));
    }
  }
  EXPECT_EQ(ui_seen, ui);
}

TEST(Catalog, MakeAlgoByIdAndUnknownThrows) {
  for (const auto& f : catalog().families) {
    AnyAlgo a = make_algo(f.id, f.spec.defaults(), Position{});
    EXPECT_STREQ(algo_id(a), f.id);
  }
  EXPECT_THROW(make_algo("nope", Params{}, Position{}), std::invalid_argument);
}

TEST(Catalog, ReasonNamesAreUniqueAndBlockScoped) {
  std::set<std::string> names;
  for (Rc r : kAllReasons) {
    EXPECT_TRUE(names.insert(to_string(r)).second) << to_string(r);
    EXPECT_STRNE(reason_block(code(r)), "unknown");
  }
  EXPECT_STREQ(reason_block(code(Rc::WashSale)), "tax");
  EXPECT_STREQ(reason_block(code(Rc::RoutedKalshi)), "routing");
  EXPECT_STREQ(reason_name(0xFFFF), "unknown");
}
