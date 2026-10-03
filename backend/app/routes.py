from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from polybridge_research.schema import STRATEGY_FOR_FAMILY, assign_family, normalize_ticker

from .models import (MARKET_EVENT_LABEL, OPP_DEFAULT_MAX_CONTRACTS, OPP_DEFAULT_MAX_NOTIONAL, OPPORTUNITY_LABEL,
                     AlgoChoice, ClassifyIn, ClassifyOut, Proposal, ProposalIn)
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


def checked_algo(request: Request, algo: AlgoChoice | None, target_coverage: float,
                 division: str = "hedge", max_contracts: int | None = None) -> AlgoChoice | None:
    """Validate an algo choice against the library (compiled catalog, else the committed manifest) and pin it to
    concrete params, so the approved proposal says exactly what will run: ``resolved_params`` are the preset's (or
    the explicit) params with every size param capped (hedge: hedge-size params at the proposal's target_coverage;
    opportunity: ``contracts`` at max_contracts; ``capped`` lists what the cap lowered). 422 when the library cannot
    run it in that division."""
    if algo is None:
        return None
    from .pipeline.engine_adapter import AlgoChoiceError, cap_contracts, cap_coverage, resolve_algo
    from .pipeline.router import get_adapter
    manifest, _ = get_adapter(request).library()
    try:
        r = resolve_algo(manifest, algo.family, algo.preset_index, algo.params, division=division)
    except AlgoChoiceError as e:
        raise HTTPException(422, f"algo: {e}.")
    if division == "opportunity":
        run, lowered = cap_contracts(r["params"], max_contracts)
        cap = None
    else:
        run, lowered = cap_coverage(r["params"], target_coverage)
        cap = float(target_coverage)
    return AlgoChoice(family=r["family"], preset_index=r["preset_index"],
                      params=r["params"] if r["preset_index"] is None else None, source=algo.source,
                      resolved_params=run, coverage_cap=cap, capped=lowered)


def _opp_strategy(request: Request, family: str) -> str:
    from .pipeline.router import get_adapter
    fam = next((f for f in get_adapter(request).library()[0].get("families") or [] if f.get("id") == family), {})
    kinds = [str(i).split(":", 1)[-1] for i in fam.get("instruments") or []]
    return "options:" + "/".join(kinds) if kinds else "options"


def _caps(body: ProposalIn) -> tuple[int, float]:
    return (body.max_contracts or OPP_DEFAULT_MAX_CONTRACTS,
            float(body.max_notional if body.max_notional is not None else OPP_DEFAULT_MAX_NOTIONAL))


@router.post("/proposals", response_model=Proposal, status_code=201)
def create_proposal(body: ProposalIn, request: Request) -> Proposal:
    ticker = normalize_ticker(body.ticker)
    if ticker is None:
        raise HTTPException(422, "ticker must not be blank.")
    if body.market is not None and body.division == "opportunity":
        # Opportunity on a market: an options trade run by an approved Opportunity-division options family.
        if body.closed_pm_hedge:
            raise HTTPException(422, "closed_pm_hedge (hedge A) applies to hedge proposals only.")
        max_c, max_n = _caps(body)
        algo = checked_algo(request, body.algo, body.target_coverage, "opportunity", max_c)
        return _store(request).propose(ticker=ticker, family="opportunity", strategy=_opp_strategy(request, algo.family),
                                       basis="market_event", label=OPPORTUNITY_LABEL, market=body.market,
                                       direction=body.direction, shares_held=body.shares_held,
                                       target_coverage=body.target_coverage, algo=algo,
                                       max_contracts=max_c, max_notional=max_n)
    if body.market is not None:  # market-event path: a product hedge, no filing tags invented, no research claim
        if body.max_contracts is not None or body.max_notional is not None:
            raise HTTPException(422, "max_contracts / max_notional apply to opportunity proposals only.")
        return _store(request).propose(ticker=ticker, family="hedge", strategy="protective_put", basis="market_event",
                                       label=MARKET_EVENT_LABEL, market=body.market, direction=body.direction,
                                       shares_held=body.shares_held, target_coverage=body.target_coverage,
                                       algo=checked_algo(request, body.algo, body.target_coverage),
                                       closed_pm_hedge=body.closed_pm_hedge)
    fam = assign_family(body.tags)
    if fam is None:
        raise HTTPException(422, "These tags map to no pre-registered family, so there is no hedge to propose.")
    if fam.value == "opportunity":
        # The pre-registered H2 strategy; an options algo (e.g. eightk_opportunity) may run it on a bridge.
        if body.closed_pm_hedge:
            raise HTTPException(422, "closed_pm_hedge (hedge A) applies to hedge proposals only.")
        max_c, max_n = _caps(body)
        return _store(request).propose(ticker=ticker, family=fam.value, strategy=STRATEGY_FOR_FAMILY[fam],
                                       basis="filing_tags", shares_held=body.shares_held,
                                       target_coverage=body.target_coverage,
                                       algo=checked_algo(request, body.algo, body.target_coverage, "opportunity", max_c),
                                       max_contracts=max_c, max_notional=max_n)
    if body.max_contracts is not None or body.max_notional is not None:
        raise HTTPException(422, "max_contracts / max_notional apply to opportunity proposals only.")
    return _store(request).propose(ticker=ticker, family=fam.value, strategy=STRATEGY_FOR_FAMILY[fam],
                                   basis="filing_tags", shares_held=body.shares_held,
                                   target_coverage=body.target_coverage, algo=checked_algo(request, body.algo, body.target_coverage),
                                   closed_pm_hedge=body.closed_pm_hedge)


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
