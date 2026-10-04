from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

CLOB = "https://clob.polymarket.com/prices-history"
_RETRY = {429, 500, 502, 503, 504}


class CountingSession(requests.Session):

    def __init__(self):
        super().__init__()
        self.counts: Counter = Counter()

    def get(self, url, **kw):  # noqa: D401
        host = requests.utils.urlparse(url).netloc
        self.counts[host] += 1
        return super().get(url, **kw)


def fetch_pm_history(token_id: str, start: pd.Timestamp, end: pd.Timestamp, cache_dir: Path,
                     session: requests.Session | None = None, sleep=time.sleep, max_attempts: int = 6) -> list[tuple[int, float]]:
    session = session or requests.Session()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    params = {"market": token_id, "startTs": int(start.timestamp()), "endTs": int(end.timestamp()), "fidelity": 1}
    full_url = requests.Request("GET", CLOB, params=params).prepare().url
    cache_file = cache_dir / (hashlib.sha1(full_url.encode()).hexdigest() + ".json")
    if cache_file.exists():
        payload = json.loads(cache_file.read_text())
    else:
        resp = None
        for attempt in range(max_attempts):
            try:
                resp = session.get(full_url, timeout=60)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                if attempt == max_attempts - 1:
                    raise
                sleep(min(2 ** attempt, 20))
                continue
            if resp.status_code not in _RETRY:
                break
            sleep(min(2 ** attempt, 20))
        if resp.status_code == 400:
            payload = {"history": [], "_error": resp.text[:200]}
        else:
            resp.raise_for_status()
            payload = resp.json()
        tmp = cache_file.with_name(f"{cache_file.stem}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, cache_file)
    return [(int(h["t"]), float(h["p"])) for h in payload.get("history", [])]


def fetch_equity_minutes(client, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    path = f"/v2/aggs/ticker/{ticker}/range/1/minute/{int(start.timestamp() * 1000)}/{int(end.timestamp() * 1000)}"
    rows = client.get_all(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
    if not rows:
        return pd.DataFrame(columns=["close", "volume"], index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame(rows)
    idx = pd.to_datetime(df["t"], unit="ms", utc=True)
    out = pd.DataFrame({"close": df["c"].astype(float).to_numpy(), "volume": df["v"].astype(float).to_numpy()}, index=idx)
    return out[~out.index.duplicated(keep="last")].sort_index()
