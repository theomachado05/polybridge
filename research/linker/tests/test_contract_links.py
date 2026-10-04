"""The contract parser's ticker universe when the generic linker's instrument list sits next to it."""
import json

from linker import link_map as lm


def test_the_nested_instrument_list_does_not_replace_the_named_stock_list():
    here = lm.__file__.rsplit("/", 1)[0]
    nested = json.load(open(f"{here}/instruments.json"))
    assert {"classes", "tickers"} <= set(nested)                    # the generic linker's file: not a ticker -> name table
    assert not {"AS_OF", "CLASSES", "TICKERS"} & set(lm.UNIVERSE)    # so its keys never become tickers
    assert lm.UNIVERSE.get("BAC")                                    # and the backend's named stock list is still read
    assert lm.ticker_of("Will Bank of America close above $50 on October 9?")[0] == "BAC"


def test_a_ticket_on_a_named_stock_links_and_a_crypto_level_does_not():
    m = {"createdAt": "2026-10-01T00:00:00Z"}
    c = lm.classify("Will Bank of America close above $50 on October 9?", None, m)
    assert c["type"] == "close_above_ticket" and c["linkable"]
    assert (c["fields"]["underlying"], c["fields"]["level"], c["fields"]["direction"], c["fields"]["window_end"]) == ("BAC", 50.0, "up", "2026-10-09")
    assert lm.classify("Will Bitcoin close above $150,000 on October 9?", None, m)["type"] == "other"


# ---- Amendment 1 (linker/contract_eval/PLAN.md): the four parser faults found on half A, one test group each

FOMC_RULES = ("This market will resolve to \"Yes\" if the upper bound of the target federal funds rate is decreased at any "
              "point between December 16, 2025 and the completion of the Federal Open Market Committee (FOMC) meeting for "
              "October 2026, currently scheduled for October 27-28. Otherwise, this market will resolve to \"No\".\n\n"
              "If no October meeting takes place by November 7, 2026, 11:59 PM ET, and no qualifying rate cut has been "
              "announced, this market will resolve to \"No\".")


def test_fault1_a_month_followed_by_a_year_is_not_day_20_of_the_month_for_a_close_ticket():
    c = lm.classify("Will S&P 500 (SPX) close over $6,900 on the final trading day of January 2026?", None,
                    {"createdAt": "2026-01-06T00:00:00Z", "event_title": "S&P 500 (SPX) above ___ end of January?"})
    assert c["type"] == "close_above_ticket" and c["linkable"]
    f = c["fields"]
    assert (f["underlying"], f["level"], f["direction"]) == ("SPX", 6900.0, "up")
    assert f["window_end"] == "2026-01-31" and f["end_session"] == "2026-01-30"          # not 2026-01-20
    assert f["year_source"] == "explicit year"
    # an explicit year wins even when the market was created in another year
    m = lm.classify("Will S&P 500 (SPX) close over $6,500 on the last trading day of March 2026?", None,
                    {"createdAt": "2025-12-15T00:00:00Z"})
    assert m["fields"]["window_end"] == "2026-03-31" and m["fields"]["end_session"] == "2026-03-31"
    e = lm.classify("Will Meta (META) close above $840 end of October 2026?", None, {"createdAt": "2026-09-25T00:00:00Z"})
    assert e["fields"]["window_end"] == "2026-10-31" and e["fields"]["end_session"] == "2026-10-30"
    # a month without a year keeps the old reading: the month's last day, year from the creation date
    n = lm.classify("Will Meta (META) close above $840 end of October?", None, {"createdAt": "2026-09-25T00:00:00Z"})
    assert n["fields"]["window_end"] == "2026-10-31"


