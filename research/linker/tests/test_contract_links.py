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
    nye = lm.classify("Will Amazon (AMZN) finish week of December 28 above $220?", None, {"createdAt": "2027-01-01T00:00:00Z"})
    assert nye["fields"]["window_end"] == "2027-01-01"
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
