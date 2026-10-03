from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from polybridge_research.schema import STRATEGY_FOR_FAMILY, assign_family, normalize_ticker

from .models import MARKET_EVENT_LABEL, AlgoChoice, ClassifyIn, ClassifyOut, Proposal, ProposalIn
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


def checked_algo(request: Request, algo: AlgoChoice | None, target_coverage: float) -> AlgoChoice | None:
    """Validate an algo choice against the library (compiled catalog, else the committed manifest) and pin it to
    concrete params, so the approved proposal says exactly what will run: ``resolved_params`` are the preset's (or
    the explicit) params with every hedge-size param capped at the proposal's target_coverage (the approval gate
    limits how much is hedged; ``capped`` lists what the cap lowered). 422 when the library cannot run it."""
    if algo is None:
        return None
    from .pipeline.engine_adapter import AlgoChoiceError, cap_coverage, resolve_algo
    from .pipeline.router import get_adapter
    manifest, _ = get_adapter(request).library()
    try:
        r = resolve_algo(manifest, algo.family, algo.preset_index, algo.params)
    except AlgoChoiceError as e:
        raise HTTPException(422, f"algo: {e}.")
    run, lowered = cap_coverage(r["params"], target_coverage)
    return AlgoChoice(family=r["family"], preset_index=r["preset_index"],
                      params=r["params"] if r["preset_index"] is None else None, source=algo.source,
                      resolved_params=run, coverage_cap=float(target_coverage), capped=lowered)


@router.post("/proposals", response_model=Proposal, status_code=201)
def create_proposal(body: ProposalIn, request: Request) -> Proposal:
    ticker = normalize_ticker(body.ticker)
    if ticker is None:
        raise HTTPException(422, "ticker must not be blank.")
    if body.market is not None:  # market-event path: a product hedge, no filing tags invented, no research claim
        return _store(request).propose(ticker=ticker, family="hedge", strategy="protective_put", basis="market_event",
                                       label=MARKET_EVENT_LABEL, market=body.market, direction=body.direction,
                                       shares_held=body.shares_held, target_coverage=body.target_coverage,
                                       algo=checked_algo(request, body.algo, body.target_coverage))
    fam = assign_family(body.tags)
    if fam is None:
        raise HTTPException(422, "These tags map to no pre-registered family, so there is no hedge to propose.")
    if body.algo is not None and fam.value != "hedge":
        raise HTTPException(422, "algo: opportunity proposals are executed outside hedgecore; an algo applies to hedges only.")
    return _store(request).propose(ticker=ticker, family=fam.value, strategy=STRATEGY_FOR_FAMILY[fam],
                                   basis="filing_tags", shares_held=body.shares_held,
                                   target_coverage=body.target_coverage, algo=checked_algo(request, body.algo, body.target_coverage))


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
