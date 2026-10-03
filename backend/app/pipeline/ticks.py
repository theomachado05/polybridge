"""Step 3: build replay ticks from a market's real price history, aligned to the ticker's equity bars.

Sources, in order: Polymarket CLOB ``prices-history`` for the market's YES token ("live_history"), then a
recorded replay file ("replay"), else nothing ("none"). Kalshi history is not wired yet (no ticks from it).

Honesty rules:
- History is a mid-price series. ``yes_bid``/``yes_ask`` are set to that mid (``quote_model = "mid_only"``)
  and ``no_bid``/``no_ask`` to ``1 - mid``; the true spread at the time is unknown.
- Book depth (``bid_px_*``, ``bid_qty_*``, ``ask_px_*``, ``ask_qty_*``) is never invented: always NaN.
- Equity: ``under_px`` is the last Massive bar close at or before each tick (as-of join, no look-ahead);
  NaN before the first bar or when no bars are available. ``under_bid``/``under_ask`` are NaN.
- Options, other-venue and 8-K fields are NaN / 0 (``eightk_score`` 0 = none, per the MarketTick contract).
"""
from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import httpx
import numpy as np

from .. import markets as mk

TicksSource = Literal["live_history", "replay", "none"]
BACKEND = Path(__file__).resolve().parents[2]
DATA = BACKEND / "app" / "data"
REPLAYS = BACKEND / "replays"
GAMMA_MARKET = "https://gamma-api.polymarket.com/markets/{id}"
MIN_TICKS = 10
KDEPTH = 5

FLOAT_FIELDS = (["yes_bid", "yes_ask", "no_bid", "no_ask"]
                + [f"{side}_{kind}_{i}" for side in ("bid", "ask") for kind in ("px", "qty") for i in range(KDEPTH)]
                + ["p_other_venue", "under_px", "under_bid", "under_ask",
                   "opt_mid", "opt_delta", "opt_iv", "opt_implied_prob", "eightk_score"])


@dataclass
class TickSet:
    ticks: dict[str, np.ndarray] | None
    source: TicksSource
    n: int = 0
    has_underlying: bool = False
    quote_model: str = "mid_only"
    notes: list[str] = field(default_factory=list)
    token_id: str | None = None
    question: str | None = None


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def assemble(points: list[tuple[int, float]], bars: list[tuple[int, float]] | None = None,
             venue: int = 0) -> dict[str, np.ndarray]:
    """points: [(ts_s, p)] sorted; bars: [(ts_s, close)] sorted. Returns equal-length arrays per MarketTick field."""
    n = len(points)
    ts = np.array([int(t) * 1_000_000_000 for t, _ in points], dtype=np.int64)
    p = np.array([float(x) for _, x in points], dtype=np.float64)
    out: dict[str, np.ndarray] = {"ts_ns": ts, "venue": np.full(n, venue, dtype=np.int64)}
    for f in FLOAT_FIELDS:
        out[f] = np.full(n, np.nan, dtype=np.float64)
    out["yes_bid"], out["yes_ask"] = p.copy(), p.copy()
    out["no_bid"], out["no_ask"] = 1.0 - p, 1.0 - p
    out["eightk_score"] = np.zeros(n, dtype=np.float64)
    if bars:
        bt = [b[0] for b in bars]
        under = np.full(n, np.nan)
        for i, (t, _) in enumerate(points):
            j = bisect.bisect_right(bt, t) - 1
            if j >= 0:
                under[i] = bars[j][1]
        out["under_px"] = under
    return out


# ---------------------------------------------------------------- Polymarket

def _universe_entry(source: str, mid: str, data_dir: Path = DATA) -> dict:
    try:
        uni = json.loads((data_dir / "market_universe.json").read_text()).get("markets", [])
    except (OSError, ValueError):
        return {}
    return next((m for m in uni if m.get("source") == source and str(m.get("id")) == str(mid)), {})


async def resolve_polymarket(http: httpx.AsyncClient, market_id: str) -> tuple[str | None, str | None]:
    """(YES token id, question). A long all-digit id is already a CLOB token id."""
    mid = str(market_id)
    if mid.isdigit() and len(mid) >= 30:
        return mid, None
    entry = _universe_entry("polymarket", mid)
    if entry.get("token_id"):
        return str(entry["token_id"]), entry.get("question")
    r = await http.get(GAMMA_MARKET.format(id=mid), timeout=mk.TIMEOUT)
    r.raise_for_status()
    m = r.json() or {}
    tokens = [str(t) for t in mk._jlist(m.get("clobTokenIds"))]
    return (tokens[0] if tokens else None), (m.get("question") or entry.get("question"))


async def polymarket_points(http: httpx.AsyncClient, token_id: str) -> list[tuple[int, float]]:
    """About a month of hourly YES prices; falls back to the shared 1-day helper in app.markets."""
    pts: list[tuple[int, float]] = []
    try:
        r = await http.get(f"{mk.CLOB}/prices-history", params={"market": token_id, "interval": "1m", "fidelity": 60},
                           timeout=mk.TIMEOUT)
        r.raise_for_status()
        for h in r.json().get("history", []) or []:
            t, p = _num(h.get("t")), _num(h.get("p"))
            if t is not None and p is not None:
                pts.append((int(t), p))
    except Exception:
        pts = []
    if len(pts) < MIN_TICKS:
        hist = await mk.polymarket_history(http, token_id)
        pts = [(h.t, h.p) for h in hist if math.isfinite(h.p)]
    return sorted(set(pts))


