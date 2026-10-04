#pragma once
// Renders the golden text for the 17 families that predate the micro families: every preset's replay output and the
// default preset's intent stream, doubles as hex floats (%a). Shared by test_golden_existing.cpp (against the file
// recorded on the reference machine) and golden_dump.cpp (CI builds it on the base commit and on the branch with the
// same compiler and flags and diffs the two outputs byte for byte). Uses only API that predates the micro families.
#include <algorithm>
#include <cstdio>
#include <sstream>
#include <string>
#include <vector>
#include "hedgecore/replay.hpp"
#include "tick_helpers.hpp"

namespace hcgolden {
using namespace hedgecore;
using namespace hctest;

// Fri 2026-10-02 14:00 ET to Mon 2026-10-05 12:00 ET in 5-minute steps: a session close, a weekend and an open,
// so the session-aware families take both paths. Both venues, missing fields and 8-K events along the way.
inline std::vector<MarketTick> golden_tape() {
  constexpr std::int64_t kFri1400 = 1790964000LL * kSec;
  std::vector<MarketTick> v;
  double p = 0.3, u = 100.0;
  std::uint64_t s = 20261004;
  for (int i = 0; i < 1000; ++i) {
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    const double z = static_cast<double>(s >> 11) / 9007199254740992.0 - 0.5;
    p = std::min(0.95, std::max(0.05, p + 0.02 * z + 0.0004));
    u = u * (1.0 - 0.4 * 0.02 * z);
    MarketTick t = with_book(pm(kFri1400 + i * 300LL * kSec, p, 0.005, u, 0.01), 400 + 200 * z, 300 - 100 * z);
    t.venue = (i % 7 == 0) ? Venue::Kalshi : Venue::Poly;
    t.no_bid = 1 - p - 0.005;
    t.no_ask = 1 - p + 0.005;
    t.p_other_venue = std::min(0.99, std::max(0.01, p - 0.1 * z));
    t.opt_mid = 2.0 + 6 * p;
    t.opt_delta = 0.5 - p / 2;
    t.opt_iv = 0.3 + 0.1 * z;
    t.opt_implied_prob = std::min(1.0, std::max(0.0, p - 0.3 * z));
    t.eightk_score = (i % 150 == 0) ? 0.85 : ((i % 150 == 75) ? -0.85 : 0.0);
    if (i % 53 == 0) t.yes_bid = NaN;
    if (i % 89 == 0) t.under_bid = NaN;
    v.push_back(t);
  }
  return v;
}

inline void put(std::ostringstream& o, double x) {
  char b[64];
  std::snprintf(b, sizeof b, " %a", x);
  o << b;
}

inline std::string render() {
  const auto tape = golden_tape();
  Position pos;
  pos.shares_held = 1000;
  std::ostringstream o;
  o << "families " << catalog().families.size() << " total " << catalog().total << "\n";
  for (const auto& f : catalog().families) {
    o << "family " << f.id << " presets " << f.preset_count << "\n";
    for (const auto& st : replay_grid(f.id, pos, tape)) {
      o << "  p" << st.preset_index << " n " << st.n_ticks << " " << st.n_orders << " " << st.n_fills << " "
        << st.n_rejected;
      for (double x : {st.pnl, st.fees, st.max_dd, st.hedge_var_reduction, st.hedge_var_reduction_vs_static,
                       st.avg_hedge_ratio, st.turnover})
        put(o, x);
      o << "\n";
    }
    AnyAlgo a = make_algo(f.id, f.spec.defaults(), pos);  // the default preset's intents, fills fed back at the touch
    int k = 0;
    for (const auto& t : tape) {
      const Intent in = on_tick(a, t, t.ts_ns);
      if (in.action == Action::Order) {
        o << "  i" << k << " " << static_cast<int>(in.instrument) << " " << in.side << " " << in.reason << " "
          << static_cast<int>(in.venue);
        put(o, in.qty);
        put(o, in.limit_px);
        put(o, in.signal);
        o << "\n";
        const double px = touch_price(in.instrument, in.side, in.venue, t, FeeModel{});
        if (num(px)) on_fill(a, in.instrument, in.side * in.qty, px);
        else on_reject(a, in.instrument);
      }
      ++k;
    }
  }
  return o.str();
}

}  // namespace hcgolden
