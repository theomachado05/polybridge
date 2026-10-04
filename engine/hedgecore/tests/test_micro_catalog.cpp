#include <gtest/gtest.h>
#include <set>
#include <string>
#include "hedgecore/library.hpp"
#include "hedgecore/micro.hpp"

using namespace hedgecore;

TEST(MicroCatalog, TwoFamiliesWithFixedStatusWordsAndPresets) {
  const auto& m = micro_catalog();
  ASSERT_EQ(m.families.size(), 2u);
  EXPECT_STREQ(m.families[0].id, "ladder_pair");
  EXPECT_STREQ(m.families[0].status, "lead");
  EXPECT_EQ(m.families[0].preset_count, 18u);  // min_edge 1/2/3 x max_age 10/30/60 x cap 100/500
  EXPECT_STREQ(m.families[1].id, "touch_ticket_reference");
  EXPECT_STREQ(m.families[1].status, "unvalidated");
  EXPECT_EQ(m.families[1].preset_count, 1u);   // threshold 5 points; no tuning grid on an unvalidated mechanism
  EXPECT_EQ(m.total, 19u);
  const auto& g = m.families[0].spec;
  const double want[3][3] = {{1, 2, 3}, {10, 30, 60}, {100, 500, 0}};
  for (int k = 0; k < 3; ++k)
    for (int j = 0; j < g.defs[k].n_grid; ++j) EXPECT_EQ(g.defs[k].grid[j], want[k][j]) << g.defs[k].name;
  for (const auto& f : m.families) {
    EXPECT_EQ(f.preset_count, f.spec.preset_count());
    EXPECT_TRUE(f.spec.valid(f.spec.defaults())) << f.id;
    for (std::size_t i = 0; i < f.preset_count; ++i) EXPECT_TRUE(f.spec.valid(f.spec.preset(i))) << f.id;
    EXPECT_EQ(find_family(f.id), nullptr) << "micro ids must not collide with the 17-family library";
    EXPECT_FALSE(f.inputs.empty());
  }
  EXPECT_EQ(catalog().families.size(), 17u);  // the existing library is untouched
  EXPECT_EQ(catalog().total, 1386u);
}

TEST(MicroCatalog, MicroReasonsAreNamedUniqueAndOutsideTheExistingTable) {
  std::set<std::string> existing, micro;
  for (Rc r : kAllReasons) existing.insert(to_string(r));
  for (Rc r : kMicroReasons) {
    EXPECT_STRNE(to_string(r), "unknown");
    EXPECT_STRNE(reason_block(code(r)), "unknown");
    EXPECT_TRUE(micro.insert(to_string(r)).second);
    EXPECT_EQ(existing.count(to_string(r)), 0u);
  }
}
