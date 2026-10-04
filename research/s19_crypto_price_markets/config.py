"""S19 crypto price markets: every fixed parameter of METHOD.md. Committed with it, before any print of these markets is pulled."""
SEARCHES = ("What price will Bitcoin hit", "What price will Ethereum hit", "What price will Solana hit", "What price will XRP hit",
            "Bitcoin hit in", "Ethereum hit in")
SEARCH_PAGES = 5
TITLE_RE = r"what price will (bitcoin|ethereum|solana|xrp) hit"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
MIN_MARKET_VOLUME = 5_000.0
PER_EVENT, SAMPLE_SEED = 4, 0            # markets drawn at random from each event
WINDOW_S = 48 * 3600                     # from the market's own listing time
MIN_PRINT_CASH = 50.0                    # the data API is asked for prints of at least this many dollars
BUCKETS = ((0.02, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.90), (0.90, 0.98))
PRICE_RANGE = (0.02, 0.98)
CONTRACTS = 100
OOS_FRACTION = 0.20
MONTHS_PER_YEAR = 12
