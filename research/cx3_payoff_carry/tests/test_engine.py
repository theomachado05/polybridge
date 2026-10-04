from dataclasses import replace

import numpy as np
import pytest

from cx3_payoff_carry import config as c
from cx3_payoff_carry.engine import (
    Book, EvidenceError, FeeTerms, Portfolio, Proof, SourceObservation,
    basket_signal, carry_signal, daily_metrics, first_execution_book, funding,
    implication_payoffs, payoff_floor, sequential_entry, synchronized, walk,
)


def book(token="B_yes", at=10., venue="pm", bid=.39, ask=.40, depth=1000.):
    fees = FeeTerms(0., 1., .00001, "nearest", 0., "synthetic fee-free schedule")
    return Book(token, venue, at, at, ((bid, depth),), ((ask, depth),), .01, 5., fees)


def proof():
    return Proof("synthetic_implication", "synthetic_family", ("B_yes", "A_no"), 0.,
                 ("synthetic full B rules", "synthetic full A rules"),
                 ("synthetic official source", "synthetic official source"),
                 implication_payoffs(), "synthetic reviewed state space", True)


def test_implication_orientation_has_one_dollar_floor_and_possible_two_dollars():
    assert payoff_floor(implication_payoffs()) == 1
    assert sum(implication_payoffs()[1]) == 2
    # The inverse basket YES(A)+NO(B) loses both legs in the allowed A=0,B=1 state.
    assert payoff_floor(((0, 1), (0, 0), (1, 0))) == 0


def test_disagreement_or_refund_state_breaks_apparent_twin_arbitrage():
    assert payoff_floor(((0, 1), (1, 0), (.5, .5))) == 1
    assert payoff_floor(((0, 1), (1, 0), (.5, 0))) == .5
    with pytest.raises(EvidenceError, match="below"):
        replace(proof(), payouts=((0, 1), (1, 0), (.5, 0))).validate(10)


def test_named_only_set_is_not_exhaustive_when_other_can_win():
    one_of_three = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    assert payoff_floor(one_of_three) == 1
    assert payoff_floor(one_of_three + ((0, 0, 0),)) == 0


@pytest.mark.parametrize("kwargs", [
    {"complete_rules": ("", "full")},
    {"source_refs": ("", "source")},
    {"captured_at": 11.},
    {"completeness_certificate": ""},
    {"exceptional_states_reviewed": False},
    {"tokens": ("B_yes", "B_yes")},
])
def test_text_similarity_and_post_entry_rules_cannot_certify_contract(kwargs):
    with pytest.raises(EvidenceError):
        replace(proof(), **kwargs).validate(10.)


@pytest.mark.parametrize("kwargs", [
    {"received_at": 11.}, {"received_at": 7., "venue_at": 7.},
    {"venue_at": 7.}, {"venue_at": 11.}, {"asks": ()},
    {"bids": ((.41, 1000.),)}, {"asks": ((.405, 1000.),)},
    {"accepting_orders": False}, {"bids": ((.39, float("nan")),)},
])
def test_bad_future_stale_crossed_or_one_sided_books_are_not_executable(kwargs):
    with pytest.raises(EvidenceError):
        replace(book(), **kwargs).validate(10.)


def test_cross_leg_receive_time_skew_and_missing_fee_terms_fail():
    with pytest.raises(EvidenceError, match="skew"):
        synchronized([book(at=10), book("A_no", at=8.5)], 10)
    with pytest.raises(EvidenceError, match="fee terms"):
        replace(book(), fees=replace(book().fees, captured_at=11)).validate(10)


def test_fok_walk_respects_each_level_participation_and_real_ask_prices():
    b = replace(book(), asks=((.40, 500.), (.42, 500.)))
    fill = walk(b, 100, "BUY", 1.)
    assert fill.vwap == pytest.approx(.41)
    assert fill.cash_delta == pytest.approx(-42.)
    with pytest.raises(EvidenceError, match="depth"):
        walk(b, 101, "BUY", 1.)


