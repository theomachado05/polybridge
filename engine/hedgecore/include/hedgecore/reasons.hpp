#pragma once
// Block-level reason codes carried in Intent::reason (uint16). High byte = block kind, low byte = the specific reason.
// Every Hold and every Order names the block that decided it, so the UI log can explain each tick.
#include <cstdint>

namespace hedgecore {

enum class Rc : std::uint16_t {
  // 0x00 general
  None = 0x0000,
  Invalid = 0x0001,        // tick fields out of range (e.g. probability outside [0, 1])
  InvalidParams = 0x0002,  // params outside the family's ParamSpec bounds, or non-finite
  InvalidState = 0x0003,   // a non-finite fill latched the algo
  // 0x01 signals
  SignalMissing = 0x0101,  // a required input field is NaN
  Warmup = 0x0102,         // stateful signal not warm yet
  NoSignal = 0x0103,       // signal finite but below the family's entry threshold
  // 0x02 gates
  Stale = 0x0201,
  BelowSigma = 0x0202,
  SpreadTooWide = 0x0203,
  ThinBook = 0x0204,
  OutOfSession = 0x0205,
  Cooldown = 0x0206,
  OutsideEventWindow = 0x0207,
  // 0x03 sizers
  Rebalance = 0x0301,   // hedge moved toward the sizer's target
  Entry = 0x0302,       // opportunity position opened
  Exit = 0x0303,        // opportunity position closed (converged / window closed / max hold)
  ZeroTarget = 0x0304,  // sizer target equals the current position
  // 0x04 execution
  InsideBand = 0x0401,
  BelowFees = 0x0402,
  FeeUnknown = 0x0403,   // cannot price the fee gate (price missing)
  Sliced = 0x0404,       // order emitted, clipped by the Slicer
  IcebergCapped = 0x0405,
  Passive = 0x0406,      // order emitted as a passive join
  Aggressive = 0x0407,   // order emitted crossing the spread because urgency is high
  // 0x05 risk
  PositionCapped = 0x0501,
  NotionalCapped = 0x0502,
  DrawdownKill = 0x0503,
  GapFlipKill = 0x0504,
  DailyLossCap = 0x0505,
  NotionalUnknown = 0x0506,
  // 0x06 tax
  WashSale = 0x0601,
  // 0x07 routing
  RoutedPoly = 0x0701,
  RoutedKalshi = 0x0702,
  NoRoute = 0x0703,
};

constexpr std::uint16_t code(Rc r) noexcept { return static_cast<std::uint16_t>(r); }

constexpr const char* to_string(Rc r) noexcept {
  switch (r) {
    case Rc::None: return "none";
    case Rc::Invalid: return "invalid";
    case Rc::InvalidParams: return "invalid_params";
    case Rc::InvalidState: return "invalid_state";
    case Rc::SignalMissing: return "signal_missing";
    case Rc::Warmup: return "warmup";
    case Rc::NoSignal: return "no_signal";
    case Rc::Stale: return "stale";
    case Rc::BelowSigma: return "below_sigma";
    case Rc::SpreadTooWide: return "spread_too_wide";
    case Rc::ThinBook: return "thin_book";
    case Rc::OutOfSession: return "out_of_session";
    case Rc::Cooldown: return "cooldown";
    case Rc::OutsideEventWindow: return "outside_event_window";
    case Rc::Rebalance: return "rebalance";
    case Rc::Entry: return "entry";
    case Rc::Exit: return "exit";
    case Rc::ZeroTarget: return "zero_target";
    case Rc::InsideBand: return "inside_band";
    case Rc::BelowFees: return "below_fees";
    case Rc::FeeUnknown: return "fee_unknown";
    case Rc::Sliced: return "sliced";
    case Rc::IcebergCapped: return "iceberg_capped";
    case Rc::Passive: return "passive";
    case Rc::Aggressive: return "aggressive";
    case Rc::PositionCapped: return "position_capped";
    case Rc::NotionalCapped: return "notional_capped";
    case Rc::DrawdownKill: return "drawdown_kill";
    case Rc::GapFlipKill: return "gap_flip_kill";
    case Rc::DailyLossCap: return "daily_loss_cap";
    case Rc::NotionalUnknown: return "notional_unknown";
    case Rc::WashSale: return "wash_sale";
    case Rc::RoutedPoly: return "routed_poly";
    case Rc::RoutedKalshi: return "routed_kalshi";
    case Rc::NoRoute: return "no_route";
  }
  return "unknown";
}

constexpr const char* reason_name(std::uint16_t c) noexcept { return to_string(static_cast<Rc>(c)); }

// The block kind that owns a reason code.
constexpr const char* reason_block(std::uint16_t c) noexcept {
  switch (c >> 8) {
    case 0x00: return "general";
    case 0x01: return "signals";
    case 0x02: return "gates";
    case 0x03: return "sizers";
    case 0x04: return "execution";
    case 0x05: return "risk";
    case 0x06: return "tax";
    case 0x07: return "routing";
  }
  return "unknown";
}

inline constexpr Rc kAllReasons[] = {
    Rc::None, Rc::Invalid, Rc::InvalidParams, Rc::InvalidState, Rc::SignalMissing, Rc::Warmup, Rc::NoSignal,
    Rc::Stale, Rc::BelowSigma, Rc::SpreadTooWide, Rc::ThinBook, Rc::OutOfSession, Rc::Cooldown,
    Rc::OutsideEventWindow, Rc::Rebalance, Rc::Entry, Rc::Exit, Rc::ZeroTarget, Rc::InsideBand, Rc::BelowFees,
    Rc::FeeUnknown, Rc::Sliced, Rc::IcebergCapped, Rc::Passive, Rc::Aggressive, Rc::PositionCapped,
    Rc::NotionalCapped, Rc::DrawdownKill, Rc::GapFlipKill, Rc::DailyLossCap, Rc::NotionalUnknown, Rc::WashSale,
    Rc::RoutedPoly, Rc::RoutedKalshi, Rc::NoRoute};

}  // namespace hedgecore
