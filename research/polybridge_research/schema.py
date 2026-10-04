from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class Family(str, Enum):
    HEDGE = "hedge"
    OPPORTUNITY = "opportunity"


H1_TAGS: frozenset[str] = frozenset({
    "material_litigation", "class_action_filing", "regulatory_investigation", "cybersecurity_incident",
    "goodwill_impairment", "asset_impairment", "investment_impairment",
})
H2_TAGS: frozenset[str] = frozenset({
    "restructuring_plan", "workforce_reduction", "facility_closure", "business_line_exit",
})

STRATEGY_FOR_FAMILY: dict[Family, str] = {
    Family.HEDGE: "protective_put",
    Family.OPPORTUNITY: "cash_secured_put",
}


def assign_family(tags: Iterable[str]) -> Family | None:
    tag_set = set(tags)
    in_h1, in_h2 = bool(tag_set & H1_TAGS), bool(tag_set & H2_TAGS)
    if in_h1 and not in_h2:
        return Family.HEDGE
    if in_h2 and not in_h1:
        return Family.OPPORTUNITY
    return None


def normalize_ticker(t: object) -> str | None:
    if not isinstance(t, str) or not t.strip():
        return None
    return t.strip().upper().replace("/", ".")


@dataclass(frozen=True)
class Event:
    ticker: str
    filing_date: dt.date
    tags: frozenset[str]
    source: str = "massive_8k"
    accession_number: str | None = None

    @property
    def family(self) -> Family | None:
        return assign_family(self.tags)
