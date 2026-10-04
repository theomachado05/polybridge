from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from .config import EVENTS_PATH


@dataclass(frozen=True)
class Event:
    id: str
    name: str
    family: str
    selection: str
    anchor: pd.Timestamp | None
    start: pd.Timestamp
    end: pd.Timestamp
    token_id: str
    market_slug: str
    condition_id: str
    question: str
    expected_sign: int
    instruments: tuple[str, ...]
    sign_rationale: str = ""
    volume_usd: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def primary(self) -> str:
        return self.instruments[0]

    @property
    def date(self) -> str:
        return self.start.strftime("%Y-%m-%d")


def _ts(v) -> pd.Timestamp | None:
    if v is None:
        return None
    t = pd.Timestamp(v)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def parse_event(d: dict) -> Event:
    pm = d["pm"]
    if d["expected_sign"] not in (-1, 1):
        raise ValueError(f"{d['id']}: expected_sign must be +1 or -1")
    ev = Event(
        id=d["id"], name=d["name"], family=d["family"], selection=d["selection"],
        anchor=_ts(d.get("anchor_utc")), start=_ts(d["window_start_utc"]), end=_ts(d["window_end_utc"]),
        token_id=str(pm.get("token_id", "")), market_slug=pm.get("market_slug", ""),
        condition_id=pm.get("condition_id", ""), question=pm.get("question", ""),
        expected_sign=int(d["expected_sign"]), instruments=tuple(d["instruments"]),
        sign_rationale=d.get("sign_rationale", ""), volume_usd=float(pm.get("volume_usd") or 0),
    )
    if not ev.end > ev.start:
        raise ValueError(f"{ev.id}: window end must be after start")
    if not ev.instruments:
        raise ValueError(f"{ev.id}: no instruments")
    return ev


def load_events(path: Path = EVENTS_PATH) -> list[Event]:
    doc = yaml.safe_load(Path(path).read_text())
    return [parse_event(d) for d in doc["events"]]
