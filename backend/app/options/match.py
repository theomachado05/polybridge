from __future__ import annotations

import calendar
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _NY: dt.tzinfo = ZoneInfo("America/New_York")
except Exception:
    _NY = dt.timezone(dt.timedelta(hours=-5))
YEAR_SLACK_DAYS = 3

DATA = Path(__file__).resolve().parent.parent / "data"

AMBIGUOUS = {"PM", "NOW", "LOW", "SO", "DE", "MA", "MO", "CAT", "DIS", "MET", "LIN", "ALL", "ET", "ON", "IT", "A"}
ALIASES = {"Google": "GOOGL", "Facebook": "META", "Berkshire": "BRK.B", "Exxon": "XOM", "Coca Cola": "KO",
           "JP Morgan": "JPM", "Lilly": "LLY", "Walt Disney": "DIS", "Microsoft Corp": "MSFT"}
ETFS = {"SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF", "XLE", "USO", "KRE", "XLK", "SMH", "ARKK"}

INDEXES: list[tuple[str, str, float, tuple[str, float] | None, str]] = [
    (r"s\s*&\s*p\s*500|s&p500|\bsp\s*500\b|\bspx\b|\bs\s*&\s*p\b", "I:SPX", 1.0, ("SPY", 0.1), "S&P 500"),
    (r"nasdaq[\s-]*100|\bndx\b", "I:NDX", 1.0, None, "Nasdaq-100"),
    (r"russell\s*2000|\brut\b", "I:RUT", 1.0, ("IWM", 0.1), "Russell 2000"),
    (r"\bdow jones\b|\bdjia\b|\bthe dow\b", "DIA", 0.01, None, "Dow Jones"),
]

REFUSE = [
    (r"\b(hit|hits|reach|reaches|reached|touch|touches|dip|dips|drop to|fall to|falls to|rise to|rises to|"
     r"all[- ]time high|ath|at any (point|time)|intraday)\b", "path question (touch probability, not terminal)"),
    (r"\b(fall|falls|fell|falling|drop|drops|dropped|dropping|sink|sinks|sank|sinking|plunge|plunges|plunged|"
     r"crash|crashes|crashed|tumble|tumbles|slide|slides|slip|slips|rise|rises|rose|rising|climb|climbs|climbed|"
     r"climbing|jump|jumps|jumped|surge|surges|surged|soar|soars|soared|rally|rallies|spike|spikes|break|breaks|"
     r"broke|cross|crosses|crossed|go|goes|went|move|moves|moved)\s+(above|below|over|under|past|through|beneath)\b",
     "path question (movement verb: touch probability, not terminal)"),
    (r"\bbetween\b|\$?\d[\d,]*(?:\.\d+)?k?\s+(?:to|and)\s+\$?\d|\$\d[\d,]*(?:\.\d+)?\s*[-\u2013]\s*\$?\d",
     "range question"),
    (r"%|\bpercent\b|\bbps\b|\bbasis points\b", "percent / rate question"),
    (r"market cap|\bmarket value\b|\bfdv\b|\bvaluation\b|\btrillion\b|\bbillion\b", "market-cap question"),
    (r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|dogecoin|doge|crypto)\b", "crypto has no listed equity options here"),
    (r"\b(cpi|inflation|gdp|unemployment|fed funds|interest rate|yield|mortgage)\b", "macro print, not a price level"),
]

_CMP_ABOVE = r"(?:close|closes|closing|finish|finishes|end|ends|settle|settles|be|trade|trades|stay|stays)?\s*" \
             r"(?:at or above|at least|above|over|higher than|greater than|more than|>=|>)"
_CMP_BELOW = r"(?:close|closes|closing|finish|finishes|end|ends|settle|settles|be|trade|trades|stay|stays)?\s*" \
             r"(?:at or below|at most|below|under|lower than|less than|<=|<)"
