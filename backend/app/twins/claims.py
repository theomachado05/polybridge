from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

STOPWORDS = frozenset("""will the a an of in on by before after at to be is are was were or and for any than with this
that from as it its who what which how does do did has have if then there their during within least most into over
under up down above below more less higher lower""".split())

UP_WORDS = ("at or above", "or above", "or more", "or higher", "at least", "greater than or equal", "above", "over",
            "exceed", "exceeds", "more than", "greater than", "higher than", "increase", "increases", "raise",
            "raises", "hike", "hikes", "rise", "rises", "rises above", "surpass", "surpasses")
DOWN_WORDS = ("at or below", "or below", "or less", "or lower", "at most", "less than or equal", "below", "under",
              "less than", "fewer than", "lower than", "decrease", "decreases", "cut", "cuts", "drop", "drops",
              "fall", "falls", "decline", "declines")
FLAT_WORDS = ("no change", "unchanged", "maintain", "maintains", "holds steady", "no cut", "no hike")
INCLUSIVE = ("at or above", "or above", "or more", "or higher", "at least", "greater than or equal", "at or below",
             "or below", "or less", "or lower", "at most", "less than or equal")

NEG_WORDS = frozenset({"not", "no", "never", "without", "neither", "nor", "fail", "fails"})

SOURCE_PATTERNS: dict[str, re.Pattern] = {k: re.compile(v, re.I) for k, v in {
    "bls": r"bureau of labor statistics|\bbls\b",
    "bea": r"bureau of economic analysis|\bbea\b",
    "fed": r"federal open market committee|federal reserve|\bfomc\b",
    "binance": r"binance",
    "coinbase": r"coinbase",
    "coingecko": r"coingecko",
    "cfb": r"cf benchmarks|\bbrti\b|\bcf [a-z]+ real[- ]time index",
    "yahoo": r"yahoo finance",
    "ap": r"associated press|\bthe ap\b|\bap\b",
    "nhc": r"national hurricane center",
    "noaa": r"noaa|national weather service|\bnws\b",
    "fec": r"federal election commission|\bfec\b",
    "congress": r"congress\.gov",
    "treasury": r"u\.?s\.? department of the treasury|treasury\.gov",
    "eia": r"energy information administration|\beia\b",
    "aaa": r"\baaa\b",
    "spglobal": r"s&p dow jones|spglobal|s&p global",
    "nasdaq_src": r"nasdaq\.com|nasdaq omx",
    "census": r"census bureau",
    "bloomberg": r"bloomberg",
    "reuters": r"reuters",
    "who": r"world health organization",
}.items()}

PRICE_WORDS = frozenset({"bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "dogecoin", "doge", "price",
                         "close", "closes", "closing", "s&p", "nasdaq", "dow", "gold", "silver", "oil", "crude",
                         "wti", "brent", "spx", "index", "settle", "settles"})

SENTENCE_STARTERS = frozenset({"will", "who", "what", "which", "how", "does", "do", "is", "are", "when", "where",
                               "can", "could", "should", "would", "the", "a", "an", "if", "in", "by", "on", "at"})

_SYN = {"democratic": "dem", "democrat": "dem", "democrats": "dem", "republican": "rep", "republicans": "rep",
        "gop": "rep", "u.s.": "us", "u.s": "us", "usa": "us", "america": "us", "american": "us", "u.s.a.": "us",
        "rates": "rate", "elections": "election", "senators": "senate", "midterms": "midterm", "bps": "bp",
        "federal": "fed", "reserve": "reserve", "presidency": "president", "presidential": "president"}

_DATE_FULL = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.I)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_YEAR = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{4})\b", re.I)
_NUM = re.compile(r"(?<![\w.])(\$)?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(%|(?:percent|bp|bps|basis points?|"
                  r"k|m|mm|b|bn|million|billion|thousand|trillion|t)\b)?", re.I)
