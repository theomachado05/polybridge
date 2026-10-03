"""Opportunity-division data layer: option chains, options-implied probabilities, question matching, 8-K score.

Public entry points for other streams (bridges, tick builder, pipeline):
- ``match.match_question(question, resolution_date)`` -> Match(underlying, strike, expiry, direction, ...) | None
- ``await enrich.enrich_market(tick, question, end_date)`` -> (tick, detail): match + chain refresh + live 8-K
  refresh + enrich in one call (simplest integration for the bridge loop)
- ``enrich.refresh(underlying, K, expiry)`` (async, fetch + cache per query) then
  ``enrich.enrich(tick, underlying, K, expiry, above=..., eightk_ticker=...)`` (network-free; opt_* stay NaN when
  the nearest expiry is too far from the resolution date)
- ``implied.implied_for_threshold(chain, K, target, above=True)``
- ``await eightk.refresh_eightk()`` then ``eightk.eightk_score(ticker, as_of=None)``: 0.0 = no filing, NaN = no
  data covers that date (a live date before refresh_eightk, no key, outage, or the frozen OOS window)
- ``fills.structure_quote(fills.structure_legs(chain, "call_spread", expiry, k_lo, k_hi))`` for option fills
"""
