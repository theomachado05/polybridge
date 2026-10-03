import datetime as dt
import re
from pathlib import Path

from polybridge_research.schema import (
    H1_TAGS, H2_TAGS, STRATEGY_FOR_FAMILY, Event, Family, assign_family, normalize_ticker,
)

TAGS_MD = Path(__file__).resolve().parents[1] / "HYPOTHESIS_TAGS.md"


def _tags_in_section(heading_prefix: str) -> set[str]:
    text = TAGS_MD.read_text()
    section = text.split(heading_prefix, 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([a-z0-9_]+)` \|", section, flags=re.M))


def test_code_tags_match_preregistration():
    assert H1_TAGS == _tags_in_section("## H1")
    assert H2_TAGS == _tags_in_section("## H2")
    assert len(H1_TAGS) == 7 and len(H2_TAGS) == 4
    assert not (H1_TAGS & H2_TAGS)


def test_assign_family_single_family():
    assert assign_family({"material_litigation"}) is Family.HEDGE
    assert assign_family(["workforce_reduction", "facility_closure"]) is Family.OPPORTUNITY


def test_cross_family_filing_belongs_to_neither():
    assert assign_family({"restructuring_plan", "asset_impairment"}) is None


def test_unrelated_tags_belong_to_neither():
    assert assign_family({"cfo_appointment"}) is None
    assert assign_family(set()) is None


def test_strategy_for_family():
    assert STRATEGY_FOR_FAMILY[Family.HEDGE] == "protective_put"
    assert STRATEGY_FOR_FAMILY[Family.OPPORTUNITY] == "cash_secured_put"


def test_event_family_and_immutability():
    ev = Event("AAPL", dt.date(2024, 3, 1), frozenset({"cybersecurity_incident"}))
    assert ev.family is Family.HEDGE
    assert ev.source == "massive_8k"


def test_normalize_ticker():
    assert normalize_ticker(" brk/b ") == "BRK.B"
    assert normalize_ticker("") is None
    assert normalize_ticker(None) is None