def test_fault1_a_rung_with_a_month_and_year_but_no_day_takes_its_day_from_the_rules_or_is_unlinkable():
    m = {"createdAt": "2026-02-25T00:00:00Z", "event_id": "fed", "groupItemTitle": "October 2026 Meeting"}
    c = lm.classify("Fed rate cut by October 2026 meeting?", FOMC_RULES, m)
    assert c["type"] == "ladder_rung" and c["linkable"]
    assert c["fields"]["date"] == "2026-10-28"                         # the meeting's last day, from the rules; not 2026-10-20
    assert c["fields"]["date_phrase"] == "October 2026"
    # an en dash range and a year re-read from the phrase (half A's pair p018)
    r25 = FOMC_RULES.replace("October 2026, currently scheduled for October 27-28", "October 2025, currently scheduled for October 28–29")
    assert lm.classify("Fed rate cut by October 2025 meeting?", r25, {**m, "createdAt": "2025-09-17T00:00:00Z"})["fields"]["date"] == "2025-10-29"
    # no day anywhere: no day is invented
    u = lm.classify("Fed rate cut by October 2026 meeting?", "Resolves Yes if the Fed cuts at its October 2026 meeting.", m)
    assert u["type"] == "ladder_rung" and not u["linkable"] and u["fields"]["date"] is None
    assert "no day in the deadline" in u["reasons"]
    # rungs with real days are unchanged
    d = lm.classify("Will Russia invade a NATO country by December 31, 2026?", "Resolves by December 31, 2026.", {**m, "createdAt": "2026-06-30T00:00:00Z"})
    assert d["fields"]["date"] == "2026-12-31" and d["linkable"]


def test_fault1_a_ladder_of_month_year_rungs_is_ordered_by_the_rules_days():
    def fed(i, mon, day_range):
        desc = FOMC_RULES.replace("October 2026, currently scheduled for October 27-28", f"{mon} 2026, currently scheduled for {mon} {day_range}")
        return {"id": str(i), "question": f"Fed rate cut by {mon} 2026 meeting?", "description": desc, "resolutionSource": "",
                "startDate": "2026-02-25T00:00:00Z", "endDate": "2026-12-31T00:00:00Z"}
    [lad] = lm.link_ladders([fed(2, "December", "8-9"), fed(1, "October", "27-28")], {"id": "fed", "title": "Fed rate cut by...?"})
    assert [r["date"] for r in lad["rungs"]] == ["2026-10-28", "2026-12-09"]


def test_fault2_weekly_close_tickets():
    m = {"createdAt": "2026-10-02T00:00:00Z", "event_title": "Will Google (GOOGL) finish week of October 5 above___?"}
    c = lm.classify("Will Google (GOOGL) finish week of October 5 above $365?", None, m)
    assert c["type"] == "close_above_ticket" and c["linkable"]
    f = c["fields"]
    assert (f["underlying"], f["level"], f["direction"], f["window_end"], f["end_session"]) == ("GOOGL", 365.0, "up", "2026-10-09", "2026-10-09")
    below = lm.classify("Will Opendoor (OPEN) finish week of October 5 below $4.50?", None, m | {"event_title": ""})
    assert below["type"] == "close_above_ticket" and below["fields"]["direction"] == "down" and below["fields"]["level"] == 4.5
    # a named day that is not a Monday: the Friday on or after it
    wed = lm.classify("Will Apple (AAPL) close the week of October 7 above $320?", None, {"createdAt": "2026-10-02T00:00:00Z"})
    assert wed["fields"]["window_end"] == "2026-10-09"
    # the year as for every ticket: re-derived from the creation date
    dec = lm.classify("Will Amazon (AMZN) finish week of January 4 above $220?", None, {"createdAt": "2026-12-28T00:00:00Z"})
    assert dec["fields"]["window_end"] == "2027-01-08"
    # review: a strike added mid-week (after the named Monday) settles on that week's Friday, not a year later
    for created in ("2026-10-06", "2026-10-08", "2026-10-09"):
        mid = lm.classify("Will Google (GOOGL) finish week of October 5 above $365?", None, m | {"createdAt": f"{created}T00:00:00Z"})
        assert mid["fields"]["window_end"] == "2026-10-09" and mid["linkable"], created
    # a late-December week settling in January, created after New Year
    # (that Friday, 2027-01-01, is New Year's Day: hardening fault 6 moves the week's close to Thursday 2026-12-31)
    nye = lm.classify("Will Amazon (AMZN) finish week of December 28 above $220?", None, {"createdAt": "2027-01-01T00:00:00Z"})
    assert nye["fields"]["window_end"] == "2026-12-31" and nye["fields"]["end_session"] == "2026-12-31"
    # bucket questions on the week's close stay "other"
    assert lm.classify("Will Micron (MU) close at $1,080-$1,100 on the final day of trading of the week of Oct 5 – Oct 9?", None,
                       {"createdAt": "2026-10-02T00:00:00Z"})["type"] == "other"


