// hedgecore_bench: on_tick latency per algo family on a deterministic synthetic tape (default preset, seed 42),
// plus replay_grid throughput (presets x ticks per second). Usage: hedgecore_bench [ticks=1000000] [grid_ticks=20000]
// NOTE: AlgoBase::on_tick stamps Intent::latency_ns with two steady_clock reads of its own (about 15 ns total), so
// every on_tick figure below INCLUDES that self-timing. Columns:
//   mean      = batch mean of on_tick (no bench clock reads per call, but on_tick's own two reads are inside it)
//   step_mean = batch mean of step() called directly: the decision logic alone, without the latency stamp
//   call*     = per-call percentiles around each on_tick: four clock reads in all (two bench, two inside on_tick),
//               quantized by the clock resolution (about 42 ns on Apple Silicon), so an upper bound
//   blk*      = percentiles of 64-call blocks / 64: amortizes only the bench's outer two reads; on_tick's own two
//               reads per call remain in the figure
// All passes feed fills back through on_fill (fill application is inside the timed region for mean/step_mean/blk
// and outside it for call*). An untimed warm-up pass over the tape runs first.
#include <span>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "hedgecore/library.hpp"
#include "hedgecore/micro.hpp"
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
      for (std::size_t j = 0; j < kB; ++j) {
        const auto& t = ticks[i + j];
        const Intent in = b.on_tick(t, t.ts_ns);
        bsink = bsink + in.qty;
        if (in.action == Action::Order)
          b.on_fill(in.instrument, in.side * in.qty, in.instrument == Instrument::Equity ? t.under_px : t.yes_ask);
      }
      const auto c1 = std::chrono::steady_clock::now();
      blk.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(c1 - c0).count() /
                    static_cast<std::int64_t>(kB));
    }
  }
  F fresh(F::spec().defaults(), pos);  // batch timing
  volatile double sink = 0;
  const auto b0 = std::chrono::steady_clock::now();
  for (const auto& t : ticks) {
    const Intent in = fresh.on_tick(t, t.ts_ns);
    sink = sink + in.qty;
    if (in.action == Action::Order)
      fresh.on_fill(in.instrument, in.side * in.qty, in.instrument == Instrument::Equity ? t.under_px : t.yes_ask);
  }
  const auto b1 = std::chrono::steady_clock::now();
  const double mean = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(b1 - b0).count()) /
                      static_cast<double>(ticks.size());
  F sf(F::spec().defaults(), pos);  // step() only: decision logic without the latency stamp
  volatile double ssink = 0;
  const auto s0 = std::chrono::steady_clock::now();
  for (const auto& t : ticks) {
    const Intent in = sf.step(t, t.ts_ns);
    ssink = ssink + in.qty;
    if (in.action == Action::Order)
      sf.on_fill(in.instrument, in.side * in.qty, in.instrument == Instrument::Equity ? t.under_px : t.yes_ask);
  }
  const auto s1 = std::chrono::steady_clock::now();
  const double step_mean = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(s1 - s0).count()) /
                           static_cast<double>(ticks.size());
  std::sort(lat.begin(), lat.end());
  std::sort(blk.begin(), blk.end());
  const auto pct = [](const std::vector<std::int64_t>& v, double q) {
    if (v.empty()) return 0LL;
    return static_cast<long long>(v[static_cast<std::size_t>(q * static_cast<double>(v.size() - 1))]);
  };
  std::printf("%-22s %8.1f %8.1f %7lld %7lld %8lld %7lld %7lld %8lld %8zu %8zu\n", F::id, mean, step_mean, pct(lat, 0.50),
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

// ---- micro families: own tick types, same four timing views -------------------------------------------------------
// Synthetic, deterministic (LCG seed 42), 1-second ticks. Ladder: rich bid 0.50 + 0.08 z around a cheap ask of 0.47
// (an edge above 1 point on about a third of ticks), sizes 5 to 120, fee rate 0.02 on both legs, tick 0.01, quote
// ages 0 to 89 s, nested missing on 1 tick in 10. Ticket: bid 0.30 + 0.10 z, central reference 0.28, sizes 1 to 200,
// validated True on half the ticks, positions 0. Fills are fed back in full at the quote.
std::vector<LadderTick> ladder_tape(int n) {
  std::vector<LadderTick> v;
  v.reserve(static_cast<std::size_t>(n));
  std::uint64_t s = 42;
  for (int i = 0; i < n; ++i) {
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    const double z = static_cast<double>(s >> 11) / 9007199254740992.0 - 0.5;
    LadderTick t;
    t.ts_ns = (i + 1) * 1'000'000'000LL;
    t.bid_rich = 0.50 + 0.08 * z;
    t.ask_cheap = 0.47;
    t.bid_rich_qty = 5 + static_cast<double>((s >> 20) % 116);
    t.ask_cheap_qty = 5 + static_cast<double>((s >> 30) % 116);
    t.fee_rate_rich = t.fee_rate_cheap = 0.02;
    t.tick = 0.01;
    t.ts_rich_ns = t.ts_ns - static_cast<std::int64_t>((s >> 40) % 90) * 1'000'000'000LL;
    t.ts_cheap_ns = t.ts_ns;
    t.nested = (i % 10 == 0) ? Tri::Missing : Tri::True;
    t.event_held = 0;
    v.push_back(t);
  }
  return v;
}
std::vector<TicketTick> ticket_tape(int n) {
  std::vector<TicketTick> v;
  v.reserve(static_cast<std::size_t>(n));
  std::uint64_t s = 42;
  for (int i = 0; i < n; ++i) {
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    const double z = static_cast<double>(s >> 11) / 9007199254740992.0 - 0.5;
    TicketTick t;
    t.ts_ns = (i + 1) * 1'000'000'000LL;
    t.bid = 0.30 + 0.10 * z;
    t.bid_qty = 1 + static_cast<double>((s >> 20) % 200);
    t.ask = t.bid + 0.02;
    t.ref_lower = 0.20;
    t.ref_central = 0.28;
    t.validated = (i % 2) ? Tri::True : Tri::False;
    t.underlying_short = t.event_short = 0;
    v.push_back(t);
  }
  return v;
}

std::size_t feed(algos::LadderPair& a, const PairIntent& in) {
  if (in.action != MicroAction::Order) return 0;
  a.on_fill(Leg::Rich, in.rich.qty, in.rich.limit_px);
  a.on_fill(Leg::Cheap, in.cheap.qty, in.cheap.limit_px);
  return 1;
}
std::size_t feed(algos::TouchTicketReference& a, const TicketIntent& in) {
  if (in.action != MicroAction::Order) return 0;
  a.on_fill(in.qty, in.limit_px);
  return 1;
}
double sink_of(const PairIntent& i) { return i.rich.qty; }
double sink_of(const TicketIntent& i) { return i.qty; }

template <class F, class T>
void bench_micro(const std::vector<T>& ticks) {
  const Params dp = F::spec().defaults();
  {
    F w(dp, Position{});
    volatile double wsink = 0;
    for (const auto& t : ticks) { const auto in = w.on_tick(t, t.ts_ns); wsink = wsink + sink_of(in); feed(w, in); }
  }
  F algo(dp, Position{});
  std::vector<std::int64_t> lat;
  lat.reserve(ticks.size());
  std::size_t orders = 0;
  for (const auto& t : ticks) {
    const auto t0 = std::chrono::steady_clock::now();
    const auto in = algo.on_tick(t, t.ts_ns);
    const auto t1 = std::chrono::steady_clock::now();
    lat.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    orders += feed(algo, in);
  }
  std::vector<std::int64_t> blk;
  {
    F b(dp, Position{});
    volatile double bsink = 0;
    constexpr std::size_t kB = 64;
    for (std::size_t i = 0; i + kB <= ticks.size(); i += kB) {
      const auto c0 = std::chrono::steady_clock::now();
      for (std::size_t j = 0; j < kB; ++j) {
        const auto& t = ticks[i + j];
        const auto in = b.on_tick(t, t.ts_ns);
        bsink = bsink + sink_of(in);
        feed(b, in);
      }
      const auto c1 = std::chrono::steady_clock::now();
      blk.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(c1 - c0).count() /
                    static_cast<std::int64_t>(kB));
    }
  }
  F fresh(dp, Position{});
  volatile double sink = 0;
  const auto b0 = std::chrono::steady_clock::now();
  for (const auto& t : ticks) { const auto in = fresh.on_tick(t, t.ts_ns); sink = sink + sink_of(in); feed(fresh, in); }
  const auto b1 = std::chrono::steady_clock::now();
  const double mean = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(b1 - b0).count()) /
                      static_cast<double>(ticks.size());
  F sf(dp, Position{});
  volatile double ssink = 0;
  const auto s0 = std::chrono::steady_clock::now();
  for (const auto& t : ticks) { const auto in = sf.step(t, t.ts_ns); ssink = ssink + sink_of(in); feed(sf, in); }
  const auto s1 = std::chrono::steady_clock::now();
  const double step_mean = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(s1 - s0).count()) /
                           static_cast<double>(ticks.size());
  std::sort(lat.begin(), lat.end());
  std::sort(blk.begin(), blk.end());
  const auto pct = [](const std::vector<std::int64_t>& v, double q) {
    if (v.empty()) return 0LL;
    return static_cast<long long>(v[static_cast<std::size_t>(q * static_cast<double>(v.size() - 1))]);
  };
  std::printf("%-22s %8.1f %8.1f %7lld %7lld %8lld %7lld %7lld %8lld %8zu %8zu\n", F::id, mean, step_mean,
              pct(lat, 0.50), pct(lat, 0.99), pct(lat, 0.999), pct(blk, 0.50), pct(blk, 0.99), pct(blk, 0.999),
              F::spec().preset_count(), orders);
}