_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
         "t": 1e12, "trillion": 1e12}


@dataclass(frozen=True)
class Claim:
    venue: str
    id: str
    question: str
    rules: str
    deadline: date | None
    ref: dict = field(default_factory=dict)
    tokens: frozenset[str] = frozenset()
    entities: frozenset[str] = frozenset()
    numbers: frozenset[tuple[float, str]] = frozenset()
    years: frozenset[int] = frozenset()
    dates: frozenset[date] = frozenset()
    periods: frozenset[tuple[int, int]] = frozenset()
    directions: frozenset[str] = frozenset()
    inclusive: bool | None = None
    negated: bool = False
    sources: frozenset[str] = frozenset()
    price_like: bool = False
    clock: frozenset[str] = frozenset()
    rules_tokens: frozenset[str] = frozenset()
    cond_entities: frozenset[str] = frozenset()


def _num(x) -> float | None:
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def _et_date(ts: str | None) -> date | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return d.date()
    return d.astimezone(ET).date()


def _phrase_regex(words: tuple[str, ...]) -> re.Pattern:
    alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![\w])(?:{alt})(?![\w])", re.I)


_UP, _DOWN, _FLAT, _INCL = (_phrase_regex(UP_WORDS), _phrase_regex(DOWN_WORDS), _phrase_regex(FLAT_WORDS),
                            _phrase_regex(INCLUSIVE))


def extract_dates(text: str, default_year: int | None = None) -> tuple[set[date], set[tuple[int, int]], str]:
    dates: set[date] = set()
    periods: set[tuple[int, int]] = set()

    def full(m: re.Match) -> str:
        mon = MONTHS.get(m.group(1).lower().rstrip("."))
        yr = int(m.group(3)) if m.group(3) else default_year
        if mon and yr:
            try:
                dates.add(date(yr, mon, int(m.group(2))))
            except ValueError:
                pass
        return " "

    def iso(m: re.Match) -> str:
        try:
            dates.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
        return " "

    def month_year(m: re.Match) -> str:
        mon = MONTHS.get(m.group(1).lower().rstrip("."))
        if mon:
            periods.add((int(m.group(2)), mon))
        return " "

    t = _DATE_ISO.sub(iso, text)
    t = _DATE_FULL.sub(full, t)
    t = _MONTH_YEAR.sub(month_year, t)
    return dates, periods, t


def extract_numbers(text: str) -> tuple[set[tuple[float, str]], set[int]]:
    nums: set[tuple[float, str]] = set()
    years: set[int] = set()
    for m in _NUM.finditer(text):
        raw = m.group(2).replace(",", "")
        v = float(raw)
        suf = (m.group(3) or "").lower()
        cur = bool(m.group(1))
        if not suf and not cur and re.fullmatch(r"(19|20|21)\d\d", raw):
            years.add(int(raw))
            continue
        unit = ""
        if suf in ("%", "percent"):
            unit = "%"
        elif suf.startswith("b") and suf in ("bp", "bps", "basis point", "basis points"):
            unit = "bp"
        elif suf in _MULT:
            v *= _MULT[suf]
        if cur and not unit:
            unit = "$"
        nums.add((round(v, 9), unit))
    return nums, years


