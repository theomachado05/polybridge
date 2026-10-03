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
- ``await mark.mark("O:AAPL261023P00300000")`` -> per-share mid + spread + exit prices + stale flag (option P&L in
  bridges / portfolio); ``mark.mark_quote(quote, nbbo=None, spot=...)`` is the network-free form for a chain quote
- ``await live.live_chain(underlying, client=...)``: one expiry, per contract with quotes and greeks
  (``GET /options/chain/{underlying}``)
- ``await hedge.hedge_quote(ticker, shares, horizon_days, protection_pct, client=...)``: short stock vs protective
  put vs collar vs put spread at executable prices (``GET /options/hedge-quote``)
- ``bs``: scalar Black–Scholes price / greeks / implied vol
"""