void bench_micro_replay(int n) {
  const auto lt = ladder_tape(n);
  std::vector<LadderRow> lrows(lt.size());
  for (std::size_t i = 0; i < lt.size(); ++i) {
    lrows[i].tick = lt[i];
    lrows[i].now_ns = lt[i].ts_ns;
    lrows[i].pair = static_cast<std::uint32_t>(i % 50);
    lrows[i].event = static_cast<std::uint32_t>(i % 10);
    lrows[i].result_rich = 0;
    lrows[i].result_cheap = 1;
  }
  const auto tt = ticket_tape(n);
  std::vector<TicketRow> trows(tt.size());
  for (std::size_t i = 0; i < tt.size(); ++i) {
    trows[i].tick = tt[i];
    trows[i].now_ns = tt[i].ts_ns;
    trows[i].ticket = static_cast<std::uint32_t>(i % 200);
    trows[i].underlying = static_cast<std::uint32_t>(i % 20);
    trows[i].event = static_cast<std::uint32_t>(i % 40);
    trows[i].outcome = 0;
  }
  const ParamSpec ls = algos::LadderPair::spec();
  (void)replay_ladder(ls.defaults(), lrows);
  std::size_t trades = 0;
  auto t0 = std::chrono::steady_clock::now();
  for (std::size_t i = 0; i < ls.preset_count(); ++i) trades += replay_ladder(ls.preset(i), lrows).n_trades;
  auto t1 = std::chrono::steady_clock::now();
  double sec = std::chrono::duration<double>(t1 - t0).count();
  std::printf("%-22s %8zu %10d %9.3f %14.3e   (%zu trades over all presets; 50 pairs, 10 events)\n", "ladder_pair",
              ls.preset_count(), n, sec, static_cast<double>(ls.preset_count()) * n / sec, trades);
  const ParamSpec ts = algos::TouchTicketReference::spec();
  (void)replay_tickets(ts.defaults(), trows);
  std::size_t props = 0, ords = 0;
  t0 = std::chrono::steady_clock::now();
  for (std::size_t i = 0; i < ts.preset_count(); ++i) {
    const auto st = replay_tickets(ts.preset(i), trows);
    props += st.n_proposals;
    ords += st.n_orders;
  }
  t1 = std::chrono::steady_clock::now();
  sec = std::chrono::duration<double>(t1 - t0).count();
  std::printf("%-22s %8zu %10d %9.3f %14.3e   (%zu proposals, %zu orders; 200 tickets, 20 underlyings, 40 events)\n",
              "touch_ticket_reference", ts.preset_count(), n, sec, static_cast<double>(ts.preset_count()) * n / sec,
              props, ords);
}

