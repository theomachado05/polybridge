// hedgecore_bench: on_tick latency per algo family on a deterministic synthetic tape (default preset).
// Prints the batch mean (total time / calls, no per-call clock overhead) and per-call p50/p99 measured around each
// call. Per-call figures include two steady_clock reads and are quantized by the clock's resolution
// (about 42 ns on Apple Silicon), so the mean is the better estimate of the work itself.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "hedgecore/library.hpp"

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
  F fresh(F::spec().defaults(), pos);  // batch timing
  volatile double sink = 0;
  const auto b0 = std::chrono::steady_clock::now();
  for (const auto& t : ticks) sink = sink + fresh.on_tick(t, t.ts_ns).qty;
  const auto b1 = std::chrono::steady_clock::now();
  const double mean = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(b1 - b0).count()) /
                      static_cast<double>(ticks.size());
  std::sort(lat.begin(), lat.end());
  const auto pct = [&](double q) { return lat[static_cast<std::size_t>(q * static_cast<double>(lat.size() - 1))]; };
  std::printf("%-22s %8.1f %8lld %8lld %8zu %8zu\n", F::id, mean, static_cast<long long>(pct(0.50)),
              static_cast<long long>(pct(0.99)), F::spec().preset_count(), orders);
}

template <std::size_t... I>
void bench_all(const std::vector<MarketTick>& ticks, std::index_sequence<I...>) {
  (bench_family<std::variant_alternative_t<I, AnyAlgo>>(ticks), ...);
}
}  // namespace

int main(int argc, char** argv) {
  const int n = argc > 1 ? std::atoi(argv[1]) : 200'000;
  const auto ticks = tape(n);
  std::printf("hedgecore_bench: %d ticks per family, default preset, shares_held 1000\n", n);
  std::printf("%-22s %8s %8s %8s %8s %8s\n", "family", "mean_ns", "p50_ns", "p99_ns", "presets", "orders");
  bench_all(ticks, std::make_index_sequence<kNumFamilies>{});
  std::printf("total presets: %zu\n", catalog().total);
  return 0;
}