_NUM = r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k\b)?"
_LEVEL_NOISE = r"(?:a\s+)?(?:(?:share\s+)?price\s+of\s+|level\s+of\s+|the\s+)?"

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|" \
       r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


@dataclass
class Match:
    underlying: str
    strike: float
    expiry: dt.date
    direction: str = "above"
    scale: float = 1.0
    level: float = 0.0
    label: str = ""
    fallback: tuple[str, float] | None = None
    approx: bool = False
    date_source: str = "question"
    notes: list[str] = field(default_factory=list)

    def __iter__(self):
        return iter((self.underlying, self.strike, self.expiry))

    def to_dict(self) -> dict:
        return {"underlying": self.underlying, "strike": self.strike, "expiry": self.expiry.isoformat(),
                "direction": self.direction, "scale": self.scale, "level": self.level, "label": self.label,
                "fallback": list(self.fallback) if self.fallback else None, "approx": self.approx,
                "date_source": self.date_source, "notes": list(self.notes)}


_NAMES: dict[str, str] | None = None


def names(data_dir: Path = DATA) -> dict[str, str]:
    global _NAMES
    if _NAMES is None:
        try:
            _NAMES = {str(k).upper(): str(v) for k, v in json.loads((data_dir / "names.json").read_text()).items()}
        except (OSError, ValueError):
            _NAMES = {}
    return _NAMES


def why_unsupported(question: str) -> str | None:
    q = (question or "").lower()
    for pat, why in REFUSE:
        if re.search(pat, q):
            return why
    return None


def _underlyings(question: str) -> list[tuple[str, float, tuple[str, float] | None, str]]:
    found: dict[str, tuple[str, float, tuple[str, float] | None, str]] = {}
    low = question.lower()
    for pat, u, scale, fb, label in INDEXES:
        if re.search(pat, low):
            found[u] = (u, scale, fb, label)
            break
    nm = names()
    tickers = set(nm) | ETFS
    for m in re.finditer(r"(\$|\()?\b([A-Z]{1,5}(?:\.[A-Z])?)\b(\))?", question):
        tk = m.group(2)
        marked = bool(m.group(1)) or bool(m.group(3))
        if tk in tickers and (marked or (len(tk) >= 2 and tk not in AMBIGUOUS)):
            found.setdefault(tk, (tk, 1.0, None, nm.get(tk, tk)))
    for name, tk in [(v, k) for k, v in nm.items()] + list(ALIASES.items()):
        if len(name) < 3 or (tk not in nm and tk not in ETFS):
            continue
        for m in re.finditer(r"\b" + re.escape(name) + r"(?:'s)?(?![\w&])", question, re.IGNORECASE):
            if m.group(0)[0].isupper() or m.group(0)[0].isdigit():
                found.setdefault(tk, (tk, 1.0, None, nm.get(tk, name)))
                break
    if "I:SPX" in found:
        found.pop("SPY", None)
    return list(found.values())


_POST_ABOVE = r"\s+or\s+(?:above|more|higher|greater)\b"
_POST_BELOW = r"\s+or\s+(?:below|less|lower|fewer)\b"