# ---------------------------------------------------------------- recorded replays

def _replay_candidates(source: str | None, mid: str | None, token_id: str | None, data_dir: Path,
                       replays: Path) -> list[Path]:
    names: list[str] = []
    try:
        index = json.loads((data_dir / "replay_index.json").read_text())
    except (OSError, ValueError):
        index = {}
    for key in (f"{source}:{mid}", f"token:{token_id}"):
        v = index.get(key)
        if v:
            names.append(v)
    if mid:
        names += [f"{mid}-history.jsonl", f"{mid}.jsonl"]
    return [replays / n for n in names if n and "/" not in n and ".." not in n]


def replay_points(source: str | None, mid: str | None, token_id: str | None = None, data_dir: Path = DATA,
                  replays: Path = REPLAYS) -> tuple[list[tuple[int, float]], str | None]:
    for path in _replay_candidates(source, mid, token_id, data_dir, replays):
        if not path.is_file():
            continue
        pts = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                t, p = int(row["ts_ns"]) // 1_000_000_000, _num(row["p"])
            except (ValueError, KeyError, TypeError):
                continue
            if p is not None:
                pts.append((t, p))
        if pts:
            return sorted(set(pts)), path.name
    return [], None


# ---------------------------------------------------------------- equity bars

def massive_bars(client: Any, ticker: str, start_s: int, end_s: int) -> list[tuple[int, float]]:
    """Hourly Massive aggregates (daily if hourly is empty). Sync: run through app.chain.bounded."""
    d0 = datetime.fromtimestamp(start_s, timezone.utc).date() - timedelta(days=5)
    d1 = datetime.fromtimestamp(end_s, timezone.utc).date()
    for span in ("hour", "day"):
        rows = client.get_all(f"/v2/aggs/ticker/{ticker.upper()}/range/1/{span}/{d0:%Y-%m-%d}/{d1:%Y-%m-%d}",
                              {"adjusted": "true", "sort": "asc", "limit": 50000}, max_pages=5)
        bars = [(int(r["t"]) // 1000, float(r["c"])) for r in rows if _num(r.get("t")) and _num(r.get("c"))]
        if bars:
            return sorted(bars)
    return []


def recorded_bars(ticker: str, data_dir: Path = DATA) -> list[tuple[int, float]]:
    """Offline bars at app/data/equity_bars/<TICKER>.json: [{"t": unix_s, "c": close}, ...]."""
    try:
        rows = json.loads((data_dir / "equity_bars" / f"{ticker.upper()}.json").read_text())
    except (OSError, ValueError):
        return []
    return sorted((int(r["t"]), float(r["c"])) for r in rows if _num(r.get("t")) and _num(r.get("c")))


# ---------------------------------------------------------------- orchestration

async def build_ticks(market: dict | None, ticker: str, *, http: httpx.AsyncClient | None,
                      massive: Callable[[], Any] | None = None, offline: bool = False,
                      data_dir: Path = DATA, replays: Path = REPLAYS) -> TickSet:
    """Never raises: every failure degrades to the next source, and the notes say what happened."""
    from .. import chain  # lazy: pulls in pandas/research only when ticks are built

    notes: list[str] = []
    source = (market or {}).get("source")
    mid = str((market or {}).get("id") or "") or None
    token_id = (market or {}).get("token_id")
    question: str | None = None
    points: list[tuple[int, float]] = []
    ts_source: TicksSource = "none"

    if market and source == "polymarket" and not offline and http is not None:
        try:
            if not token_id:
                token_id, question = await resolve_polymarket(http, mid or "")
            if token_id:
                points = await polymarket_points(http, token_id)
                ts_source = "live_history" if len(points) >= MIN_TICKS else "none"
            else:
                notes.append("no YES token id for this market")
        except Exception as e:
            notes.append(f"Polymarket history unavailable ({type(e).__name__})")
            points = []
    elif market and source == "kalshi":
        notes.append("Kalshi price history is not wired yet")

    if ts_source == "none":
        rp, name = replay_points(source, mid, token_id, data_dir, replays) if market else ([], None)
        if len(rp) >= MIN_TICKS:
            points, ts_source = rp, "replay"
            notes.append(f"recorded replay {name}")
        else:
            points = []

    if ts_source == "none" or not points:
        if not market:
            notes.append("no market given, so no price history")
        return TickSet(None, "none", 0, notes=notes, token_id=token_id, question=question)

    bars: list[tuple[int, float]] = []
    if ticker:
        if not offline and massive is not None:
            try:
                client = massive()
                if client is None:
                    notes.append("MASSIVE_API_KEY not set: no equity bars")
                else:
                    bars = await chain.bounded(massive_bars, client, ticker, points[0][0], points[-1][0])
            except Exception as e:
                notes.append(f"Massive bars unavailable ({type(e).__name__})")
        if not bars:
            bars = recorded_bars(ticker, data_dir)
            if bars:
                notes.append(f"recorded equity bars for {ticker.upper()}")
    ticks = assemble(points, bars)
    has_under = bool(np.isfinite(ticks["under_px"]).any())
    if not has_under:
        notes.append(f"no {ticker.upper() if ticker else 'equity'} prices aligned to the history")
    return TickSet(ticks, ts_source, len(points), has_under, notes=notes, token_id=token_id, question=question)
