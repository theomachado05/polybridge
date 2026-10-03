"""Liquidity and capacity (docs/design.md: liquidity and capital): participation caps, the cost model, and the gate every order
passes. ``model`` is pure, ``service`` fetches and caches (Massive, Polymarket CLOB, Kalshi), ``gate`` caps orders,
``router`` serves GET /liquidity/{ticker}, /liquidity/option, /liquidity/pm."""
