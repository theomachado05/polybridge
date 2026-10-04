"""Small exact-id public metadata audit. No credentials, Kalshi or bulk downloads."""
from __future__ import annotations
import csv
import json
import time
from datetime import datetime, timezone
import requests
from . import config as cfg

FIELDS = ('id','question','slug','description','resolutionSource','startDate','endDate','createdAt','updatedAt','conditionId','clobTokenIds','outcomes','feesEnabled','feeSchedule','orderMinSize','orderPriceMinTickSize','negRisk')
TARGETS = {'694936':'NBIS','2154920':'EBAY','700396':'PRIVATE','694938':'VKTX','694940':'GTLB','694937':'BP'}

def local_candidates():
    path=cfg.PACKAGE.parent/'s5_big_moves'/'candidates.json'
    rows=json.loads(path.read_text())
    return [{k:r[k] for k in ('id','question','start','end','token') if k in r} for r in rows if str(r.get('id','')).split(':')[-1] in cfg.CANDIDATE_IDS]

def main():
    cfg.RESULTS.mkdir(parents=True,exist_ok=True)
    cache=cfg.PACKAGE/'.cache';cache.mkdir(exist_ok=True)
    s=requests.Session();s.headers['User-Agent']='PolyBridge research metadata audit (public, low rate)'
    logs=[];rules=[]
    for mid in cfg.CANDIDATE_IDS:
        dest=cache/f'metadata_{mid}.json'
        if dest.exists():
            d=json.loads(dest.read_text());origin='own_metadata_cache';status=200
        else:
            time.sleep(1/cfg.PUBLIC_REQUESTS_PER_SECOND+0.05)
            url=f'https://gamma-api.polymarket.com/markets/{mid}'
            at=datetime.now(timezone.utc).isoformat()
            try:
                r=s.get(url,timeout=25);status=r.status_code
                if status==200:
                    full=r.json();d={k:full.get(k) for k in FIELDS};dest.write_text(json.dumps(d,indent=2))
                else:d={'id':mid,'fetch_error':str(status)}
            except requests.RequestException as e:
                status=0;d={'id':mid,'fetch_error':type(e).__name__}
            logs.append({'time_utc':at,'kind':'metadata','url':url,'status':status})
            origin='gamma_public_current'
        rules.append({**d,'target_ticker':TARGETS[mid],'retrieval_origin':origin})
        print(json.dumps({k:d.get(k) for k in ('id','question','description','startDate','endDate','createdAt','updatedAt','feesEnabled','feeSchedule')},ensure_ascii=False))
    (cfg.RESULTS/'local_catalog_audit.json').write_text(json.dumps({'candidate_catalog_count':892,'restricted_universe_count':240,'candidates':local_candidates(),'target_equity_cache_files':0,'metadata_fetches':logs},indent=2))
    (cfg.RESULTS/'current_rules.json').write_text(json.dumps(rules,indent=2))
    with (cfg.RESULTS/'requests.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['time_utc','kind','url','status'],lineterminator='\n');w.writeheader();w.writerows(logs)
    return 0

if __name__=='__main__':raise SystemExit(main())
