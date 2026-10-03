#pragma once
// Small NaN-safe helpers shared by blocks. Everything here is constexpr/inline, allocation-free and noexcept.
#include <chrono>
#include <cmath>
#include <cstdint>
#include "hedgecore/market.hpp"

namespace hedgecore {

inline constexpr std::int64_t kNsPerSec = 1'000'000'000;
inline constexpr std::int64_t kNsPerDay = 86'400 * kNsPerSec;

inline bool num(double x) noexcept { return std::isfinite(x); }
inline bool prob(double p) noexcept { return p >= 0.0 && p <= 1.0; }  // false for NaN
inline double clampd(double x, double lo, double hi) noexcept { return x < lo ? lo : (x > hi ? hi : x); }
inline int sgn(double x) noexcept { return (x > 0) - (x < 0); }
// floor() tolerant of binary rounding (0.2 * 1000 / 0.5 is 399.999...); sizes are whole units.
inline double floor_units(double x) noexcept { return std::floor(x + 1e-9); }

// Mid of a two-sided quote; NaN unless both sides exist and bid <= ask.
inline double mid(double bid, double ask) noexcept {
  if (!num(bid) || !num(ask) || bid > ask) return kNaN;
  return 0.5 * (bid + ask);
}
inline double half_spread(double bid, double ask) noexcept {
  if (!num(bid) || !num(ask) || bid > ask) return kNaN;
  return 0.5 * (ask - bid);
}
// Underlying reference price: under_px, else the mid of under_bid/under_ask.
inline double under_ref(const MarketTick& t) noexcept {
  if (num(t.under_px) && t.under_px > 0) return t.under_px;
  const double m = mid(t.under_bid, t.under_ask);
  return m > 0 ? m : kNaN;
}

inline std::int64_t mono_ns() noexcept {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

// ---- civil calendar (Howard Hinnant's algorithms), used by the Session gate ----
constexpr std::int64_t days_from_civil(std::int64_t y, unsigned m, unsigned d) noexcept {
  y -= m <= 2;
  const std::int64_t era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<std::int64_t>(doe) - 719468;
}
struct Civil { std::int64_t y; unsigned m, d; };
constexpr Civil civil_from_days(std::int64_t z) noexcept {
  z += 719468;
  const std::int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  const unsigned doe = static_cast<unsigned>(z - era * 146097);
  const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  const std::int64_t y = static_cast<std::int64_t>(yoe) + era * 400;
  const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  const unsigned mp = (5 * doy + 2) / 153;
  const unsigned d = doy - (153 * mp + 2) / 5 + 1;
  const unsigned m = mp < 10 ? mp + 3 : mp - 9;
  return {y + (m <= 2), m, d};
}
constexpr unsigned weekday_from_days(std::int64_t z) noexcept {  // 0 = Sunday
  return static_cast<unsigned>(z >= -4 ? (z + 4) % 7 : (z + 5) % 7 + 6);
}
// Day number of the n-th (1-based) Sunday of a month.
constexpr std::int64_t nth_sunday(std::int64_t y, unsigned m, unsigned n) noexcept {
  const std::int64_t first = days_from_civil(y, m, 1);
  const unsigned wd = weekday_from_days(first);
  return first + (7 - wd) % 7 + 7 * (n - 1);
}
// Day number of the n-th (1-based) given weekday (0 = Sunday) of a month, and of the last one.
constexpr std::int64_t nth_weekday(std::int64_t y, unsigned m, unsigned wd, unsigned n) noexcept {
  const std::int64_t first = days_from_civil(y, m, 1);
  return first + (7 + wd - weekday_from_days(first)) % 7 + 7 * (n - 1);
}
constexpr std::int64_t last_weekday(std::int64_t y, unsigned m, unsigned wd) noexcept {
  const std::int64_t last = days_from_civil(m == 12 ? y + 1 : y, m == 12 ? 1 : m + 1, 1) - 1;
  return last - (7 + weekday_from_days(last) - wd) % 7;
}
// Gregorian Easter Sunday (anonymous / Meeus-Jones-Butcher algorithm).
constexpr std::int64_t easter_sunday(std::int64_t y) noexcept {
  const std::int64_t a = y % 19, b = y / 100, c = y % 100, d = b / 4, e = b % 4, f = (b + 8) / 25,
                     g = (b - f + 1) / 3, h = (19 * a + b - d - g + 15) % 30, i = c / 4, k = c % 4,
                     l = (32 + 2 * e + 2 * i - h - k) % 7, m = (a + 11 * h + 22 * l) / 451,
                     month = (h + l - 7 * m + 114) / 31, day = (h + l - 7 * m + 114) % 31 + 1;
  return days_from_civil(y, static_cast<unsigned>(month), static_cast<unsigned>(day));
}
// A fixed-date holiday moves to Friday when it falls on Saturday and to Monday when it falls on Sunday.
constexpr std::int64_t observed(std::int64_t day) noexcept {
  const unsigned wd = weekday_from_days(day);
  return wd == 6 ? day - 1 : (wd == 0 ? day + 1 : day);
}
// NYSE full-day closures (rule 7.2): New Year's Day (Sunday -> Monday; a Saturday New Year is not made up on the
// Friday before), MLK Day, Washington's Birthday, Good Friday, Memorial Day, Juneteenth (from 2022), Independence
// Day, Labor Day, Thanksgiving, Christmas. Early (13:00) closes and one-off closures are not modeled.
constexpr bool nyse_holiday(std::int64_t lday) noexcept {
  const Civil c = civil_from_days(lday);
  const std::int64_t y = c.y;
  const std::int64_t ny = days_from_civil(y, 1, 1);
  if (weekday_from_days(ny) == 0 && lday == ny + 1) return true;
  if (lday == ny) return true;
  if (lday == nth_weekday(y, 1, 1, 3) || lday == nth_weekday(y, 2, 1, 3)) return true;
  if (lday == easter_sunday(y) - 2) return true;
  if (lday == last_weekday(y, 5, 1)) return true;
  if (y >= 2022 && lday == observed(days_from_civil(y, 6, 19))) return true;
  if (lday == observed(days_from_civil(y, 7, 4))) return true;
  if (lday == nth_weekday(y, 9, 1, 1) || lday == nth_weekday(y, 11, 4, 4)) return true;
  if (lday == observed(days_from_civil(y, 12, 25))) return true;
  return false;
}

// True when ts_ns (UTC) falls in the US equity regular session, 09:30-16:00 America/New_York, Mon-Fri, outside NYSE
// full-day holidays. DST per the 2007 rule (2nd Sunday of March to 1st Sunday of November, 02:00 local).
constexpr bool us_equity_session(std::int64_t ts_ns) noexcept {
  const std::int64_t s = ts_ns >= 0 ? ts_ns / kNsPerSec : -((-ts_ns + kNsPerSec - 1) / kNsPerSec);
  const std::int64_t utc_day = s >= 0 ? s / 86400 : -((-s + 86399) / 86400);
  const std::int64_t y = civil_from_days(utc_day).y;
  const std::int64_t dst_start = nth_sunday(y, 3, 2) * 86400 + 7 * 3600;  // 02:00 EST = 07:00 UTC
  const std::int64_t dst_end = nth_sunday(y, 11, 1) * 86400 + 6 * 3600;   // 02:00 EDT = 06:00 UTC
  const std::int64_t offset = (s >= dst_start && s < dst_end) ? -4 * 3600 : -5 * 3600;
  const std::int64_t ls = s + offset;
  const std::int64_t lday = ls >= 0 ? ls / 86400 : -((-ls + 86399) / 86400);
  const unsigned wd = weekday_from_days(lday);
  if (wd == 0 || wd == 6 || nyse_holiday(lday)) return false;
  const std::int64_t sod = ls - lday * 86400;
  return sod >= 9 * 3600 + 30 * 60 && sod < 16 * 3600;
}

// Swap the YES and NO sides of a tick (for positions where YES is the favorable outcome: hedge families treat YES as
// the adverse event). Missing NO quotes are derived from YES as 1 - px; nothing missing becomes 0.
inline MarketTick flip_yes_no(const MarketTick& t) noexcept {
  MarketTick f = t;
  const bool no_q = num(t.no_bid) && num(t.no_ask);
  f.yes_bid = no_q ? t.no_bid : (num(t.yes_ask) ? 1.0 - t.yes_ask : kNaN);
  f.yes_ask = no_q ? t.no_ask : (num(t.yes_bid) ? 1.0 - t.yes_bid : kNaN);
  f.no_bid = t.yes_bid;
  f.no_ask = t.yes_ask;
  for (int i = 0; i < kDepth; ++i) {  // YES bids at px == NO asks at 1 - px
    f.bids[i] = {num(t.asks[i].px) ? 1.0 - t.asks[i].px : kNaN, t.asks[i].qty};
    f.asks[i] = {num(t.bids[i].px) ? 1.0 - t.bids[i].px : kNaN, t.bids[i].qty};
  }
  f.p_other_venue = num(t.p_other_venue) ? 1.0 - t.p_other_venue : kNaN;
  return f;
}

}  // namespace hedgecore
