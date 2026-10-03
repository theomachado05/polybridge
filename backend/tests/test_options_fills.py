"""Structure fill quotes for option intents (app/options/fills.py)."""
import pytest

from app.options import chain as ch
from app.options.fills import structure_legs, structure_quote

EXP = "2026-12-18"


def chain(put_quotes=True):
    c = ch.Chain("NVDA", 0.0)
    for k, cm, pm in ((145.0, 8.0, 2.0), (155.0, 3.0, 6.5)):
        c.quotes.append(ch.OptionQuote(f"C{k}", "call", k, EXP, bid=cm - 0.1, ask=cm + 0.1, mid=cm, mark_source="quote"))
        if put_quotes:
            c.quotes.append(ch.OptionQuote(f"P{k}", "put", k, EXP, bid=pm - 0.05, ask=pm + 0.05, mid=pm, mark_source="quote"))
        else:
            c.quotes.append(ch.OptionQuote(f"P{k}", "put", k, EXP, mid=pm, mark_source="fmv"))
    return c


def test_call_spread_net_mid_and_summed_half_spread():
    q = structure_quote(structure_legs(chain(), "call_spread", EXP, 145, 155))
    assert q["mid"] == pytest.approx(5.0) and q["half_spread"] == pytest.approx(0.2)
    assert (q["bid"], q["ask"]) == (pytest.approx(4.8), pytest.approx(5.2)) and q["source"] == "quote"
    assert [leg["side"] for leg in q["legs"]] == [1, -1] and q["legs"][0]["ticker"] == "C145.0"


def test_put_spread_straddle_and_csp():
    assert structure_quote(structure_legs(chain(), "put_spread", EXP, 145, 155))["mid"] == pytest.approx(4.5)
    assert structure_quote(structure_legs(chain(), "straddle", EXP, 145))["mid"] == pytest.approx(10.0)
    assert structure_quote(structure_legs(chain(), "cash_secured_put", EXP, 145))["mid"] == pytest.approx(-2.0)


def test_unquoted_leg_gives_mid_without_half_spread():
    q = structure_quote(structure_legs(chain(put_quotes=False), "straddle", EXP, 145))
    assert q["mid"] == pytest.approx(10.0) and q["half_spread"] is None and q["source"] == "fmv+quote"


def test_missing_leg_or_unknown_structure():
    assert structure_quote(structure_legs(chain(), "call_spread", EXP, 145, 150))["source"] == "missing_leg"
    assert structure_quote(structure_legs(chain(), "call_spread", "2027-01-15", 145, 155))["mid"] is None
    assert structure_legs(chain(), "iron_condor", EXP, 145) is None
    assert structure_quote(None)["mid"] is None
