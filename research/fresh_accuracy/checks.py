import json
from pathlib import Path

import numpy as np
import pandas as pd

RES = Path(__file__).resolve().parent.parent / "results" / "fresh_accuracy"
rng = np.random.default_rng(20261004)


def brier_diff(df):
    return ((df.pm_mid - df.outcome) ** 2 - (df.p_mid - df.outcome) ** 2).to_numpy()


def boot(df, n=10000):
    d = brier_diff(df)
    dates = df.res_date.to_numpy()
    keys = np.unique(dates)
    sums = np.array([d[dates == k].sum() for k in keys])
    cnts = np.array([(dates == k).sum() for k in keys])
    draw = rng.integers(len(keys), size=(n, len(keys)))
    means = sums[draw].sum(1) / cnts[draw].sum(1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"rows": int(len(df)), "dates": int(len(keys)), "brier_diff": float(d.mean()), "ci_lo": float(lo), "ci_hi": float(hi)}


r = pd.read_csv(RES / "rows.csv", low_memory=False)
s = r[r.status == "scored"].copy()
contrib = s.assign(d=brier_diff(s)).groupby("res_date").d.sum().sort_values(ascending=False)
top5 = list(contrib.index[:5])
cut = sorted(s.res_date.unique())
start = cut[int(np.floor(0.8 * len(cut)))]
out = {
    "primary": boot(s),
    "drop_5_most_influential_dates": {**boot(s[~s.res_date.isin(top5)]), "dropped": top5},
    "symmetric_filter_options_also_in_2_98": boot(s[(s.p_mid >= 0.02) & (s.p_mid <= 0.98)]),
    "pm_age_at_most_30s": boot(s[s.pm_age_s <= 30]),
    "pm_age_under_30s": boot(s[s.pm_age_s < 30]),
    "latest_20pct_of_resolution_dates": {**boot(s[s.res_date >= start]), "from": start},
    "mean_pm_age_s": float(s.pm_age_s.mean()),
    "mean_option_quote_age_s": float(s.opt_quote_age_s.mean()),
}
(RES / "checks.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
