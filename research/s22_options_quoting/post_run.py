from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .run import load_input


def main():
    out = C.RESULTS_DIR
    d, _ = load_input()
    ok = d[d["status"] == "ok"].copy()
    rows: list[tuple[str, object]] = []

    def put(k, v):
        rows.append((k, round(float(v), 4) if isinstance(v, (float, np.floating)) else v))

    ok["offer"], ok["bid"] = ok["p_hi"] + 0.05, ok["p_lo"] - 0.05
    o = ok[(ok["side"] == "BUY") & ok["offer"].between(0.02, 0.98) & (ok["px"] >= ok["offer"] - 1e-9)].copy()
    b = ok[(ok["side"] == "SELL") & ok["bid"].between(0.02, 0.98) & (ok["px"] <= ok["bid"] + 1e-9)].copy()
    o["pnl"], b["pnl"] = o["offer"] - o["y"], b["y"] - b["bid"]
    o["cap"], b["cap"] = (1 - o["offer"]) * o["size"].clip(upper=100), b["bid"] * b["size"].clip(upper=100)
    a = pd.concat([o, b])
    put("check_fills", len(a)); put("check_dates", a["res_date"].nunique()); put("check_markets", a["market_id"].nunique())
    put("check_mean_pt", 100 * a["pnl"].mean()); put("check_offer_fills", len(o)); put("check_offer_mean_pt", 100 * o["pnl"].mean())
    put("check_bid_fills", len(b)); put("check_bid_mean_pt", 100 * b["pnl"].mean())
    put("check_pnl_usd", (a["pnl"] * a["size"].clip(upper=100)).sum()); put("check_capital_usd", a["cap"].sum())
    put("check_y_values", str(sorted(int(x) for x in ok["y"].dropna().unique()))); put("check_y_missing", int(ok["y"].isna().sum()))
    put("check_size_not_positive", int((ok["size"] <= 0).sum()))

    put("prints_share_yes", ok["y"].mean()); put("prints_mean_px", ok["px"].mean()); put("prints_mean_p_mid", ok["p_mid"].mean())
    pm = ok.sort_values("ts").groupby("market_id").first()
    put("per_market_share_yes", pm["y"].mean()); put("per_market_mean_p_mid", pm["p_mid"].mean()); put("per_market_mean_px", pm["px"].mean())
    dd = ok.groupby("res_date").agg(y=("y", "mean"), p=("p_mid", "mean"), px=("px", "mean"))
    put("per_date_share_yes", dd["y"].mean()); put("per_date_mean_p_mid", dd["p"].mean()); put("per_date_mean_px", dd["px"].mean())

    t = pd.read_csv(out / "trades.csv", dtype={"market_id": str})
    for s in ("bid", "offer"):
        g = t[t["our_side"] == s]
        put(f"{s}_fills", len(g)); put(f"{s}_resolved_yes", int(g["y"].sum())); put(f"{s}_share_yes", g["y"].mean())
        put(f"{s}_mean_quote", g["quote"].mean()); put(f"{s}_mean_p_mid", g["p_mid"].mean()); put(f"{s}_mean_px", g["px"].mean())
    by_d = t.groupby("res_date")["pnl_usd"].sum()
    by_m = t.groupby("market_id")["pnl_usd"].sum()
    best_d, best_m = by_d.idxmax(), by_m.idxmax()
    x = t[t["res_date"] != best_d]
    put("best_date", best_d); put("best_date_fills", int((t["res_date"] == best_d).sum())); put("best_date_pnl_usd", by_d.max())
    put("without_best_date_fills", len(x)); put("without_best_date_mean_pt", x["pnl_pt"].mean()); put("without_best_date_pnl_usd", x["pnl_usd"].sum())
    x = t[t["market_id"] != best_m]
    g = t[t["market_id"] == best_m]
    put("best_market", f"{g['tk'].iloc[0]} above {g['k'].iloc[0]:g} on {g['res_date'].iloc[0]}"); put("best_market_fills", len(g))
    put("best_market_pnl_usd", by_m.max())
    put("without_best_market_fills", len(x)); put("without_best_market_mean_pt", x["pnl_pt"].mean()); put("without_best_market_pnl_usd", x["pnl_usd"].sum())
    put("turnover_cash_locked_over_bankroll", t["capital_usd"].sum() / t.groupby("res_date")["capital_usd"].sum().max())

    v = pd.read_csv(out / "trades_variants.csv", dtype={"market_id": str})
    bench = v[v["variant"] == "benchmark_every_print_at_px"]
    dates = sorted(bench["res_date"].unique())
    rng = np.random.default_rng(C.SEED)
    for s in ("bid", "offer"):
        f, g = t[t["our_side"] == s], bench[bench["our_side"] == s]
        fs = f.groupby("res_date")["pnl_pt"].agg(["sum", "size"]).reindex(dates).fillna(0).to_numpy()
        gs = g.groupby("res_date")["pnl_pt"].agg(["sum", "size"]).reindex(dates).fillna(0).to_numpy()
        draws = []
        for _ in range(C.BOOT_DRAWS):
            i = rng.integers(0, len(dates), len(dates))
            if fs[i, 1].sum() and gs[i, 1].sum():
                draws.append(fs[i, 0].sum() / fs[i, 1].sum() - gs[i, 0].sum() / gs[i, 1].sum())
        lo, hi = np.percentile(draws, [2.5, 97.5])
        put(f"{s}_excess_over_benchmark_pt", f["pnl_pt"].mean() - g["pnl_pt"].mean())
        put(f"{s}_excess_ci_lo_pt", lo); put(f"{s}_excess_ci_hi_pt", hi)

    at_px = bench.merge(t[["market_id", "ts", "taker_side"]], on=["market_id", "ts", "taker_side"])
    put("our_fills_at_print_price_n", len(at_px)); put("our_fills_at_print_price_mean_pt", at_px["pnl_pt"].mean())
    for s in ("bid", "offer"):
        put(f"our_{s}_fills_at_print_price_mean_pt", at_px[at_px["our_side"] == s]["pnl_pt"].mean())

    res = pd.DataFrame(rows, columns=["item", "value"])
    res.to_csv(out / "post_run.csv", index=False)
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
