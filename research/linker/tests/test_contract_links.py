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
