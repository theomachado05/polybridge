#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>
#include "hedgecore/algos/ladder_pair.hpp"
#include "hedgecore/algos/touch_ticket_reference.hpp"

namespace hedgecore {

struct MicroFamilyInfo {
  const char* id;
  const char* division;
  const char* ui_kind;
  const char* status;
  const char* idea;
  std::span<const char* const> event_classes;
  std::span<const char* const> instruments;
  std::span<const BlockRef> blocks;
  std::span<const char* const> inputs;
  ParamSpec spec;
  std::size_t preset_count;
};

struct MicroCatalog {
  std::vector<MicroFamilyInfo> families;
  std::size_t total = 0;
};

namespace detail {
template <class F>
MicroFamilyInfo micro_info_of() {
  return MicroFamilyInfo{F::id,
                         F::division,
                         F::ui_kind,
                         F::status,
                         F::idea,
                         std::span<const char* const>(F::event_classes),
                         std::span<const char* const>(F::instruments),
                         std::span<const BlockRef>(F::blocks),
                         std::span<const char* const>(F::inputs),
                         F::spec(),
                         F::spec().preset_count()};
}
}

inline const MicroCatalog& micro_catalog() {
  static const MicroCatalog c = [] {
    MicroCatalog m;
    m.families.push_back(detail::micro_info_of<algos::LadderPair>());
    m.families.push_back(detail::micro_info_of<algos::TouchTicketReference>());
    for (const auto& f : m.families) m.total += f.preset_count;
    return m;
  }();
  return c;
}

struct LadderRow {
  LadderTick tick;
  std::int64_t now_ns = 0;
  std::uint32_t pair = 0;
  std::uint32_t event = 0;
  double result_rich = kNaN;
  double result_cheap = kNaN;
};

struct LadderTrade {
  std::size_t row = 0;
  std::uint32_t pair = 0, event = 0;
  std::int64_t t_entry_ns = 0;
  double qty = 0;
  double px_rich = 0, px_cheap = 0;
  double fee_rich = 0, fee_cheap = 0;
  double edge_locked = 0;
  double payoff = 0;
  bool settled = false;
  double pnl_points = 0;
  double pnl_usd = 0;
  double capital_usd = 0;
};

struct LadderReplayStats {
  std::size_t n_rows = 0, n_orders = 0, n_trades = 0;
  std::size_t n_leg_rejects = 0;
  std::size_t n_leg_risk = 0;
  double mean_pnl_points = kNaN;
  double total_pnl_usd = 0, total_capital_usd = 0;
  double min_pnl_minus_edge = kNaN;
  std::int64_t p50_ns = 0, p99_ns = 0;
  std::vector<LadderTrade> trades;
};

LadderReplayStats replay_ladder(const Params& params, std::span<const LadderRow> rows);

struct TicketRow {
  TicketTick tick;
  std::int64_t now_ns = 0;
  std::uint32_t ticket = 0;
  std::uint32_t underlying = 0, event = 0;
  double outcome = kNaN;
};

struct TicketDecision {
  std::size_t row = 0;
  std::uint32_t ticket = 0;
  MicroAction action = MicroAction::Hold;
  double qty = 0, px = kNaN, signal = kNaN;
  std::uint16_t reason = 0;
  bool filled = false;
  double pnl_points = kNaN;
};

struct TicketReplayStats {
  std::size_t n_rows = 0, n_proposals = 0, n_orders = 0, n_fills = 0;
  std::int64_t p50_ns = 0, p99_ns = 0;
  std::vector<TicketDecision> decisions;
};

TicketReplayStats replay_tickets(const Params& params, std::span<const TicketRow> rows);

}
