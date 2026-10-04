"""S24 secondary analysis (METHOD.md amendment 1): classify every pair that traded by the partner study's corrected rule.

Reads matches.csv (prints only) and catalogue texts; reads no result and computes no P&L. Writes pair_checks.csv and
pair_checks.json. `run settle` then carries the verdicts into trades.csv. Not part of the registered test.

Run from `research/`:  python -m s24_ladder_fresh.secondary
"""
from __future__ import annotations

import json
import sys
from collections import Counter

import numpy as np
import pandas as pd

from s1_twin_spread import data as ds

from . import config as cfg
from . import nesting as ne
from . import run as rn


def outcome_text_check(M: dict, mid: str) -> dict:
    """The partner study found the data API's `outcomeIndex` wrong on many prints and mapped prints by `asset` (the token).
    This study maps by the `outcome` text, as S11 did. One market's prints are read once more to compare the two."""
    from .net import GATE
    GATE.kind = "texts"
    d = ds.get_json(ds.DATA_API, {"market": M[mid]["conditionId"], "limit": cfg.PRINT_PAGE, "offset": 0}, throttle=GATE, allow=(400, 404))
    d = d if isinstance(d, list) else []
    yes, no = str(M[mid]["token"]), str(M[mid]["no_token"])
    agree = disagree = other = idx_wrong = 0
    for x in d:
        asset, out = str(x.get("asset") or ""), str(x.get("outcome") or "").lower()
        by_asset = "yes" if asset == yes else ("no" if asset == no else None)
        if by_asset is None or out not in ("yes", "no"):
            other += 1
        elif by_asset == out:
            agree += 1
        else:
            disagree += 1
        if by_asset is not None and x.get("outcomeIndex") is not None and int(x["outcomeIndex"]) != (0 if by_asset == "yes" else 1):
            idx_wrong += 1
    return {"market": mid, "prints": len(d), "outcome_text_agrees_with_token": agree, "disagrees": disagree, "unmapped": other,
            "outcomeIndex_disagrees_with_token": idx_wrong}


def main() -> int:
    L = json.loads((rn.HERE / "ladders.json").read_text())
    st = json.loads((rn.CACHE / "pull_state.json").read_text())
    M = L["markets"]
    partner = set(json.loads((rn.HERE / "partner_markets.json").read_text())["markets"])
    X = pd.read_csv(rn.RESULTS / "matches.csv", dtype={"rich": str, "cheap": str})
    traded = X[["ladder", "rich", "cheap"]].drop_duplicates()
    g = ne.texts(sorted(set(traded.rich) | set(traded.cheap), key=int))
    rows = []
    for r in traded.itertuples():
        b = L["ladders"][int(r.ladder)]
        y = ne.year_ok(b, r.rich, r.cheap, g) if b["kind"] == "date" else True
        ok, why = ne.nested(b["kind"], b, r.rich, r.cheap, g, order_check=True)
        rows.append({"ladder": int(r.ladder), "set": b["set"], "kind": b["kind"], "rich": r.rich, "cheap": r.cheap, "year_ok": bool(y),
                     "corrected_ok": bool(ok), "corrected_reason": why, "partner_used": bool({r.rich, r.cheap} & partner)})
    C = pd.DataFrame(rows)
    C.to_csv(rn.RESULTS / "pair_checks.csv", index=False)
    # every pulled date pair, year check alone, from the stored catalogue fields (question and start date; no group title)
    uni = Counter()
    for k in st["done"]:
        b = L["ladders"][k]
        for a_id, b_id in b["pairs"]:
            uni[f"{b['set']} {b['kind']} pairs"] += 1
            if {a_id, b_id} & partner:
                uni[f"{b['set']} {b['kind']} pairs with a market the partner used"] += 1
            if b["kind"] == "date" and not ne.year_ok(b, a_id, b_id, M):
                uni[f"{b['set']} date pairs failing the year check"] += 1
    big = max((i for i in set(traded.rich) | set(traded.cheap)), key=lambda i: (rn.prints(i) or {"served": 0})["served"] if (rn.prints(i) or {"served": 0})["served"] < cfg.PRINT_PAGE else -1,
              default=None)
    out = {"traded_pairs": int(len(C)), "by_reason": C.groupby(["set", "kind", "corrected_reason"]).size().reset_index(name="pairs").to_dict("records") if len(C) else [],
           "year_check_fails_traded": int((~C.year_ok).sum()) if len(C) else 0, "partner_used_traded": int(C.partner_used.sum()) if len(C) else 0,
           "universe": dict(uni), "texts_read": len(g), "outcome_text_check": outcome_text_check(M, big) if big else None}
    (rn.RESULTS / "pair_checks.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
