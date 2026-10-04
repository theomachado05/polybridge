#pragma once
// The micro families: ladder_pair (status: lead) and touch_ticket_reference (status: unvalidated). They take their
// own tick types (two books for a ladder pair; a ticket book plus an options reference for a ticket), so they sit
// beside the AnyAlgo library rather than in it: the 17 families, their presets and the catalog keys that list them
// are unchanged. The catalog lists these under `micro_families`.
//
// Replay: fills only at a quoted bid or ask, never more than the quoted size, never at a mid. A ladder pair is held to
// the result; a pair with no known result is valued at its floor payoff of $1 a contract (a nested pair pays at least
// that), and is reported as unsettled.
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
  const char* status;  // "lead" | "unvalidated"
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
}  // namespace detail

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

// ---- ladder replay ------------------------------------------------------------------------------------------------
struct LadderRow {
  LadderTick tick;            // tick.event_held is filled in by the replay from the other pairs it has entered
  std::int64_t now_ns = 0;    // decision time
  std::uint32_t pair = 0;     // one family instance per pair
  std::uint32_t event = 0;    // for the per-event cap
  double result_rich = kNaN;  // YES result of each rung (0, 0.5 or 1); NaN = not resolved
  double result_cheap = kNaN;
};

struct LadderTrade {
  std::size_t row = 0;
  std::uint32_t pair = 0, event = 0;
  std::int64_t t_entry_ns = 0;
  double qty = 0;                  // matched contracts on both legs
  double px_rich = 0, px_cheap = 0;  // fill prices: the rich bid and the cheap ask as quoted
  double fee_rich = 0, fee_cheap = 0;  // taker fee per contract on each leg
  double edge_locked = 0;          // px_rich - px_cheap - both fees: the floor of the P&L per contract
  double payoff = 0;               // per contract: (1 - result_rich) + result_cheap, or 1 when unresolved
  bool settled = false;
  double pnl_points = 0;           // 100 * (payoff - capital per contract)
  double pnl_usd = 0;
  double capital_usd = 0;          // qty * ((1 - px_rich) + px_cheap + both fees)
};

struct LadderReplayStats {
  std::size_t n_rows = 0, n_orders = 0, n_trades = 0;
  std::size_t n_leg_rejects = 0;   // legs that could not fill in full at the quote
  std::size_t n_leg_risk = 0;      // entries that left one leg unpaired
  double mean_pnl_points = kNaN;   // trade-weighted, as in the research summaries
  double total_pnl_usd = 0, total_capital_usd = 0;
  double min_pnl_minus_edge = kNaN;  // min over trades of (P&L per contract - edge locked at entry), in points
  std::int64_t p50_ns = 0, p99_ns = 0;
  std::vector<LadderTrade> trades;
};

LadderReplayStats replay_ladder(const Params& params, std::span<const LadderRow> rows);

// ---- ticket replay ------------------------------------------------------------------------------------------------
struct TicketRow {
  TicketTick tick;             // underlying_short / event_short are filled in by the replay from its own fills
  std::int64_t now_ns = 0;
  std::uint32_t ticket = 0;    // one family instance per ticket
  std::uint32_t underlying = 0, event = 0;
  double outcome = kNaN;       // YES result, for the P&L of filled sales only
};

struct TicketDecision {
  std::size_t row = 0;
  std::uint32_t ticket = 0;
  MicroAction action = MicroAction::Hold;  // Propose or Order
  double qty = 0, px = kNaN, signal = kNaN;
  std::uint16_t reason = 0;
  bool filled = false;
  double pnl_points = kNaN;  // filled sales with a known outcome: 100 * (px - outcome)
};

struct TicketReplayStats {
  std::size_t n_rows = 0, n_proposals = 0, n_orders = 0, n_fills = 0;
  std::int64_t p50_ns = 0, p99_ns = 0;
  std::vector<TicketDecision> decisions;  // every non-hold intent, in row order
};

TicketReplayStats replay_tickets(const Params& params, std::span<const TicketRow> rows);

}  // namespace hedgecore
