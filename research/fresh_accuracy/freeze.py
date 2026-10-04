from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import fresh_accuracy  # noqa: F401
from arbscan import datasrc as ds
from arbscan.parse import parse_pm_question

from fresh_accuracy.config import CACHE_DIR, FROZEN_IDS, FROZEN_SHA, GAMMA, PARAMS, R3_EVENTS

ET = ZoneInfo("America/New_York")
FIELDS = ["id", "ticker", "strike", "kind", "res_date", "start", "end", "token", "cid", "question"]


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _jl(x) -> list:
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x) if isinstance(x, str) else []
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def keyset_events(http: ds.Http, p=PARAMS) -> list[dict]:
    out: dict[str, dict] = {}
    cursor = None
    while True:
        q = {"tag_id": p.tag_id, "closed": "true", "limit": 100,
             "end_date_min": f"{p.end_min}T00:00:00Z", "end_date_max": f"{p.end_max}T23:59:59Z"}
        if cursor:
            q["after_cursor"] = cursor
        d = http.get_json(f"{GAMMA}/events/keyset", q)
        if not isinstance(d, dict):
            raise RuntimeError("gamma keyset listing failed")
        for e in d.get("events") or []:
            out[str(e.get("id"))] = e
        cursor = d.get("next_cursor")
        if not cursor or not d.get("events"):
            break
    return list(out.values())


def r3_exclusions(path: Path = R3_EVENTS) -> tuple[set[str], set[str]]:
    ids, dates = set(), set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            ids.add(str(r["market_id"]))
            if r.get("res_date"):
                dates.add(r["res_date"])
    return ids, dates


def frame(events: list[dict], ex_ids: set[str], ex_dates: set[str], p=PARAMS) -> tuple[list[dict], dict]:
    lo, hi = date.fromisoformat(p.end_min), date.fromisoformat(p.end_max)
    counts: dict[str, int] = {}
    seen: dict[str, dict] = {}

    def bump(k):
        counts[k] = counts.get(k, 0) + 1

    for ev in events:
        for m in ev.get("markets") or []:
            bump("markets_listed")
            if not m.get("closed"):
                bump("not_closed")
                continue
            th, why = parse_pm_question(m.get("question") or "", ev.get("title") or "")
            if th is None or th.kind not in p.kinds:
                bump(f"parse_{why or 'kind_other'}")
                continue
            tok = [str(t) for t in _jl(m.get("clobTokenIds"))]
            if not tok or not m.get("endDate"):
                bump("no_token_or_date")
                continue
            end = _iso(m["endDate"])
            rd = end.astimezone(ET).date()
            if not (lo <= rd <= hi):
                bump("res_date_outside_window")
                continue
            mid = str(m.get("id"))
            if mid in ex_ids:
                bump("in_r3_events")
                continue
            if rd.isoformat() in ex_dates:
                bump("on_r3_res_date")
                continue
            seen[mid] = dict(id=mid, ticker=th.ticker, strike=th.strike, kind=th.kind, res_date=rd.isoformat(),
                             start=_iso(m["startDate"]).isoformat() if m.get("startDate") else "", end=end.isoformat(),
                             token=tok[0], cid=m.get("conditionId") or "", question=m.get("question") or "")
    rows = sorted(seen.values(), key=lambda r: (r["res_date"], int(r["id"]) if r["id"].isdigit() else 0, r["id"]))
    counts["frame_markets"] = len(rows)
    counts["frame_dates"] = len({r["res_date"] for r in rows})
    counts["frame_tickers"] = len({r["ticker"] for r in rows})
    return rows, counts


def write_frozen(rows: list[dict], path: Path = FROZEN_IDS, sha_path: Path = FROZEN_SHA) -> str:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    h = sha256(path)
    sha_path.write_text(f"{h}  {path.name}\n")
    return h


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_frozen(path: Path = FROZEN_IDS, sha_path: Path = FROZEN_SHA) -> list[dict]:
    want = sha_path.read_text().split()[0]
    if sha256(path) != want:
        raise RuntimeError(f"{path.name} does not match its frozen hash")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    http = ds.Http(CACHE_DIR / "http")
    events = keyset_events(http)
    ex_ids, ex_dates = r3_exclusions()
    rows, counts = frame(events, ex_ids, ex_dates)
    h = write_frozen(rows)
    counts["events_listed"] = len(events)
    counts["kinds"] = {k: sum(r["kind"] == k for r in rows) for k in PARAMS.kinds}
    (FROZEN_IDS.parent / "frozen_counts.json").write_text(json.dumps(counts, indent=1, sort_keys=True))
    print(json.dumps(counts, sort_keys=True), h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
