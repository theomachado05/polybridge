"""Record the closed-market demo replay: one real weekend (Friday 15:30 ET to Monday 10:00 ET) on a market whose
expected-gap model is validated out of sample, picked by a fixed rule, with the PM history and the mapped ETF's bars.

Rule (applied to committed research tables only; no price is looked at to choose):
  1. markets: those ``backend/app/data/gap_evidence.json`` marks validated (R2: the market's own out-of-sample record
     passes). Today: US recession in 2025 (sign 64.2% of 151, slope +1.28).
  2. closures: that market's weekend closures in research/results/leadlag_closed/closures_all.csv (all 397 closures,
     the hand-picked news weekends included: they are real weekends; R2 tested the rate on the unselected ones).
  3. pick the largest ADVERSE move: the most equity-bearish oriented PM move (sign x YES change, most negative), so
     hedge B has a gap to stage for; ties go to the most recent.
Window: Friday 15:30 ET (a regular-session warm-up and the closure tracker's price at the 16:00 close) to Monday 10:01
ET (the open plus 30 minutes, the window of R1's hedge B test), PM history at 5-minute points and 5-minute bars of the
market's ETF (gap_rates.json ``etf``: SPY), through ``history_with_equity.py --start/--end``. Writes the replay, its
sidecar (with the rule and the research row of the chosen weekend), and adds the market to app/data/replay_index.json.

    cd backend && uv run --env-file ../.env python scripts/record_weekend.py            # pick, then record
    cd backend && uv run python scripts/record_weekend.py --dry-run                     # only print the pick
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for p in (BACKEND, BACKEND / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

ET = ZoneInfo("America/New_York")
CLOSURES = ROOT / "research" / "results" / "leadlag_closed" / "closures_all.csv"
EVIDENCE = BACKEND / "app" / "data" / "gap_evidence.json"
RATES = BACKEND / "app" / "data" / "gap_rates.json"
INDEX = BACKEND / "app" / "data" / "replay_index.json"
REPLAYS = BACKEND / "replays"
LABELS = {"us-recession-in-2025": "recession", "will-donald-trump-win-the-2024-us-presidential-election": "election"}
START_ET, END_ET = dt.time(15, 30), dt.time(10, 1)
FIDELITY_MIN = BAR_MIN = 5


def pick(evidence: dict, closures: list[dict]) -> dict:
    validated = [slug for slug, m in (evidence.get("markets") or {}).items() if m.get("validated")]
    cands = []
    for slug in validated:
        label = LABELS.get(slug, slug)
        for r in closures:
            if r["market"] != label or r["kind"] != "weekend" or not r.get("dpm_pp"):
                continue
            oriented = int(float(r["sign"])) * float(r["dpm_pp"])
            if oriented < 0:
                cands.append((oriented, r["closure"], slug, r))
    if not cands:
        raise SystemExit("no adverse weekend closure on a validated market")
    cands.sort(key=lambda c: (c[0], [-ord(ch) for ch in c[1]]))
    oriented, _, slug, row = cands[0]
    return {"slug": slug, "row": row, "oriented_move_pp": oriented, "n_candidates": len(cands)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the pick and the command, record nothing")
    a = ap.parse_args(argv)
    evidence = json.loads(EVIDENCE.read_text())
    closures = list(csv.DictReader(CLOSURES.open()))
    p = pick(evidence, closures)
    slug, row = p["slug"], p["row"]
    m = evidence["markets"][slug]
    rate = (json.loads(RATES.read_text()).get("markets") or {}).get(slug) or {}
    etf = (rate.get("etf") or "SPY").upper()
    fri, mon = dt.date.fromisoformat(row["closure"]), dt.date.fromisoformat(row["open_day"])
    start = dt.datetime.combine(fri, START_ET, ET)
    end = dt.datetime.combine(mon, END_ET, ET)
    out = REPLAYS / f"{slug}-weekend-{fri.isoformat()}.jsonl"
    market_id = m.get("polymarket_id") or m["token_id"]
    print(f"rule pick: {slug} weekend {fri} -> {mon} (oriented PM move {p['oriented_move_pp']:+.1f} pp, YES "
          f"{row['pm_close']} -> {row['pm_open']}, SPY gap {float(row['gap_bp']):+.1f} bp, 09:30-10:00 "
          f"{float(row['ret30_bp']):+.1f} bp; {p['n_candidates']} adverse weekends; event: {row.get('name') or 'none'})")
    args = ["--market", f"{slug}={market_id}", "--equity", etf, "--out", str(out), "--start", start.isoformat(),
            "--end", end.isoformat(), "--fidelity", str(FIDELITY_MIN), "--bar-minutes", str(BAR_MIN)]
    print("history_with_equity.py " + " ".join(args))
    if a.dry_run:
        return 0
    import history_with_equity
    code = history_with_equity.main(args)
    if code:
        return code
    side = out.with_name(out.name + ".meta.json")
    meta = json.loads(side.read_text())
    meta["weekend"] = {
        "rule": "largest adverse (equity-bearish) oriented PM move over a weekend closure of a market whose expected-gap "
                "model is validated out of sample (gap_evidence.json); research/results/leadlag_closed/closures_all.csv; "
                "ties to the most recent (scripts/record_weekend.py)",
        "closure": row["closure"], "open_day": row["open_day"], "sign": int(float(row["sign"])),
        "research_pm_close_pct": float(row["pm_close"]), "research_pm_open_pct": float(row["pm_open"]),
        "research_dpm_pp": float(row["dpm_pp"]), "research_gap_bp": float(row["gap_bp"]),
        "research_ret30_bp": float(row["ret30_bp"]), "news": row.get("news") == "True",
        "event": row.get("name") or None, "n_adverse_weekends": p["n_candidates"],
        "validated_oos": {k: m.get(k) for k in ("verdict", "sign_k", "sign_n", "sign_rate", "slope", "slope_p_perm")},
        "gap_rate_bp_per_pp": rate.get("rate_bp_per_pp"), "gap_rate_n": rate.get("n"),
    }
    side.write_text(json.dumps(meta, indent=1) + "\n")
    idx = json.loads(INDEX.read_text())
    idx[f"polymarket:{m.get('polymarket_id')}"] = out.name
    idx[f"token:{m['token_id']}"] = out.name
    INDEX.write_text(json.dumps(idx, indent=1) + "\n")
    print(f"sidecar + replay index updated: {side.name}, {INDEX.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
