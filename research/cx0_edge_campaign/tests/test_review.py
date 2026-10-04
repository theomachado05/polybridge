from dataclasses import replace
import math

import pytest

from cx0_edge_campaign.review import Evidence, nav_metrics, screen


BASE = Evidence(1.8, 0.05, 0.02, 0.0001, 40, 100, True, True, False)


def test_first_day_cost_and_starting_capital_are_in_drawdown():
    r = nav_metrics([90, 100], 100)
    assert r["max_drawdown"] == pytest.approx(0.10)
    assert r["total_return"] == 0


def test_compounded_equity_is_not_sum_of_trade_percentage_returns():
    assert nav_metrics([110, 99], 100)["total_return"] == pytest.approx(-0.01)


def test_constant_return_cannot_produce_infinite_claimed_sharpe():
    assert math.isnan(nav_metrics([100, 100], 100)["sharpe"])


@pytest.mark.parametrize("nav", [[100, float("nan")], [100, 0], [], [[100, 101]]])
def test_invalid_marks_are_not_silently_imputed(nav):
    with pytest.raises(ValueError):
        nav_metrics(nav, 100)


def test_tiny_high_sharpe_sample_cannot_pass():
    assert screen(replace(BASE, oos_sharpe=9, independent_oos_entry_dates=4))[0] == "INSUFFICIENT"


def test_missing_execution_data_cannot_pass_on_attractive_pnl():
    assert screen(replace(BASE, execution_inputs_supported=False))[0] == "NOT_TESTABLE"


def test_unknown_rewards_block_a_performance_claim():
    assert screen(replace(BASE, accounting_supported=False))[0] == "NOT_TESTABLE"


def test_doubled_cost_loss_fails():
    assert screen(replace(BASE, oos_return_2x=-0.01))[0] == "FAIL"


def test_exposed_history_is_not_independent_confirmation():
    assert screen(BASE)[0] == "EXPLORATORY_PASS"
    assert screen(replace(BASE, independent_confirmation=True))[0] == "CONFIRMED"
