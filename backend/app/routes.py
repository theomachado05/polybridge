from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from polybridge_research.schema import STRATEGY_FOR_FAMILY, assign_family, normalize_ticker

from .models import ClassifyIn, ClassifyOut, Proposal, ProposalIn
from .store import AlreadyDecided, NotFound, ProposalStore

router = APIRouter()


def _store(request: Request) -> ProposalStore:
    return request.app.state.store


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/classify", response_model=ClassifyOut)
def classify(body: ClassifyIn) -> ClassifyOut:
    fam = assign_family(body.tags)
    return ClassifyOut(family=fam.value if fam else None, strategy=STRATEGY_FOR_FAMILY[fam] if fam else None)


@router.post("/proposals", response_model=Proposal, status_code=201)
def create_proposal(body: ProposalIn, request: Request) -> Proposal:
    fam = assign_family(body.tags)
    if fam is None:
        raise HTTPException(422, "These tags map to no pre-registered family, so there is no hedge to propose.")
    ticker = normalize_ticker(body.ticker)
    if ticker is None:
        raise HTTPException(422, "ticker must not be blank.")
    return _store(request).propose(ticker=ticker, family=fam.value, strategy=STRATEGY_FOR_FAMILY[fam],
                                   shares_held=body.shares_held, target_coverage=body.target_coverage)


@router.get("/proposals", response_model=list[Proposal])
def list_proposals(request: Request) -> list[Proposal]:
    return _store(request).list()


def _decide(request: Request, pid: str, action: str) -> Proposal:
    try:
        return getattr(_store(request), action)(pid)
    except NotFound:
        raise HTTPException(404, f"No proposal {pid}.")
    except AlreadyDecided:
        raise HTTPException(409, f"Proposal {pid} was already approved or rejected.")


@router.post("/proposals/{pid}/approve", response_model=Proposal)
def approve(pid: str, request: Request) -> Proposal:
    return _decide(request, pid, "approve")


@router.post("/proposals/{pid}/reject", response_model=Proposal)
def reject(pid: str, request: Request) -> Proposal:
    return _decide(request, pid, "reject")
