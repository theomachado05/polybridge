#pragma once
#include <cstdint>

namespace hedgecore {

enum class Rc : std::uint16_t {
  None = 0x0000,
  Invalid = 0x0001,
  InvalidParams = 0x0002,
  InvalidState = 0x0003,
  SignalMissing = 0x0101,
  Warmup = 0x0102,
  NoSignal = 0x0103,
  Stale = 0x0201,
  BelowSigma = 0x0202,
  SpreadTooWide = 0x0203,
  ThinBook = 0x0204,
  OutOfSession = 0x0205,
  Cooldown = 0x0206,
  OutsideEventWindow = 0x0207,
  NotNested = 0x0208,
  Rebalance = 0x0301,
  Entry = 0x0302,
  Exit = 0x0303,
  ZeroTarget = 0x0304,
  Handoff = 0x0305,
  Proposal = 0x0306,
  InsideBand = 0x0401,
  BelowFees = 0x0402,
  FeeUnknown = 0x0403,
  Sliced = 0x0404,
  IcebergCapped = 0x0405,
  Passive = 0x0406,
  Aggressive = 0x0407,
  Working = 0x0408,
  PositionCapped = 0x0501,
  NotionalCapped = 0x0502,
  DrawdownKill = 0x0503,
  GapFlipKill = 0x0504,
  DailyLossCap = 0x0505,
  NotionalUnknown = 0x0506,
  EventCapped = 0x0507,
  LegRisk = 0x0508,
  PositionUnknown = 0x0509,
  WashSale = 0x0601,
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
    case Rc::NotNested: return "not_nested";
    case Rc::Rebalance: return "rebalance";
    case Rc::Entry: return "entry";
    case Rc::Exit: return "exit";
    case Rc::ZeroTarget: return "zero_target";
    case Rc::Handoff: return "handoff";
    case Rc::Proposal: return "proposal";
    case Rc::InsideBand: return "inside_band";
    case Rc::BelowFees: return "below_fees";
    case Rc::FeeUnknown: return "fee_unknown";
    case Rc::Sliced: return "sliced";
    case Rc::IcebergCapped: return "iceberg_capped";
    case Rc::Passive: return "passive";
    case Rc::Aggressive: return "aggressive";
    case Rc::Working: return "working";
    case Rc::PositionCapped: return "position_capped";
    case Rc::NotionalCapped: return "notional_capped";
    case Rc::DrawdownKill: return "drawdown_kill";
    case Rc::GapFlipKill: return "gap_flip_kill";
    case Rc::DailyLossCap: return "daily_loss_cap";
    case Rc::NotionalUnknown: return "notional_unknown";
    case Rc::EventCapped: return "event_capped";
    case Rc::LegRisk: return "leg_risk";
    case Rc::PositionUnknown: return "position_unknown";
    case Rc::WashSale: return "wash_sale";
    case Rc::RoutedPoly: return "routed_poly";
    case Rc::RoutedKalshi: return "routed_kalshi";
    case Rc::NoRoute: return "no_route";
  }
  return "unknown";
}

constexpr const char* reason_name(std::uint16_t c) noexcept { return to_string(static_cast<Rc>(c)); }

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
    Rc::OutsideEventWindow, Rc::Rebalance, Rc::Entry, Rc::Exit, Rc::ZeroTarget, Rc::Handoff, Rc::InsideBand,
    Rc::BelowFees, Rc::FeeUnknown, Rc::Sliced, Rc::IcebergCapped, Rc::Passive, Rc::Aggressive, Rc::PositionCapped,
    Rc::NotionalCapped, Rc::DrawdownKill, Rc::GapFlipKill, Rc::DailyLossCap, Rc::NotionalUnknown, Rc::WashSale,
    Rc::RoutedPoly, Rc::RoutedKalshi, Rc::NoRoute};

inline constexpr Rc kMicroReasons[] = {Rc::NotNested, Rc::Proposal, Rc::Working, Rc::EventCapped, Rc::LegRisk,
                                       Rc::PositionUnknown};

}
