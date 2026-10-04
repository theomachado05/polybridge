"""Snapshot of the currently listed eligible markets (METHOD.md section 2). Gamma metadata and Massive contract lists only;
no price, print, quote or outcome is fetched or written.

    cd research && .venv/bin/python -m forward_monday.snapshot
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import forward_monday  # noqa: F401
from arbscan import datasrc as ds
from polybridge_research.massive import MassiveClient, load_api_key

from . import config as C
from . import core
from .run import UNI_COLS, listing, sessions, sha256, universe, write_csv


def main():
    sess = sessions()
    reo = core.reopenings(sess)
    http = ds.Http(C.CACHE_DIR / "http")
    massive = MassiveClient(load_api_key(search_from=C.RESEARCH_DIR, interactive=False), cache_dir=C.CACHE_DIR / "massive")
    opts = ds.OptionSource(massive, date.fromisoformat(C.SNAPSHOT_DATE))
    meta = listing(http, reo[0], core.week_end(reo[-1], sess), closed_states=("false",))
    rows, scope = [], Counter()
    for d in reo:
        rows += universe(meta, d, sess, opts, scope)
    path = C.PKG_DIR / f"snapshot_{C.SNAPSHOT_DATE}.csv"
    write_csv(path, UNI_COLS, rows)
    h = sha256(path)
    (C.PKG_DIR / f"snapshot_{C.SNAPSHOT_DATE}.sha256").write_text(f"{h}  {path.name}\n")
    print(json.dumps({"listed_markets": len(meta), "eligible": len(rows), "by_reopening": dict(Counter(r["reopening"] for r in rows)),
                      "by_ticker": dict(Counter(r["tk"] for r in rows)), "drops": dict(scope), "sha256": h}))


if __name__ == "__main__":
    main()
