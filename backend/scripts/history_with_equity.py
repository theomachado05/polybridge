"""A month of real Polymarket price history as a replay JSONL that also carries the equity price, so the demo replay
can hedge without any other file: each row is ``{"ts_ns", "p", "under_px"}``.

``under_px`` is the close of the last Massive bar that had already ENDED at the row's time (bar start + span: no
look-ahead, same rule as app.pipeline.ticks). Rows before the first finished bar carry no ``under_px`` (NaN on replay).
Needs MASSIVE_API_KEY (read by the client, never printed). Price history is a mid-price series: the true spread
and the book depth at those times are unknown and are not invented (see record_book.py for depth).

    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py \\
        --market indiana-datacenter-2027=5126779 --equity VRT --out ../replays/indiana-datacenter-2027-history.jsonl

Replay it at the demo speed: POLYBRIDGE_REPLAY_SPEED=36000 (hourly points, ten ticks per second).

``--options`` (threshold questions ``app.options.match`` maps, e.g. "Will NVIDIA (NVDA) close above $230 end of
September?") also records the options-implied history of the same threshold, so a replay can run the Opportunity
division offline: ``opt_mid`` / ``opt_implied_prob`` / ``opt_iv`` and ``opt_legs`` ({leg ticker: bar close}) per row.

- Structure: the YES-equivalent spread (call spread k_lo/k_hi around K for "above", put spread for "below") at the
  listed expiry nearest the resolution date, chosen from Massive's contract LISTING as it stood on the first recorded
  day (point in time: ``options_join.historical_structure`` passes Massive's ``as_of``, so contracts listed later are
  not candidates): no price is looked at to choose it.
- Values: the legs' Massive hourly bar CLOSES joined as of the time each close became known (bar end), through
  ``options_join.option_columns`` (the fit's own builder): both legs must have closed within one bar interval of each
  other, and (fresh-close rule, as the engine applies to equity fills) only inside the regular session once both legs
  have printed that day; elsewhere the option fields are absent (NaN on replay). ``opt_iv`` is the Black-Scholes
  inversion of those leg closes against the underlying's bar closes (paired within one bar interval), an estimate.
  ``opt_legs`` is written only where ``opt_mid`` is (a fresh, synced pair), so a replay bridge can price each leg at
  its recorded close at that replayed time.
- Settlement: rows at or after the expiry close (16:00 New York on the expiry date) carry the structure's value at
  expiry instead: each leg at its intrinsic value from the underlying's official close that day (Massive
  ``/v1/open-close``, else its daily bar), as ``opt_legs`` / ``opt_mid`` plus ``opt_settlement`` {expiry,
  underlying_close, source}. No ``opt_implied_prob`` / ``opt_iv`` there: it is a settlement value, not a quote, so no
  family opens a trade on it; the engine marks an open structure to it and a replay bridge closes at it.
- ``--since YYYY-MM-DD`` drops the rows before that New York day BEFORE the structure is chosen, so the listing is read
  as of the replay's own first day. ``--since options`` (older recordings) cuts after the join, at the New York day of
  the first option row; the structure is then chosen as of the uncut history's first day. 8-K scores are never
  fetched here.
- The sidecar ``<out>.meta.json`` names the market and carries the structure (``options``).

    cd backend && uv run --env-file ../.env python scripts/history_with_equity.py --options --since 2026-09-16 \\
        --market nvda-230-sep-2026=3961215 --equity NVDA --out replays/nvda-230-sep-2026-history.jsonl

``--start`` / ``--end`` (ISO-8601; a time without an offset is New York time) record a fixed window instead of the last
month, for any market including a resolved one: the CLOB ``prices-history`` with ``startTs``/``endTs`` at
``--fidelity`` minutes, and Massive bars of ``--bar-minutes`` minutes over the same window (hourly by default), still
joined only once each bar has ended. ``scripts/record_weekend.py`` uses it for the closed-market demo replay.
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from history_to_replay import fetch as fetch_history  # noqa: E402
from record_book import resolve  # noqa: E402
from record_equity_bars import fetch as fetch_bars  # noqa: E402

from app.pipeline.ticks import BAR_SPAN_S  # noqa: E402


CLOB_HISTORY = "https://clob.polymarket.com/prices-history"


def parse_when(s: str):
    """An ISO-8601 time; without an offset it is New York time. Returns an aware datetime."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo is not None else t.replace(tzinfo=ZoneInfo("America/New_York"))


