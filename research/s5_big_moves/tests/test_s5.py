import json

import pandas as pd
import pytest

from polybridge_research.calendar import TradingCalendar
from s5_big_moves import config as cfg
from s5_big_moves import run as r5
from s5_big_moves import universe as un


def test_events_are_dropped_by_tag():
    assert un.dropped_by_tag(["Sports", "Soccer"]) and un.dropped_by_tag(["Crypto Prices"]) and un.dropped_by_tag(["NBA Finals"])
    assert not un.dropped_by_tag(["Politics", "Fed Rates", "Economy"])


def test_sessions_alive_counts_only_the_window():
    cal = TradingCalendar("2025-01-01", "2027-12-31")
    assert un.sessions_alive("2026-03-02T00:00:00Z", "2026-03-06T00:00:00Z", cal) == 5
    assert un.sessions_alive("2025-01-01T00:00:00Z", "2025-09-01T00:00:00Z", cal) == 0
    assert un.sessions_alive("2026-09-28T00:00:00Z", "2027-06-01T00:00:00Z", cal) == 5


def test_a_link_needs_both_labellers_and_both_calling_it_an_event(tmp_path, monkeypatch):
    uni = {"counts": {}, "candidates": 3, "markets": [
        {"id": f"polymarket:{i}", "question": f"q{i}", "volume": 1.0, "start": "s", "end": "e", "token": "t"} for i in (1, 2, 3)]}
    (tmp_path / "universe.json").write_text(json.dumps(uni))

    def lab(name, answers):
        (tmp_path / f"labels_{name}.json").write_text(json.dumps({"labeller": name, "answers": answers}))

    up, down = {"ticker": "TLT", "direction": "up_on_yes", "confidence": 0.7}, {"ticker": "TLT", "direction": "down_on_yes", "confidence": 0.6}
    lab("1A", [{"id": "polymarket:1", "family": "event", "links": [up, {"ticker": "IWM", "direction": "up_on_yes", "confidence": 0.5}]},
               {"id": "polymarket:2", "family": "event", "links": [up]},
               {"id": "polymarket:3", "family": "event", "links": [up]}])
    lab("1B", [{"id": "polymarket:1", "family": "event", "links": [up, {"ticker": "NOT_ON_MENU", "direction": "up_on_yes"}]},
               {"id": "polymarket:2", "family": "event", "links": [down]},
               {"id": "polymarket:3", "family": "spot_proxy", "links": [up]}])
    monkeypatch.setattr(r5, "HERE", tmp_path)
    links, stats = r5.merge_links()
    assert [(l["market"], l["ticker"], l["direction"]) for l in links] == [("polymarket:1", "TLT", 1)]
    assert stats["agreed"] == 1 and stats["opposite_direction"] == 1 and stats["both_event"] == 2 and stats["markets_with_link"] == 1


def test_pick_uses_the_variant_threshold():
    s = pd.DataFrame({"ticker": list("abcd"), "x": [9.9, -10.0, 25.0, -4.0]})
    assert list(r5.pick(s, 10.0).ticker) == ["c", "b"]
    assert list(r5.pick(s, 5.0).ticker) == ["c", "b", "a"]


def test_costs_cover_both_legs_and_both_sides():
    assert "TLT" in cfg.LIQUID and "ZIM" not in cfg.LIQUID
    assert r5.cost_bp("TLT", 0.5, 1.0) == pytest.approx(2 * cfg.COST_LIQUID + 0.5 * 2 * cfg.COST_SPY)
    assert r5.cost_bp("ZIM", -1.0, 2.0) == pytest.approx(2 * (2 * cfg.COST_OTHER + 2 * cfg.COST_SPY))


def test_the_menu_has_no_duplicates_and_liquid_names_are_on_it():
    assert len(cfg.MENU) == len(set(cfg.MENU))
    assert cfg.LIQUID <= set(cfg.MENU) and cfg.CRYPTO_EQUITIES <= set(cfg.MENU)
