from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone

from ladder_replay import replay as lr
from s11_bundles import config as s11cfg
from s11_bundles.universe import date_template, parse_date
from s21_options_anchor import engine as s21

AS_OF = "2026-10-02"
TODAY = "2026-10-04"
TRUST_SCORE = 0.5

TYPES = ("ladder_rung", "touch_ticket", "close_above_ticket", "other")
NOT_STOCK_RE = (r"\bbitcoin\b|\bbtc\b|\bethereum\b|\beth\b|\bsolana\b|\bxrp\b|\bdogecoin\b|\bcrude\b|\boil\b|\bgold\b|"
                r"\bsilver\b|\bnatural gas\b|\bdollar index\b|\bnasdaq\b|\bdow jones\b|\brussell\b|\bnyse\b|\bnikkei\b|"
                r"\bhang seng\b|\bftse\b|\bdax\b")
NOT_STOCK = {"XAUUSD", "XAGUSD", "WTI", "CL", "GC", "SI", "NG", "DXY", "QQQ", "NDX", "DJIA", "RUT", "NYA", "NIK", "HSI", "UKX",
             "DAX", "BTC", "ETH", "SOL", "XRP", "DOGE", "HIGH", "LOW"}
NAMES = {"nvidia": "NVDA", "tesla": "TSLA", "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN", "alphabet": "GOOGL",
         "google": "GOOGL", "meta": "META", "netflix": "NFLX", "palantir": "PLTR", "robinhood": "HOOD", "opendoor": "OPEN",
         "rocket lab": "RKLB", "coinbase": "COIN", "microstrategy": "MSTR", "amd": "AMD", "broadcom": "AVGO"}
BTC_15M_RE = r"(bitcoin|\bbtc\b).{0,40}(up or down|15[- ]?min)|(up or down|15[- ]?min).{0,40}(bitcoin|\bbtc\b)"
SYMBOL_RE = re.compile(r"\(([A-Z]{1,5})\)")
TOUCH_RE = re.compile(r"\b(reach(?:es)?|hits?|touch(?:es)?|dips?\s+to|falls?\s+to|drops?\s+to)\s+(?:\((HIGH|LOW)\)\s+)?"
                      r"(\$\s?)?([\d,]+(?:\.\d+)?)\b", re.I)
CLOSE_RE = re.compile(r"\b(?:close|finish|settle)s?\s+(?:the\s+day\s+)?(at\s+or\s+above|at\s+or\s+below|above|over|higher\s+than|"
                      r"below|under|lower\s+than)\s+\$\s?([\d,]+(?:\.\d+)?)", re.I)


def _price(m: dict) -> float | None:
    for k in ("underlying_price", "last_price", "price"):
        try:
            v = float(m.get(k))
        except (TypeError, ValueError):
            continue
        if v > 0 and v == v and v != float("inf"):
            return v
    return None


def _check(name: str, ok: bool, detail: str = "") -> dict:
    return {"check": name, "ok": bool(ok), "detail": detail}


def _ts(m: dict) -> float | None:
    return lr.ts_of(m.get("startDate") or m.get("createdAt"))


def created_on(m: dict) -> date | None:
    t = _ts(m)
    return datetime.fromtimestamp(t, timezone.utc).date() if t is not None else None