template <std::size_t... I>
void bench_all(const std::vector<MarketTick>& ticks, std::index_sequence<I...>) {
  (bench_family<std::variant_alternative_t<I, AnyAlgo>>(ticks), ...);
}
}  // namespace

int main(int argc, char** argv) {
  const int n = std::max(64, argc > 1 ? std::atoi(argv[1]) : 1'000'000);
  const int gn = std::max(1, argc > 2 ? std::atoi(argv[2]) : 20'000);
  const auto ticks = tape(n);
  std::printf("hedgecore_bench: %d ticks per family, default preset, shares_held 1000, seed 42\n", n);
  std::printf("mean = on_tick batch mean (incl. its own latency stamp); step_ns = step() only; call* = per-call incl. 4 clock reads; blk* = ns/call over 64-call blocks\n");
  std::printf("%-22s %8s %8s %7s %7s %8s %7s %7s %8s %8s %8s\n", "family", "mean_ns", "step_ns", "call50", "call99", "call99.9",
              "blk50", "blk99", "blk99.9", "presets", "orders");
  bench_all(ticks, std::make_index_sequence<kNumFamilies>{});
  std::printf("total presets: %zu\n\n", catalog().total);
  std::printf("replay_grid throughput: all presets of a family over %d ticks\n", std::min(gn, n));
  std::printf("%-22s %8s %10s %9s %14s\n", "family", "presets", "ticks", "seconds", "preset_ticks/s");
  const std::span<const MarketTick> gt(ticks.data(), static_cast<std::size_t>(std::min(gn, n)));
  for (const auto& f : catalog().families) bench_grid(f, gt);
  std::printf("\nmicro families (own tick types; synthetic tape, seed 42): %d ticks each, default preset\n", n);
  std::printf("%-22s %8s %8s %7s %7s %8s %7s %7s %8s %8s %8s\n", "family", "mean_ns", "step_ns", "call50", "call99",
              "call99.9", "blk50", "blk99", "blk99.9", "presets", "orders");
  bench_micro<algos::LadderPair>(ladder_tape(n));
  bench_micro<algos::TouchTicketReference>(ticket_tape(n));
  std::printf("total micro presets: %zu\n\n", micro_catalog().total);
  std::printf("micro replay throughput: all presets over %d rows (fills only at the quote)\n", std::min(gn, n));
  std::printf("%-22s %8s %10s %9s %14s\n", "family", "presets", "rows", "seconds", "preset_rows/s");
  bench_micro_replay(std::min(gn, n));
  return 0;
}
