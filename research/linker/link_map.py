"""The link map: every link on a question that is still open, with the scorer's score, what the prices say, the
measured sensitivity, and the option contract that carries it. This is what the product would serve in place of the
text-only `ai_map.json`.

A link is **trusted** when two models agreed on it, the data do not contradict it, and either the prices already
confirm it or the scorer puts it at 0.5 or more.

Run from `research/` (after benchmark, scorer and heldout):  python -m linker.link_map
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from s4_linked_assets import data as d4
from s5_big_moves import run as r5

from . import heldout as ho
from . import options as op
from .benchmark import OUT

AS_OF = "2026-10-02"
TODAY = "2026-10-04"
TRUST_SCORE = 0.5


def end_dates() -> dict[str, tuple[str, bool]]:
    """market id -> (the day the question ends, whether it has already resolved)."""
    out: dict[str, tuple[str, bool]] = {}
    for m in json.loads((d4.CACHE / "pull_meta.json").read_text())["markets"]:
        out[m["market"]] = (str(m["end"])[:10], bool(m["closed"]))
    for f in (r5.HERE / "universe.json", ho.HERE / "universe.json"):
        for m in json.loads(f.read_text())["markets"]:
            out[m["id"]] = (str(m["end"])[:10], bool(m["closed"]))
    return out


def main() -> int:
    b = pd.read_csv(OUT / "benchmark_scored.csv").rename(columns={"score_full_model": "score"})
    h = pd.read_csv(OUT / "heldout_links.csv")
    cols = ["source", "linker", "market", "question", "theme", "ticker", "direction", "two_models", "confidence", "days", "gap_bp_per_point", "gap_t",
            "verdict", "score"]
    df = pd.concat([b[cols], h[cols]], ignore_index=True).drop_duplicates(["market", "ticker", "direction"])
    from s4_linked_assets import run as r4
    fam = {k: v["family"] for k, v in r4.load_critic().items()}
    df["kind"] = df.market.map(lambda m: "price proxy" if fam.get(m) == "spot_proxy" else "event")
    ends = end_dates()
    df["ends"] = df.market.map(lambda m: ends.get(m, ("", True))[0])
    df["resolved"] = df.market.map(lambda m: ends.get(m, ("", True))[1])
    live = df[(~df.resolved) & (df.ends >= TODAY) & (df.ticker != "SPY")].copy()
    live["trusted"] = (live.two_models == 1) & (live.verdict != "contradicted") & ((live.verdict == "confirmed") | (live.score >= TRUST_SCORE))
    s, base = d4._massive_session()
    contracts = []
    for r in live.itertuples():
        c = None
        if r.trusted:
            try:
                c = op.resolve(s, base, r.ticker, r.direction, r.ends, AS_OF)
            except Exception:
                c = None
        contracts.append(c or {})
    live["option_expiry"] = [c.get("expiry", "") for c in contracts]
    live["option_strike"] = [c.get("strike", float("nan")) for c in contracts]
    live["option_contract"] = [c.get("directional_leg", "") for c in contracts]
    live["option_straddle"] = [f"{c.get('call')} + {c.get('put')}" if c.get("call") and c.get("put") else "" for c in contracts]
    live = live.sort_values(["trusted", "score"], ascending=[False, False])
    live.to_csv(OUT / "link_map.csv", index=False)
    t = live[live.trusted]
    summary = {"as_of": AS_OF, "open_links": int(len(live)), "open_questions": int(live.market.nunique()), "trusted_links": int(len(t)),
               "trusted_questions": int(t.market.nunique()), "trusted_tickers": sorted(t.ticker.unique().tolist()),
               "trusted_confirmed_by_prices": int((t.verdict == "confirmed").sum()), "trusted_with_an_option_contract": int((t.option_contract != "").sum()),
               "trusted_event_links": int((t.kind == "event").sum()), "trusted_event_questions": int(t[t.kind == "event"].market.nunique()),
               "trusted_price_proxy_links": int((t.kind == "price proxy").sum()), "trusted_by_theme": t.theme.value_counts().to_dict()}
    (OUT / "link_map.json").write_text(json.dumps({"summary": summary, "links": json.loads(t.drop(columns=["resolved"]).to_json(orient="records"))}, indent=1))
    print(json.dumps(summary, indent=1))
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 62)
    print(t[["kind", "question", "ticker", "direction", "ends", "verdict", "gap_bp_per_point", "gap_t", "score", "option_contract"]].round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
