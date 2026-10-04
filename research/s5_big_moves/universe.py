from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from polybridge_research.calendar import TradingCalendar
from s1_twin_spread import data as ds

from . import config as cfg

HERE = Path(__file__).resolve().parent
AI_MAP = HERE.parents[1] / "backend" / "app" / "data" / "ai_map.json"


def dropped_by_tag(tags: list[str]) -> bool:
    low = [t.lower() for t in tags]
    return any(d in t for t in low for d in cfg.DROP_TAGS)


def sessions_alive(start: str, end: str, cal: TradingCalendar) -> int:
    a = max(pd.Timestamp(start[:10]), pd.Timestamp(cfg.WINDOW_START))
    b = min(pd.Timestamp(end[:10]), pd.Timestamp(cfg.WINDOW_END))
    if b < a:
        return 0
    return int(np.sum((cal.sessions >= a) & (cal.sessions <= b)))


def main() -> int:
    cal = TradingCalendar("2025-01-01", "2027-12-31")
    seen_s4 = {k.split(":")[1] for k in json.loads(AI_MAP.read_text())["items"] if k.startswith("polymarket:")}
    pt = ds.Throttle(4.0)
    cands, counts = [], {"events": 0, "events_dropped_by_tag": 0, "markets_seen": 0, "in_s4": 0, "by_word": 0, "low_volume": 0, "short_life": 0}
    for closed in ("true", "false"):
        offset, last_vol = 0, float("nan")
        while offset < 3000:
            evs = ds.get_json(f"{ds.GAMMA}/events", {"closed": closed, "limit": 100, "offset": offset, "order": "volume", "ascending": "false",
                                                     "end_date_min": cfg.EVENT_END_MIN, "end_date_max": cfg.EVENT_END_MAX}, throttle=pt,
                              allow=(422,))
            if isinstance(evs, dict):
                counts[f"stopped_at_offset_{closed}"] = offset
                counts[f"last_event_volume_{closed}"] = last_vol
                break
            if not evs:
                break
            last_vol = float(evs[-1].get("volume") or 0)
            for ev in evs:
                counts["events"] += 1
                tags = [t.get("label") or "" for t in (ev.get("tags") or [])]
                if dropped_by_tag(tags):
                    counts["events_dropped_by_tag"] += 1
                    continue
                ms = []
                for m in ev.get("markets") or []:
                    counts["markets_seen"] += 1
                    q, vol = m.get("question") or "", float(m.get("volumeNum") or m.get("volume") or 0)
                    if str(m.get("id")) in seen_s4:
                        counts["in_s4"] += 1
                        continue
                    if any(w in q.lower() for w in cfg.DROP_WORDS):
                        counts["by_word"] += 1
                        continue
                    if vol < cfg.MIN_VOLUME:
                        counts["low_volume"] += 1
                        continue
                    start, end = m.get("startDate") or m.get("createdAt"), m.get("closedTime") or m.get("endDate")
                    if not start or not end or sessions_alive(start, str(end).replace(" ", "T"), cal) < cfg.MIN_SESSIONS:
                        counts["short_life"] += 1
                        continue
                    tokens = m.get("clobTokenIds")
                    tokens = json.loads(tokens) if isinstance(tokens, str) else (tokens or [])
                    if not tokens:
                        continue
                    ms.append({"id": f"polymarket:{m['id']}", "question": q, "volume": vol, "start": start, "end": str(end),
                               "closed": bool(m.get("closed")), "token": tokens[0], "event": ev.get("slug"), "tags": tags})
                cands.extend(sorted(ms, key=lambda x: -x["volume"])[: cfg.MAX_PER_EVENT])
            if len(evs) < 100 or float(evs[-1].get("volume") or 0) < cfg.MIN_VOLUME:
                break
            offset += 100
    uniq = {c["id"]: c for c in cands}
    top = sorted(uniq.values(), key=lambda x: -x["volume"])[: cfg.N_MARKETS]
    (HERE / "universe.json").write_text(json.dumps({"counts": counts, "candidates": len(uniq), "markets": top}, indent=1, ensure_ascii=False))
    if "--keep" in sys.argv:
        (HERE / "candidates.json").write_text(json.dumps(sorted(uniq.values(), key=lambda x: -x["volume"]), indent=1, ensure_ascii=False))
        print("candidates saved:", len(uniq))
        return 0
    half = [top[0::2], top[1::2]]
    for name, part in zip(("1", "2"), half):
        (HERE / f"questions_{name}.json").write_text(json.dumps(
            {"tickers": cfg.MENU, "questions": [{"id": m["id"], "question": m["question"]} for m in part]}, indent=1, ensure_ascii=False))
    print(json.dumps(counts), "| candidates", len(uniq), "| kept", len(top))
    print("volume of the last kept market:", round(top[-1]["volume"]), "| resolved:", sum(m["closed"] for m in top), "| open:", sum(not m["closed"] for m in top))
    print("events represented:", len({m["event"] for m in top}))
    for m in top[:12]:
        print("  ", round(m["volume"] / 1e6, 1), "M |", m["question"][:80])
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(HERE.parent))
    sys.exit(main())