def _level(question: str) -> tuple[str, float] | None:
    low = question.lower()
    hits = []
    for direction, cmp in (("above", _CMP_ABOVE), ("below", _CMP_BELOW)):
        for m in re.finditer(cmp + r"\s+" + _LEVEL_NOISE + _NUM, low):
            tail = low[m.end():m.end() + 12]
            if re.match(r"\s*(%|percent|bps|b\b|bn|billion|t\b|trillion|m\b|million)", tail):
                continue
            v = float(m.group(1).replace(",", "")) * (1000.0 if m.group(2) else 1.0)
            if v > 0:
                hits.append((direction, v))
    for direction, post in (("above", _POST_ABOVE), ("below", _POST_BELOW)):
        for m in re.finditer(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(k\b)?" + post, low):
            v = float(m.group(1).replace(",", "")) * (1000.0 if m.group(2) else 1.0)
            if v > 0:
                hits.append((direction, v))
    uniq = set(hits)
    return hits[0] if len(uniq) == 1 else None


def _safe_date(y: int, month: int, day: int) -> dt.date:
    return dt.date(y, month, min(day, calendar.monthrange(y, month)[1]))


def _year_for(month: int, day: int, resolution: dt.date | None, as_of: dt.date) -> int:
    if resolution is not None:
        cap = resolution + dt.timedelta(days=YEAR_SLACK_DAYS)
        y = cap.year
        return y if _safe_date(y, month, day) <= cap else y - 1
    y = as_of.year
    return y if _safe_date(y, month, day) >= as_of else y + 1


def _date(question: str, resolution: dt.date | None, as_of: dt.date) -> dt.date | None:
    low = question.lower()
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", low)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\bend of " + _MON + r"\b(?:,?\s*(20\d\d))?", low)
    if m:
        mon = MONTHS[m.group(1)[:4] if m.group(1).startswith("sept") else m.group(1)[:3]]
        y = int(m.group(2)) if m.group(2) else _year_for(mon, 31, resolution, as_of)
        return dt.date(y, mon, calendar.monthrange(y, mon)[1])
    m = re.search(r"\b" + _MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(20\d\d))?", low)
    if m:
        mon = MONTHS[m.group(1)[:4] if m.group(1).startswith("sept") else m.group(1)[:3]]
        d = int(m.group(2))
        y = int(m.group(3)) if m.group(3) else _year_for(mon, d, resolution, as_of)
        try:
            return dt.date(y, mon, d)
        except ValueError:
            return None
    m = re.search(r"\b(?:end of|by the end of|year[- ]end)\s*(?:the\s+)?(?:year\s*)?(20\d\d)?\b", low)
    if m and ("year" in m.group(0) or m.group(1)):
        y = int(m.group(1)) if m.group(1) else (_year_for(12, 31, resolution, as_of) if resolution else as_of.year)
        return dt.date(y, 12, 31)
    m = re.search(r"\b(?:in|by|for|end of|finish|finishes|close|closes|end|ends)\s+(20\d\d)\b", low)
    if m:
        return dt.date(int(m.group(1)), 12, 31)
    return None


def _to_date(x) -> dt.date | None:
    if x is None or x == "":
        return None
    if isinstance(x, str) and len(x.strip()) > 10:
        try:
            x = dt.datetime.fromisoformat(x.strip().replace("Z", "+00:00"))
        except ValueError:
            pass
    if isinstance(x, dt.datetime):
        return (x.astimezone(_NY) if x.tzinfo is not None else x).date()
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def match_question(question: str, resolution_date=None, as_of=None) -> Match | None:
    if not question or not isinstance(question, str):
        return None
    if why_unsupported(question):
        return None
    unders = _underlyings(question)
    if len(unders) != 1:
        return None
    lv = _level(question)
    if lv is None:
        return None
    as_of_d = _to_date(as_of) or dt.date.today()
    res = _to_date(resolution_date)
    when = _date(question, res, as_of_d)
    src = "question"
    if when is None:
        when, src = res, "resolution_date"
    if when is None or when < as_of_d:
        return None
    u, scale, fb, label = unders[0]
    direction, level = lv
    m = Match(underlying=u, strike=round(level * scale, 6), expiry=when, direction=direction, scale=scale,
              level=level, label=label, fallback=fb, approx=scale != 1.0, date_source=src)
    if scale != 1.0:
        m.notes.append(f"{label} level {level:g} mapped to {u} strike {m.strike:g} (approximate scaling)")
    return m


def why_no_match(question: str, resolution_date=None, as_of=None) -> str:
    if not question:
        return "no question text"
    w = why_unsupported(question)
    if w:
        return w
    n = len(_underlyings(question))
    if n == 0:
        return "no listed underlying named"
    if n > 1:
        return "more than one candidate underlying"
    if _level(question) is None:
        return "no single numeric threshold with above/below"
    return "no resolution date (or it has passed)"
