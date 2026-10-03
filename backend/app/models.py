from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, model_validator

FamilyName = Literal["hedge", "opportunity"]
Status = Literal["proposed", "approved", "rejected"]
Direction = Literal["down_on_yes", "up_on_yes"]  # which outcome hurts a long holder
Basis = Literal["filing_tags", "market_event"]
MARKET_EVENT_LABEL = "Product hedge — no confirmatory claim"


class MarketRef(BaseModel):
    source: str = Field(min_length=1)
    id: str = Field(min_length=1)
    token_id: str | None = None


class AlgoChoice(BaseModel):
    """Which hedgecore algo a bridge runs: a catalog family plus one preset (``preset_index``, a grid point of the
    family) or explicit ``params``, never both. Absent: the bridge runs the legacy Engine default spec."""
    family: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    preset_index: int | None = Field(default=None, ge=0)
    params: dict[str, float] | None = None
    source: Literal["ai_fit", "user"] = "ai_fit"  # label only: who chose it
    # Set by the server on the stored proposal (ignored in requests): the exact params that will run, after the
    # approved target_coverage capped the hedge-size params, and which params the cap lowered ({name: original}).
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
    """Either a filing-tags body ({ticker, tags, ...}) or a market-event body ({ticker, market, direction, ...})."""
    ticker: str = Field(min_length=1, max_length=12)
    tags: list[str] | None = None
    market: MarketRef | None = None
    direction: Direction | None = None
    shares_held: float = Field(gt=0, allow_inf_nan=False)
    target_coverage: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    algo: AlgoChoice | None = None  # the AI fit (or a user pick) the bridge should run once approved

    @model_validator(mode="after")
    def _one_basis(self) -> "ProposalIn":
        if self.market is not None:
            if self.tags:
                raise ValueError("Send either tags (filing path) or market + direction (market-event path), not both.")
            if self.direction is None:
                raise ValueError("A market-event proposal needs direction (down_on_yes or up_on_yes).")
        elif not self.tags:
            raise ValueError("Send tags (filing path) or market + direction (market-event path).")
        return self


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
    created_at: dt.datetime
    decided_at: dt.datetime | None = None
    bridge_started_at: dt.datetime | None = None
