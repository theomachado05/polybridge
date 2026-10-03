"""Routes: GET /session (now or ?at=) and GET /closed/expected-gap.

The expected-gap route reads the app's closure tracker (fed by bridges). When the tracker has no price at the last
close for a Polymarket market, it seeds the tracker once from the CLOB price history around the close
(``app.state.closed_history_fetcher`` overrides the fetch; tests set it). Kalshi history is not fetched: a Kalshi
market needs a running bridge (or ``move_pp``) for a move.

Seeding is skipped during regular hours (no gap applies). A seed that fails or leaves no close anchor is not retried
for the same (market, last close) for ``SEED_RETRY_S`` (5 min), so a polling UI does not wait on the CLOB every call.
A seed for an instant the shared tracker would not keep (a historical ``at`` on a market with live ticks more than
10 days newer) goes into a tracker local to the request instead.
"""
from __future__ import annotations

import math
import time
from typing import Any, Awaitable, Callable, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from .gap import GapRates, expected_gap_for, load_rates
from .session import check_supported, now_utc, session_at
from .tracker import ClosureState, ClosureTracker, market_key, tracker_for

CLOB = "https://clob.polymarket.com"
TIMEOUT = httpx.Timeout(5.0)
SEED_BEFORE_CLOSE_S = 2 * 3600
SEED_RETRY_S = 300.0

Fetcher = Callable[[str, str, int, int], Awaitable[list[tuple[int, float]]]]

router = APIRouter()


def _at(at: str | None) -> Any:
    if at is None or not at.strip():
        return now_utc()
    try:
        return check_supported(at)
    except ValueError:
        raise HTTPException(422, "at must be an ISO-8601 time or an epoch number (s, ms, us or ns) between "
                                 "1971-01-01 and 2100-01-01.") from None


async def polymarket_points(source: str, token_id: str, start_s: int, end_s: int) -> list[tuple[int, float]]:
    """Polymarket CLOB price history (1-minute fidelity) as [(epoch s, YES p)]. Polymarket only."""
    if source != "polymarket":
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        r = await http.get(f"{CLOB}/prices-history",
                           params={"market": token_id, "startTs": start_s, "endTs": end_s, "fidelity": 1})
        r.raise_for_status()
        return [(int(h["t"]), float(h["p"])) for h in r.json().get("history", []) or []]


async def seed_from_history(tracker: ClosureTracker, key: str, source: str, history_id: str, at: Any,
                            fetcher: Fetcher = polymarket_points) -> int:
    """Fill the tracker from price history spanning [last close - 2 h, at]. Returns the points the tracker accepted
    (0 on failure or when it rejected them all)."""
    sess = session_at(at)
    start = int(sess.last_close.timestamp()) - SEED_BEFORE_CLOSE_S
    end = int(sess.at.timestamp())
    try:
        pts = await fetcher(source, history_id, start, end)
    except Exception:
        return 0
    return tracker.observe_many(key, ((t, p) for t, p in pts if start <= t <= end))


def closed_fields(tracker: ClosureTracker, market_source: str, market_id: str, at: Any, *,
                  ticker: str | None = None, direction: str | None = None, token_id: str | None = None,
                  rates: GapRates | None = None) -> dict:
    """``{"session", "closure", "expected_gap"}`` for a bridge summary (P5): pure reads, explicit instant."""
    state = tracker.state(market_key(market_source, market_id), at)
    gap = expected_gap_for(state, market_source, market_id, ticker=ticker, direction=direction, token_id=token_id,
                           rates=rates)
    return {"session": state.session.to_dict(), "closure": state.to_dict(), "expected_gap": gap.to_dict()}


def _seed_misses(app: Any) -> dict[tuple[str, float], float]:
    """(market key, last close ts) -> monotonic time before which a failed or anchorless seed is not retried."""
    misses = getattr(app.state, "closed_seed_misses", None)
    if misses is None:
        misses = app.state.closed_seed_misses = {}
    now = time.monotonic()
    if len(misses) > 1000:
        for k in [k for k, v in misses.items() if v <= now]:
            del misses[k]
    return misses


@router.get("/session")
def get_session(at: str | None = None) -> dict:
    """The NYSE session at ``at`` (ISO-8601 or epoch s/ms/us/ns; default now)."""
    return session_at(_at(at)).to_dict()


@router.get("/closed/expected-gap")
async def get_expected_gap(request: Request, market_source: str = Query(min_length=1),
                           market_id: str = Query(min_length=1), ticker: str | None = Query(None, max_length=12),
                           direction: Literal["down_on_yes", "up_on_yes"] | None = None,
                           token_id: str | None = None, at: str | None = None,
                           move_pp: float | None = Query(None, description="what-if: use this PM move (pp)")) -> dict:
    t = _at(at)
    tracker = tracker_for(request.app)
    key = market_key(market_source, market_id)
    seeded = 0
    sess = session_at(t)
    if (move_pp is None and market_source == "polymarket" and sess.closed
            and not tracker.has_close_anchor(key, t)):
        misses = _seed_misses(request.app)
        miss_key = (key, sess.last_close.timestamp())
        if misses.get(miss_key, 0.0) <= time.monotonic():
            misses.pop(miss_key, None)
            if not tracker.accepts(key, sess.last_close.timestamp() - SEED_BEFORE_CLOSE_S):
                tracker = ClosureTracker()  # historical instant behind the live series: seed a request-local tracker
            fetcher = getattr(request.app.state, "closed_history_fetcher", None) or polymarket_points
            seeded = await seed_from_history(tracker, key, market_source, token_id or market_id, t, fetcher)
            if not tracker.has_close_anchor(key, t):
                misses[miss_key] = time.monotonic() + SEED_RETRY_S
    state = tracker.state(key, t)
    if move_pp is not None:
        if not math.isfinite(move_pp) or abs(move_pp) > 100:
            raise HTTPException(422, "move_pp must be a finite number of percentage points in [-100, 100].")
        state = ClosureState(key=key, status="TRACKING" if state.session.closed else "MARKET_OPEN",
                             session=state.session, close_at=state.close_at, p_close=None, p_close_at=None,
                             p_now=None, p_now_at=None, move_pp=float(move_pp), high_pp=None, low_pp=None,
                             n_points=0)
    gap = expected_gap_for(state, market_source, market_id, ticker=ticker, direction=direction, token_id=token_id,
                           rates=load_rates())
    return {"market_source": market_source, "market_id": market_id, "ticker": gap.ticker,
            "session": state.session.to_dict(), "closure": state.to_dict(), "expected_gap": gap.to_dict(),
            "move_source": "what_if" if move_pp is not None else "history_seed" if seeded else "tracker",
            "seeded_points": seeded}
