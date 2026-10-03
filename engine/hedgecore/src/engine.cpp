#include "hedgecore/engine.hpp"

#include <chrono>
#include <cmath>
#include <type_traits>
#include <utility>

namespace hedgecore {

const char* to_string(Reason r) noexcept {
  switch (r) {
    case Reason::Invalid: return "invalid";
    case Reason::Stale: return "stale";
    case Reason::BelowSigma: return "below_sigma";
    case Reason::InsideBand: return "inside_band";
    case Reason::Rebalance: return "rebalance";
    case Reason::RiskCapped: return "risk_capped";
    case Reason::BelowFees: return "below_fees";
  }
  return "unknown";
}

bool SigmaGate::pass(const Tick& t, std::int64_t) noexcept {
  if (last_p < 0) {          // first observation: nothing to compare against
    last_p = t.p;
    return true;
  }
  const double dp = t.p - last_p;
  const double sigma = std::sqrt(var);
  const bool ok = std::abs(dp) >= k * sigma;
  var = (1 - alpha) * var + alpha * dp * dp;  // update after the decision: the gate judges against the past
  last_p = t.p;
  return ok;
}

namespace {
bool spec_ok(const HedgeSpec& s) noexcept {
  const bool finite = std::isfinite(s.shares_held) && std::isfinite(s.target_coverage) &&
                      std::isfinite(s.band_shares) && std::isfinite(s.max_hedge_shares) &&
                      std::isfinite(s.sigma_k) && std::isfinite(s.sigma_alpha) &&
                      std::isfinite(s.gap_per_share) && std::isfinite(s.fee_per_share) &&
                      std::isfinite(s.half_spread) && std::isfinite(s.min_benefit_ratio);
  return finite && s.shares_held >= 0 && s.target_coverage >= 0 && s.target_coverage <= 1 &&
         s.band_shares >= 0 && s.max_hedge_shares >= 0 && s.sigma_k >= 0 && s.sigma_alpha >= 0 &&
         s.sigma_alpha <= 1 && s.max_staleness_ns >= 0 &&
         s.gap_per_share >= 0 && s.fee_per_share >= 0 && s.half_spread >= 0 && s.min_benefit_ratio >= 0;
}
}  // namespace

Engine::Engine(HedgeSpec spec)
    : spec_(std::move(spec)),
      gates_{StalenessGate{spec_.max_staleness_ns}, SigmaGate{spec_.sigma_k, spec_.sigma_alpha}},
      spec_valid_(spec_ok(spec_)) {}

Decision Engine::on_tick(const Tick& t, std::int64_t now_ns) {
  const auto t0 = std::chrono::steady_clock::now();
  auto finish = [&](Action a, Reason r, double qty, double target) {
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - t0).count();
    return Decision{a, r, qty, target, hedge_, static_cast<std::int64_t>(ns)};
  };

  if (!(t.p >= 0.0 && t.p <= 1.0)) return finish(Action::Hold, Reason::Invalid, 0, hedge_);
  if (!spec_valid_ || fill_invalid_ || !std::isfinite(hedge_)) return finish(Action::Hold, Reason::Invalid, 0, hedge_);

  for (auto& gate : gates_) {
    Reason failed = Reason::Rebalance;
    bool ok = std::visit([&](auto& g) {
      using G = std::decay_t<decltype(g)>;
      const bool pass = g.pass(t, now_ns);
      if (!pass) failed = G::fail_reason;
      return pass;
    }, gate);
    // The initial position h0 is sized on the first valid tick regardless of the sigma gate.
    if (!ok && !(failed == Reason::BelowSigma && !sized_once_)) return finish(Action::Hold, failed, 0, hedge_);
  }

  const double cap = spec_.max_hedge_shares > 0 ? spec_.max_hedge_shares : spec_.shares_held;
  const double uncapped = std::round(spec_.target_coverage * spec_.shares_held * t.p);
  const bool capped = uncapped > cap;
  const double target = capped ? cap : uncapped;
  const double qty = target - hedge_;
  if (!std::isfinite(qty) || !std::isfinite(target) || !std::isfinite(hedge_))
    return finish(Action::Hold, Reason::Invalid, 0, hedge_);

  if (std::abs(qty) < spec_.band_shares) return finish(Action::Hold, Reason::InsideBand, 0, target);
  if (spec_.gap_per_share > 0) {  // fee gate: expected benefit must cover round-trip cost
    const double cost = std::abs(qty) * (spec_.fee_per_share + spec_.half_spread);
    const double benefit = std::abs(qty) * spec_.gap_per_share * std::abs(t.p - p_at_last_order_);
    if (!std::isfinite(cost) || !std::isfinite(benefit)) return finish(Action::Hold, Reason::Invalid, 0, hedge_);
    if (benefit < cost * spec_.min_benefit_ratio) return finish(Action::Hold, Reason::BelowFees, 0, target);
  }
  sized_once_ = true;
  p_at_last_order_ = t.p;
  return finish(Action::Order, capped ? Reason::RiskCapped : Reason::Rebalance, qty, target);
}

}  // namespace hedgecore
