// Full NYSE calendar (us_equity_regular_session, nyse_trading_day, nyse_early_close) against the backend session clock.
// The two tables below are backend/app/closed/session.py's answers for 2015-2030: every weekday that is not a trading
// day (rule-7.2 holidays plus one-off closures), and every 13:00 early-close day. backend/tests/
// test_engine_closed_session_hedge.py (test_engine_calendar_table_matches_session_py) re-derives them from session.py and fails if either side drifts.
#include <gtest/gtest.h>
#include <algorithm>
#include <cstdint>
#include <iterator>
#include "hedgecore/blocks/gates.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hctest;

namespace {
// session.py: weekdays 2015-2030 with is_trading_day == False (YYYYMMDD).
constexpr std::int64_t kSessionPyClosedWeekdays[] = {
    20150101, 20150119, 20150216, 20150403, 20150525, 20150703, 20150907, 20151126, 20151225, 20160101, 20160118,
    20160215, 20160325, 20160530, 20160704, 20160905, 20161124, 20161226, 20170102, 20170116, 20170220, 20170414,
    20170529, 20170704, 20170904, 20171123, 20171225, 20180101, 20180115, 20180219, 20180330, 20180528, 20180704,
    20180903, 20181122, 20181205, 20181225, 20190101, 20190121, 20190218, 20190419, 20190527, 20190704, 20190902,
    20191128, 20191225, 20200101, 20200120, 20200217, 20200410, 20200525, 20200703, 20200907, 20201126, 20201225,
    20210101, 20210118, 20210215, 20210402, 20210531, 20210705, 20210906, 20211125, 20211224, 20220117, 20220221,
    20220415, 20220530, 20220620, 20220704, 20220905, 20221124, 20221226, 20230102, 20230116, 20230220, 20230407,
    20230529, 20230619, 20230704, 20230904, 20231123, 20231225, 20240101, 20240115, 20240219, 20240329, 20240527,
    20240619, 20240704, 20240902, 20241128, 20241225, 20250101, 20250109, 20250120, 20250217, 20250418, 20250526,
    20250619, 20250704, 20250901, 20251127, 20251225, 20260101, 20260119, 20260216, 20260403, 20260525, 20260619,
    20260703, 20260907, 20261126, 20261225, 20270101, 20270118, 20270215, 20270326, 20270531, 20270618, 20270705,
    20270906, 20271125, 20271224, 20280117, 20280221, 20280414, 20280529, 20280619, 20280704, 20280904, 20281123,
    20281225, 20290101, 20290115, 20290219, 20290330, 20290528, 20290619, 20290704, 20290903, 20291122, 20291225,
    20300101, 20300121, 20300218, 20300419, 20300527, 20300619, 20300704, 20300902, 20301128, 20301225,
};
// session.py: days 2015-2030 with is_early_close == True (YYYYMMDD).
constexpr std::int64_t kSessionPyEarlyCloses[] = {
    20151127, 20151224, 20161125, 20170703, 20171124, 20180703, 20181123, 20181224, 20190703, 20191129, 20191224,
    20201127, 20201224, 20211126, 20221125, 20230703, 20231124, 20240703, 20241129, 20241224, 20250703, 20251128,
    20251224, 20261127, 20261224, 20271126, 20280703, 20281124, 20290703, 20291123, 20291224, 20300703, 20301129,
    20301224,
};
std::int64_t ymd(std::int64_t lday) {
  const Civil c = civil_from_days(lday);
  return c.y * 10000 + c.m * 100 + c.d;
}
bool in(const std::int64_t* b, const std::int64_t* e, std::int64_t v) { return std::find(b, e, v) != e; }
// ns of an ET wall-clock time on local day lday, with the 2007 DST rule.
std::int64_t et_ns(std::int64_t lday, int h, int m, int s = 0) {
  const std::int64_t y = civil_from_days(lday).y;
  const std::int64_t local = lday * 86400 + h * 3600 + m * 60 + s;
  const bool dst = lday > nth_sunday(y, 3, 2) && lday < nth_sunday(y, 11, 1);  // daytime only: never on a switch day
  return (local + (dst ? 4 : 5) * 3600) * kSec;
}
}  // namespace

TEST(CalendarParity, TradingDaysAndEarlyClosesMatchSessionPy2015To2030) {
  const auto* cb = std::begin(kSessionPyClosedWeekdays);
  const auto* ce = std::end(kSessionPyClosedWeekdays);
  const auto* eb = std::begin(kSessionPyEarlyCloses);
  const auto* ee = std::end(kSessionPyEarlyCloses);
  int closed = 0, early = 0;
  for (std::int64_t d = days_from_civil(2015, 1, 1); d <= days_from_civil(2030, 12, 31); ++d) {
    const unsigned wd = weekday_from_days(d);
    const bool weekday = wd != 0 && wd != 6;
    const bool want_trading = weekday && !in(cb, ce, ymd(d));
    const bool want_early = in(eb, ee, ymd(d));
    ASSERT_EQ(nyse_trading_day(d), want_trading) << ymd(d);
    ASSERT_EQ(nyse_early_close(d), want_early) << ymd(d);
    closed += weekday && !want_trading;
    early += want_early;
    // Regular-session membership at the edges, on the tick's own ET time.
    const int close_h = want_early ? 13 : 16;
    ASSERT_FALSE(us_equity_regular_session(et_ns(d, 9, 29, 59))) << ymd(d);
    ASSERT_EQ(us_equity_regular_session(et_ns(d, 9, 30)), want_trading) << ymd(d);
    ASSERT_EQ(us_equity_regular_session(et_ns(d, 12, 59, 59)), want_trading) << ymd(d);
    ASSERT_EQ(us_equity_regular_session(et_ns(d, 13, 0)), want_trading && !want_early) << ymd(d);
    ASSERT_EQ(us_equity_regular_session(et_ns(d, close_h - 1, 59, 59)), want_trading) << ymd(d);
    ASSERT_FALSE(us_equity_regular_session(et_ns(d, close_h, 0))) << ymd(d);
  }
  EXPECT_EQ(closed, static_cast<int>(std::size(kSessionPyClosedWeekdays)));
  EXPECT_EQ(early, static_cast<int>(std::size(kSessionPyEarlyCloses)));
}

TEST(CalendarParity, LegacySessionGateIsUnchanged) {
  // Other families keep us_equity_session: no one-off closures, 16:00 close on early-close days.
  blocks::Session legacy{true};
  blocks::Session full{true, true};
  const std::int64_t mourning = et_ns(days_from_civil(2025, 1, 9), 10, 0);
  EXPECT_TRUE(legacy.pass({pm(mourning, 0.5), 0}));
  EXPECT_FALSE(full.pass({pm(mourning, 0.5), 0}));
  const std::int64_t black_friday_1430 = et_ns(days_from_civil(2026, 11, 27), 14, 30);
  EXPECT_TRUE(legacy.pass({pm(black_friday_1430, 0.5), 0}));
  EXPECT_FALSE(full.pass({pm(black_friday_1430, 0.5), 0}));
}
