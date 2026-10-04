"""Root-acknowledged DATA_ONLY completion. Never writes shared caches or puts credentials in URLs."""
from __future__ import annotations
import hashlib
import json
import time
from datetime import datetime,timezone
from pathlib import Path
import requests
from polybridge_research.massive import load_api_key
from . import config as cfg
from .data import OfflineSource,HERE
from .run import main


class CompletionSource(OfflineSource):
    def __init__(self):
        super().__init__()
        self.overlay_dir.mkdir(parents=True,exist_ok=True)
        self.session=requests.Session()
        self.session.headers["Authorization"]="Bearer "+load_api_key(search_from=HERE,interactive=False)
        self.count=0;self.bytes=0;self.last=0.0;self.log=[]
        blocked=HERE.parent/"results"/cfg.PACKAGE/"initial_offline/data_completion_attempt_sandbox.json"
        self.prior_attempts=json.loads(blocked.read_text()).get("requests",0) if blocked.is_file() else 0
    def read(self,path,params):
        got,name=super().read(path,params)
        if got is not None:return got,name
        if self.count+self.prior_attempts>=cfg.DATA_ONLY_REQUEST_BUDGET:raise RuntimeError("DATA_ONLY total-attempt budget exhausted")
        if self.bytes>=cfg.DATA_ONLY_DOWNLOAD_BUDGET_BYTES:raise RuntimeError("DATA_ONLY byte budget exhausted")
        delay=self.last+1/cfg.DATA_ONLY_MAX_RPS-time.monotonic()
        if delay>0:time.sleep(delay)
        self.last=time.monotonic();self.count+=1
        # path and params are frozen nonsecret request fields; token stays solely in the header.
        try:response=self.session.get("https://api.massive.com"+path,params=params,timeout=30)
        except requests.RequestException as exc:
            self.log.append(dict(request=self.count,cache_key=name,path=path,status=type(exc).__name__))
            raise RuntimeError("Massive request failed; details suppressed to protect authentication") from None
        self.bytes+=len(response.content)
        self.log.append(dict(request=self.count,cache_key=name,path=path,status=response.status_code,response_bytes=len(response.content)))
        if response.status_code!=200:raise RuntimeError(f"Massive HTTP {response.status_code}; response suppressed")
        if self.bytes>cfg.DATA_ONLY_DOWNLOAD_BUDGET_BYTES:raise RuntimeError("DATA_ONLY byte budget exceeded; response not cached")
        payload=response.json()
        (self.overlay_dir/name).write_text(json.dumps(payload))
        self.read_files.add(name);self.read_paths.add(self.overlay_dir/name)
        return payload,name


def pull():
    from .data import context,signal_states
    from .run import observe,OUT
    import math
    bars,sess,links=context();states,_=signal_states(sess,links)
    oos_day=sess.day.iloc[len(sess)-int(math.ceil(len(sess)*cfg.OOS_FRACTION))]
    src=CompletionSource();started=datetime.now(timezone.utc).isoformat();error=None
    try:
        for j in range(1,len(sess)):
            if int(sess.open.iloc[j])-int(sess.close.iloc[j-1])>cfg.MIN_CLOSURE_HOURS*3600:
                observe(src,bars,sess,states,j-1,j,oos_day)
    except RuntimeError as exc:error=str(exc)
    finally:
        src.session.close()
        info=dict(started_utc=started,finished_utc=datetime.now(timezone.utc).isoformat(),requests=src.count,
                  response_bytes=src.bytes,max_rps=cfg.DATA_ONLY_MAX_RPS,error=error,log=src.log)
        info["total_attempts_including_blocked_sandbox"]=src.count+src.prior_attempts
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/"data_completion_log.json").write_text(json.dumps(info,indent=2)+"\n")
        print(json.dumps({k:v for k,v in info.items() if k!="log"},indent=2))
    main()


if __name__=="__main__":pull()
