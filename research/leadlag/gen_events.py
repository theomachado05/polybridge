from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

UTC = timezone.utc


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


RATE_ETFS = ["SPY", "QQQ", "IWM", "XLF", "TLT"]
BROAD = ["SPY", "QQQ", "IWM", "XLY", "XLF"]

FOMC = [
    ("fomc-2024-09-18", "2024-09-18 18:00", "fed-interest-rates-november-2024"),
    ("fomc-2024-11-07", "2024-11-07 19:00", "fed-interest-rates-december-2024"),
    ("fomc-2024-12-18", "2024-12-18 19:00", "fed-interest-rates-january-2025"),
    ("fomc-2025-01-29", "2025-01-29 19:00", "fed-decision-in-march"),
    ("fomc-2025-03-19", "2025-03-19 18:00", "fed-decision-in-may-2025"),
    ("fomc-2025-05-07", "2025-05-07 18:00", "fed-decision-in-june"),
    ("fomc-2025-06-18", "2025-06-18 18:00", "fed-decision-in-july"),
    ("fomc-2025-07-30", "2025-07-30 18:00", "fed-decision-in-september"),
    ("fomc-2025-09-17", "2025-09-17 18:00", "fed-decision-in-october"),
    ("fomc-2025-10-29", "2025-10-29 18:00", "fed-decision-in-december"),
    ("fomc-2025-12-10", "2025-12-10 19:00", "fed-decision-in-january"),
    ("fomc-2026-01-28", "2026-01-28 19:00", "fed-decision-in-march-885"),
    ("fomc-2026-03-18", "2026-03-18 18:00", "fed-decision-in-april"),
    ("fomc-2026-04-29", "2026-04-29 18:00", "fed-decision-in-june-825"),
    ("fomc-2026-06-17", "2026-06-17 18:00", "fed-decision-in-july-181"),
    ("fomc-2026-07-29", "2026-07-29 18:00", "fed-decision-in-september-762"),
    ("fomc-2026-09-16", "2026-09-16 18:00", "fed-decision-in-october-20260617190323537"),
]

events = []
for eid, anchor, slug in FOMC:
    a = ts(anchor)
    events.append(dict(
        id=eid, name=f"FOMC statement {a:%Y-%m-%d}", family="fomc", selection="scheduled",
        anchor_utc=fmt(a), window_start_utc=fmt(a - timedelta(minutes=60)), window_end_utc=fmt(a + timedelta(minutes=150)),
        pm=dict(event_slug=slug, match="no change"),
        expected_sign=-1,
        sign_rationale="P(no change at the next meeting) rising = fewer cuts expected = hawkish = bearish for equities",
        instruments=RATE_ETFS,
    ))


def cur(eid, name, anchor, start, end, pm, sign, why, instruments, family):
    events.append(dict(
        id=eid, name=name, family=family, selection="curated",
        anchor_utc=fmt(ts(anchor)) if anchor else None,
        window_start_utc=fmt(ts(start)), window_end_utc=fmt(ts(end)),
        pm=pm, expected_sign=sign, sign_rationale=why, instruments=instruments))


cur("jh-2024-08-23", "Powell Jackson Hole speech 2024", "2024-08-23 14:00", "2024-08-23 13:00", "2024-08-23 16:30",
    dict(event_slug="fed-interest-rates-september-2024", match="no change"), -1,
    "dovish guidance = P(no change) down = bullish", RATE_ETFS, "fed_speech")
cur("jh-2025-08-22", "Powell Jackson Hole speech 2025", "2025-08-22 14:00", "2025-08-22 13:00", "2025-08-22 16:30",
    dict(event_slug="fed-decision-in-september", match="no change"), -1,
    "dovish guidance = P(no change) down = bullish", RATE_ETFS, "fed_speech")
cur("crash-2024-08-05", "Global growth scare / yen carry unwind, US open", "2024-08-05 13:30", "2024-08-05 12:00", "2024-08-05 16:00",
    dict(market_slug="us-recession-in-2024-1"), -1,
    "recession odds up = bearish", ["SPY", "QQQ", "IWM", "XLF", "XLY"], "macro_stress")
cur("iran-2024-10-01", "Iran missile attack on Israel", None, "2024-10-01 14:00", "2024-10-01 21:00",
    dict(market_slug="iran-strike-on-israel-before-november"), -1,
    "escalation = risk-off", ["SPY", "QQQ", "XLE", "ITA", "GLD"], "geopolitics")
