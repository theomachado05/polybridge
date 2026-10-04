"""Loader for ``data/link_map.json``, the link agent's map (written by ``research/linker/link_map2.py``).

``load()`` returns the shape ``mapping._load()`` returns for ``ai_map.json`` ({"generated_at", "generator", "items":
{"polymarket:<id>": {"question", "mappings": [...]}}}), so ``/map`` can serve it unchanged. By default only trusted
mappings are kept (two models agree, prices do not contradict, and prices confirm or the score is 0.5 or more), and an
item left with no trusted mapping is dropped so ``/map`` treats it as a miss (live fallback) rather than an empty hit;
every extra field (score, verdict, option contract, ...) stays on each mapping. An item where both labellers answered
"no listed instrument" is always kept, with an empty mapping list, ``no_instrument`` and ``no_instrument_reason``
(``/map`` puts the reason in its ``note``).

The four contract types come first (the final decision): every item carries ``contract_type`` and ``contract`` from
the rule parser. An item whose type is not "other" (a ladder rung, a touch or close-above ticket) is linked by its
contract, so its generic mappings (the labellers' question -> instrument guess, an unvalidated estimate) are never
served: the item is kept with an empty mapping list and a ``no_instrument_reason`` (``/map`` shows it as the note).
``exact_contract`` is true only when the exact link really exists (``has_exact_contract``: a linkable rung with a ladder
id, a ticket whose resolve_exact link is ok; the same rule as ``research/linker/link_map2.py``); then the note says
where the link is. Otherwise ``exact_contract`` is false and the note says the item was classified but has no exact
link, with the parser's reasons. A file written before contract types existed is read as all "other".

The product serves ``ai_map.json`` unless ``POLYBRIDGE_LINK_MAP=1`` (see ``mapping._load``).
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).parent / "data" / "link_map.json"
_cache: dict[tuple, dict] = {}
CONTRACT_NOTE = {
    "ladder_rung": "A ladder rung: its link is its date ladder (exact contract link), not a generic instrument mapping.",
    "touch_ticket": "A touch ticket: its link is its exact option contracts (expiry and two bracketing strikes), not a "
                    "generic instrument mapping.",
    "close_above_ticket": "A close-above ticket: its link is its exact option contracts (expiry and two bracketing "
                          "strikes), not a generic instrument mapping.",
}


LABEL = {"ladder_rung": "a ladder rung", "touch_ticket": "a touch ticket", "close_above_ticket": "a close-above ticket"}


def has_exact_contract(ctype: str, contract: object) -> bool:
    """True only when the parser found the exact link: a linkable rung with a ladder id, or a ticket whose exact link is ok."""
    c = contract if isinstance(contract, dict) else {}
    if ctype == "ladder_rung":
        return bool(c.get("linkable") and c.get("ladder_id"))
    ex = c.get("exact")
    return ctype in ("touch_ticket", "close_above_ticket") and bool(c.get("linkable") and isinstance(ex, dict) and ex.get("ok"))


def no_link_note(ctype: str, contract: object) -> str:
    """The note for a classified item whose exact link was not found, with the parser's reasons."""
    c = contract if isinstance(contract, dict) else {}
    ex = c.get("exact") if isinstance(c.get("exact"), dict) else {}
    why = [str(r) for r in c.get("reasons") or [] if r] + ([str(ex["reason"])] if ex.get("reason") else [])
    return (f"Classified as {LABEL[ctype]}; no exact link: {'; '.join(why) or 'no exact contract was listed'}. "
            "The generic instrument mapping (an unvalidated estimate) is not served.")


def contract_type(e: dict) -> str:
    """The item's contract type; "other" when the file has none (older map) or an unknown value."""
    t = str(e.get("contract_type") or "other")
    return t if t in CONTRACT_NOTE else "other"


def load(path: Path | str = PATH, trusted_only: bool = True) -> dict:
    """The map in ai_map.json's shape; ``{"items": {}, "error": "missing" | "malformed"}`` when it cannot be read."""
    p = Path(path)
    try:
        key = (str(p), p.stat().st_mtime, trusted_only)
        if key in _cache:
            return _cache[key]
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return {"items": {}, "error": "missing"}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"items": {}, "error": "malformed"}
    items = {}
    for k, e in data["items"].items():
        if not isinstance(e, dict):
            continue
        ctype = contract_type(e)
        if ctype != "other":       # linked by its exact contract: the generic mapping (the old guess) is never served
            ok = has_exact_contract(ctype, e.get("contract"))
            items[k] = {**e, "mappings": [], "no_instrument": False, "exact_contract": ok,
                        "no_instrument_reason": CONTRACT_NOTE[ctype] if ok else no_link_note(ctype, e.get("contract"))}
            continue
        rows = [m for m in e.get("mappings") or [] if isinstance(m, dict) and (m.get("trusted") or not trusted_only)]
        no_inst = bool(e.get("no_instrument"))
        if trusted_only and not rows and not no_inst:
            continue  # only untrusted links: leave it out so /map falls through to its miss / live path
        items[k] = {**e, "mappings": rows, "no_instrument": no_inst,
                    "no_instrument_reason": str(e.get("no_instrument_reason") or "")}
    out = {k: v for k, v in data.items() if k != "items"} | {"items": items}
    _cache.clear()
    _cache[key] = out
    return out


def entry(key: str, path: Path | str = PATH, trusted_only: bool = True) -> dict | None:
    """One item by ``"polymarket:<id>"`` (its mappings, ``no_instrument`` and the reason), or None."""
    return load(path, trusted_only)["items"].get(key)


def option_for(key: str, ticker: str, path: Path | str = PATH) -> dict | None:
    """The option contract of a trusted link, or None."""
    e = entry(key, path)
    for m in (e or {}).get("mappings", []):
        if m.get("ticker") == ticker:
            return m.get("option")
    return None
