from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

FamilyName = Literal["hedge", "opportunity"]
Status = Literal["proposed", "approved", "rejected"]


class ClassifyIn(BaseModel):
    tags: list[str]


class ClassifyOut(BaseModel):
    family: FamilyName | None
    strategy: str | None


class ProposalIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    tags: list[str] = Field(min_length=1)
    shares_held: float = Field(gt=0)
    target_coverage: float = Field(default=0.5, ge=0, le=1)


class Proposal(BaseModel):
    id: str
    ticker: str
    family: FamilyName
    strategy: str
    shares_held: float
    target_coverage: float
    status: Status
    created_at: dt.datetime
    decided_at: dt.datetime | None = None
