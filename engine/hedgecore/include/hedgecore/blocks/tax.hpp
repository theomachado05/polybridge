#pragma once
// Tax blocks (UI kind: Tax). A fixed-capacity lot ledger (no heap) and a wash-sale guard.
// Not tax advice: the rules are simplified (no lot-level wash adjustment of basis, no constructive sales).
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

inline constexpr std::int64_t kLongTermNs = 365 * kNsPerDay;

struct Lot {
  double qty = 0;  // > 0; the ledger's sign gives the direction
  double px = 0;
  std::int64_t ts_ns = 0;
};

struct Realized {
  double short_term = 0, long_term = 0;
  int closed_dir = 0;  // +1 closed long lots, -1 closed short lots, 0 nothing closed
  double total() const noexcept { return short_term + long_term; }
};

// Selects which lots a closing trade consumes. FIFO (0): oldest first. HIFO (1): the lot with the smallest gain first
// (highest cost for longs, lowest sale price for shorts). LongTermFirst (2): long-term lots first (HIFO among them).
struct TaxLotSelector {
  static constexpr const char* name = "TaxLotSelector";
  enum Mode : int { FIFO = 0, HIFO = 1, LongTermFirst = 2 };
  static constexpr int kCap = 32;
  int mode = HIFO;
  int dir = 0;  // +1 long lots, -1 short lots
  std::array<Lot, kCap> lots{};
  int n = 0;

  double open_qty() const noexcept {
    double s = 0;
    for (int i = 0; i < n; ++i) s += lots[static_cast<std::size_t>(i)].qty;
    return s * dir;
  }

  Realized apply_fill(double signed_qty, double px, std::int64_t ts) noexcept {
    Realized r;
    if (!num(signed_qty) || !num(px) || signed_qty == 0) return r;
    const int s = sgn(signed_qty);
    double q = std::abs(signed_qty);
    if (n > 0 && s != dir) {
      r.closed_dir = dir;
      while (q > 0 && n > 0) {
        const int i = pick(ts);
        Lot& l = lots[static_cast<std::size_t>(i)];
        const double take = std::min(q, l.qty);
        const double gain = take * (px - l.px) * dir;
        (ts - l.ts_ns >= kLongTermNs ? r.long_term : r.short_term) += gain;
        l.qty -= take;
        q -= take;
        if (l.qty <= 1e-12) { lots[static_cast<std::size_t>(i)] = lots[static_cast<std::size_t>(n - 1)]; --n; }
      }
      if (n == 0) dir = 0;
    }
    if (q > 0) add(s, q, px, ts);
    return r;
  }

 private:
  void add(int s, double q, double px, std::int64_t ts) noexcept {
    dir = s;
    if (n < kCap) { lots[static_cast<std::size_t>(n++)] = {q, px, ts}; return; }
    Lot& last = lots[kCap - 1];  // full: merge into the newest slot at the weighted cost
    last.px = (last.px * last.qty + px * q) / (last.qty + q);
    last.qty += q;
    last.ts_ns = ts;
  }
  bool better_hifo(const Lot& a, const Lot& b) const noexcept { return dir > 0 ? a.px > b.px : a.px < b.px; }
  int pick(std::int64_t ts) const noexcept {
    int best = 0;
    for (int i = 1; i < n; ++i) {
      const Lot& a = lots[static_cast<std::size_t>(i)];
      const Lot& b = lots[static_cast<std::size_t>(best)];
      bool take = false;
      if (mode == FIFO) take = a.ts_ns < b.ts_ns;
      else if (mode == HIFO) take = better_hifo(a, b);
      else {
        const bool alt = ts - a.ts_ns >= kLongTermNs, blt = ts - b.ts_ns >= kLongTermNs;
        take = alt != blt ? alt : better_hifo(a, b);
      }
      if (take) best = i;
    }
    return best;
  }
};

// Blocks re-opening a position in the direction of a loss close within window_ns (30 days by default): after a loss
// sale of long lots, re-buys are blocked; after a loss cover of short lots, re-shorts are blocked.
struct WashSaleGuard {
  static constexpr const char* name = "WashSaleGuard";
  static constexpr Rc fail = Rc::WashSale;
  bool enabled = true;
  std::int64_t window_ns = 30 * kNsPerDay;
  std::int64_t last_loss_ns = std::numeric_limits<std::int64_t>::min();
  int loss_dir = 0;
  void record(const Realized& r, std::int64_t ts) noexcept {
    if (r.closed_dir != 0 && r.total() < 0) { last_loss_ns = ts; loss_dir = r.closed_dir; }
  }
  bool allows(int open_dir, std::int64_t ts) const noexcept {
    if (!enabled || loss_dir == 0 || open_dir != loss_dir) return true;
    return ts - last_loss_ns >= window_ns;
  }
};

}  // namespace hedgecore::blocks
