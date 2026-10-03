"""Closed-market mode (docs/design.md, section 2): session clock, closure tracker, expected gap.

Everything takes an explicit instant; replays pass the tick's recorded time."""
from .gap import (POOLED, ExpectedGap, GapRate, GapRates, choose_rate, direction_sign, expected_gap,
                  expected_gap_for, load_rates, rate_for)
from .session import (Closure, Session, check_supported, is_early_close, is_trading_day, last_regular_close,
                      next_extended_open, next_regular_open, regular_hours, session_at, to_utc)
from .tracker import ClosureState, ClosureTracker, default_tracker, market_key, replay_key, tracker_for

__all__ = ["POOLED", "Closure", "ClosureState", "ClosureTracker", "ExpectedGap", "GapRate", "GapRates", "Session",
           "check_supported", "choose_rate", "default_tracker", "direction_sign", "expected_gap", "expected_gap_for",
           "is_early_close", "is_trading_day", "last_regular_close", "load_rates", "market_key", "next_extended_open",
           "next_regular_open", "rate_for", "regular_hours", "replay_key", "session_at", "to_utc", "tracker_for"]
