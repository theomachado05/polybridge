"""Explicit cash-flow checks for the observational cohort capital diagnostic."""
import pandas as pd
import pytest

from cx5_strategy_selection.option_micro_audit import cash_book


def ticket(entry, result, outcome):
    # Five NO shares cost $2, entry fee $0.25, payout is $5 or $0.
    return {"event": "fixture", "sell_size": 5, "sell_price": 0.6,
            "sell_pnl_points": 55 if outcome == 0 else -45,
            "outcome": outcome, "entry_epoch": entry, "result_epoch": result}


def audit(rows):
    return cash_book(pd.DataFrame(rows), "sell_pnl_points", "sell_price",
                     "sell_size", "entry_epoch")


def test_entry_fees_must_be_funded_before_redemption():
    result = audit([ticket(0, 86400, 0)])
    assert result["peak_locked_cash"] == pytest.approx(2)
    assert result["minimum_initial_cash_with_recycling"] == pytest.approx(2.25)
    assert result["capped_book_pnl"] == pytest.approx(2.75)


def test_prior_lost_stakes_raise_funding_requirement():
    result = audit([ticket(0, 86400, 1), ticket(2 * 86400, 3 * 86400, 1)])
    # Stakes do not overlap, but the second purchase needs new cash after a loss.
    assert result["peak_locked_cash"] == pytest.approx(2)
    assert result["minimum_initial_cash_with_recycling"] == pytest.approx(4.5)
    assert result["capped_book_pnl"] == pytest.approx(-4.5)


def test_payoff_can_be_recycled_only_at_the_assumed_release_clock():
    before = audit([ticket(0, 2 * 86400, 0), ticket(86400, 3 * 86400, 0)])
    after = audit([ticket(0, 86400, 0), ticket(2 * 86400, 3 * 86400, 0)])
    assert before["minimum_initial_cash_with_recycling"] == pytest.approx(4.5)
    assert after["minimum_initial_cash_with_recycling"] == pytest.approx(2.25)
