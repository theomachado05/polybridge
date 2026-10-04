from __future__ import annotations

import datetime as dt
import json
import re

import numpy as np
import pytest

needs_engine = pytest.mark.skipif(__import__("importlib.util").util.find_spec("hedgecore") is None, reason="engine not installed")

from app.closed.session import is_early_close, is_trading_day
from app.pipeline.engine_adapter import (ENGINE_MANIFEST, AlgoChoiceError, normalize_manifest, resolve_algo)
from app.pipeline.shortlist import shortlist, unmet_requirements
from app.pipeline.ticks import TickSet, available_requirements
from tests.test_bridges import _approved, _body, client, replay_file  # noqa: F401

PARITY_CPP = ENGINE_MANIFEST.parent / "tests" / "test_calendar_parity.cpp"


def _cpp_table(name: str) -> set[dt.date]:
    m = re.search(name + r"\[\]\s*=\s*\{([^}]*)\}", PARITY_CPP.read_text())
    assert m, f"{name} not found in {PARITY_CPP}"
    return {dt.datetime.strptime(x, "%Y%m%d").date() for x in re.findall(r"\d{8}", m.group(1))}


def test_engine_calendar_table_matches_session_py():
    closed_weekdays, early, d = set(), set(), dt.date(2015, 1, 1)
    while d <= dt.date(2030, 12, 31):
        if d.weekday() < 5 and not is_trading_day(d):
            closed_weekdays.add(d)
        if is_early_close(d):
            early.add(d)
        d += dt.timedelta(days=1)
    assert _cpp_table("kSessionPyClosedWeekdays") == closed_weekdays
    assert _cpp_table("kSessionPyEarlyCloses") == early
    assert dt.date(2025, 1, 9) in closed_weekdays and dt.date(2026, 11, 27) in early


def _real() -> dict:
    return normalize_manifest(json.loads(ENGINE_MANIFEST.read_text()))


def test_closed_session_hedge_requires_a_simulated_pm_leg():
    fams = {f["id"]: f for f in _real()["families"]}
    assert fams["closed_session_hedge"]["requires"] == ["pm_leg_sim"]
    assert fams["poly_kalshi_spread"]["requires"] == ["both_venues"]
    assert all(f["requires"] in ([], ["both_venues"], ["listed_options"])
               for fid, f in fams.items() if fid != "closed_session_hedge")


def test_no_tick_set_satisfies_pm_leg_sim():
    n = 4
    ticks = {"ts_ns": np.arange(n, dtype=np.int64), "p_other_venue": np.full(n, 0.5),
             "opt_implied_prob": np.full(n, 0.5)}
    have = available_requirements(TickSet(ticks=ticks, source="replay"))
    assert have == {"both_venues", "listed_options"}


@pytest.mark.parametrize("event_class", ["macro_fed", "corporate_8k", "company_specific", "crypto"])
def test_fit_never_offers_closed_session_hedge(event_class):
    available = {"both_venues", "listed_options"}
    lists = {d: [f for f in fams if not unmet_requirements(f, available)]
             for d, fams in shortlist(_real(), event_class, available).items()}
    assert all(f["id"] != "closed_session_hedge" for fams in lists.values() for f in fams)
    assert lists["hedge"], "other hedge families are still offered"
    assert shortlist(_real(), event_class, available)["hedge"][-1]["id"] == "closed_session_hedge"


def test_hedge_bridge_refuses_closed_session_hedge():
    with pytest.raises(AlgoChoiceError, match="pm_leg_sim"):
        resolve_algo(_real(), "closed_session_hedge")
    assert resolve_algo(_real(), "equity_delta_bridge")["family"] == "equity_delta_bridge"


@needs_engine
def test_post_bridges_with_closed_session_hedge_is_422(client):  # noqa: F811
    pid = _approved(client)
    r = client.post("/bridges", json=_body(pid, family="closed_session_hedge"))
    assert r.status_code == 422
    assert "pm_leg_sim" in r.json()["detail"]
