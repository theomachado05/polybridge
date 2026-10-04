from __future__ import annotations

from .engine_adapter import DIVISIONS, family_matches, is_specific

GENERIC_PREFERENCE = ["equity_delta_bridge", "book_imbalance_hedge", "no_bid_seller", "binary_vs_spread_arb",
                      "vol_vs_pm_move", "poly_kalshi_spread"]


def _rank(family: dict, event_class: str, available: set[str] | None) -> tuple:
    unmet = [r for r in (family.get("requires") or []) if available is not None and r not in available]
    pref = GENERIC_PREFERENCE.index(family["id"]) if family["id"] in GENERIC_PREFERENCE else len(GENERIC_PREFERENCE)
    specific = is_specific(family, event_class)
    breadth = len(family.get("event_classes") or []) if specific else 0
    return (bool(unmet), not specific, breadth, pref, family["id"])


def shortlist(manifest: dict, event_class: str, available: set[str] | None = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {d: [] for d in DIVISIONS}
    for fam in manifest.get("families") or []:
        if not family_matches(fam, event_class):
            continue
        for d in fam.get("divisions") or [fam.get("division", "hedge")]:
            if d in out:
                out[d].append(fam)
    for d in out:
        out[d].sort(key=lambda f: _rank(f, event_class, available))
    return out


def unmet_requirements(family: dict, available: set[str] | None) -> list[str]:
    if available is None:
        return []
    return [r for r in (family.get("requires") or []) if r not in available]
