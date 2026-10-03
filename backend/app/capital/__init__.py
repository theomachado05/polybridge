"""Capital controls (docs/design.md: liquidity and capital): the account risk budget (gross hedge notional and per-event
exposure as a share of equity), Reg T margin for shorts and option requirements, the pre-trade buying-power check,
and GET /capital. ``budget`` is pure, ``service`` reads the account and checks orders, ``router`` serves the route."""