def fetch_window(token: str, http: httpx.Client, start_s: int, end_s: int, fidelity_min: int) -> list[dict]:
    """CLOB price history (YES mid) over [start_s, end_s] at ``fidelity_min``-minute points, as replay rows."""
    from history_to_replay import parse_history
    r = http.get(CLOB_HISTORY, params={"market": token, "startTs": start_s, "endTs": end_s,
                                       "fidelity": fidelity_min}, timeout=30)
    r.raise_for_status()
    rows = [x for x in parse_history(r.json()) if start_s <= x["ts_ns"] // 1_000_000_000 <= end_s]
    if not rows:
        raise SystemExit("no price history in the window")
    return rows


def fetch_minute_bars(client, ticker: str, start_s: int, end_s: int, minutes: int) -> list[dict]:
    """Massive ``minutes``-minute aggregates (extended hours included) covering the window, [{"t": start s, "c"}]."""
    from datetime import datetime, timedelta, timezone
    d0 = datetime.fromtimestamp(start_s, timezone.utc).date() - timedelta(days=1)
    d1 = datetime.fromtimestamp(end_s, timezone.utc).date() + timedelta(days=1)
    rows = client.get_all(f"/v2/aggs/ticker/{ticker.upper()}/range/{minutes}/minute/{d0:%Y-%m-%d}/{d1:%Y-%m-%d}",
                          {"adjusted": "true", "sort": "asc", "limit": 50000}, max_pages=10) or []
    bars = [{"t": int(r["t"]) // 1000, "c": float(r["c"])} for r in rows
            if isinstance(r, dict) and r.get("t") is not None and r.get("c") is not None]
    return sorted(bars, key=lambda b: b["t"])


def join(rows: list[dict], span_s: int, bars: list[dict]) -> list[dict]:
    """Stamp each row with the close of the last bar already finished at its time."""
    known = [b["t"] + span_s for b in bars]
    out = []
    for r in rows:
        j = bisect.bisect_right(known, r["ts_ns"] // 1_000_000_000) - 1
        out.append({**r, "under_px": bars[j]["c"]} if j >= 0 else dict(r))
    return out


def _round(x: float) -> float:
    return float(f"{x:.6g}")


async def _direct(fn, *args):
    """``app.chain.bounded`` without its 8 s API bound: a one-off recording may wait for Massive."""
    return fn(*args)


def option_rows(rows: list[dict], question: str, end_date: str | None, client, *,
                bars=None) -> tuple[list[dict], dict]:
    """``rows`` with the options-implied fields of the question's threshold (see the module docstring), and the
    structure (for the sidecar). Raises SystemExit when the question cannot be mapped or nothing is listed."""
    import datetime as dt

    import numpy as np

    from app.options.match import _NY, match_question, why_no_match
    from app.pipeline.options_join import historical_structure, leg_closes, option_columns
    from app.pipeline.ticks import massive_bars
    bars = bars or massive_bars
    ts_s = np.array([r["ts_ns"] // 1_000_000_000 for r in rows], dtype=np.int64)
    as_of = dt.datetime.fromtimestamp(int(ts_s[0]), dt.timezone.utc).astimezone(_NY).date()
    m = match_question(question, end_date, as_of=as_of)
    if m is None:
        raise SystemExit(f"question not mapped: {why_no_match(question, end_date, as_of=as_of)}")
    above = m.direction == "above"
    und, k = m.underlying, m.strike
    st = historical_structure(client, und, k, m.expiry, above=above, as_of=as_of)
    if st is None and m.fallback:
        und, k = m.fallback[0], round(m.level * m.fallback[1], 6)
        st = historical_structure(client, und, k, m.expiry, above=above, as_of=as_of)
    if st is None:
        raise SystemExit(f"no listed {und} contracts near {k:g} and {m.expiry}")
    start_s, end_s = int(ts_s.min()), int(ts_s.max())
    legs = [(lg["sign"], bars(client, lg["ticker"], start_s, end_s)) for lg in st["legs"]]
    cols, stats = asyncio.run(option_columns(
        ts_s, legs, above=above, k_lo=st["k_lo"], k_hi=st["k_hi"], k=k, expiry=dt.date.fromisoformat(st["expiry"]),
        und=und, client=client, bars=bars, bounded=_direct, session_fresh=True))
    closes = [leg_closes(ts_s, b) for _, b in legs]
    keep = stats["keep"]
    out = []
    for i, r in enumerate(rows):
        row = dict(r)
        for f in ("opt_mid", "opt_implied_prob", "opt_iv"):
            v = float(cols[f][i])
            if np.isfinite(v):
                row[f] = _round(v)
        if keep[i]:
            row["opt_legs"] = {lg["ticker"]: _round(float(c[i])) for lg, c in zip(st["legs"], closes)}
        out.append(row)
    settlement = None
    if int(ts_s.max()) >= settle_s(st["expiry"]):  # the history reaches the expiry close: record the settlement
        got = official_close(client, und, dt.date.fromisoformat(st["expiry"]))
        if got is None:
            raise SystemExit(f"no official close for {und} on {st['expiry']}: cannot record the expiry settlement")
        n_settled = settle_rows(out, st, *got)
        settlement = {"underlying_close": got[0], "source": got[1], "rows": n_settled,
                      "rule": "each leg at intrinsic value from the underlying's official close on the expiry date"}
    st = {**st, "match": m.to_dict(), "as_of": as_of.isoformat(), "settlement": settlement,
          "n_with_options": stats["n_with_options"], "n_with_iv": stats["n_with_iv"],
          "n_unsynced_legs": stats["n_unsynced_legs"], "n_off_session": stats["n_off_session"],
          "leg_bars": {lg["ticker"]: len(b) for lg, (_, b) in zip(st["legs"], legs)}}
    return out, st


SETTLE_SOURCE_OFFICIAL = "Massive /v1/open-close (official close)"
SETTLE_SOURCE_DAILY = "Massive daily bar close"


def official_close(client, underlying: str, day) -> tuple[float, str] | None:
    """(the underlying's official close on ``day``, source): Massive /v1/open-close, else that day's daily bar."""
    try:
        r = client.get(f"/v1/open-close/{underlying.upper()}/{day.isoformat()}", {"adjusted": "true"}) or {}
        c = float(r.get("close"))
        if c > 0:
            return c, SETTLE_SOURCE_OFFICIAL
    except Exception:
        pass
    try:
        rows = client.get_all(f"/v2/aggs/ticker/{underlying.upper()}/range/1/day/{day.isoformat()}/{day.isoformat()}",
                              {"adjusted": "true"}, max_pages=1) or []
        c = float(rows[-1]["c"])
        if c > 0:
            return c, SETTLE_SOURCE_DAILY
    except Exception:
        pass
    return None


def settle_s(expiry: str) -> int:
    """Unix s of the expiry close: 16:00 New York on the expiry date (the listed contracts' last trade)."""
    import datetime as dt

    from app.options.match import _NY
    return int(dt.datetime.combine(dt.date.fromisoformat(expiry), dt.time(16, 0), _NY).timestamp())


def settle_rows(rows: list[dict], structure: dict, close: float, source: str) -> int:
    """Stamp every row at or after the expiry close with the structure's settlement: each leg at its intrinsic value
    (call max(S - K, 0), put max(K - S, 0)) at the official close ``close``. Replaces any option fields there, drops
    opt_implied_prob / opt_iv (a settlement value is not a quote). Returns the number of rows stamped."""
    at = settle_s(structure["expiry"])
    legs = {lg["ticker"]: max((close - lg["strike"]) if lg["kind"] == "call" else (lg["strike"] - close), 0.0)
            for lg in structure["legs"]}
    mid = sum(lg["sign"] * legs[lg["ticker"]] for lg in structure["legs"])
    n = 0
    for r in rows:
        if r["ts_ns"] // 1_000_000_000 < at:
            continue
        for f in ("opt_implied_prob", "opt_iv", "opt_delta"):
            r.pop(f, None)
        r["opt_mid"] = _round(mid)
        r["opt_legs"] = {tk: _round(v) for tk, v in legs.items()}
        r["opt_settlement"] = {"expiry": structure["expiry"], "underlying_close": close, "source": source}
        n += 1
    return n


def since_day(rows: list[dict], day) -> list[dict]:
    """Rows from the start of New York day ``day``."""
    import datetime as dt

    from app.options.match import _NY
    start = dt.datetime.combine(day, dt.time(0, 0), _NY).timestamp()
    return [r for r in rows if r["ts_ns"] // 1_000_000_000 >= start]


def since_first_option(rows: list[dict]) -> list[dict]:
    """Rows from the New York day of the first row that carries an options estimate."""
    import datetime as dt

    from app.options.match import _NY
    first = next((r for r in rows if "opt_implied_prob" in r), None)
    if first is None:
        return rows
    return since_day(rows, dt.datetime.fromtimestamp(first["ts_ns"] // 1_000_000_000, dt.timezone.utc).astimezone(_NY).date())


def write_sidecar(out: Path, *, market_id: str, token: str, question: str, end_date: str | None,
                  options: dict | None, rows: list[dict], equity: str, extra: dict | None = None) -> Path:
    import datetime as dt
    span = [dt.datetime.fromtimestamp(rows[i]["ts_ns"] // 1_000_000_000, dt.timezone.utc).isoformat()
            .replace("+00:00", "Z") for i in (0, -1)]
    meta = {"source": "polymarket", "id": market_id, "token_id": token, "question": question, "end_date": end_date,
            "equity": equity.upper(), "rows": len(rows), "span": span,
            "provenance": f"gamma-api.polymarket.com/markets/{market_id} (clobTokenIds[0]); CLOB prices-history "
                          f"(hourly mid); Massive hourly bars ({equity.upper()}"
                          + (", option legs" if options else "") + f"); recorded {dt.date.today().isoformat()} with "
                          "scripts/history_with_equity.py" + (" --options" if options else "")}
    if options:
        meta["options"] = options
    meta.update(extra or {})
    path = out.with_name(out.name + ".meta.json")
    path.write_text(json.dumps(meta, indent=1) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--market", required=True, metavar="SLUG=ID")
    ap.add_argument("--equity", required=True, metavar="TICKER")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--options", action="store_true", help="also record the options-implied history (threshold markets)")
    ap.add_argument("--since", metavar="YYYY-MM-DD|options",
                    help="a New York day: drop earlier rows before the options join (the structure is chosen as of that "
                         "day); 'options': cut after the join, at the day of the first option row")
    ap.add_argument("--start", help="record a fixed window from this time (ISO-8601; no offset = New York time)")
    ap.add_argument("--end", help="end of the fixed window (with --start)")
    ap.add_argument("--fidelity", type=int, default=60, help="with --start: PM history point spacing in minutes")
    ap.add_argument("--bar-minutes", type=int, default=0,
                    help="with --start: Massive bars of this many minutes (default 0: hourly, else daily)")
    a = ap.parse_args(argv)
    if bool(a.start) != bool(a.end):
        ap.error("--start and --end go together")
    window = (int(parse_when(a.start).timestamp()), int(parse_when(a.end).timestamp())) if a.start else None
    if window and window[0] >= window[1]:
        ap.error("--start must be before --end")
    since = None
    if a.since and a.since != "options":
        import datetime as dt
        try:
            since = dt.date.fromisoformat(a.since)
        except ValueError:
            ap.error("--since takes YYYY-MM-DD or 'options'")
    slug, token, question = asyncio.run(_resolve(a.market))
    market_id = a.market.partition("=")[2]
    end_date = None
    with httpx.Client() as http:
        rows = fetch_window(token, http, *window, a.fidelity) if window else fetch_history(token, http)
        if a.options and not (market_id.isdigit() and len(market_id) >= 30):
            end_date = (http.get(f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=15).json() or {}).get("endDate")
    from app import chain
    client = chain.make_client()
    if client is None:
        print("MASSIVE_API_KEY is not set: writing the history without under_px", file=sys.stderr)
        joined = rows
    else:
        lo, hi = rows[0]["ts_ns"] // 1_000_000_000, rows[-1]["ts_ns"] // 1_000_000_000
        if window and a.bar_minutes > 0:
            span_s, bars = a.bar_minutes * 60, fetch_minute_bars(client, a.equity, lo, hi, a.bar_minutes)
        else:
            span, bars = fetch_bars(client, a.equity, lo, hi)
            span_s = BAR_SPAN_S[span]
        if not bars:
            print(f"no Massive bars for {a.equity.upper()}: writing the history without under_px", file=sys.stderr)
            joined = rows
        else:
            joined = join(rows, span_s, bars)
    if since is not None:
        joined = since_day(joined, since)
        if not joined:
            raise SystemExit(f"no history on or after {since}")
    structure = None
    if a.options:
        if client is None:
            raise SystemExit("--options needs MASSIVE_API_KEY")
        joined, structure = option_rows(joined, question, end_date, client)
        structure["counts_over_rows"] = len(joined)  # the rows the n_* counts above are over (before --since options)
        if a.since == "options":
            joined = since_first_option(joined)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in joined))
    ps = [r["p"] for r in joined]
    n_eq = sum(1 for r in joined if "under_px" in r)
    n_opt = sum(1 for r in joined if "opt_implied_prob" in r)
    print(f"{question or slug}: {len(joined)} points, p {min(ps):.4f}..{max(ps):.4f}, {n_eq} with under_px, "
          f"{n_opt} with an options estimate -> {a.out}")
    if a.options or a.since or window:
        extra = None
        if window:
            import datetime as dt
            iso = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: E731
            bars_desc = f"{a.bar_minutes}-minute" if a.bar_minutes > 0 else "hourly (else daily)"
            extra = {"window": {"start": iso(window[0]), "end": iso(window[1]), "fidelity_min": a.fidelity,
                                "bar_minutes": a.bar_minutes or None},
                     "provenance": f"gamma-api.polymarket.com/markets/{market_id} (clobTokenIds[0]); CLOB prices-history "
                                   f"startTs/endTs at {a.fidelity}-minute fidelity (YES mid); Massive {bars_desc} "
                                   f"{a.equity.upper()} bars (extended hours included), each joined only once it had "
                                   f"ended; recorded {dt.date.today().isoformat()} with scripts/history_with_equity.py "
                                   "--start/--end"}
        meta = write_sidecar(a.out, market_id=market_id, token=token, question=question, end_date=end_date,
                             options=structure, rows=joined, equity=a.equity, extra=extra)
        print(f"sidecar -> {meta}")
    return 0


async def _resolve(spec: str):
    async with httpx.AsyncClient() as http:
        return await resolve(http, spec)


if __name__ == "__main__":
    raise SystemExit(main())
