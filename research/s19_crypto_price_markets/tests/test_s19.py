"""S19: the horizon rule of the universe, and the book built from per-market results."""
import pandas as pd
import pytest

from s19_crypto_price_markets import run as s19
from s19_crypto_price_markets import universe as uni


def test_daily_events_are_recognised_and_left_out():
    assert uni.horizon("What price will Solana hit on March 9?") == "daily"
    assert uni.horizon("What price will Bitcoin hit in October?") == "monthly or longer"
    assert uni.horizon("What price will Bitcoin hit in 2025?") == "monthly or longer"
    assert uni.horizon("What price will Bitcoin hit July 14-20?") == "weekly"
    assert uni.horizon("What price will Bitcoin hit before July 14?") == "other range"


def test_the_book_caps_size_at_100_and_at_the_printed_size_and_books_in_the_result_month():
    d = pd.DataFrame([
        {"event": "a", "segment": "IS", "sell_pnl_points": 30.0, "sell_price": 0.30, "sell_size": 500.0, "start_epoch": 0.0, "result_epoch": 86400.0 * 20, "fee_rate": 0.0},
        {"event": "b", "segment": "IS", "sell_pnl_points": -60.0, "sell_price": 0.40, "sell_size": 40.0, "start_epoch": 86400.0 * 5, "result_epoch": 86400.0 * 40, "fee_rate": 0.0},
        {"event": "c", "segment": "OOS", "sell_pnl_points": float("nan"), "sell_price": float("nan"), "sell_size": 0.0, "start_epoch": 0.0, "result_epoch": 86400.0, "fee_rate": 0.0}])
    monthly, rows = s19.book(d, "sell")
    allr = [r for r in rows if r["segment"] == "ALL"][0]
    assert allr["markets"] == 2                                            # the market with no taker sale is not in the book
    assert allr["pnl"] == pytest.approx(100 * 0.30 + 40 * -0.60)           # 100 contracts, then 40 (the printed size)
    assert allr["capital_base"] == pytest.approx(100 * 0.70 + 40 * 0.60)   # both locked between day 5 and day 20
    assert list(monthly.result_month) == ["1970-01", "1970-02"] and monthly.pnl.tolist() == pytest.approx([30.0, -24.0])
