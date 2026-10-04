import json
from pathlib import Path

import numpy as np
import pandas as pd

from fresh_accuracy.stats import brier_diff, cluster_boot, log_score

RES = Path(__file__).resolve().parent.parent / "results" / "fresh_accuracy"
BURN_DATES = 20


def boot(df, series, clusters="res_date"):
    out = cluster_boot(series, df[clusters].to_numpy())
    return {"rows": out["n"], "clusters": out["clusters"],
            **{k: {"mean": out[k]["mean"], "ci95": out[k]["ci95"]} for k in series}}


def bd(df):
    return {"brier": brier_diff(df.pm_mid, df.p_mid, df.outcome)}


def sq(p, y):
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def logit(p):
    p = np.clip(np.asarray(p, float), 0.01, 0.99)
    return np.log(p / (1 - p))


def fit_logit(X, y, iters=50):
    X = np.column_stack([np.ones(len(X)), X])
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p) + 1e-9
        b = b + np.linalg.solve(X.T @ (X * W[:, None]) + 1e-6 * np.eye(len(b)), X.T @ (y - p))
    return b


def predict(b, X):
    X = np.column_stack([np.ones(len(X)), X])
    return 1 / (1 + np.exp(-X @ b))


r = pd.read_csv(RES / "rows.csv", low_memory=False)
s = r[r.status == "scored"].copy()
s["p_opt"] = s.p_mid.clip(0, 1)
s["snap_utc"] = pd.to_datetime(s.snap_utc, utc=True)
s["snap_date"] = s.snap_utc.dt.tz_convert("America/New_York").dt.date.astype(str)
y = s.outcome.to_numpy(float)
out = {}

out["primary"] = boot(s, bd(s))
w = s[s.width_sens <= 0.05]
out["exclude_width_sensitive"] = boot(w, bd(w))
first = s.sort_values("snap_utc").groupby("market_id", as_index=False).head(1)
out["earliest_per_contract"] = boot(first, bd(first))
s["group"] = s.ticker.astype(str) + "|" + s.res_date.astype(str)
g = s.assign(d=brier_diff(s.pm_mid, s.p_mid, s.outcome)).groupby("group").agg(d=("d", "mean"), res_date=("res_date", "first")).reset_index()
out["equal_weight_stock_date"] = boot(g, {"brier": g.d.to_numpy()})

fresh_dates = s.loc[s.pm_age_s <= 30, "res_date"].unique()
on = s[s.res_date.isin(fresh_dates)]
out["all_rows_on_fresh_dates"] = boot(on, bd(on))
old = on[on.pm_age_s > 30]
out["older_rows_on_fresh_dates"] = boot(old, bd(old))

avg = (s.pm_mid + s.p_opt) / 2
out["brier_levels"] = {"polymarket": float(sq(s.pm_mid, y).mean()), "options": float(sq(s.p_opt, y).mean()), "average": float(sq(avg, y).mean())}
out["average_vs_options"] = boot(s, {"avg_minus_opt": sq(avg, y) - sq(s.p_opt, y), "pm_minus_avg": sq(s.pm_mid, y) - sq(avg, y)})

dates = sorted(s.res_date.unique())
test_dates = dates[BURN_DATES:]
preds = {k: np.full(len(s), np.nan) for k in ("cal_pm", "cal_opt", "combined")}
lp, lo = logit(s.pm_mid), logit(s.p_opt)
res_dt = pd.to_datetime(s.res_date).dt.date.astype(str).to_numpy()
snap_d = s.snap_date.to_numpy()
for d in test_dates:
    idx = np.where(s.res_date.to_numpy() == d)[0]
    cut = snap_d[idx].min()
    tr = np.where(res_dt < cut)[0]
    preds["cal_pm"][idx] = predict(fit_logit(lp[tr, None], y[tr]), lp[idx, None])
    preds["cal_opt"][idx] = predict(fit_logit(lo[tr, None], y[tr]), lo[idx, None])
    preds["combined"][idx] = predict(fit_logit(np.column_stack([lp[tr], lo[tr]]), y[tr]), np.column_stack([lp[idx], lo[idx]]))
m = ~np.isnan(preds["combined"])
t = s[m]
yt = y[m]
lv = {"polymarket": sq(t.pm_mid, yt), "options": sq(t.p_opt, yt), **{k: sq(v[m], yt) for k, v in preds.items()}}
out["walk_forward"] = {"burn_in_dates": BURN_DATES, "test_dates": len(test_dates),
                       "brier": {k: float(v.mean()) for k, v in lv.items()},
                       **boot(t, {f"{k}_minus_options": lv[k] - lv["options"] for k in ("polymarket", "cal_pm", "cal_opt", "combined")})}
out["walk_forward"]["log"] = {k: float(log_score(v, yt).mean()) for k, v in
                              {"polymarket": t.pm_mid, "options": t.p_opt, **{k: v[m] for k, v in preds.items()}}.items()}

rd = pd.to_datetime(s.res_date)
s["week1"] = rd.dt.strftime("%G-%V")
iso = rd.dt.isocalendar()
s["week2"] = iso.year.astype(str) + "-" + (iso.week // 2).astype(str)
s["week4"] = iso.year.astype(str) + "-" + (iso.week // 4).astype(str)
out["calendar_blocks"] = {k: boot(s, bd(s), clusters=k) for k in ("week1", "week2", "week4")}

(RES / "checks2.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
