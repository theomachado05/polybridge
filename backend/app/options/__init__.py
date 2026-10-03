"""Opportunity-division data layer: option chains, options-implied probabilities, question matching, 8-K score.

Public entry points for other streams (bridges, tick builder, pipeline):
- ``match.match_question(question, resolution_date)`` -> Match(underlying, strike, expiry, direction, ...) | None
- ``enrich.refresh(underlying, K, expiry)`` (async, fetch + cache) then ``enrich.enrich(tick, underlying, K, expiry)``
- ``implied.implied_for_threshold(chain, K, target, above=True)``
- ``eightk.eightk_score(ticker, as_of=None)``
"""
