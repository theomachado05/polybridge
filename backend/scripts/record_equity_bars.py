"""Record Massive equity bars for offline replays (app/data/equity_bars/<TICKER>.json).

    cd backend && uv run --env-file ../.env python scripts/record_equity_bars.py SPY --replay fed-hike-25bps-oct-2026-history.jsonl
    cd backend && uv run --env-file ../.env python scripts/record_equity_bars.py TLT --start 1788415213 --end 1791006316

Bars are stored with their Massive START time ``t`` plus ``span_s`` (3600 hourly, 86400 daily); the tick builder
joins each bar only from ``t + span_s`` on, when its close is known (no look-ahead). Needs MASSIVE_API_KEY; the key
is read by the client and never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.pipeline.ticks import BAR_SPAN_S, DATA, REPLAYS, _num  # noqa: E402


def replay_range(path: Path) -> tuple[int, int]:
    ts = []
    for line in path.read_text().splitlines():
        try:
            ts.append(int(json.loads(line)["ts_ns"]) // 1_000_000_000)
        except (ValueError, KeyError, TypeError):
            continue
    if not ts:
        raise SystemExit(f"no ticks in {path}")
    return min(ts), max(ts)


def fetch(client, ticker: str, start_s: int, end_s: int) -> tuple[str, list[dict]]:
    """(span, [{"t": start_s, "c": close}]) - hourly, else daily. Same request shape as ticks.massive_bars."""
    d0 = datetime.fromtimestamp(start_s, timezone.utc).date() - timedelta(days=5)
    d1 = datetime.fromtimestamp(end_s, timezone.utc).date()
    for span in ("hour", "day"):
        rows = client.get_all(f"/v2/aggs/ticker/{ticker.upper()}/range/1/{span}/{d0:%Y-%m-%d}/{d1:%Y-%m-%d}",
                              {"adjusted": "true", "sort": "asc", "limit": 50000}, max_pages=5)
        bars = [{"t": int(r["t"]) // 1000, "c": float(r["c"])} for r in rows
                if _num(r.get("t")) is not None and _num(r.get("c")) is not None]
        if bars:
            return span, sorted(bars, key=lambda b: b["t"])
    return "hour", []


def write(ticker: str, span: str, bars: list[dict], source: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker.upper()}.json"
    doc = {"ticker": ticker.upper(), "span_s": BAR_SPAN_S[span], "t_is": "bar start (unix s)", "source": source,
           "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bars": bars}
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return path


def main(argv: list[str] | None = None, client=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ticker")
    ap.add_argument("--replay", help="file in backend/replays/ whose time range to cover")
    ap.add_argument("--start", type=int, help="unix seconds")
    ap.add_argument("--end", type=int, help="unix seconds")
    ap.add_argument("--out-dir", type=Path, default=DATA / "equity_bars")
    a = ap.parse_args(argv)
    if a.replay:
        name = Path(a.replay).name
        start, end = replay_range(REPLAYS / name)
    elif a.start and a.end:
        start, end = a.start, a.end
    else:
        ap.error("give --replay or --start and --end")
    if client is None:
        from app import chain
        client = chain.make_client()
        if client is None:
            print("MASSIVE_API_KEY is not set", file=sys.stderr)
            return 2
    span, bars = fetch(client, a.ticker, start, end)
    if not bars:
        print(f"no bars for {a.ticker.upper()}", file=sys.stderr)
        return 1
    path = write(a.ticker, span, bars, "massive /v2/aggs", a.out_dir)
    print(f"wrote {len(bars)} {span} bars to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