def _universe() -> dict[str, str]:
    from pathlib import Path
    here = Path(__file__).resolve().parent
    out: dict[str, str] = {}
    for f in (here / "instruments.json", here.parents[1] / "backend" / "app" / "data" / "names.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if isinstance(d, list):
            d = {str(x.get("ticker") or x.get("symbol") or ""): str(x.get("name") or "") for x in d if isinstance(x, dict)}
        if isinstance(d, dict):
            out.update({str(k).upper(): str(v or "") for k, v in d.items() if k})
        break
    for k, v in NAMES.items():
        out.setdefault(v, k.title())
    out.setdefault("SPY", "SPDR S&P 500 ETF")
    out.setdefault("SPX", "S&P 500 index")
    return {k: v for k, v in out.items() if k not in NOT_STOCK}


UNIVERSE = _universe()
BARE_STOP = {"A", "I", "ALL", "ON", "IT", "ARE", "BE", "SO", "NOW", "ONE", "CEO", "AI", "US", "USA", "ETF", "IPO", "GDP",
             "FED", "CPI", "ET", "PM", "AM", "EOD", "YES", "NO", "BY", "OR", "AND", "THE", "TO", "IN", "AT", "OF"}
CASHTAG_RE = re.compile(r"(?<![\w$])\$([A-Z]{1,5}(?:\.[A-Z])?)\b(?![\d,.]*\d)")
BARE_RE = re.compile(r"(?<![\w$&.])([A-Z]{2,5}(?:\.[A-Z])?)(?![\w&])")
_NAME_TO_TICKER: dict[str, set[str]] = {}
for _tk, _nm in UNIVERSE.items():
    if _nm and len(_nm) >= 3 and _nm.upper() != _tk:
        _NAME_TO_TICKER.setdefault(_nm, set()).add(_tk)


def _symbols_in(text: str) -> list[str]:
    out = [x for x in SYMBOL_RE.findall(text or "") if x not in ("HIGH", "LOW")]
    out += CASHTAG_RE.findall(text or "")
    out += [x for x in BARE_RE.findall(text or "") if x in UNIVERSE and x not in BARE_STOP]
    return list(dict.fromkeys(out))


def ticker_of(question: str, title: str = "") -> tuple[str | None, str]:
    t_sym = _symbols_in(title or "")
    q_sym = _symbols_in(question or "")
    if len(set(t_sym)) > 1:
        return None, "more than one ticker in the event title"
    if len(set(q_sym)) > 1 and not t_sym:
        return None, "more than one ticker in the question"
    if t_sym and q_sym and set(q_sym) != set(t_sym):
        return None, "the question's ticker and the event's ticker disagree"
    sym = (t_sym or q_sym or [None])[0]
    if sym is None:
        raw = f"{title} {question}"
        text = raw.lower()
        if "s&p 500" in text or "s&p500" in text:
            return None, "S&P 500 without (SPY) or (SPX): the level's underlying is ambiguous"
        hits = {v for k, v in NAMES.items() if re.search(rf"\b{re.escape(k)}\b", text)}
        hits |= {tk for nm, tks in _NAME_TO_TICKER.items() if re.search(rf"\b{re.escape(nm)}\b", raw) for tk in tks}
        if len(hits) != 1:
            return None, "no single stock ticker named"
        sym = hits.pop()
    if sym in NOT_STOCK:
        return None, f"{sym} is not a stock or the S&P 500"
    return sym, ""


def _year_date(phrase: str, m: dict) -> tuple[date | None, str]:
    key = parse_date(phrase, 2024)
    if key is None:
        return None, "date phrase does not parse"
    explicit = re.search(r"20\d\d", phrase)
    d = lr.deadline(m, key)
    if d is None:
        return None, "no creation date: the year cannot be re-derived"
    return d, "explicit year" if explicit else "re-derived from the creation date"


def _window_end(question: str, title: str, m: dict) -> tuple[date | None, str]:
    listed = created_on(m)
    for txt in (title, question):
        if not txt:
            continue
        t = re.sub(r"\s*\?\s*$", "", txt.strip())
        if listed is None and not re.search(r"\b20\d\d\b", t):
            continue
        d = s21.window_end(t, listed or date(2000, 1, 1))
        if d is not None:
            return d, "explicit year" if re.search(r"\b20\d\d\b", t) else "re-derived from the creation date"
    templ, phrase = date_template(question or "")
    if phrase and re.search(r"\b(?:by|before|on)\s+(?:the\s+)?@D@", templ, re.I):
        return _year_date(phrase, m)
    if listed is None:
        return None, "no window end with a year, and no creation date to re-derive it"
    return None, "no window end in the question or the event title"


def classify(question: str, rules: str | None = None, market: dict | None = None) -> dict:
    m = dict(market or {})
    q = (question or "").strip()
    m.setdefault("question", q)
    rules = rules if rules is not None else (m.get("description") or "")
    title = str(m.get("event_title") or "")
    src = m.get("resolutionSource") or m.get("_event_resolutionSource") or ""
    text = f"{title} {q}"
    if re.search(BTC_15M_RE, text, re.I):
        return {"type": "other", "mechanism": "btc_15m_watch", "fields": {"underlying": "BTC"}, "linkable": False,
                "checks": [_check("watch only", False, "15-minute Bitcoin markets are watched against spot, never traded")],
                "reasons": ["watch only: the gap to spot closes in under a minute"]}
    stockish = not re.search(NOT_STOCK_RE, text, re.I)
    close = CLOSE_RE.search(q) if stockish else None
    touch = TOUCH_RE.search(q) if stockish and not close else None
    if close or touch:
        ticker, why = ticker_of(q, title)
        checks = [_check("single stock or S&P 500 ticker", ticker is not None, why)]
        if close:
            word = close.group(1).lower()
            direction = "down" if re.search(r"below|under|lower", word) else "up"
            level = float(close.group(2).replace(",", ""))
            phrases = list(re.finditer(s11cfg.DATE_RE, q))
            end, year_src = _year_date(phrases[-1].group(0), m) if phrases else (None, "no close date in the question")
            kind, mech = "close_above_ticket", "close_above"
        else:
            verb, hl, dollar = touch.group(1).lower(), touch.group(2), touch.group(3)
            level = float(touch.group(4).replace(",", ""))
            up = verb.startswith("reach") or hl == "HIGH"
            down = bool(re.match(r"(dip|fall|drop)", verb)) or hl == "LOW"
            label, sign = str(m.get("label") or ""), int(m.get("sign") or 0)
            if up and down:
                direction = None
            elif up or down:
                direction = "up" if up else "down"
            elif "↑" in label or "↓" in label:
                direction = "up" if "↑" in label else "down"
            elif sign:
                direction = "up" if sign > 0 else "down"
            else:
                direction = None
            dir_src = "question wording, label arrow or sign" if direction else ""
            if direction is None and not (up and down):
                px = _price(m)
                if px is not None and level != px:
                    direction, dir_src = ("up" if level > px else "down"), f"inferred: level vs latest price {px:g}"
                else:
                    dir_src = "direction unknown: no direction word, label arrow, sign or latest price"
            if not dollar and level < 10:
                checks.append(_check("level is a price", False, "the number after the verb has no $ and is too small to be a price"))
            end, year_src = _window_end(q, title, m)
            kind, mech = "touch_ticket", "touch_ticket"
        if close:
            dir_src = "question wording"
        checks += [_check("direction up or down", direction is not None,
                          "" if direction else (dir_src or "direction unknown: no direction word, label arrow or sign")),
                   _check("window end with its year", end is not None, year_src if end is None else ""),
                   _check("year re-derived from the creation date or written out", end is not None and year_src != "", year_src)]
        fields = {"underlying": ticker, "level": level, "direction": direction, "window_end": end.isoformat() if end else None,
                  "end_session": s21.last_weekday(end).isoformat() if end else None, "year_source": year_src,
                  "direction_source": dir_src,
                  "option_root": None, "resolution_source": src or None}
        if ticker:
            fields["option_root"] = "O:SPXW" if ticker == "SPX" else f"O:{ticker}"
        bad = [c["detail"] or c["check"] for c in checks if not c["ok"]]
        if ticker is not None or close or (touch and touch.group(3)):
            return {"type": kind, "mechanism": mech, "fields": fields, "checks": checks, "linkable": not bad, "reasons": bad}
    templ, phrase = date_template(q)
    if phrase and re.search(s11cfg.CUMULATIVE_DATE_RE, templ, re.I):
        d, year_src = _year_date(phrase, m)
        event = str(m.get("event_id") or m.get("event_slug") or title or "")
        checks = [_check("rung date with its year re-derived (amendment 5)", d is not None, year_src if d is None else year_src),
                  _check("event known (a rung links only within its event)", bool(event), "" if event else "no event id, slug or title")]
        fields = {"ladder_id": f"{event}::{templ}" if event else None, "event": event or None, "template": templ, "date": d.isoformat() if d else None,
                  "date_phrase": phrase, "year_source": year_src, "resolution_source": src or None}
        bad = [c["detail"] or c["check"] for c in checks if not c["ok"]]
        return {"type": "ladder_rung", "mechanism": "ladder", "fields": fields, "checks": checks, "linkable": not bad, "reasons": bad}
    return {"type": "other", "mechanism": "none", "fields": {}, "linkable": False,
            "checks": [_check("tested mechanism", False, "no tested mechanism")], "reasons": ["no tested mechanism"]}


def registered_date(phrase: str, m: dict) -> date | None:
    end = date.fromisoformat(str(m.get("endDate") or "2026-12-31")[:10])
    d = parse_date(phrase, end.year)
    if d is not None and not re.search(r"20\d\d", phrase) and d > date.fromordinal(end.toordinal() + 7):
        d = parse_date(phrase, end.year - 1)
    return d


def link_ladders(markets: list[dict], event: dict | None = None) -> list[dict]:
    ev = dict(event or {})
    groups: dict[str, list[tuple[dict, dict]]] = {}
    unplaced = []
    for m in markets:
        mm = dict(m)
        mm.setdefault("event_title", ev.get("title"))
        mm.setdefault("event_id", ev.get("id") or ev.get("slug"))
        mm.setdefault("_event_resolutionSource", ev.get("resolutionSource") or "")
        c = classify(mm.get("question") or "", mm.get("description"), mm)
        if c["type"] != "ladder_rung":
            continue
        if not c["linkable"]:
            unplaced.append({"id": str(mm.get("id")), "question": mm.get("question"), "reasons": c["reasons"]})
            continue
        groups.setdefault(c["fields"]["ladder_id"], []).append((mm, c))
    out = []
    for lid, rungs in groups.items():
        rungs.sort(key=lambda x: (x[1]["fields"]["date"], str(x[0].get("id"))))
        dates = [c["fields"]["date"] for _, c in rungs]
        ladder = {"ladder_id": lid, "event": rungs[0][1]["fields"]["event"], "template": rungs[0][1]["fields"]["template"],
                  "rungs": [{"id": str(m.get("id")), "question": m.get("question"), "date": c["fields"]["date"],
                             "year_source": c["fields"]["year_source"],
                             "year_corrected": (registered_date(c["fields"]["date_phrase"], m) or date.min).isoformat() != c["fields"]["date"]}
                            for m, c in rungs],
                  "unplaced": unplaced, "pairs": [], "valid": True, "reasons": []}
        if len(rungs) < 2:
            ladder.update(valid=False, reasons=["fewer than two rungs"])
        elif len(set(dates)) != len(dates):
            ladder.update(valid=False, reasons=["two rungs on one date: not a clean ladder (S11 rule)"])
        g = {str(m.get("id")): m for m, _ in rungs}
        for (ma, ca), (mb, cb) in zip(rungs, rungs[1:]):
            ra, rb = str(ma.get("id")), str(mb.get("id"))
            checks = [_check("rich rung's deadline strictly earlier (amendment 5)", ca["fields"]["date"] < cb["fields"]["date"],
                             f"{ca['fields']['date']} vs {cb['fields']['date']}")]
            ok, why = lr.nested("date", {"legs": [ra, rb], "keys": [ca["fields"]["date"], cb["fields"]["date"]]}, ra, rb, g)
            checks.append(_check("same event definition and source; cheap rung not created after the window opens "
                                 "(step 1, amendments 2 and 4)", ok, why))
            bad = [c["detail"] for c in checks if not c["ok"]]
            ladder["pairs"].append({"rich": ra, "cheap": rb, "rich_date": ca["fields"]["date"], "cheap_date": cb["fields"]["date"],
                                    "nested": not bad, "checks": checks, "reasons": bad})
        out.append(ladder)
    return out


def end_dates() -> dict[str, tuple[str, bool]]:
    from s4_linked_assets import data as d4
    from s5_big_moves import run as r5

    from . import heldout as ho
    out: dict[str, tuple[str, bool]] = {}
    for m in json.loads((d4.CACHE / "pull_meta.json").read_text())["markets"]:
        out[m["market"]] = (str(m["end"])[:10], bool(m["closed"]))
    for f in (r5.HERE / "universe.json", ho.HERE / "universe.json"):
        for m in json.loads(f.read_text())["markets"]:
            out[m["id"]] = (str(m["end"])[:10], bool(m["closed"]))
    return out


def main() -> int:
    import pandas as pd

    from s4_linked_assets import data as d4

    from . import options as op
    from .benchmark import OUT

    b = pd.read_csv(OUT / "benchmark_scored.csv")
    h = pd.read_csv(OUT / "heldout_links.csv")
    df = pd.concat([b[["market", "question"]], h[["market", "question"]]], ignore_index=True).drop_duplicates("market")
    ends = end_dates()
    df["ends"] = df.market.map(lambda m: ends.get(m, ("", True))[0])
    df["resolved"] = df.market.map(lambda m: ends.get(m, ("", True))[1])
    live = df[(~df.resolved) & (df.ends >= TODAY)].copy()
    s, base = d4._massive_session()
    rows = []
    for r in live.itertuples():
        c = classify(r.question, None, {"id": r.market, "endDate": r.ends})
        link: dict = {}
        if c["type"] in ("touch_ticket", "close_above_ticket") and c["linkable"]:
            f = c["fields"]
            try:
                link = op.resolve_exact(s, base, f["underlying"], f["level"], f["direction"], f["window_end"])
            except Exception as e:
                link = {"ok": False, "reason": f"contract listing failed: {type(e).__name__}"}
        rows.append({"market": r.market, "question": r.question, "ends": r.ends, "type": c["type"], "mechanism": c["mechanism"],
                     "linkable": c["linkable"], "reasons": "; ".join(c["reasons"]), **{f"field_{k}": v for k, v in c["fields"].items()},
                     "contract_ok": bool(link.get("ok")), "contract_reason": link.get("reason", ""), "expiry": link.get("expiry", ""),
                     "lower_strike": link.get("lower_strike"), "upper_strike": link.get("upper_strike"),
                     "long_leg": link.get("long_leg", ""), "short_leg": link.get("short_leg", "")})
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "link_map.csv", index=False)
    summary = {"as_of": AS_OF, "open_questions": int(len(out)), "by_type": out.type.value_counts().to_dict() if len(out) else {},
               "tickets_with_exact_contracts": int(out.contract_ok.sum()) if len(out) else 0}
    (OUT / "link_map.json").write_text(json.dumps({"summary": summary, "links": json.loads(out.to_json(orient="records"))}, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
