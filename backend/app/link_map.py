"""Loader for ``data/link_map.json``, the link agent's map (written by ``research/linker/link_map2.py``).

``load()`` returns the shape ``mapping._load()`` returns for ``ai_map.json`` ({"generated_at", "generator", "items":
{"polymarket:<id>": {"question", "mappings": [...]}}}), so ``/map`` can serve it unchanged. By default only trusted
mappings are kept (two models agree, prices do not contradict, and prices confirm or the score is 0.5 or more), and an
item left with no trusted mapping is dropped so ``/map`` treats it as a miss (live fallback) rather than an empty hit;
every extra field (score, verdict, option contract, ...) stays on each mapping. An item where both labellers answered
"no listed instrument" is always kept, with an empty mapping list, ``no_instrument`` and ``no_instrument_reason``
(``/map`` puts the reason in its ``note``).

The product serves ``ai_map.json`` unless ``POLYBRIDGE_LINK_MAP=1`` (see ``mapping._load``).
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).parent / "data" / "link_map.json"
_cache: dict[tuple, dict] = {}


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
