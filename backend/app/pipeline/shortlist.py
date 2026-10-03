"""Step 2: families from the manifest whose event classes include the class, split by division.

Within a division, families that name the class explicitly come before wildcard ("all") families, and
families whose requirements are known to be unmet (no listed options, no second venue) go last.
"""
from __future__ import annotations

from .engine_adapter import DIVISIONS, family_matches, is_specific

# Rule order for wildcard families when nothing is scored (the generic, always-applicable hedge first).
GENERIC_PREFERENCE = ["equity_delta_bridge", "book_imbalance_hedge", "no_bid_seller", "binary_vs_spread_arb",
                      "vol_vs_pm_move", "poly_kalshi_spread"]


def _rank(family: dict, event_class: str, available: set[str] | None) -> tuple:
    unmet = [r for r in (family.get("requires") or []) if available is not None and r not in available]
    pref = GENERIC_PREFERENCE.index(family["id"]) if family["id"] in GENERIC_PREFERENCE else len(GENERIC_PREFERENCE)
    return (bool(unmet), not is_specific(family, event_class), pref, family["id"])


def shortlist(manifest: dict, event_class: str, available: set[str] | None = None) -> dict[str, list[dict]]:
    """{'hedge': [family, ...], 'opportunity': [...]} in rule-preference order.

    ``available`` lists satisfied requirements (e.g. {'listed_options', 'both_venues'}); None means unknown,
    in which case no family is demoted for its requirements.
    """
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