cur("election-2024-11-05", "2024 US election night (after-hours session only)", "2024-11-06 00:00", "2024-11-05 20:30", "2024-11-06 01:00",
    dict(market_slug="will-donald-trump-win-the-2024-us-presidential-election"), +1,
    "Trump win odds up = 'Trump trade' = bullish SPY/IWM/financials", ["SPY", "IWM", "QQQ", "XLF", "KRE"], "election")
cur("tiktok-2025-01-17", "SCOTUS upholds TikTok divest-or-ban law", "2025-01-17 15:00", "2025-01-17 14:00", "2025-01-17 18:00",
    dict(market_slug="tiktok-banned-in-the-us-before-may-2025"), +1,
    "ban odds up = bullish for the ad-share beneficiaries (META, SNAP, PINS)", ["META", "SNAP", "PINS", "QQQ", "SPY"], "policy_ruling")
cur("oval-2025-02-28", "Trump-Zelensky Oval Office meeting breaks down", "2025-02-28 16:00", "2025-02-28 15:00", "2025-02-28 19:00",
    dict(market_slug="russia-x-ukraine-ceasefire-in-2025"), -1,
    "ceasefire odds up = bearish for US defense names", ["ITA", "LMT", "RTX", "NOC", "SPY"], "geopolitics")
cur("tariff-2025-04-02", "Liberation Day tariff announcement (after-hours session)", "2025-04-02 20:00", "2025-04-02 19:00", "2025-04-03 00:00",
    dict(market_slug="us-recession-in-2025"), -1,
    "recession odds up = bearish", BROAD, "tariffs")
cur("tariff-2025-04-04", "China retaliation plus Powell remarks on tariffs", "2025-04-04 17:30", "2025-04-04 13:30", "2025-04-04 21:00",
    dict(market_slug="will-trump-lower-tariffs-on-china-in-april"), +1,
    "odds of tariff relief up = bullish", BROAD, "tariffs")
cur("tariff-2025-04-07", "Unconfirmed 90-day tariff-pause report, then White House denial", None, "2025-04-07 13:00", "2025-04-07 17:00",
    dict(market_slug="us-recession-in-2025"), -1,
    "recession odds up = bearish", BROAD, "tariffs")
cur("tariff-2025-04-09", "Tariff pause announced", "2025-04-09 17:20", "2025-04-09 16:00", "2025-04-09 20:30",
    dict(market_slug="us-recession-in-2025"), -1,
    "recession odds up = bearish", BROAD, "tariffs")
cur("powell-2025-07-16", "Reports Trump may move to fire Powell", None, "2025-07-16 14:00", "2025-07-16 21:00",
    dict(market_slug="will-trump-try-to-fire-powell-by-august-31"), -1,
    "Fed-independence scare = bearish", ["SPY", "QQQ", "IWM", "TLT", "XLF"], "fed_independence")
cur("alaska-2025-08-15", "Trump-Putin Alaska summit", "2025-08-15 20:00", "2025-08-15 18:00", "2025-08-16 00:00",
    dict(market_slug="russia-x-ukraine-ceasefire-in-2025"), -1,
    "ceasefire odds up = bearish for US defense names", ["ITA", "LMT", "RTX", "NOC", "SPY"], "geopolitics")
cur("shutdown-2026-01-30", "Funding deadline, partial shutdown risk", None, "2026-01-30 14:30", "2026-01-30 21:00",
    dict(market_slug="will-there-be-another-us-government-shutdown-by-january-31"), -1,
    "shutdown odds up = mildly bearish", ["SPY", "QQQ", "IWM", "TLT", "XLF"], "shutdown")
cur("warsh-2026-01-30", "Trump names Kevin Warsh as Fed Chair pick", None, "2026-01-30 13:30", "2026-01-30 21:00",
    dict(event_slug="who-will-trump-nominate-as-fed-chair", match="kevin warsh"), -1,
    "Warsh odds up = hawkish read vs. the alternatives = bearish for gold and risk", ["GLD", "SLV", "TLT", "SPY", "UUP"], "fed_chair")

if __name__ == "__main__":
    out = Path(__file__).with_name("events.yaml")
    out.write_text(yaml.safe_dump({"events": events}, sort_keys=False, width=110, allow_unicode=True))
    print(len(events), "events ->", out)
