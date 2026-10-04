from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from s1_twin_spread import data as ds
from s11_bundles import config as s11cfg
from s11_bundles.universe import parse_date

from . import config as cfg

HERE = Path(__file__).resolve().parent
TEXT_FIELDS = ("id", "question", "groupItemTitle", "description", "resolutionSource", "startDate", "createdAt", "conditionId")


def ts_of(s) -> float | None:
    if not s:
        return None
    s = str(s).replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def date_spellings(d: date) -> list[str]:
    m_full, m_abbr = d.strftime("%B").lower(), d.strftime("%b").lower()
    day = d.day
    suf = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    out = []
    for mo in (m_full, m_abbr + ".", m_abbr):
        for dd in (f"{day}{suf}", str(day)):
            out += [f"{mo} {dd}, {d.year}", f"{mo} {dd} {d.year}", f"{mo} {dd}"]
        out += [f"{day} {mo} {d.year}", f"{day} {mo}"]
    last = date(d.year + (d.month == 12), d.month % 12 + 1, 1).toordinal() - 1 == d.toordinal()
    if last:
        out += [f"end of {m_full} {d.year}", f"end of {m_full}", f"{m_full} {d.year}"]
    out += [d.isoformat(), f"{d.month}/{d.day}/{d.year}", f"{d.month}/{d.day}"]
    return sorted(set(out), key=len, reverse=True)


def level_spellings(v: float) -> list[str]:
    outs = set()
    for base in (v, v / 1e3, v / 1e6, v / 1e9):
        if base < 1 and base != v:
            continue
        s = f"{base:,.10f}".rstrip("0").rstrip(".")
        s2 = s.replace(",", "")
        suf = "" if base == v else {v / 1e3: "k", v / 1e6: "m", v / 1e9: "b"}.get(base, "")
        for x in {s, s2}:
            for cur in ("$", ""):
                outs.add(f"{cur}{x}{suf}")
                if suf:
                    outs.add(f"{cur}{x} {dict(k='thousand', m='million', b='billion')[suf]}")
        if base == v:
            outs |= {f"${v:,.2f}", f"{v:,.2f}", f"{v:.2f}"}
    return sorted(outs, key=len, reverse=True)


def mask(text: str, spellings: list[str], placeholder: str) -> str:
    t = norm(text)
    for s in spellings:
        t = re.sub(r"(?<![\w.,$])" + re.escape(s) + r"(?![\w]|[.,]\d)", placeholder, t)
    return t


def rung_key(kind: str, bundle: dict, leg: str):
    k = bundle["keys"][bundle["legs"].index(leg)]
    return date.fromisoformat(k) if kind == "date" else float(k)


def deadline(m: dict, key: date) -> date | None:
    for txt in (m.get("groupItemTitle") or "", m.get("question") or ""):
        for ph in re.findall(s11cfg.DATE_RE, txt):
            y = re.search(r"20\d\d", ph)
            d = parse_date(ph, int(y.group(0))) if y else None
            if d is not None and (d.month, d.day) == (key.month, key.day):
                return d
    st = ts_of(m.get("startDate") or m.get("createdAt"))
    if st is None:
        return None
    s0 = datetime.fromtimestamp(st - 86400, timezone.utc).date()
    for y in (s0.year, s0.year + 1, s0.year + 2):
        try:
            d = date(y, key.month, key.day)
        except ValueError:
            continue
        if d >= s0:
            return d
    return None


def year_ok(bundle: dict, rich: str, cheap: str, g: dict[str, dict]) -> bool:
    a, b = g.get(rich), g.get(cheap)
    if not a or not b:
        return False
    da_, db_ = deadline(a, rung_key("date", bundle, rich)), deadline(b, rung_key("date", bundle, cheap))
    return bool(da_ is not None and db_ is not None and da_ < db_)


def nested(kind: str, bundle: dict, rich: str, cheap: str, g: dict[str, dict], order_check: bool = True) -> tuple[bool, str]:
    a, b = g.get(rich), g.get(cheap)
    if not a or not b:
        return False, "no gamma record"
    if order_check and kind == "date":
        da_, db_ = deadline(a, rung_key(kind, bundle, rich)), deadline(b, rung_key(kind, bundle, cheap))
        if da_ is None or db_ is None or not da_ < db_:
            return False, "rung order wrong once each deadline's year is re-derived"
    sp = date_spellings if kind == "date" else level_spellings
    da = mask(a.get("description") or "", sp(rung_key(kind, bundle, rich)), "@k@")
    db = mask(b.get("description") or "", sp(rung_key(kind, bundle, cheap)), "@k@")
    if not da or not db:
        return False, "empty description"
    if da != db:
        return False, "descriptions differ"
    sa = norm(a.get("resolutionSource") or a.get("_event_resolutionSource"))
    sb = norm(b.get("resolutionSource") or b.get("_event_resolutionSource"))
    if sa != sb:
        return False, "sources differ"
    if re.search(r"market(?:'s|’s)? creation|market (?:was|is) created|creation of (?:this|the) market", da):
        ta, tb = ts_of(a.get("startDate") or a.get("createdAt")), ts_of(b.get("startDate") or b.get("createdAt"))
        if ta is None or tb is None or tb > ta + cfg.CREATION_TOLERANCE_S:
            return False, "window starts at creation and the cheap rung was created later"
    return True, "nested"


def texts(ids: list[str]) -> dict[str, dict]:
    from .net import CACHE, GATE
    path = CACHE / "texts"
    path.mkdir(parents=True, exist_ok=True)
    out, need = {}, []
    for i in ids:
        f = path / f"{i}.json"
        if f.exists():
            out[i] = json.loads(f.read_text())
        else:
            need.append(i)
    GATE.kind = "texts"
    for closed in ("true", "false"):
        need = [i for i in need if i not in out]
        for a in range(0, len(need), cfg.TEXT_BATCH):
            chunk = need[a:a + cfg.TEXT_BATCH]
            d = ds.get_json(f"{ds.GAMMA}/markets", [("id", x) for x in chunk] + [("closed", closed), ("limit", 100)], throttle=GATE, allow=(400, 422))
            for m in d if isinstance(d, list) else []:
                rec = {k: m.get(k) for k in TEXT_FIELDS}
                rec["id"] = str(rec["id"])
                rec["_event_resolutionSource"] = ((m.get("events") or [{}])[0] or {}).get("resolutionSource") or ""
                (path / f"{rec['id']}.json").write_text(json.dumps(rec))
                out[rec["id"]] = rec
    return out
