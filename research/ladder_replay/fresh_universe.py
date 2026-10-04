from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from s1_twin_spread import data as ds
from s11_bundles import universe as s11u
from s11_bundles import config as s11cfg

from . import config as cfg

HERE = Path(__file__).resolve().parent
TEXT_KEYS = ("description", "resolutionSource", "orderPriceMinTickSize", "slug", "umaEndDate")


def events(closed: bool, pt: ds.Throttle):
    cur = None
    while True:
        p = {"closed": str(closed).lower(), "end_date_min": cfg.FRESH_END_DATE_MIN + "T00:00:00Z", "volume_min": 2 * s11cfg.MIN_MARKET_VOLUME,
             "limit": cfg.GAMMA_PAGE}
        if cur:
            p["after_cursor"] = cur
        d = ds.get_json(f"{ds.GAMMA}/events/keyset", p, throttle=pt)
        for e in d.get("events") or []:
            yield e
        cur = d.get("next_cursor")
        if not cur or not d.get("events"):
            return


def main() -> int:
    s11 = json.loads((HERE.parent / "s11_bundles" / "bundles.json").read_text())
    s11_events = {str(b["event"]) for b in s11["bundles"]}
    s11_legs = set(s11["markets"])
    pt = ds.Throttle(cfg.REQ_RATE)
    seen, out, meta, n_ev, n_closed_ev, n_excl = set(), [], {}, 0, 0, 0
    for closed in (True, False):
        for e in events(closed, pt):
            if str(e["id"]) in seen:
                continue
            seen.add(str(e["id"]))
            n_ev += 1
            if not any(m.get("closed") for m in e.get("markets") or []):
                continue
            n_closed_ev += 1
            if str(e["id"]) in s11_events or (e.get("slug") or "") in s11_events:
                n_excl += 1
                continue
            bs, mm = s11u.event_bundles(e)
            raw = {str(m["id"]): m for m in e.get("markets") or []}
            for b in bs:
                if b["kind"] != "date" or set(b["legs"]) & s11_legs:
                    continue
                b["event_id"], b["event_resolutionSource"] = str(e["id"]), e.get("resolutionSource") or ""
                out.append(b)
                for i in b["legs"]:
                    meta[i] = dict(mm[i], **{k: raw[i].get(k) for k in TEXT_KEYS})
                    assert not s11u.PRICE_FIELDS & set(meta[i])
    res = {"built_utc": datetime.now(timezone.utc).isoformat(), "events_read": n_ev, "events_with_closed_market": n_closed_ev,
           "events_in_s11": n_excl, "bundles": out, "markets": meta}
    (HERE / "fresh_universe.json").write_text(json.dumps(res, indent=1))
    print(f"events read {n_ev}, with a closed market {n_closed_ev}, in S11 {n_excl}; date ladders {len(out)}, "
          f"pairs {sum(len(b['pairs']) for b in out)}, markets {len(meta)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
