"""Run the expected-gap OOS study once (METHOD.md). No network: reads saved closure tables only.

    cd research && uv run --env-file ../.env python -m gap_model.run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from . import report
from .config import (EXPORT_PATH, MAPPED_ETF, PANEL_A_CSV, PANEL_A_EVENTS, PANEL_B_CSV, PANEL_B_MARKETS, PARAMS,
                     REPO_DIR, RESULTS_DIR)
from .model import (band_coverage, between_market_sd, calibration_table, fit_rate, oos_r2, sign_accuracy, slope_test,
                    verdict, walk_forward)

OUTCOMES = {"SPY": "gap_spy", "QQQ": "gap_qqq"}


def git_commit() -> str:
    try:
        c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "research/gap_model"], cwd=REPO_DIR,
                               capture_output=True, text=True).stdout.strip()
        return c + (" + uncommitted changes in gap_model/" if dirty else "")
    except Exception:  # pragma: no cover
        return "unknown"


def load_panel_a() -> tuple[pd.DataFrame, dict]:
    d = pd.read_csv(PANEL_A_CSV)
    d = d[d["reason"].isna() | (d["reason"].astype(str) == "")]
    out = pd.DataFrame({"market": d["market"], "closure": d["closure"].astype(str), "open_day": d["open_day"].astype(str),
                        "kind": d["kind"], "x": d["dpm_o_pp"].astype(float), "gap_spy": d["gap_bp"].astype(float),
                        "gap_qqq": d["gap_qqq_bp"].astype(float), "news": d["news"].astype(bool), "panel": "A"})
    meta = yaml.safe_load(PANEL_A_EVENTS.read_text())["markets"]
    names = {"election": "Trump wins the 2024 US presidential election", "recession": "US recession in 2025"}
    info = {k: {"slug": v["market_slug"], "token_id": str(v["token_id"]), "sign": int(v["sign"]), "question": names[k]}
            for k, v in meta.items()}
    return out, info


def load_panel_b() -> tuple[pd.DataFrame | None, dict]:
    if not PANEL_B_CSV.exists():
        return None, {}
    d = pd.read_csv(PANEL_B_CSV)
    if "reason" in d:
        d = d[d["reason"].isna() | (d["reason"].astype(str) == "")]
    d = d[np.isfinite(d.get("x_pp", pd.Series(dtype=float)).astype(float))
          & np.isfinite(d.get("gap_spy_bp", pd.Series(dtype=float)).astype(float))]
    if d.empty:
        return None, {}
    out = pd.DataFrame({"market": d["market"].astype(str), "closure": d["closure"].astype(str),
                        "open_day": d["open_day"].astype(str), "kind": d.get("kind", ""),
                        "x": d["x_pp"].astype(float), "gap_spy": d["gap_spy_bp"].astype(float),
                        "gap_qqq": d["gap_qqq_bp"].astype(float) if "gap_qqq_bp" in d else np.nan,
                        "news": False, "panel": "B"})
    cands = {c["market_slug"]: c for c in json.loads(PANEL_B_MARKETS.read_text())["candidates"]}
    info = {m: {"slug": m, "token_id": str(cands.get(m, {}).get("token_id", "")), "sign": int(cands.get(m, {}).get("sign", 0)),
                "question": cands.get(m, {}).get("question", "").strip()} for m in out["market"].unique()}
    return out, info


def evaluate(pr: pd.DataFrame, groups=None, with_extras: bool = True) -> dict:
    g1 = sign_accuracy(pr["pred_bp"], pr["gap_bp"])
    g2 = slope_test(pr["pred_bp"], pr["gap_bp"], groups=None if groups is None else pr[groups].to_numpy())
    res = {"n_test": len(pr), "g1": g1, "g2": g2, "verdict": verdict(g1, g2)[0]}
    if with_extras:
        res["g1_theta"] = sign_accuracy(pr["pred_bp"], pr["gap_bp"], x=pr["x_pp"], theta=PARAMS.theta_pp)
        res["oos_r2_zero"] = oos_r2(pr["pred_bp"], pr["gap_bp"], np.zeros(len(pr)))
        res["oos_r2_mean"] = oos_r2(pr["pred_bp"], pr["gap_bp"], pr["mean_past_bp"])
        res["band"] = band_coverage(pr)
        res["sources"] = pr["source"].value_counts().to_dict()
    return res


def split(pr: pd.DataFrame, col: str, groups=None) -> dict:
    return {k: evaluate(s, groups=groups, with_extras=False) for k, s in pr.groupby(col)}


def export(rows: pd.DataFrame, info: dict, res: dict, commit: str) -> dict:
    """Full-sample per-market and pooled rates for the product (METHOD.md section 5)."""
    markets = {}
    own_rates = []
    for m, s in rows.groupby("market"):
        f = fit_rate(s["x"], s["gap_spy"])
        meta = info[m]
        use = "own" if f["n_nonzero"] >= PARAMS.n_min else "pooled"
        if use == "own":
            own_rates.append(f["rate"])
        markets[meta["slug"]] = {
            "question": meta["question"], "token_id": meta["token_id"], "sign": meta["sign"], "etf": MAPPED_ETF,
            "panel": s["panel"].iloc[0], "rate_bp_per_pp": f["rate"], "rate_raw_bp_per_pp": meta["sign"] * f["rate"],
            "se": f["se"], "resid_sd_bp": f["resid_sd"], "n": f["n"], "n_nonzero": f["n_nonzero"],
            "first_closure": s["closure"].min(), "last_closure": s["closure"].max(), "use": use}
    p = fit_rate(rows["x"], rows["gap_spy"])
    tau = between_market_sd(own_rates, p["rate"])
    prim = res["primary"]["SPY"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "research/gap_model/run.py", "method": "research/gap_model/METHOD.md", "git_commit": commit,
        "units": "rate_bp_per_pp = bp of SPY open gap per pp of ORIENTED PM move (x = sign * change in Yes price, pp); "
                 "rate_raw_bp_per_pp = bp per pp of the raw Yes-price change (= sign * rate)",
        "formula": "expected_gap_bp = rate_bp_per_pp * sign * (pm_now_pp - pm_at_last_regular_close_pp)",
        "n_min": PARAMS.n_min, "z80": PARAMS.z80,
        "band_rule": "80% band = expected_gap +- z80 * sqrt(x^2 * se_eff^2 + resid_sd_bp^2); se_eff = se for use=own; "
                     "for use=pooled (or a market not listed) use the pooled rate, pooled resid_sd_bp and "
                     "se_eff = sqrt(pooled.se^2 + tau^2)",
        "pooled": {"rate_bp_per_pp": p["rate"], "se": p["se"], "resid_sd_bp": p["resid_sd"], "n": p["n"],
                   "n_nonzero": p["n_nonzero"], "n_markets": len(markets)},
        "tau_bp_per_pp": tau,
        "sample": "unselected closures only: leadlag_closed placebo panel (380)"
                  + (" + leadlag_replication panel" if (rows["panel"] == "B").any() else "")
                  + "; the 17 hand-picked news closures are excluded",
        "oos": {"verdict": prim["verdict"], "n_test": prim["n_test"],
                "sign_accuracy": prim["g1"]["rate"], "sign_n": prim["g1"]["n"], "sign_p": prim["g1"]["p"],
                "slope": prim["g2"]["c"], "slope_p_perm": prim["g2"]["p_perm"], "slope_hc3_t": prim["g2"]["t"],
                "band80_coverage": prim["band"]["all"]["coverage"]},
        "markets": markets,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=None, help="write results here instead of research/results/gap_model")
    ap.add_argument("--no-export", action="store_true", help="do not write backend/app/data/gap_rates.json")
    args = ap.parse_args(argv)
    out_dir = RESULTS_DIR if args.out_dir is None else __import__("pathlib").Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    commit = git_commit()

    a, info_a = load_panel_a()
    b, info_b = load_panel_b()
    placebo = a[~a["news"]].copy()

    res: dict = {"primary": {}, "params": PARAMS.__dict__, "panel_b_available": b is not None}
    preds = []
    for etf, col in OUTCOMES.items():
        pr = walk_forward(placebo, col)
        pr["set"], pr["etf"] = "A_placebo", etf
        preds.append(pr)
        r = evaluate(pr)
        r["by_market"] = split(pr, "market")
        r["by_source"] = split(pr, "source")
        res["primary"][etf] = r
    prim = preds[0]
    res["calibration"] = calibration_table(prim["pred_bp"], prim["gap_bp"]).to_dict("records")

    pr_all = walk_forward(a, "gap_spy")
    pr_all["set"], pr_all["etf"] = "A_all397", "SPY"
    preds.append(pr_all)
    res["all397"] = evaluate(pr_all)

    if b is not None:
        comb = pd.concat([placebo.assign(test=False), b.assign(test=True)], ignore_index=True)
        prb = walk_forward(comb, "gap_spy")
        prb["set"], prb["etf"] = "B_replication", "SPY"
        preds.append(prb)
        rb = evaluate(prb, groups="closure")
        rb["by_market"] = split(prb, "market", groups="closure")
        rb["by_source"] = split(prb, "source", groups="closure")
        rb["n_markets"] = int(b["market"].nunique())
        res["panel_b"] = rb
        rb["calibration"] = calibration_table(prb["pred_bp"], prb["gap_bp"]).to_dict("records")

    rows_export = placebo if b is None else pd.concat([placebo, b], ignore_index=True)
    info = {**info_a, **info_b}
    exp = export(rows_export, info, res, commit)
    res["export"] = {k: exp[k] for k in ("pooled", "tau_bp_per_pp", "sample")}
    res["export"]["markets"] = {k: {kk: v[kk] for kk in ("rate_bp_per_pp", "se", "n", "n_nonzero", "use")}
                                for k, v in exp["markets"].items()}

    predictions = pd.concat(preds, ignore_index=True)
    report.write_all(predictions, res, info, out_dir)
    if not args.no_export:
        EXPORT_PATH.write_text(json.dumps(report.jsonable(exp), indent=1) + "\n")

    wall = time.time() - t0
    p = res["primary"]["SPY"]
    entry = (f"## {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}\n- code commit: `{commit}`\n"
             f"- mode: analysis of saved closure tables (panel A{' + panel B' if b is not None else '; panel B not available'})\n"
             f"- wall time: {wall:.0f} s\n- network requests: 0\n"
             f"- result: {p['n_test']} test closures; sign accuracy {p['g1']['k']}/{p['g1']['n']} "
             f"({100 * p['g1']['rate']:.1f}%, p = {p['g1']['p']:.3g}); slope {p['g2']['c']:+.2f} "
             f"(permutation p = {p['g2']['p_perm']:.3g}); verdict: {p['verdict']}\n- exit: 0\n")
    report.append_run_log(out_dir, entry)
    print(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