def test_double_costs_add_extra_spread_and_double_fee_and_tick():
    b = replace(book(), fees=FeeTerms(.04, 1., .00001, "nearest", 0., "synthetic"))
    one, two = walk(b, 100, "BUY", 1.), walk(b, 100, "BUY", 2.)
    assert one.fee == pytest.approx(.96)
    assert -two.cash_delta + one.cash_delta == pytest.approx(.5 + .96 + 1.)
    assert two.fee == pytest.approx(2 * one.fee)


def test_fee_rounding_and_symmetry():
    f = FeeTerms(.07, 1., .01, "up", 0., "synthetic cent-rounded schedule")
    assert f.charge([(.5, 1)]) == .02
    assert f.charge([(.3, 100)]) == f.charge([(.7, 100)])


def test_execution_chooses_first_causal_book_even_if_later_book_is_cheaper():
    stream = [book(at=10.5, ask=.20, bid=.19), book(at=11., ask=.60, bid=.59),
              book(at=12., ask=.20, bid=.19)]
    assert first_execution_book(stream, "B_yes", 10.).asks[0][0] == .60
    with pytest.raises(EvidenceError, match="execution-time"):
        first_execution_book([book(at=12.1)], "B_yes", 10.)


def test_single_snapshot_or_low_edge_cannot_trigger_basket():
    first = [book(at=10), book("A_no", at=10)]
    second = [book(at=12), book("A_no", at=12)]
    assert basket_signal(proof(), first, second, 10., 12., 86400., 100, 1.) > .02
    with pytest.raises(EvidenceError, match="subsequent"):
        basket_signal(proof(), first, first, 10., 10., 86400., 100, 1.)
    costly = [book(at=12, bid=.49, ask=.5), book("A_no", at=12, bid=.49, ask=.5)]
    with pytest.raises(EvidenceError, match="net edge"):
        basket_signal(proof(), first, costly, 10., 12., 86400., 100, 1.)


def test_two_venue_basket_completes_as_simulation_without_live_acknowledgments():
    p = Portfolio(1., {"pm": 5000., "k": 5000.})
    stream = [book("A_no", at=10, venue="k"), book(at=11), book("A_no", at=12, venue="k")]
    result = sequential_entry(proof(), stream, 10., 100., 1., p, 86400.)
    assert result["status"] == "complete_simulated"
    assert len(p.lots) == 2
    assert p.cash["pm"] < 5000 and p.cash["k"] < 5000


def test_failed_second_leg_unwinds_first_and_records_leg_loss():
    p = Portfolio(1., {"pm": 5000., "k": 5000.})
    stream = [book("A_no", at=10, venue="k"), book(at=11), book("A_no", at=12, venue="k", depth=10),
              book(at=13, bid=.30, ask=.31)]
    result = sequential_entry(proof(), stream, 10., 100., 1., p, 86400.)
    assert result["status"] == "legging_failure"
    assert result["filled_legs"] == 1
    assert not p.lots
    assert sum(p.cash.values()) < 9988.01
    assert p.turnover == pytest.approx(70.)


def test_partial_unwind_leaves_funded_residual_exposure():
    p = Portfolio(1., {"pm": 5000., "k": 5000.})
    stream = [book("A_no", at=10, venue="k"), book(at=11), book("A_no", at=12, venue="k", depth=10),
              book(at=13, bid=.30, ask=.31, depth=100)]
    result = sequential_entry(proof(), stream, 10., 100., 1., p, 86400.)
    assert result["status"] == "legging_failure"
    assert len(result["residual_lots"]) == 1
    lot = next(iter(p.lots.values()))
    assert lot.qty == 90
    assert lot.collateral == pytest.approx(36.9)
    p.advance(86413.)
    assert p.financing > 36.9 * .1 / 365


