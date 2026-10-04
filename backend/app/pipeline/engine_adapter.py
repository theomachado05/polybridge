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
BRIDGE_UNMET = frozenset({"pm_leg_sim"})


def _divisions(raw: Any) -> list[str]:
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").replace(",", "/").split("/")
    out = []
    for x in items:
        x = str(x).strip().lower()
        x = "opportunity" if x.startswith("opp") else x
        if x in DIVISIONS and x not in out:
            out.append(x)
    return out or ["hedge"]


def _params(raw: Any) -> list[dict]:
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
    out = set()
    for b in blocks or []:
        name = b.get("name") if isinstance(b, dict) else b
        if name:
            out.add(str(name))
    return out


def derive_requires(family: dict) -> list[str]:
    req = []
    if "CrossVenueGap" in _block_names(family.get("blocks")):
        req.append("both_venues")
    if any(str(i).lower().startswith("option") for i in family.get("instruments") or []):
        req.append("listed_options")
    divs = family.get("divisions") or _divisions(family.get("division"))
    if divs == ["hedge"] and any(str(i).lower().startswith("pred_") for i in family.get("instruments") or []):
        req.append("pm_leg_sim")
    return req


def derive_proxies(instruments: list) -> list[str]:
    out = []
    for i in instruments or []:
        kind, _, sym = str(i).partition(":")
        if kind in ("etf", "equity") and sym and sym.isupper() and sym.isalpha() and sym not in out:
            out.append(sym)
    return out


def normalize_manifest(raw: Any) -> dict:
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
    return event_class in (family.get("event_classes") or []) and not family.get("generic", False)


def preset_grid(family: dict) -> list[dict[str, float]]:
    params = family.get("params") or []
    if not params:
        return [{}]
    names = [p["name"] for p in params]
    return [dict(zip(names, combo)) for combo in itertools.product(*(p["grid"] for p in params))]


def default_preset(family: dict) -> tuple[int, dict[str, float]]:
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

    def __init__(self, module: Any = "auto", engine_manifest: Path = ENGINE_MANIFEST,
                 fallback_manifest: Path = FALLBACK_MANIFEST) -> None:
        self._module = self._import() if module == "auto" else module
        self.engine_manifest, self.fallback_manifest = Path(engine_manifest), Path(fallback_manifest)
        self._library: tuple[dict, LibrarySource] | None = None

    @staticmethod
    def _import() -> Any:
        try:
            return importlib.import_module("hedgecore")
        except Exception:
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


class AlgoChoiceError(ValueError):
    pass


def is_option_family(family: dict) -> bool:
    ins = [str(i).lower() for i in family.get("instruments") or []]
    return "opportunity" in (family.get("divisions") or []) and any(i.startswith("option") for i in ins)


def resolve_algo(manifest: dict, family_id: str, preset_index: int | None = None,
                 params: dict[str, float] | None = None, division: str = "hedge") -> dict:
    fam = next((f for f in manifest.get("families") or [] if f.get("id") == family_id), None)
    if fam is None:
        raise AlgoChoiceError(f"unknown algo family '{family_id}'")
    if division == "opportunity":
        if not is_option_family(fam):
            raise AlgoChoiceError(f"'{family_id}' is not an options family; opportunity bridges run the "
                                  "Opportunity division's option families only")
    elif fam.get("divisions") != ["hedge"]:
        raise AlgoChoiceError(f"'{family_id}' is a {'/'.join(fam.get('divisions') or [])} family; bridges run "
                              "hedge-division families only (they hedge an equity position)")
    unmet = sorted(BRIDGE_UNMET & set(fam.get("requires") or []))
    if division == "hedge" and unmet:
        raise AlgoChoiceError(f"'{family_id}' needs {', '.join(unmet)} (a simulated prediction-market leg), which "
                              "hedge bridges do not provide yet; they route equity intents only")
    if preset_index is not None and params is not None:
        raise AlgoChoiceError("send preset_index or params, not both")
    if params is None:
        if preset_index is None:
            idx, chosen = default_preset(fam)
            return {"family": family_id, "preset_index": idx, "params": chosen, "division": division}
        grid = preset_grid(fam)
        if not 0 <= int(preset_index) < len(grid):
            raise AlgoChoiceError(f"'{family_id}' has presets 0..{len(grid) - 1}; got {preset_index}")
        return {"family": family_id, "preset_index": int(preset_index), "params": grid[int(preset_index)],
                "division": division}
    defs = {p["name"]: p for p in fam.get("params") or []}
    unknown = sorted(set(params) - set(defs))
    if unknown:
        raise AlgoChoiceError(f"'{family_id}' has no param(s) {', '.join(unknown)}")
    out = {}
    for name, d in defs.items():
        g = d.get("grid") or []
        v = float(params.get(name, d.get("default", g[(len(g) - 1) // 2] if g else math.nan)))
        lo, hi = float(d.get("min", -math.inf)), float(d.get("max", math.inf))
        if not math.isfinite(v) or (math.isfinite(lo) and v < lo) or (math.isfinite(hi) and v > hi):
            raise AlgoChoiceError(f"'{family_id}' param {name}={v} is outside [{lo}, {hi}]")
        out[name] = v
    return {"family": family_id, "preset_index": None, "params": out, "division": division}


COVERAGE_PARAMS = ("coverage", "max_cov")


CONTRACT_PARAMS = ("contracts",)


def cap_contracts(params: dict[str, float], max_contracts: float | None) -> tuple[dict[str, float], dict[str, float] | None]:
    out, lowered = dict(params), {}
    if max_contracts is None:
        return out, None
    for name in CONTRACT_PARAMS:
        v = out.get(name)
        if v is not None and math.isfinite(float(v)) and float(v) > float(max_contracts):
            lowered[name] = float(v)
            out[name] = float(max_contracts)
    return out, (lowered or None)


def cap_coverage(params: dict[str, float], target_coverage: float) -> tuple[dict[str, float], dict[str, float] | None]:
    cap = float(target_coverage)
    out, lowered = dict(params), {}
    for name in COVERAGE_PARAMS:
        v = out.get(name)
        if v is not None and math.isfinite(float(v)) and float(v) > cap:
            lowered[name] = float(v)
            out[name] = cap
    return out, (lowered or None)
