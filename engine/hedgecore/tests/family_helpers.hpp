#pragma once
#include <gtest/gtest.h>
#include <initializer_list>
#include <utility>
#include "hedgecore/library.hpp"
#include "tick_helpers.hpp"

namespace hctest {

template <class F>
Params params(std::initializer_list<std::pair<const char*, double>> kv = {}) {
  const ParamSpec s = F::spec();
  Params p = s.defaults();
  for (const auto& [k, v] : kv) {
    const int i = s.index_of(k);
    EXPECT_GE(i, 0) << "unknown param " << k;
    if (i >= 0) p.v[static_cast<std::size_t>(i)] = v;
  }
  return p;
}
inline Position held(double n, double equity = 0) {
  Position p;
  p.shares_held = n;
  p.equity = equity;
  return p;
}
inline std::uint16_t rc(Rc r) { return code(r); }
inline bool is_order(const Intent& i) { return i.action == Action::Order; }

template <class F>
void expect_nan_and_stale_safety(const Params& p, const Position& pos) {
  F a(p, pos);
  const Intent e = a.on_tick(MarketTick{}, 0);
  EXPECT_EQ(e.action, Action::Hold);
  F b(p, pos);
  const Intent s = b.on_tick(pm(kSec, 0.5), 10 * kSec);
  EXPECT_EQ(s.action, Action::Hold);
  EXPECT_EQ(s.reason, code(Rc::Stale));
  Params bad = p;
  bad.v[0] = NaN;
  F c(bad, pos);
  EXPECT_EQ(c.on_tick(pm(kSec, 0.5), kSec).reason, code(Rc::InvalidParams));
}

}