def test_later_leg_price_change_invalidates_edge_and_forces_lossy_unwind():
    p = Portfolio(1., {"pm": 5000., "k": 5000.})
    stream = [book("A_no", at=10, venue="k"), book(at=11),
              book("A_no", at=12, venue="k", bid=.59, ask=.60),
              book(at=13, bid=.30, ask=.31)]
    result = sequential_entry(proof(), stream, 10., 100., 1., p, 86400.)
    assert result["status"] == "legging_failure"
    assert "economics" in result["reason"]
    assert result["filled_legs"] == 1 and not p.lots
    assert sum(p.cash.values()) < 9988.01


def test_funding_runs_until_actual_release_and_doubles_at_two_costs():
    base = funding(100., 0, 30 * 86400, 1.)
    assert base == pytest.approx(100 * .1 * 30 / 365)
    assert funding(100., 0, 60 * 86400, 2.) == pytest.approx(4 * base)


def test_winner_not_redeemed_cannot_create_cash_or_finance_new_leg():
    p = Portfolio(1., {"pm": 50., "k": 9950.})
    fill = walk(book(at=10), 100, "BUY", 1.)
    p.buy(fill, "first", "family1")
    with pytest.raises(EvidenceError, match="unreleased"):
        p.redeem("first", 10., 86400., 1., 0.)
    with pytest.raises(EvidenceError, match="venue cash"):
        p.buy(fill, "second", "family2")
    p.redeem("first", 86400., 86400., .5, .1)
    assert not p.lots
    assert p.cash["pm"] < 59


def test_daily_equity_uses_liquidation_bid_and_missing_marks_fail():
    p = Portfolio(1., {"pm": 5000., "k": 5000.})
    p.buy(walk(book(at=10), 100, "BUY", 1.), "position", "family")
    e = p.equity(12., {"B_yes": book(at=12, bid=.30, ask=.31)})
    assert e < 9988.01
    with pytest.raises(EvidenceError, match="missing daily"):
        p.equity(86400., {})


def source():
    return SourceObservation(100., 120., 0., "synthetic official source", "content_hash",
                             "B_yes", True)


def test_publication_entry_uses_first_observed_time_and_cannot_use_outcome_label():
    assert source().entry_at() == 180.
    with pytest.raises(EvidenceError, match="timestamps missing"):
        replace(source(), released_at=None).entry_at()
    with pytest.raises(EvidenceError, match="ambiguous"):
        replace(source(), mechanically_unambiguous=False).entry_at()
    with pytest.raises(EvidenceError, match="before it was released"):
        replace(source(), first_observed_at=99.).entry_at()


def test_carry_requires_open_market_and_beats_thirty_day_funding():
    b = book(at=180., bid=.94, ask=.95)
    assert carry_signal(source(), b, 100., 1.) > .02
    with pytest.raises(EvidenceError, match="closed"):
        carry_signal(source(), replace(b, accepting_orders=False), 100., 1.)
    with pytest.raises(EvidenceError, match="does not beat"):
        carry_signal(source(), book(at=180., bid=.98, ask=.99), 100., 1.)


def test_daily_metrics_keep_idle_days_include_initial_drawdown_and_enforce_sample_gate():
    e = [9990., 10020.] + [10020.] * 60
    metrics = daily_metrics(np.arange(1, 63) * 86400, e, 10000., 12)
    assert metrics["daily_observations"] == 62
    assert metrics["max_drawdown"] == pytest.approx(.001)
    assert not metrics["sample_gate"]
    assert not metrics["numerical_gate"]
    with pytest.raises(EvidenceError, match="contiguous"):
        daily_metrics([86400., 3 * 86400.], [10000., 10001.], 10000., 30)


def test_daily_metrics_do_not_manufacture_sharpe_on_flat_missing_trade_history():
    metrics = daily_metrics(np.arange(1, 61) * 86400, np.full(60, 10000.), 10000., 0)
    assert np.isnan(metrics["sharpe"])
    assert not metrics["numerical_gate"]