def stem(w: str) -> str:
    for suf in ("ement", "ment", "ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf) and not (suf == "s" and w.endswith("ss")):
            w = w[: -len(suf)]
            break
    return w[:-1] if len(w) > 4 and w.endswith("e") else w


def _canon_phrases(text: str) -> str:
    return re.sub(r"\bfederal reserve(?: board| system)?\b", "Fed", text, flags=re.I)


def _tokens(text: str) -> set[str]:
    t = _canon_phrases(text).lower().replace("’", "'")
    t = re.sub(r"\bu\.s\.a?\.?", "us", t)
    t = re.sub(r"'s\b", "", t)
    out = set()
    for w in re.findall(r"[a-z][a-z0-9&\-']*", t):
        w = w.strip("-'")
        w = _SYN.get(w, w)
        if len(w) < 2 or w in STOPWORDS or w in MONTHS:
            continue
        out.add(stem(w))
    return out


def _entities(question: str) -> set[str]:
    out = set()
    words = re.findall(r"[A-Za-z][A-Za-z0-9&.\-']*", _canon_phrases(question))
    for i, w in enumerate(words):
        w = w.rstrip(".")
        if not w or not (w[0].isupper() or w.isupper()):
            continue
        lw = w.lower().replace("'s", "")
        if lw in SENTENCE_STARTERS and i == 0:
            continue
        if lw in MONTHS or lw in STOPWORDS:
            continue
        out.add(stem(_SYN.get(lw, lw)))
    return out


_GENERIC_CAPS = frozenset({"this", "market", "yes", "no", "otherwise", "if", "for", "the", "et", "est", "edt", "us",
                           "utc", "pm", "am", "resolution", "contract", "issuance", "each", "any", "an", "a", "in",
                           "on", "at", "by", "after", "before", "only", "note", "tie", "ties"})


def _cond_entities(text: str) -> set[str]:
    text = re.sub(r"\bU\.S\.A?\.?", "US", _canon_phrases(text))
    m = re.search(r"(?<=[a-z0-9\"”)])\.\s+(?=[A-Z])|\n", text)
    words = re.findall(r"[A-Za-z][A-Za-z0-9&\-']*|\S", text[: m.start()] if m else text)
    out = set()
    for i, w in enumerate(words):
        if not w[0].isalpha() or not (w[0].isupper() or w.isupper()) or i == 0:
            continue
        lw = w.lower().replace("'s", "")
        if lw in _GENERIC_CAPS or lw in STOPWORDS or lw in MONTHS or len(lw) < 3:
            continue
        run = ((i > 0 and words[i - 1][:1].isupper() and words[i - 1].lower() not in _GENERIC_CAPS)
               or (i + 1 < len(words) and words[i + 1][:1].isupper() and words[i + 1].lower() not in _GENERIC_CAPS))
        if run and not w.isupper():
            continue
        out.add(stem(_SYN.get(lw, lw)))
    return out


def _direction(question: str, strike_type: str | None = None) -> tuple[set[str], bool | None]:
    dirs: set[str] = set()
    inclusive: bool | None = None
    if _UP.search(question):
        dirs.add("up")
    if _DOWN.search(question):
        dirs.add("down")
    if _FLAT.search(question):
        dirs.add("flat")
    if _INCL.search(question):
        inclusive = True
    elif dirs & {"up", "down"}:
        inclusive = False
    if re.search(r"\bbetween\b", question, re.I):
        dirs.add("between")
    st = (strike_type or "").lower()
    if st:
        table = {"greater": ({"up"}, False), "greater_or_equal": ({"up"}, True), "less": ({"down"}, False),
                 "less_or_equal": ({"down"}, True), "between": ({"between"}, None), "functional": (set(), None),
                 "custom": (set(), None), "structured": (set(), None)}
        if st in table and (table[st][0] or not dirs):
            d, inc = table[st]
            if d:
                dirs, inclusive = set(d), inc
    return dirs, inclusive


_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*\(?(?:et|est|edt|eastern)\b", re.I)


def clock_times(text: str) -> set[str]:
    out = set()
    for m in _CLOCK.finditer(text):
        h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
        if m.group(3).lower() == "p":
            h += 12
        if h < 24 and mi < 60 and (h, mi) != (23, 59):
            out.add(f"{h:02d}:{mi:02d}")
    return out


def _sources(text: str) -> set[str]:
    return {k for k, p in SOURCE_PATTERNS.items() if p.search(text)}


def _build(venue: str, id_: str, question: str, rules: str, deadline: date | None, ref: dict,
           strike_type: str | None = None, extra_numbers: set[tuple[float, str]] | None = None) -> Claim:
    default_year = deadline.year if deadline else None
    dates, periods, rest = extract_dates(question, default_year)
    nums, years = extract_numbers(rest)
    nums |= extra_numbers or set()
    dirs, inclusive = _direction(question, strike_type)
    spelled = re.sub(r"[≥]|>=", " gte ", rest)
    spelled = re.sub(r"[≤]|<=", " lte ", spelled)
    spelled = re.sub(r">", " gt ", spelled)
    spelled = re.sub(r"<", " lt ", spelled)
    q_tokens = _tokens(spelled)
    dir_vocab = {stem(w) for ws in (UP_WORDS, DOWN_WORDS, FLAT_WORDS, INCLUSIVE) for p in ws for w in p.split()}
    q_tokens = {t for t in q_tokens if t not in dir_vocab and t not in NEG_WORDS} | {str(y) for y in years}
    neg = bool(set(re.findall(r"[a-z]+", question.lower())) & NEG_WORDS) and "flat" not in dirs
    if "flat" in dirs:
        neg = bool(set(re.findall(r"[a-z]+", _FLAT.sub(" ", question).lower())) & NEG_WORDS)
    ents = {e for e in _entities(question) if e not in dir_vocab}
    r_tokens = _tokens(rules[:1500])
    price_like = bool({t for t in re.findall(r"[a-z&]+", question.lower())} & PRICE_WORDS)
    return Claim(venue=venue, id=id_, question=question.strip(), rules=rules, deadline=deadline, ref=ref,
                 tokens=frozenset(q_tokens), entities=frozenset(ents), numbers=frozenset(nums),
                 years=frozenset(years), dates=frozenset(dates), periods=frozenset(periods),
                 directions=frozenset(dirs), inclusive=inclusive, negated=neg, sources=frozenset(_sources(rules)), clock=frozenset(clock_times(rules)),
                 price_like=price_like, rules_tokens=frozenset(r_tokens),
                 cond_entities=frozenset(e for e in _cond_entities(rules[:350]) if e not in dir_vocab))


def from_polymarket(m: dict) -> Claim | None:
    q = (m.get("question") or "").strip()
    if not q or m.get("id") is None:
        return None
    desc = m.get("description") or ""
    rules = f"{desc} {m.get('resolutionSource') or ''}"
    ref = {"id": str(m["id"]), "token_id": m.get("token_id"), "question": q, "end_date": m.get("endDate"),
           "slug": m.get("slug"), "event_slug": m.get("event_slug")}
    return _build("polymarket", str(m["id"]), q, rules, _et_date(m.get("endDate")), ref)


def from_kalshi(m: dict) -> Claim | None:
    tk = m.get("ticker")
    title = (m.get("title") or "").strip()
    if not tk or not title:
        return None
    sub = (m.get("yes_sub_title") or "").strip()
    st = (m.get("strike_type") or "").lower()
    question = title if not sub or sub.lower() in title.lower() else f"{title} {sub}"
    rules = f"{m.get('rules_primary') or ''} {m.get('rules_secondary') or ''}"
    close = _et_date(m.get("close_time"))
    extra: set[tuple[float, str]] = set()
    for k in ("floor_strike", "cap_strike"):
        v = _num(m.get(k))
        if v is not None:
            extra.add((round(v, 9), ""))
    ref = {"ticker": tk, "event_ticker": m.get("event_ticker"), "question": question, "close_time": m.get("close_time"),
           "category": m.get("category")}
    c = _build("kalshi", tk, question, rules, close, ref, strike_type=st or None)
    if extra and not c.numbers:
        c = _replace(c, numbers=frozenset(extra))
    return c


def _replace(c: Claim, **kw) -> Claim:
    from dataclasses import replace
    return replace(c, **kw)


def days_between(a: date, b: date) -> int:
    return abs((a - b).days)