def test_fault3_negated_deadlines_are_not_rungs():
    m = {"createdAt": "2025-09-22T00:00:00Z", "event_id": "e"}
    why = "negated deadline: an earlier date is worth more, not less"
    for q in ("Will OpenAI not IPO by December 31, 2026?", "OpenAI won't IPO by December 31, 2026?",
              "Will the Fed fail to cut rates by December 31, 2026?", "No Fed rate cut by December 31, 2026?",
              "Will Congress not pass the bill before June 30, 2026?", "Will OpenAI still not have IPO'd by December 31, 2026?",
              "Will Trump not visit China by May 14?"):
        c = lm.classify(q, None, m)
        assert c["type"] == "other" and not c["linkable"] and c["reasons"] == [why], q
    # "not" that belongs to something else keeps the old behaviour
    for q in ("Will Israel and Hamas agree a ceasefire, not including a temporary pause, by December 31, 2026?",
              "Will a country not listed above recognise Palestine by December 31, 2026?",
              "Will the US strike Iran by December 31, 2026?"):
        assert lm.classify(q, None, m)["type"] == "ladder_rung", q


def test_fault3_negation_is_a_verb_phrase_not_any_no_or_not():
    # review: "no"/"not" that is not the question's verb-phrase negation keeps the old rung
    m = {"createdAt": "2026-09-20T00:00:00Z", "event_id": "e"}
    for q in ("Will a no-confidence vote against Starmer pass by December 31?",
              "Will the US impose a no-fly zone over Iran by June 30?",
              "Will the No Kings protest reach 5 million by December 31?",
              "Will 'No Other Land' win an Oscar by March 31?",
              "Will Ukraine agree to cede territory, no matter how small, by December 31?",
              "Will Elon Musk, not Sam Altman, win the lawsuit by December 31?"):
        c = lm.classify(q, None, m)
        assert c["type"] == "ladder_rung" and c["linkable"], q
    for q in ("Will the Fed not cut rates by December 31?", "Will the bill fail to pass by June 30?",
              "Won't Trump leave office by December 31?", "No listed company closes Warner Bros acquisition by December 31?",
              "Will no candidate win a majority by December 31?", "Will there be no recession by December 31?",
              "Will Trump never visit China by December 31?"):
        assert lm.classify(q, None, m)["type"] == "other", q


def test_fault4_tokens_are_not_stocks():
    m = {"createdAt": "2026-06-29T00:00:00Z", "event_id": "e", "event_title": "What price will $ANSEM hit in 2026?"}
    a = lm.classify("Will $ANSEM dip to $0.06 before 2027?", None, m)
    assert a["type"] not in ("touch_ticket", "close_above_ticket") and not a["linkable"]
    assert lm.ticker_of("Will $ANSEM dip to $0.06 before 2027?", "What price will $ANSEM hit in 2026?")[0] is None
    # a token's price question with a cumulative deadline is a ladder rung
    h = lm.classify("Will Hyperliquid reach $100 by December 31, 2026?", None,
                    {"createdAt": "2025-11-24T00:00:00Z", "event_id": "h", "event_title": "What price will Hyperliquid hit in 2026?"})
    assert h["type"] == "ladder_rung" and h["fields"]["date"] == "2026-12-31"
    assert lm.classify("Will $ANSEM reach $1.5 by December 31, 2026?", None, m)["type"] == "ladder_rung"
    # without one it is "other"
    assert lm.classify("Will BNB dip to $700 in October?", None,
                       {"createdAt": "2026-10-01T00:00:00Z", "event_title": "What price will BNB hit in October?"})["type"] == "other"
    assert lm.classify("Will Ink close above $2 on October 9?", None, {"createdAt": "2026-10-01T00:00:00Z"})["type"] == "other"
    # stocks are unchanged: a universe cashtag, "(TSLA)", a symbol outside the universe, and S&P 500 without (SPX)
    assert lm.ticker_of("Will $TSLA reach $500 in October?")[0] == "TSLA"
    t = lm.classify("Will Tesla, Inc. (TSLA) hit (HIGH) $435 in October?", None, {"createdAt": "2026-09-25T00:00:00Z"})
    assert t["type"] == "touch_ticket" and t["linkable"] and t["fields"]["underlying"] == "TSLA"
    s = lm.classify("Will SpaceX (SPCX) close above $110 end of October?", None, {"createdAt": "2026-09-25T00:00:00Z"})
    assert "SPCX" not in lm.UNIVERSE and s["type"] == "close_above_ticket" and s["fields"]["underlying"] == "SPCX" and s["linkable"]
    spx = lm.classify("Will S&P 500 hit $7000 by December 31?", None, {"createdAt": "2026-03-01T00:00:00Z"})
    assert spx["type"] == "touch_ticket" and not spx["linkable"]


