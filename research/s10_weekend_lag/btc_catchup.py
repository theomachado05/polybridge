import numpy as np
import pandas as pd

from s4_linked_assets import engine as en

from .run import RESULTS

R = RESULTS / "btc"
d = pd.read_csv(R / "minutes.csv.gz").sort_values(["market", "minute"])
d["fair_prev"] = d.groupby("market").fair_end.shift(1)
d = d[d.fair_end.notna() & d.pm.notna() & d.pm_entry.notna()]
rows = []
for name, x, y, sub in (("fair(t) against Polymarket(t): the same minute", d.fair_end - d.pm, d.result - d.pm, d),
                        ("fair(t) against Polymarket(t + 1 min): what a taker one minute late gets", d.fair_end - d.pm_entry, d.result - d.pm_entry, d),
                        ("fair(t - 1 min) against Polymarket(t): is Polymarket a whole minute behind?", None, None, d[d.fair_prev.notna()])):
    if x is None:
        x, y = sub.fair_prev - sub.pm, sub.result - sub.pm
    r = en.clustered_slope(x.to_numpy(), y.to_numpy(), sub.date.to_numpy())
    rows.append({"comparison": name, **r})
pd.DataFrame(rows).to_csv(R / "catchup.csv", index=False)
print(pd.DataFrame(rows)[["comparison", "slope", "t", "n"]].round(3).to_string(index=False))
