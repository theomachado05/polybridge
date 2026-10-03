"""Access to the C++ algo library (spec §3.4), with honest fallbacks.

Order of preference for the library manifest:
1. the compiled ``hedgecore`` module (``hedgecore.catalog()``)            -> source "engine"
2. ``engine/hedgecore/manifest.json`` (generated from catalog, committed) -> source "manifest_file"
3. ``app/data/manifest_fallback.json`` (hand-written from spec §3.2)      -> source "fallback"

Replay scoring (``hedgecore.replay_grid``) exists only with the compiled module. Without it the pipeline
picks by event-class rules and reports ``scored = false``; it never fabricates scores.
"""
from __future__ import annotations

import importlib
import itertools
import json
import math
from pathlib import Path
from typing import Any, Literal

LibrarySource = Literal["engine", "manifest_file", "fallback"]

BACKEND = Path(__file__).resolve().parents[2]
ENGINE_MANIFEST = BACKEND.parent / "engine" / "hedgecore" / "manifest.json"
FALLBACK_MANIFEST = BACKEND / "app" / "data" / "manifest_fallback.json"

EVENT_CLASSES = ["macro_fed", "elections", "tariffs_trade", "geopolitics_energy", "housing", "fig",
                 "tech_regulation", "crypto", "corporate_8k", "company_specific", "unsupported"]
WILDCARDS = {"all", "any", "*"}
DIVISIONS = ("hedge", "opportunity")


def _divisions(raw: Any) -> list[str]:
    """'hedge' | 'opportunity' | 'hedge/opp' | ['hedge', 'opportunity'] -> a list of known divisions."""
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").replace(",", "/").split("/")
    out = []
    for x in items:
        x = str(x).strip().lower()
        x = "opportunity" if x.startswith("opp") else x
        if x in DIVISIONS and x not in out:
            out.append(x)
    return out or ["hedge"]


def _params(raw: Any) -> list[dict]:
    """Accepts [{name, min, max, grid}] or {name: {min, max, grid}} or {name: [grid]}."""
    if isinstance(raw, dict):
        raw = [{"name": k, **(v if isinstance(v, dict) else {"grid": list(v)})} for k, v in raw.items()]
    out = []
    for p in raw or []:
        if not isinstance(p, dict) or "name" not in p:
            continue
        grid = [float(g) for g in (p.get("grid") or [])]
        out.append({**p, "name": str(p["name"]), "grid": grid,
                    "min": float(p.get("min", min(grid) if grid else math.nan)),
                    "max": float(p.get("max", max(grid) if grid else math.nan))})
    return out


def _block_names(blocks: Any) -> set[str]:
    """Block names from either ['Name', ...] (fallback manifest) or [{kind, name}, ...] (compiled catalog)."""
    out = set()
    for b in blocks or []:
        name = b.get("name") if isinstance(b, dict) else b
        if name:
            out.add(str(name))
    return out


def derive_requires(family: dict) -> list[str]:
    """Data a family cannot run without, derived from what the compiled catalog declares (its blocks and
    instruments) when the manifest does not list ``requires`` itself:

    - a ``CrossVenueGap`` signal needs the other venue's price      -> 'both_venues'
    - any ``option:*`` instrument needs a listed option chain        -> 'listed_options'
    """
    req = []
    if "CrossVenueGap" in _block_names(family.get("blocks")):
        req.append("both_venues")
    if any(str(i).lower().startswith("option") for i in family.get("instruments") or []):
        req.append("listed_options")
    return req


def derive_proxies(instruments: list) -> list[str]:
    """Tradable proxy tickers named by the catalog ('etf:SPY', 'equity:COIN'); placeholders like 'etf:sector'
    or 'equity:megacap_tech' are not tickers and are skipped."""
    out = []
    for i in instruments or []:
        kind, _, sym = str(i).partition(":")
        if kind in ("etf", "equity") and sym and sym.isupper() and sym.isalpha() and sym not in out:
            out.append(sym)
    return out


def normalize_manifest(raw: Any) -> dict:
    """Coerce whatever catalog()/manifest.json returns into the shape the pipeline uses.

    families: list of {id, divisions, division, event_classes, instruments, blocks, params, preset_count, requires,
    generic, proxies, ...}.

    The compiled catalog is authoritative but terser than the hand-written fallback: it spells a family that applies
    to every class as the full list of classes (not 'all') and has no ``requires`` / ``proxies``. So:
    ``generic`` is True when the family's classes are a wildcard or cover every supported class; ``requires`` and
    ``proxies`` are derived from blocks and instruments when absent (``derive_requires``, ``derive_proxies``).
    """
    raw = raw if isinstance(raw, dict) else {}
    fams_raw = raw.get("families") or []
    if isinstance(fams_raw, dict):
        fams_raw = [{"id": k, **v} for k, v in fams_raw.items()]
    classes = [str(c) for c in (raw.get("event_classes") or EVENT_CLASSES)]
    supported = {c for c in classes if c != "unsupported"}
    families = []
    for f in fams_raw:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        params = _params(f.get("params"))
        divs = _divisions(f.get("divisions") or f.get("division"))
        ecs = f.get("event_classes") or []
        ecs = [str(e) for e in (ecs if isinstance(ecs, (list, tuple)) else [ecs])]
        count = f.get("preset_count")
        if count is None:
            count = math.prod(len(p["grid"]) for p in params) if params else 0
        instruments = list(f.get("instruments") or [])
        generic = bool(set(ecs) & WILDCARDS) or (bool(supported) and supported <= set(ecs))
        fam = {**f, "id": str(f["id"]), "divisions": divs, "division": divs[0], "event_classes": ecs,
               "instruments": instruments, "blocks": list(f.get("blocks") or []),
               "params": params, "preset_count": int(count), "generic": generic}
        if f.get("requires") is None:
            fam["requires"] = derive_requires(fam)
        if f.get("proxies") is None:
            proxies = derive_proxies(instruments)
            if proxies:
                fam["proxies"] = proxies
        families.append(fam)
    total = raw.get("total_presets", raw.get("preset_count", raw.get("total")))
    return {**raw, "event_classes": classes, "families": families,
            "total_presets": int(total) if total is not None else sum(f["preset_count"] for f in families)}


