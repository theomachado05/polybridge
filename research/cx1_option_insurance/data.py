"""Read-only cached NBBO and as-of event signals. No network, keys or result-file imports."""
from __future__ import annotations
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from s1_twin_spread.engine import asof
from s4_linked_assets.engine import sessions_from
from s5_big_moves.run import merge_links
from . import config as cfg
HERE=Path(__file__).resolve().parent
RESEARCH=HERE.parent


class OfflineSource:
    def __init__(self,cache_dir: Path|None=None):
        self.cache_dir=cache_dir or RESEARCH/".massive_cache"
        self.read_files: set[str]=set()
        self.read_paths: set[Path]=set()
        self.overlay_dir=HERE/".cache/massive" if cache_dir is None else None
    def read(self,path: str,params: dict) -> tuple[dict|None,str]:
        full=requests.Request("GET","https://api.massive.com"+path,params=params).prepare().url
        name=hashlib.sha1(full.encode()).hexdigest()+".json"
        p=self.cache_dir/name
        if self.overlay_dir is not None and (self.overlay_dir/name).is_file():p=self.overlay_dir/name
        if not p.is_file():return None,name
        self.read_files.add(name)
        self.read_paths.add(p)
        return json.loads(p.read_text()),name
    def expiry(self,day: str) -> tuple[str|None,dict[float,str],str]:
        lower=date.fromisoformat(day)+timedelta(days=cfg.EXPIRY_MIN_DAYS)
        for delta in range(cfg.EXPIRY_SEARCH_DAYS+1):
            d=lower+timedelta(days=delta)
            if d.weekday()>=5:continue
            params={"underlying_ticker":cfg.UNDERLYING,"expiration_date":d.isoformat(),"contract_type":"call","limit":1000,"expired":"true"}
            payload,name=self.read("/v3/reference/options/contracts",params)
            if payload is None:return None,{},f"listing not cached: {d.isoformat()}"
            rows=payload.get("results") or []
            if payload.get("next_url"):
                return None,{},f"paginated listing unsupported: {d.isoformat()}"
            valid=[r for r in rows if r.get("shares_per_contract",100)==100 and r.get("underlying_ticker")==cfg.UNDERLYING
                   and r.get("contract_type")=="call" and r.get("expiration_date")==d.isoformat()]
            if valid:return d.isoformat(),{float(r["strike_price"]):r["ticker"] for r in valid},"ok"
        return None,{},"no expiry in cached search"
    def quote(self,symbol: str,at: int) -> tuple[dict|None,str]:
        iso=datetime.fromtimestamp(at,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload,name=self.read(f"/v3/quotes/{symbol}",{"limit":1,"timestamp.lte":iso,"order":"desc","sort":"timestamp"})
        if payload is None:return None,f"NBBO request not cached ({name})"
        rows=payload.get("results") or []
        if not rows:return None,"cached NBBO empty"
        x=rows[0]
        return {"bid":float(x.get("bid_price") or 0),"ask":float(x.get("ask_price") or 0),
                "bid_size":float(x.get("bid_size") or 0),"ask_size":float(x.get("ask_size") or 0),
                "timestamp":float(x.get("sip_timestamp") or 0)/1e9},"ok"


def valid_quote(q: dict|None,at: int,max_age: int,floor: int|None=None) -> str:
    if q is None:return "missing quote"
    if not all(np.isfinite(q[k]) for k in ["bid","ask","bid_size","ask_size","timestamp"]):return "nonfinite quote"
    if q["bid"]<=0 or q["ask"]<q["bid"]:return "invalid or crossed quote"
    if q["timestamp"]>at:return "future quote"
    if at-q["timestamp"]>max_age:return "stale quote"
    if floor is not None and q["timestamp"]<floor:return "quote predates session"
    return "ok"


def context() -> tuple[dict,pd.DataFrame,list[dict]]:
    with np.load(RESEARCH/"s5_big_moves/.cache/eq_SPY.npz") as z:bars={k:z[k] for k in z.files}
    sess=sessions_from(bars["t"])
    sess=sess[(sess.day>=cfg.WINDOW_START)&(sess.day<=cfg.WINDOW_END)].reset_index(drop=True)
    sess=correct_early_closes(sess)
    links,_=merge_links();links=sorted([x for x in links if x["ticker"]==cfg.UNDERLYING],key=lambda x:x["market"])
    return bars,sess,links


def correct_early_closes(sess: pd.DataFrame) -> pd.DataFrame:
    sess=sess.copy()
    for day,clock in cfg.EARLY_CLOSE_ET.items():
        at=int(pd.Timestamp(f"{day} {clock}",tz="America/New_York").timestamp())
        sess.loc[sess.day==day,"close"]=at
    return sess


def signal_states(sess: pd.DataFrame,links: list[dict]) -> tuple[dict[int,list[tuple[float,float]]],list[dict]]:
    states={i:[] for i in range(len(sess))}; manifest=[]
    op=sess.open.to_numpy(dtype=np.int64);cl=sess.close.to_numpy(dtype=np.int64)
    cutoff=cl-cfg.SIGNAL_BEFORE_CLOSE_MINUTES*60
    for link in links:
        f=RESEARCH/"s5_big_moves/.cache"/f"pm_{link['market'].split(':')[1]}.npz"
        if not f.is_file():continue
        with np.load(f) as z:t=z["t"].copy();p=z["p"].astype(float)
        close_odds=asof(cl,t,p,cfg.PM_MAX_AGE_SECONDS)
        morning=asof(op-60,t,p,cfg.PM_MAX_AGE_SECONDS)
        current=asof(cutoff,t,p,cfg.PM_MAX_AGE_SECONDS)
        abs_change=100*np.abs(morning-np.r_[np.nan,close_odds[:-1]])
        for i in range(len(sess)):
            w=abs_change[max(0,i-cfg.ACTIVITY_NIGHTS+1):i+1];w=w[np.isfinite(w)]
            activity=float(w.mean()) if len(w)>=cfg.ACTIVITY_MIN_NIGHTS else float("nan")
            states[i].append((float(current[i]),activity))
            manifest.append(dict(market=link["market"],question=link["question"],day=sess.day.iloc[i],
                                 cutoff=int(cutoff[i]),odds_at_cutoff=float(current[i]),activity_points=activity,
                                 nights_observed=len(w)))
    return states,manifest


def underlying_at(bars: dict,at: int) -> float|None:
    """A bar's close is known only after its full five-minute interval ends."""
    j=int(np.searchsorted(bars["t"]+300,at,side="right")-1)
    if j<0 or at-(int(bars["t"][j])+300)>300:return None
    px=float(bars["c"][j])
    return px if np.isfinite(px) and px>0 else None
