#pragma once
#include <array>
#include <cmath>
#include "hedgecore/market.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

struct PMid {
  static constexpr const char* name = "PMid";
  static double read(const MarketTick& t) noexcept {
    if (!prob(t.yes_bid) || !prob(t.yes_ask)) return kNaN;
    return mid(t.yes_bid, t.yes_ask);
  }
};

struct ImpliedProb {
  static constexpr const char* name = "ImpliedProb";
  static double read(const MarketTick& t) noexcept {
    const double y = PMid::read(t);
    const double n = (prob(t.no_bid) && prob(t.no_ask)) ? mid(t.no_bid, t.no_ask) : kNaN;
    if (num(y) && num(n)) return (y + n) > 0 ? y / (y + n) : kNaN;
    if (num(y)) return y;
    if (num(n)) return 1.0 - n;
    return kNaN;
  }
};

struct BookImbalance {
  static constexpr const char* name = "BookImbalance";
  int levels = 3;
  static double depth(const BookLevel* side, int levels) noexcept {
    double s = 0;
    for (int i = 0; i < levels && i < kDepth; ++i) {
      if (!num(side[i].qty) || side[i].qty < 0) break;
      s += side[i].qty;
    }
    return s;
  }
  double read(const MarketTick& t) const noexcept {
    if (!num(t.bids[0].qty) || !num(t.asks[0].qty)) return kNaN;
    const double b = depth(t.bids, levels), a = depth(t.asks, levels);
    return (a + b) > 0 ? (b - a) / (b + a) : kNaN;
  }
};

struct Microprice {
  static constexpr const char* name = "Microprice";
  static double read(const MarketTick& t) noexcept {
    const double b = num(t.bids[0].px) ? t.bids[0].px : t.yes_bid;
    const double a = num(t.asks[0].px) ? t.asks[0].px : t.yes_ask;
    const double bq = t.bids[0].qty, aq = t.asks[0].qty;
    if (!prob(b) || !prob(a) || b > a || !num(bq) || !num(aq) || bq < 0 || aq < 0 || bq + aq <= 0) return kNaN;
    return (b * aq + a * bq) / (bq + aq);
  }
};

struct CrossVenueGap {
  static constexpr const char* name = "CrossVenueGap";
  static double read(const MarketTick& t) noexcept {
    const double here = PMid::read(t);
    if (!num(here) || !prob(t.p_other_venue)) return kNaN;
    return here - t.p_other_venue;
  }
};

inline constexpr int kMaxWindow = 64;

struct DeltaDp {
  static constexpr const char* name = "DeltaDp";
  int window = 5;
  std::array<double, kMaxWindow + 1> ring{};
  int head = 0, count = 0;
  double update(double p) noexcept {
    if (!num(p)) return kNaN;
    const int w = window < 1 ? 1 : (window > kMaxWindow ? kMaxWindow : window);
    ring[static_cast<std::size_t>(head)] = p;
    head = (head + 1) % (kMaxWindow + 1);
    if (count < kMaxWindow + 1) ++count;
    if (count <= w) return kNaN;
    const int back = (head - 1 - w + 2 * (kMaxWindow + 1)) % (kMaxWindow + 1);
    return p - ring[static_cast<std::size_t>(back)];
  }
};

struct EwmaVol {
  static constexpr const char* name = "EwmaVol";
  double alpha = 0.05;
  double var = 0, last = kNaN;
  int n = 0;
  struct Out { double dp, sigma_prev, sigma; };
  Out update(double p) noexcept {
    if (!num(p)) return {kNaN, kNaN, kNaN};
    if (!num(last)) { last = p; return {kNaN, kNaN, kNaN}; }
    const double dp = p - last;
    const double prev = n > 0 ? std::sqrt(var) : kNaN;
    var = n > 0 ? (1 - alpha) * var + alpha * dp * dp : dp * dp;
    ++n;
    last = p;
    return {dp, prev, std::sqrt(var)};
  }
};

struct Momentum {
  static constexpr const char* name = "Momentum";
  double alpha = 0.2;
  double ema = 0, last = kNaN;
  bool warm = false;
  double update(double p) noexcept {
    if (!num(p)) return kNaN;
    if (!num(last)) { last = p; return kNaN; }
    const double dp = p - last;
    ema = warm ? (1 - alpha) * ema + alpha * dp : dp;
    warm = true;
    last = p;
    return ema;
  }
};

struct MeanRevertZ {
  static constexpr const char* name = "MeanRevertZ";
  double alpha = 0.1;
  double mean = 0, var = 0;
  int n = 0;
  double update(double x) noexcept {
    if (!num(x)) return kNaN;
    double z = kNaN;
    if (n >= 2 && var > 0) z = (x - mean) / std::sqrt(var);
    if (n == 0) mean = x;
    else {
      const double d = x - mean;
      mean += alpha * d;
      var = (1 - alpha) * (var + alpha * d * d);
    }
    ++n;
    return z;
  }
  double fair() const noexcept { return n > 0 ? mean : kNaN; }
};

struct OptionImpliedProb {
  static constexpr const char* name = "OptionImpliedProb";
  static double read(const MarketTick& t) noexcept {
    if (prob(t.opt_implied_prob)) return t.opt_implied_prob;
    if (num(t.opt_delta)) return clampd(std::abs(t.opt_delta), 0.0, 1.0);
    return kNaN;
  }
};

struct PMvsOptionGap {
  static constexpr const char* name = "PMvsOptionGap";
  static double read(const MarketTick& t) noexcept {
    const double pm = ImpliedProb::read(t), op = OptionImpliedProb::read(t);
    return (num(pm) && num(op)) ? pm - op : kNaN;
  }
};

struct EightKScore {
  static constexpr const char* name = "EightKScore";
  static double read(const MarketTick& t) noexcept {
    return (num(t.eightk_score) && t.eightk_score >= -1 && t.eightk_score <= 1) ? t.eightk_score : kNaN;
  }
};

}