def test_end_of_february_is_the_months_last_day_not_the_next_leap_day():
    """Found on the held-out half after it was scored: a ticket created in January 2026 linked to 2028-02-29."""
    q = "Will Amazon (AMZN) close above $230 end of February?"
    f = lm.classify(q, None, {"createdAt": "2026-01-28T00:00:00Z"})["fields"]
    assert (f["window_end"], f["end_session"]) == ("2026-02-28", "2026-02-27")          # the 28th is a Saturday
    assert lm.classify(q, None, {"createdAt": "2027-12-20T00:00:00Z"})["fields"]["window_end"] == "2028-02-29"   # a real leap year
    assert lm.classify(q, None, {"createdAt": "2026-03-02T00:00:00Z"})["fields"]["window_end"] == "2027-02-28"   # next February
    assert lm.classify("Will Apple (AAPL) close above $230 end of March?", None, {"createdAt": "2026-02-28T00:00:00Z"})["fields"]["window_end"] == "2026-03-31"
    assert lm.classify("Will Apple (AAPL) close above $230 end of December?", None, {"createdAt": "2026-12-01T00:00:00Z"})["fields"]["window_end"] == "2026-12-31"
    assert lm.classify("Will Apple (AAPL) close above $230 end of February 2028?", None, {"createdAt": "2026-01-28T00:00:00Z"})["fields"]["window_end"] == "2028-02-29"


# ---- Hardening before submission (two independent verifiers' fault classes): one test group per class. A wrong linkable
# answer is the dangerous kind; where the right answer is not certain the parser refuses with a reason.

def _c(q, title="", created="2026-02-20", rules=None, **kw):
    return lm.classify(q, rules, {"createdAt": f"{created}T00:00:00Z", "event_title": title, "event_id": "e", **kw})


def test_h1_a_year_written_only_in_the_event_title_wins_over_the_creation_year():
    eth = _c("Will Ethereum hit $10,000 by December 31?", "What price will Ethereum hit in 2025?", "2024-12-30")
    assert eth["type"] == "ladder_rung" and eth["linkable"] and eth["fields"]["date"] == "2025-12-31"   # not 2024-12-31
    assert eth["fields"]["year_source"] == "year from the event title"
    aapl = _c("Will Apple (AAPL) reach $300 by December 31?", "What will Apple (AAPL) hit in 2026?", "2025-12-30")
    assert aapl["type"] == "touch_ticket" and aapl["linkable"] and aapl["fields"]["window_end"] == "2026-12-31"
    for title in ("What will Apple hit in December 2026?", "Apple above ___ end of December 2026?", "Apple targets 2026?"):
        r = _c("Will Apple (AAPL) close above $300 on December 31?", title, "2025-12-30")
        assert r["fields"]["window_end"] == "2026-12-31", title
    # "before 2027" / "by 2027" name a deadline, not the window's year: the creation rule stands
    assert _title_years("Will X happen before 2027?") == set() and _title_years("Will X happen by 2027?") == set()
    # the title's year is in the past for a market created later: the two disagree, so the date is refused
    bad = _c("Will Apple (AAPL) reach $300 by January 31?", "What will Apple (AAPL) hit in 2025?", "2025-12-10")
    assert not bad["linkable"] and "year unclear: the event title says 2025, creation implies 2026" in bad["reasons"]


def _title_years(t):
    return lm._title_years(t)


def test_h1_a_ladder_with_the_year_only_in_its_title_is_ordered_by_that_year():
    def rung(i, q, created):
        return {"id": str(i), "question": q, "description": "Binance ETH/USDT 1m candles.", "resolutionSource": "",
                "startDate": f"{created}T00:00:00Z", "endDate": "2026-01-01T00:00:00Z"}
    [lad] = lm.link_ladders([rung(1, "Will Ethereum hit $5,000 by December 31?", "2024-12-30"),
                             rung(2, "Will Ethereum hit $5,000 by June 30?", "2025-01-05")],
                            {"id": "eth25", "title": "What price will Ethereum hit in 2025?"})
    assert [r["date"] for r in lad["rungs"]] == ["2025-06-30", "2025-12-31"]          # December was ordered first, a year early


