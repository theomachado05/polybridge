"""S10, looked at after the run (not pre-registered): does one weekend carry the crude lead, and does it hold in- and out-of-sample?
Run from `research/`:  python -m s10_weekend_lag.robust   (writes results/s10_weekend_lag/robust.csv)"""
import math
import numpy as np
import pandas as pd
from s10_weekend_lag import run as r, config as cfg

from s9_weekend_price_markets import run as s9
qs=r.questions(); cls={"crude": r.price_markets("crude"), "gold": r.price_markets("gold")}
W=[r.weekend(w,qs,cls) for w in s9.calendar()]
W=[w for w in W if len(w["live_q"]) and len(w["classes"]["crude"]["live"])]
keys=sorted(w["key"] for w in W); oos=keys[len(keys)-math.ceil(0.2*len(keys))]
def sl(WW, h, d="event first"):
    rows=[x for x in r.leadlag_rows(WW,"crude") if x["direction"]==d and x["horizon_min"]==h]
    return rows[0]["slope"], rows[0]["t"]
for h in (5,15,30):
    full=sl(W,h); loo=[(w["key"],)+sl([x for x in W if x is not w],h) for w in W]
    lo=min(loo,key=lambda x:x[1]); hi=max(loo,key=lambda x:x[1])
    print(f"event first {h}m full {full[0]:.3f} t {full[1]:.2f} | drop-one min {lo[1]:.3f} (t {lo[2]:.2f}, without {lo[0]}) max {hi[1]:.3f}")
    print(f"   IS {sl([w for w in W if w['key']<oos],h)}  OOS {sl([w for w in W if w['key']>=oos],h)}")
out=[]
for h in (5,15,30,60):
    for d in ("event first","price first"):
        f=sl(W,h,d); loo=[(w["key"],)+sl([x for x in W if x is not w],h,d) for w in W]; lo=min(loo,key=lambda x:x[1])
        i_=sl([w for w in W if w["key"]<oos],h,d); o_=sl([w for w in W if w["key"]>=oos],h,d)
        out.append({"direction":d,"horizon_min":h,"slope":f[0],"t":f[1],"drop_one_min_slope":lo[1],"drop_one_min_t":lo[2],"drop_one_min_without":lo[0],
                    "is_slope":i_[0],"is_t":i_[1],"oos_slope":o_[0],"oos_t":o_[1]})
pd.DataFrame(out).to_csv(r.RESULTS/"robust.csv",index=False)
print(pd.DataFrame(out).round(3).to_string())
