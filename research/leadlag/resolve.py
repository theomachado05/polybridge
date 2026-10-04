from __future__ import annotations

from pathlib import Path

import yaml

from .discover import event_by_slug, market_by_slug, token_ids

EVENTS_PATH = Path(__file__).with_name("events.yaml")


def _yes_token(market: dict) -> str:
    outcomes = market.get("outcomes")
    if isinstance(outcomes, str):
        import json
        outcomes = json.loads(outcomes)
    ids = token_ids(market)
    idx = [str(o).lower() for o in outcomes].index("yes") if outcomes else 0
    return ids[idx]


def resolve_pm(pm: dict) -> dict:
    if "market_slug" in pm and "event_slug" not in pm:
        m = market_by_slug(pm["market_slug"])
        if m is None:
            ev = event_by_slug(pm["market_slug"])
            if ev is None or len(ev.get("markets", [])) != 1:
                raise LookupError(f"market not found: {pm['market_slug']}")
            m = ev["markets"][0]
    else:
        ev = event_by_slug(pm["event_slug"])
        if ev is None:
            raise LookupError(f"event not found: {pm['event_slug']}")
        needle = pm["match"].lower()
        hits = [m for m in ev.get("markets", [])
                if needle in (m.get("question") or "").lower() or needle in (m.get("groupItemTitle") or "").lower()]
        if not hits:
            raise LookupError(f"no market matching {needle!r} in {pm['event_slug']}: "
                              + "; ".join(m.get("question", "") for m in ev.get("markets", [])[:8]))
        hits.sort(key=lambda m: -float(m.get("volume") or 0))
        m = hits[0]
    out = dict(pm)
    out.update(
        market_slug=m["slug"], condition_id=m["conditionId"], token_id=_yes_token(m), outcome="Yes",
        question=m.get("question"), volume_usd=round(float(m.get("volume") or 0)), closed=bool(m.get("closed")),
    )
    return out


def main() -> None:
    doc = yaml.safe_load(EVENTS_PATH.read_text())
    bad = []
    for e in doc["events"]:
        try:
            e["pm"] = resolve_pm(e["pm"])
            print(f"{e['id']:22s} vol=${e['pm']['volume_usd']:>12,}  {e['pm']['question']}")
        except Exception as exc:
            e["pm"]["unresolved"] = str(exc)[:300]
            bad.append(e["id"])
            print(f"{e['id']:22s} UNRESOLVED {exc}")
    EVENTS_PATH.write_text(yaml.safe_dump(doc, sort_keys=False, width=110, allow_unicode=True))
    print(f"{len(doc['events']) - len(bad)} resolved, {len(bad)} unresolved: {bad}")


if __name__ == "__main__":
    main()