def test_h2_symbols_in_parentheses_are_tickers_only_when_they_are_stocks():
    m = "2026-10-01"
    # a time zone or currency in parentheses is not a ticker
    et = _c("Will Apple close above $250 on October 9 (ET)?", created=m)
    assert et["fields"]["underlying"] == "AAPL" and et["linkable"]
    assert lm.ticker_of("Will the US Dollar (USD) close above $1 on October 9?")[0] is None
    # tokens written with a symbol: never the stock of the same symbol
    for q in ("Will Litecoin (LTC) reach $150 in October?", "Will Hyperliquid (HYPE) close above $50 on October 9?",
              "Will Chainlink (LINK) reach $30 in October?", "Will Cardano (ADA) dip to $0.40 in October?"):
        r = _c(q, created=m)
        assert r["type"] not in ("touch_ticket", "close_above_ticket") and not r["linkable"], q
    assert lm.ticker_of("Will (LINK) reach $30 in October?", "What price will LINK hit in October?")[0] is None
    # a token's deadline question is a rung, as for "Hyperliquid" without a symbol
    assert _c("Will Litecoin (LTC) reach $150 by December 31?", created=m)["type"] == "ladder_rung"
    # a symbol outside the universe beside a token marker is refused, not guessed
    d = _c("Will Circle (CRCL) reach $300 in October?", "What will Circle hit as the stablecoin bill passes?", m)
    assert d["type"] == "touch_ticket" and not d["linkable"] and "symbol in parentheses is not a known stock" in d["reasons"]
    # real stocks still link, including ones outside the named universe
    for q, tk in (("Will Micron (MU) close above $960 end of October?", "MU"), ("Will SK hynix (SKHY) hit (HIGH) $228 in October?", "SKHY"),
                  ("Will SpaceX (SPCX) close above $110 end of October?", "SPCX"), ("Will South Korea ETF (EWY) hit (LOW) $172 in October?", "EWY"),
                  ("Will Tesla, Inc. (TSLA) hit (HIGH) $435 in October?", "TSLA"), ("Will (SHOP) reach $120 in October?", "SHOP")):
        r = _c(q, created="2026-09-25")
        assert r["linkable"] and r["fields"]["underlying"] == tk, q


def test_h3_numbers_that_are_not_dollar_prices_are_not_levels():
    for q, why in (("Will Tesla reach 500,000 deliveries by June 30?", "unit"),
                   ("Will Netflix reach 350 million subscribers by June 30?", "unit"),
                   ("Will Nvidia (NVDA) market cap close above $6 trillion on June 30?", "unit"),
                   ("Will Apple (AAPL) market cap reach $5 by June 30?", "market cap"),
                   ("Will Tesla (TSLA) reach $1.5K by June 30?", "suffix"),
                   ("Will Netflix (NFLX) close above $0.00 end of March?", "above zero"),
                   ("Will Netflix dip to $0 in April?", "above zero")):
        r = _c(q, "What will Netflix (NFLX) hit in April 2026?" if "April" in q else "")
        assert r["type"] in ("touch_ticket", "close_above_ticket") and not r["linkable"], q
        assert any(why in x for x in r["reasons"]), (q, r["reasons"])
    # a whole number with a suffix is not read as a level at all: a deadline question, not a ticket
    assert _c("Will Tesla (TSLA) reach $2T by June 30?")["type"] not in ("touch_ticket", "close_above_ticket")
    ok = _c("Will Tesla (TSLA) reach $1,500 by June 30?")
    assert ok["linkable"] and ok["fields"]["level"] == 1500.0


def test_h4_negated_tickets_are_not_linked_as_up():
    why = "negated ticket: yes means the level was not reached"
    for q in ("Will Tesla (TSLA) not reach $500 by June 30?", "Will Tesla (TSLA) fail to reach $500 by June 30?",
              "Will Tesla (TSLA) fail to close above $500 on June 30?", "Will Tesla (TSLA) not close above $500 on June 30?",
              "Won't Tesla (TSLA) hit $500 by June 30?"):
        r = _c(q)
        assert r["type"] == "other" and not r["linkable"] and r["reasons"] == [why], q
    assert _c("Will Tesla (TSLA), not Rivian, close above $500 on June 30?")["type"] == "close_above_ticket"


