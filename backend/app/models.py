from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, model_validator

FamilyName = Literal["hedge", "opportunity"]
Status = Literal["proposed", "approved", "rejected"]
Direction = Literal["down_on_yes", "up_on_yes"]
Basis = Literal["filing_tags", "market_event"]
MARKET_EVENT_LABEL = "Product hedge, not a tested claim"
OPPORTUNITY_LABEL = ("Opportunity trade: PM price compared with the options-implied estimate, not a measured edge. "
                     "Option fills are simulated.")
OPP_DEFAULT_MAX_CONTRACTS = 10
OPP_DEFAULT_MAX_NOTIONAL = 10_000.0


class MarketRef(BaseModel):
    source: str = Field(min_length=1)
    id: str = Field(min_length=1)
    token_id: str | None = None


class AlgoChoice(BaseModel):
    family: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    preset_index: int | None = Field(default=None, ge=0)
    params: dict[str, float] | None = None
    source: Literal["ai_fit", "user"] = "ai_fit"
    resolved_params: dict[str, float] | None = None
    coverage_cap: float | None = None
    capped: dict[str, float] | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "AlgoChoice":
        if self.preset_index is not None and self.params is not None:
            raise ValueError("Send preset_index or params, not both.")
        if self.params is not None:
            import math
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in self.params.values()):
                raise ValueError("params must be finite numbers.")
        return self


class ClassifyIn(BaseModel):
    tags: list[str]


class ClassifyOut(BaseModel):
    family: FamilyName | None
    strategy: str | None


class ProposalIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    tags: list[str] | None = None
    market: MarketRef | None = None
    direction: Direction | None = None
    division: FamilyName = "hedge"
    shares_held: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    target_coverage: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    algo: AlgoChoice | None = None
    max_contracts: int | None = Field(default=None, ge=1, le=10_000)
    max_notional: float | None = Field(default=None, gt=0, le=10_000_000, allow_inf_nan=False)
    closed_pm_hedge: bool = False
    act_on_unvalidated: bool = False

    @model_validator(mode="after")
    def _one_basis(self) -> "ProposalIn":
        opp_market = self.market is not None and self.division == "opportunity"
        if self.market is not None:
            if self.tags:
                raise ValueError("Send either tags (filing path) or market + direction (market-event path), not both.")
            if self.direction is None and not opp_market:
                raise ValueError("A market-event proposal needs direction (down_on_yes or up_on_yes).")
        elif not self.tags:
            raise ValueError("Send tags (filing path) or market + direction (market-event path).")
        elif self.division != "hedge":
            raise ValueError("division applies to the market-event path; a filing proposal's family comes from its tags.")
        if opp_market and self.algo is None:
            raise ValueError("An opportunity proposal needs an algo (an Opportunity-division options family).")
        if not opp_market and not self.shares_held > 0:
            raise ValueError("shares_held must be > 0.")
        return self


class ApproveIn(BaseModel):
    ack_unvalidated: bool = False


class Proposal(BaseModel):
    id: str
    ticker: str
    family: FamilyName
    strategy: str
    shares_held: float
    target_coverage: float
    status: Status
    basis: Basis = "filing_tags"
    label: str | None = None
    market: MarketRef | None = None
    direction: Direction | None = None
    algo: AlgoChoice | None = None
    max_contracts: int | None = None
    max_notional: float | None = None
    closed_pm_hedge: bool = False
    act_on_unvalidated: bool = False
    evidence: dict | None = None
    ack_unvalidated: bool = False
    capacity: dict | None = None
    created_at: dt.datetime
    decided_at: dt.datetime | None = None
    bridge_started_at: dt.datetime | None = None
