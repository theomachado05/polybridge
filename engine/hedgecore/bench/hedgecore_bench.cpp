// hedgecore_bench: on_tick latency per algo family on a deterministic synthetic tape (default preset, seed 42),
// plus replay_grid throughput (presets x ticks per second). Usage: hedgecore_bench [ticks=1000000] [grid_ticks=20000]
// Per family it prints: the batch mean (total time / calls, no per-call clock overhead); call50/99/99.9 = per-call
// percentiles measured around each call (include two steady_clock reads and are quantized by the clock resolution,
// about 42 ns on Apple Silicon, so they are an upper bound on the work itself); and blk50/99/99.9 = percentiles of
// 64-call blocks divided by 64 (clock overhead amortized 64x, a tighter estimate). An untimed warm-up pass over the
// tape runs first so caches and branch predictors are warm.
#include <span>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "hedgecore/library.hpp"
#include "hedgecore/replay.hpp"

using namespace hedgecore;

namespace {
std::vector<MarketTick> tape(int n) {
  std::vector<MarketTick> v;
  v.reserve(static_cast<std::size_t>(n));
  double p = 0.3, u = 100.0;
  std::uint64_t s = 42;
  for (int i = 0; i < n; ++i) {
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    const double z = static_cast<double>(s >> 11) / 9007199254740992.0 - 0.5;
    p = std::min(0.95, std::max(0.05, p + 0.01 * z));
    u = u * (1 - 0.3 * 0.01 * z);
    MarketTick t;
    t.ts_ns = (i + 1) * 1'000'000'000LL;
    t.yes_bid = p - 0.005;
    t.yes_ask = p + 0.005;
    t.no_bid = 1 - p - 0.005;
    t.no_ask = 1 - p + 0.005;
    for (int k = 0; k < kDepth; ++k) {
      t.bids[k] = {t.yes_bid - 0.01 * k, 400.0 + 100 * z + 50 * k};
      t.asks[k] = {t.yes_ask + 0.01 * k, 400.0 - 100 * z + 50 * k};
    }
    t.p_other_venue = std::min(0.99, std::max(0.01, p - 0.12 * z));
    t.under_px = u;
    t.under_bid = u - 0.01;
    t.under_ask = u + 0.01;
    t.opt_mid = 2.0 + 5 * p;
    t.opt_iv = 0.3 + 0.05 * z;
    t.opt_implied_prob = std::min(1.0, std::max(0.0, p - 0.25 * z));
    t.eightk_score = (i % 5000 == 0) ? 0.8 : 0.0;
    v.push_back(t);
  }
  return v;
}

template <class F>
void bench_family(const std::vector<MarketTick>& ticks) {
  Position pos;
  pos.shares_held = 1000;
  {  // untimed warm-up pass: caches and branch predictors warm before any timing
    F w(F::spec().defaults(), pos);
    volatile double wsink = 0;
    for (const auto& t : ticks) wsink = wsink + w.on_tick(t, t.ts_ns).qty;
  }
  F algo(F::spec().defaults(), pos);
  std::vector<std::int64_t> lat;
  lat.reserve(ticks.size());
  std::size_t orders = 0;
  for (const auto& t : ticks) {  // per-call timing; fills applied so state evolves like a live bridge
    const auto t0 = std::chrono::steady_clock::now();
    const Intent in = algo.on_tick(t, t.ts_ns);
    const auto t1 = std::chrono::steady_clock::now();
    lat.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    if (in.action == Action::Order) {
      ++orders;
      algo.on_fill(in.instrument, in.side * in.qty, in.instrument == Instrument::Equity ? t.under_px : t.yes_ask);
    }
  }
  std::vector<std::int64_t> blk;  // ns per call over 64-call blocks
  {
    F b(F::spec().defaults(), pos);
    volatile double bsink = 0;
    constexpr std::size_t kB = 64;
    for (std::size_t i = 0; i + kB <= ticks.size(); i += kB) {
      const auto c0 = std::chrono::steady_clock::now();
      for (std::size_t j = 0; j < kB; ++j) bsink = bsink + b.on_tick(ticks[i + j], ticks[i + j].ts_ns).qty;
      const auto c1 = std::chrono::steady_clock::now();
      blk.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(c1 - c0).count() /
                    static_cast<std::int64_t>(kB));
    }
  }
  F fresh(F::spec().defaults(), pos);  // batch timing
  volatile double sink = 0;
  const auto b0 = std::chrono::steady_clock::now();
  for (const auto& t : ticks) sink = sink + fresh.on_tick(t, t.ts_ns).qty;
  const auto b1 = std::chrono::steady_clock::now();
  const double mean = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(b1 - b0).count()) /
                      static_cast<double>(ticks.size());
  std::sort(lat.begin(), lat.end());
  std::sort(blk.begin(), blk.end());
  const auto pct = [](const std::vector<std::int64_t>& v, double q) {
    return static_cast<long long>(v[static_cast<std::size_t>(q * static_cast<double>(v.size() - 1))]);
  };
  std::printf("%-22s %8.1f %7lld %7lld %8lld %7lld %7lld %8lld %8zu %8zu\n", F::id, mean, pct(lat, 0.50),
              pct(lat, 0.99), pct(lat, 0.999), pct(blk, 0.50), pct(blk, 0.99), pct(blk, 0.999),
              F::spec().preset_count(), orders);
}

// replay_grid throughput: every preset of the family replayed over the same tape.
void bench_grid(const FamilyInfo& f, std::span<const MarketTick> ticks) {
  Position pos;
  pos.shares_held = 1000;
  (void)replay_grid(f.id, pos, ticks);  // warm-up
  const auto t0 = std::chrono::steady_clock::now();
  const auto res = replay_grid(f.id, pos, ticks);
  const auto t1 = std::chrono::steady_clock::now();
  const double sec = std::chrono::duration<double>(t1 - t0).count();
  const double work = static_cast<double>(res.size()) * static_cast<double>(ticks.size());
  std::printf("%-22s %8zu %10zu %9.3f %14.3e\n", f.id, res.size(), ticks.size(), sec, work / sec);
}

template <std::size_t... I>
void bench_all(const std::vector<MarketTick>& ticks, std::index_sequence<I...>) {
  (bench_family<std::variant_alternative_t<I, AnyAlgo>>(ticks), ...);
}
}  // namespace

int main(int argc, char** argv) {
  const int n = argc > 1 ? std::atoi(argv[1]) : 1'000'000;
  const int gn = argc > 2 ? std::atoi(argv[2]) : 20'000;
  const auto ticks = tape(n);
  std::printf("hedgecore_bench: %d ticks per family, default preset, shares_held 1000, seed 42\n", n);
  std::printf("call* = per-call ns incl. clock reads; blk* = ns/call over 64-call blocks; mean = batch mean\n");
  std::printf("%-22s %8s %7s %7s %8s %7s %7s %8s %8s %8s\n", "family", "mean_ns", "call50", "call99", "call99.9",
              "blk50", "blk99", "blk99.9", "presets", "orders");
  bench_all(ticks, std::make_index_sequence<kNumFamilies>{});
  std::printf("total presets: %zu\n\n", catalog().total);
  std::printf("replay_grid throughput: all presets of a family over %d ticks\n", std::min(gn, n));
  std::printf("%-22s %8s %10s %9s %14s\n", "family", "presets", "ticks", "seconds", "preset_ticks/s");
  const std::span<const MarketTick> gt(ticks.data(), static_cast<std::size_t>(std::min(gn, n)));
  for (const auto& f : catalog().families) bench_grid(f, gt);
  return 0;
}