def test_h5_close_days_are_read_or_refused_never_put_on_the_months_last_day():
    def end(q, title=""):
        r = _c(q, title)
        return r["fields"].get("window_end"), r["linkable"], r["reasons"]
    assert end("Will Apple (AAPL) close above $250 on 6 March 2026?")[:2] == ("2026-03-06", True)
    assert end("Will Apple (AAPL) close above $250 on Sept 15?")[:2] == ("2026-09-15", True)
    assert end("Will Apple (AAPL) close above $250 on the 15th of March?")[:2] == ("2026-03-15", True)
    w, ok, why = end("Will Apple (AAPL) close above $250 on the first trading day of March?")
    assert w is None and not ok and "no close day in the question" in why
    # the month-end readings that are right stay
    assert end("Will Apple (AAPL) close above $250 end of March?")[:2] == ("2026-03-31", True)
    assert end("Will Apple (AAPL) close over $250 on the final trading day of March 2026?")[:2] == ("2026-03-31", True)
    assert end("Will Apple (AAPL) hit (HIGH) $300 in March?", "What will Apple (AAPL) hit in March?")[:2] == ("2026-03-31", True)
    # "before March 13" ends on March 12; a day in the question wins over the title's month; a bare month is refused
    assert end("Will Apple (AAPL) reach $300 before March 13?")[:2] == ("2026-03-12", True)
    assert end("Will Apple (AAPL) reach $300 by March 15?", "What will Apple (AAPL) hit in March?")[:2] == ("2026-03-15", True)
    assert not end("Will Apple (AAPL) reach $300 by April 15?", "What will Apple (AAPL) hit in March?")[1]
    w, ok, why = end("Will Apple (AAPL) reach $300 by March?")
    assert not ok and "no day in the window end" in why


def test_h6_a_window_ending_on_a_market_holiday_lands_on_the_last_session():
    # Good Friday 2026-04-03: the week's close is Thursday 04-02 (the option code would otherwise take the next week's expiry)
    for q, title in (("Will Apple (AAPL) finish week of March 30 above $250?", ""),
                     ("Will Apple (AAPL) hit (HIGH) $300 Week of March 30 2026?", "What will Apple (AAPL) hit Week of March 30 2026?"),
                     ("Will Apple (AAPL) close above $250 on April 3, 2026?", "")):
        f = _c(q, title, "2026-03-27")["fields"]
        assert (f["window_end"], f["end_session"]) == ("2026-04-02", "2026-04-02"), q
    # Memorial Day 2027-05-31 is May's last weekday: the month's touch window ends Friday 05-28
    f = _c("Will Apple (AAPL) hit (LOW) $200 in May?", "What will Apple (AAPL) hit in May 2027?", "2027-04-25")["fields"]
    assert (f["window_end"], f["end_session"]) == ("2027-05-28", "2027-05-28")
    # a weekend end keeps its date; its Friday is the session
    f = _c("Will Meta (META) close above $840 end of October?", created="2026-09-25")["fields"]
    assert (f["window_end"], f["end_session"]) == ("2026-10-31", "2026-10-30")
    # the repository calendar and the fallback holiday table agree for 2025-2027
    from datetime import date, timedelta
    assert lm._SESSIONS is not None
    off = {date(2025, 1, 1) + timedelta(days=i) for i in range(365 * 3)}
    off = {d for d in off if d.weekday() < 5 and d not in lm._SESSIONS}
    assert off == lm.US_MARKET_HOLIDAYS


def test_h7_conditional_questions_are_not_plain_tickets():
    for q in ("Will Apple (AAPL) close above $250 on October 9 if Nvidia closes above $200?",
              "Will the Fed cut rates by December 31 if Nvidia closes above $200?",
              "Will Tesla (TSLA) reach $500 in October unless deliveries miss?"):
        r = _c(q, created="2026-10-01")
        assert r["type"] == "other" and not r["linkable"] and r["reasons"] == ["conditional question: not a plain ticket"], q


def test_h5_a_week_with_no_named_day_is_refused_not_put_after_the_months_end():
    # review: "week of March" and "the first / last week of March" named no day and linked to the Friday after March 31
    for q in ("Will Tesla (TSLA) finish week of March above $500?",
              "Will Tesla (TSLA) close above $500 at the end of the first week of March?",
              "Will Tesla (TSLA) close above $500 in the last week of March?",
              "Will Tesla (TSLA) close above $500 in the second week of March 2?"):
        r = _c(q, created="2026-02-25")
        assert r["type"] == "close_above_ticket" and not r["linkable"], q
        assert r["fields"]["window_end"] is None and "no close day in the question" in r["reasons"], q
    # the week of a named day still links to that week's Friday
    f = _c("Will Tesla (TSLA) finish week of March 2 above $500?", created="2026-02-25")["fields"]
    assert f["window_end"] == "2026-03-06"
