#pragma once
#include <cstddef>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>
#include "hedgecore/algos/book_imbalance_hedge.hpp"
#include "hedgecore/algos/closed_session_hedge.hpp"
#include "hedgecore/algos/equity_delta_bridge.hpp"
#include "hedgecore/algos/opportunity.hpp"
#include "hedgecore/algos/options.hpp"
#include "hedgecore/algos/sector_hedges.hpp"
#include "hedgecore/algos/stress_lead_hedge.hpp"

namespace hedgecore {

using AnyAlgo = std::variant<algos::EquityDeltaBridge, algos::StressLeadHedge, algos::BookImbalanceHedge,
                             algos::PolyKalshiSpread, algos::NoBidSeller, algos::FigStress, algos::HousingRates,
                             algos::MacroFedHedge, algos::ElectionHedge, algos::TariffTradeHedge,
                             algos::EnergyGeoHedge, algos::CryptoRegHedge, algos::TechRegHedge,
                             algos::BinaryVsSpreadArb, algos::VolVsPmMove, algos::EightKOpportunity,
                             algos::ClosedSessionHedge>;
inline constexpr std::size_t kNumFamilies = std::variant_size_v<AnyAlgo>;

struct FamilyInfo {
  const char* id;
  const char* division;
  const char* ui_kind;
  const char* idea;
  std::span<const char* const> event_classes;
  std::span<const char* const> instruments;
  std::span<const BlockRef> blocks;
  ParamSpec spec;
  std::size_t preset_count;
};

struct Catalog {
  std::vector<FamilyInfo> families;
  std::size_t total = 0;
};

namespace detail {
template <class F>
FamilyInfo info_of() {
  return FamilyInfo{F::id,
                    F::division,
                    F::ui_kind,
                    F::idea,
                    std::span<const char* const>(F::event_classes),
                    std::span<const char* const>(F::instruments),
                    std::span<const BlockRef>(F::blocks),
                    F::spec(),
                    F::spec().preset_count()};
}
template <std::size_t... I>
Catalog build_catalog(std::index_sequence<I...>) {
  Catalog c;
  (c.families.push_back(info_of<std::variant_alternative_t<I, AnyAlgo>>()), ...);
  for (const auto& f : c.families) c.total += f.preset_count;
  return c;
}
template <std::size_t I = 0>
AnyAlgo make(std::string_view id, const Params& p, const Position& pos) {
  if constexpr (I == kNumFamilies) {
    throw std::invalid_argument("unknown algo family: " + std::string(id));
  } else {
    using F = std::variant_alternative_t<I, AnyAlgo>;
    if (id == F::id) return AnyAlgo{std::in_place_index<I>, p, pos};
    return make<I + 1>(id, p, pos);
  }
}
}

inline const Catalog& catalog() {
  static const Catalog c = detail::build_catalog(std::make_index_sequence<kNumFamilies>{});
  return c;
}

inline const FamilyInfo* find_family(std::string_view id) noexcept {
  for (const auto& f : catalog().families)
    if (id == f.id) return &f;
  return nullptr;
}

inline AnyAlgo make_algo(std::string_view id, const Params& p, const Position& pos) {
  return detail::make(id, p, pos);
}

inline Intent on_tick(AnyAlgo& a, const MarketTick& t, std::int64_t now_ns) noexcept {
  return std::visit([&](auto& f) noexcept { return f.on_tick(t, now_ns); }, a);
}
inline void on_fill(AnyAlgo& a, Instrument i, double signed_qty, double px) noexcept {
  std::visit([&](auto& f) noexcept { f.on_fill(i, signed_qty, px); }, a);
}
inline void on_reject(AnyAlgo& a, Instrument i) noexcept {
  std::visit(
      [&](auto& f) noexcept {
        if constexpr (requires { f.on_reject(i); }) f.on_reject(i);
      },
      a);
}
inline const char* algo_id(const AnyAlgo& a) noexcept {
  return std::visit([](const auto& f) noexcept { return std::decay_t<decltype(f)>::id; }, a);
}

}