def family_matches(family: dict, event_class: str) -> bool:
    if event_class == "unsupported":
        return False
    ecs = set(family.get("event_classes") or [])
    return event_class in ecs or bool(ecs & WILDCARDS)


def is_specific(family: dict, event_class: str) -> bool:
    """True when the family names this class explicitly and is not a generic family (one that covers every class,
    whether spelled 'all' or as the full list, as the compiled catalog does)."""
    return event_class in (family.get("event_classes") or []) and not family.get("generic", False)


def preset_grid(family: dict) -> list[dict[str, float]]:
    """All grid points in row-major order (last parameter varies fastest), matching itertools.product."""
    params = family.get("params") or []
    if not params:
        return [{}]
    names = [p["name"] for p in params]
    return [dict(zip(names, combo)) for combo in itertools.product(*(p["grid"] for p in params))]


def default_preset(family: dict) -> tuple[int, dict[str, float]]:
    """The family's declared default preset; else, per parameter, its declared ``default`` when that value is on
    the grid (the compiled catalog declares one for every parameter), else the middle grid value.

    The index uses the compiled library's ordering: mixed radix, last parameter fastest (``ParamSpec::preset``),
    the same as itertools.product. A manifest may override with ``default_preset`` (int index).
    """
    params = family.get("params") or []
    declared = family.get("default_preset")
    grid = preset_grid(family)
    if isinstance(declared, int) and 0 <= declared < len(grid):
        return declared, grid[declared]
    idx, chosen = 0, {}
    for p in params:
        g = p["grid"]
        if not g:
            continue
        d = p.get("default")
        i = (len(g) - 1) // 2
        if isinstance(d, (int, float)) and float(d) in g:
            i = g.index(float(d))
        idx = idx * len(g) + i
        chosen[p["name"]] = g[i]
    return idx, chosen


class EngineAdapter:
    """Thin wrapper; inject ``module`` (a fake hedgecore) or paths in tests."""

    def __init__(self, module: Any = "auto", engine_manifest: Path = ENGINE_MANIFEST,
                 fallback_manifest: Path = FALLBACK_MANIFEST) -> None:
        self._module = self._import() if module == "auto" else module
        self.engine_manifest, self.fallback_manifest = Path(engine_manifest), Path(fallback_manifest)
        self._library: tuple[dict, LibrarySource] | None = None

    @staticmethod
    def _import() -> Any:
        try:
            return importlib.import_module("hedgecore")
        except Exception:  # not built, or a broken build: degrade, never crash the API
            return None

    @property
    def has_catalog(self) -> bool:
        return self._module is not None and callable(getattr(self._module, "catalog", None))

    @property
    def can_score(self) -> bool:
        return self._module is not None and callable(getattr(self._module, "replay_grid", None))

    def library(self, refresh: bool = False) -> tuple[dict, LibrarySource]:
        if self._library is not None and not refresh:
            return self._library
        result: tuple[dict, LibrarySource] | None = None
        if self.has_catalog:
            try:
                m = normalize_manifest(self._module.catalog())
                if m["families"]:
                    result = (m, "engine")
            except Exception:
                result = None
        if result is None:
            for path, src in ((self.engine_manifest, "manifest_file"), (self.fallback_manifest, "fallback")):
                try:
                    m = normalize_manifest(json.loads(path.read_text()))
                except (OSError, ValueError):
                    continue
                if m["families"]:
                    result = (m, src)  # type: ignore[assignment]
                    break
        if result is None:
            result = (normalize_manifest({}), "fallback")
        self._library = result
        return result

    def replay_grid(self, family_id: str, position: dict, ticks: dict) -> list[dict] | None:
        """List of ReplayStats dicts (each with preset_index and params), or None when the engine is absent
        or the call fails. Never raises."""
        if not self.can_score:
            return None
        try:
            out = self._module.replay_grid(family_id, position, ticks)
        except Exception:
            return None
        if not isinstance(out, (list, tuple)):
            return None
        rows = []
        for i, r in enumerate(out):
            if isinstance(r, dict):
                rows.append({**r, "preset_index": int(r.get("preset_index", i)), "params": dict(r.get("params") or {})})
        return rows
