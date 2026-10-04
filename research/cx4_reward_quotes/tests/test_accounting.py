import pytest

from cx4_reward_quotes.accounting import Ledger, UnidentifiedIncome, minimum_pool, required_incentive


def test_unknown_rewards_cannot_be_assumed_profitable():
    with pytest.raises(UnidentifiedIncome):
        Ledger(-100, None, 10, 0, 0).net_pnl()


def test_income_and_hedge_losses_are_both_counted():
    assert Ledger(-100, 60, 30, 20, 5).net_pnl() == -35


def test_zero_allocated_rewards_are_known_and_valid():
    assert Ledger(-10, 0, 0, 0, 0).net_pnl() == -10


def test_required_income_exactly_offsets_all_costs():
    need = required_incentive(-120, 10, 5)
    assert need == 135
    assert Ledger(-120, need, 0, 10, 5).net_pnl() == 0


def test_competition_dilutes_payout_instead_of_crediting_whole_pool():
    assert minimum_pool(100, 0.01) == 10_000


@pytest.mark.parametrize("share", [0, -0.1, 1.01, float("nan")])
def test_invalid_reward_share(share):
    with pytest.raises(ValueError):
        minimum_pool(100, share)


def test_profitable_trading_does_not_require_a_negative_subsidy():
    assert required_incentive(120, 10, 5) == 0
