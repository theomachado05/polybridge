from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[1] / "data"
EVIDENCE_PATH = DATA / "gap_evidence.json"

VALIDATED = "validated"
UNVALIDATED = "unvalidated estimate"

HEDGE_A_LABEL = ("Estimate only, not protection: simulated prediction-market leg (no Polymarket trading account). "
                 "Research R1 found no evidence that holding the PM contract over a closure reduces the open-gap loss "
                 "(variance reduction +4.8%, 95% CI -0.8% to +10.0%; it increased the variance on the 10-market "
                 "replication panel). Off unless the proposal opts in.")
HEDGE_B_LABEL = ("Default closed-market action: an equity order staged for the first tradable moment, sent only after "
                 "approval. Research R1: it cut the post-open P&L variance by 11.4% (95% CI +5.1% to +18.1%), by timing, "
                 "not direction; it executes after the gap, so it cannot recover the gap itself.")
HEDGE_B_PREMARKET_NOTE = ("This plan executes in the pre-market (the broker supports extended hours): R1's pre-market "
                          "variant (08:00 ET) was only partial (variance reduction +13.2%, CI +3.3% to +25.5%, not "
                          "better than a static hedge); the 09:30 version is the one with evidence.")
OPPORTUNITY_LABEL = ("Research only, not a trade recommendation: options reflected 0.44 of the weekend PM move at the "
                     "Monday open (CI 0.33 to 0.57) but the residual gap net of option costs is NULL (+0.79 pt, CI -1.21 "
                     "to +2.78; R3).")


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def load(path: Path | str | None = None) -> dict:
    p = Path(path) if path is not None else EVIDENCE_PATH
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    return _load(str(p), mtime)


def _match(doc: dict, market_source: str | None, market_id: str | None, token_id: str | None) -> tuple[str, dict] | None:
    keys = {k for k in (market_id, token_id) if k}
    for slug, row in (doc.get("markets") or {}).items():
        if not isinstance(row, dict):
            continue
        names = {slug, row.get("token_id"), row.get("polymarket_id")} - {None}
        if market_source not in (None, "polymarket"):
            continue
        if keys & names:
            return slug, row
    return None


def market_evidence(market_source: str | None, market_id: str | None, token_id: str | None = None,
                    doc: dict | None = None) -> dict:
    doc = load() if doc is None else doc
    hit = _match(doc, market_source, market_id, token_id)
    if hit is None:
        return {"validated": False, "status": UNVALIDATED, "market": None, "token_id": None, "oos": None,
                "evidence": "No out-of-sample test for this market: the expected gap is an unvalidated estimate "
                            "(the pooled rate's band spans both signs; the 10-market replication was not accurate)."}
    slug, row = hit
    oos = {k: row.get(k) for k in ("verdict", "n_test", "sign_k", "sign_n", "sign_rate", "sign_p", "slope",
                                   "slope_p_perm", "panel")}
    if row.get("validated"):
        why = (f"Validated out of sample on this market (R2): sign right in {row.get('sign_k')} of {row.get('sign_n')} "
               f"({100 * (row.get('sign_rate') or 0):.1f}%), slope {row.get('slope'):+.2f} (permutation p "
               f"{_p(row.get('slope_p_perm'))}).")
    else:
        sr, sl = row.get("sign_rate"), row.get("slope")
        why = ("Not validated: this market's own out-of-sample record fails R2's rule"
               + (f" (sign {100 * sr:.1f}% of {row.get('sign_n')}, slope {sl:+.2f})" if sr is not None and sl is not None
                  else "") + "; the expected gap is an unvalidated estimate.")
    return {"validated": bool(row.get("validated")), "status": VALIDATED if row.get("validated") else UNVALIDATED,
            "market": slug, "token_id": row.get("token_id"), "oos": oos, "evidence": why}


def gate(evid: dict, label: str | None, ticker: str | None, basis_ticker: str | None,
         reasons: list[str] | tuple[str, ...] = ()) -> tuple[bool, str, str]:
    from .gap import GAP_POOLED_RATE, GAP_PROXY_TICKER, GAP_TOO_FEW_CLOSURES
    if not evid.get("validated"):
        return False, UNVALIDATED, str(evid.get("evidence") or "")
    reasons = list(reasons or ())
    if label != "market":
        if GAP_TOO_FEW_CLOSURES in reasons:
            why = ("This market passed R2 out of sample, but its own rate is not in use (too few closures or no "
                   "standard error), so the pooled rate gives an unvalidated estimate.")
        elif GAP_POOLED_RATE in reasons:
            why = ("This market passed R2 out of sample, but no per-market rate matched this id, so the pooled rate "
                   "gives an unvalidated estimate.")
        else:
            why = "The market's own rate is not in use, so this is an unvalidated estimate."
        return False, UNVALIDATED, why
    tick = (ticker or "").upper()
    basis = (basis_ticker or "").upper()
    if GAP_PROXY_TICKER in reasons or (tick and basis and tick != basis):
        why = (f"This market's rate was validated out of sample on {basis or 'SPY'} gaps only (R2); {tick or 'this '
               'ticker'} borrows that rate as a proxy, so the number is an unvalidated estimate.")
        return False, UNVALIDATED, why
    return True, VALIDATED, str(evid.get("evidence") or "")


NO_MARKET_EVIDENCE = ("No prediction market is named yet (a filing-tags proposal takes its market at bridge start), so "
                      "no market signal has passed an out-of-sample test: unvalidated estimate.")
LABEL_VALIDATED = "validated"
LABEL_ACKNOWLEDGED = "unvalidated (acknowledged)"
LABEL_OVERRIDE = "override"


def signal_status(market_source: str | None, market_id: str | None, token_id: str | None = None,
                  ticker: str | None = None, doc: dict | None = None) -> dict:
    if not market_source or not market_id:
        return {"validated": False, "status": UNVALIDATED, "evidence": NO_MARKET_EVIDENCE, "market": None,
                "rate_source": None, "basis_ticker": None, "reasons": [], "oos": None}
    from .gap import GAP_PROXY_TICKER, choose_rate, load_rates
    evid = market_evidence(market_source, market_id, token_id, doc=doc)
    rates = load_rates()
    r, _own, codes = choose_rate(rates, market_source, market_id, ticker, token_id or evid.get("token_id"))
    codes = list(codes)
    if ticker and ticker.upper() != (r.ticker or "").upper():
        codes.append(GAP_PROXY_TICKER)
    validated, status, why = gate(evid, r.label, ticker, r.ticker, codes)
    return {"validated": validated, "status": status, "evidence": why, "market": evid.get("market"),
            "rate_source": r.label, "basis_ticker": r.ticker, "reasons": codes, "oos": evid.get("oos")}


def _p(p: Any) -> str:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "n/a"
    return "< 0.001" if v < 0.001 else f"{v:.3f}"


def hedge_evidence(doc: dict | None = None) -> dict:
    doc = load() if doc is None else doc
    return {"hedge_a": {**(doc.get("hedge_a") or {}), "label": HEDGE_A_LABEL, "default": False},
            "hedge_b": {**(doc.get("hedge_b") or {}), "label": HEDGE_B_LABEL, "default": True},
            "opportunity": {**(doc.get("opportunity") or {}), "label": OPPORTUNITY_LABEL, "research_only": True}}


REPO = Path(__file__).resolve().parents[3]

CONFIRMED_FOUNDATION = "CONFIRMED_FOUNDATION"
LEAD = "LEAD"
OPEN_LEAD = "OPEN_LEAD"
WATCH_ONLY = "WATCH_ONLY"
NO_TESTED_MECHANISM = "NO_TESTED_MECHANISM"
FAILED = "FAILED"
UNVALIDATED_AVAILABLE = "UNVALIDATED"
STATUSES = (CONFIRMED_FOUNDATION, LEAD, OPEN_LEAD, WATCH_ONLY, NO_TESTED_MECHANISM, UNVALIDATED_AVAILABLE, FAILED)

STATUS_LABELS = {
    CONFIRMED_FOUNDATION: "Confirmed foundation (pre-registered, fresh data)",
    LEAD: "Lead: not validated",
    OPEN_LEAD: "Open lead: unvalidated",
    WATCH_ONLY: "Watch only: never traded",
    NO_TESTED_MECHANISM: "No tested mechanism",
    UNVALIDATED_AVAILABLE: "Unvalidated: walk-forward test failed",
    FAILED: "Failed its test",
}

CI95_DATE = "95% interval, resolution-date cluster bootstrap"
CI95_DATES = "95% interval over dates"
CI95_EVENT = "95% interval, event bootstrap"
CI90_DATE = "90% interval, date cluster bootstrap (equivalence margin +/-0.003)"
CENSUS = "census count: no sampling interval (low = high = value)"
PERCENTILES = "percentiles of the logged decisions: median (p50) and p99, not a confidence interval"
NO_INTERVAL = "no interval reported in the result file (low = high = value); see note"
RANGE_KINDS = {CI95_DATE: "ci95", CI95_DATES: "ci95", CI95_EVENT: "ci95", CI90_DATE: "ci90", CENSUS: "census",
               PERCENTILES: "percentiles", NO_INTERVAL: "none"}

FORWARD_START = "2026-10-05"

FA = "research/results/fresh_accuracy/SUMMARY.md"
FA_STATS = "research/results/fresh_accuracy/stats.json"
LR = "research/results/ladder_replay/SUMMARY.md"
LR_LIVE = "research/results/ladder_replay/live_totals.json"
S11 = "research/results/s11_bundles/SUMMARY.md"
S21 = "research/results/s21_options_anchor/SUMMARY.md"
TF = "research/results/touch_fresh/SUMMARY.md"
TF_COUNTS = "research/results/touch_fresh/counts.json"
FIT = "research/results/fit_oos/SUMMARY.md"
SCORECARD = "research/results/WEEKEND_SCORECARD.md"
S25 = "research/results/s25_ticket_option_hedge/SUMMARY.md"
S25_REF = {"source_branch": "r/weekend-options", "source_commit": "bd18b9f"}
LATENCY = "research/results/live_books/LATENCY.md"
LATENCY_REF = {"source_branch": "r/live-speed", "source_commit": "a6ba327"}


def _kind(desc: str) -> str:
    if desc in RANGE_KINDS:
        return RANGE_KINDS[desc]
    if desc.startswith("95%"):
        return "ci95"
    if desc.startswith("90%"):
        return "ci90"
    raise KeyError(desc)


def _n(label: str, value: float, lo: float, hi: float, range_kind: str, n: int, units: str, result_file: str, *,
       confirmatory: bool, unit: str = "", also: tuple[tuple[int, str], ...] = (), note: str = "",
       ref: dict | None = None) -> dict:
    out = {"label": label, "value": value, "unit": unit, "ci_low": lo, "ci_high": hi,
           "range_kind": _kind(range_kind), "range_desc": range_kind,
           "sample": {"n": n, "units": units, "also": [{"n": a, "units": u} for a, u in also]},
           "result_file": result_file, "confirmatory": confirmatory}
    if note:
        out["note"] = note
    if ref:
        out.update(ref)
    return out


def _census(label: str, value: float, n: int, units: str, result_file: str, *, confirmatory: bool, unit: str = "",
            also: tuple[tuple[int, str], ...] = (), note: str = "", ref: dict | None = None) -> dict:
    return _n(label, value, value, value, CENSUS, n, units, result_file, confirmatory=confirmatory, unit=unit,
              also=also, note=note, ref=ref)


PTS = "points per contract"

MECHANISMS: tuple[dict, ...] = (
    {
        "id": "foundation",
        "name": "Options are the more accurate price",
        "status": CONFIRMED_FOUNDATION,
        "claim": ("On 4,561 fresh Polymarket \"close above $K\" stock markets, pre-registered and run once, the "
                  "option-implied probability was a more accurate forecast than the Polymarket price."),
        "actions_allowed": {"mode": "reference_only", "trade": False, "proposals": False, "requires_approval": False,
                            "requires_acknowledgement": False,
                            "text": ("Reference only: it tells the two mechanisms which price to compare against. "
                                     "An accuracy gap is not an executable edge, so nothing is traded on it.")},
        "numbers": [
            _n("Brier score difference, Polymarket minus options (positive = options better)", 0.0108, 0.0064, 0.0158,
               CI95_DATE, 7111, "scored rows", FA_STATS, confirmatory=True,
               also=((4561, "markets"), (89, "resolution dates (clusters)"))),
            _n("Log score difference, Polymarket minus options (positive = options better)", 0.0318, 0.0170, 0.0471,
               CI95_DATE, 7111, "scored rows", FA_STATS, confirmatory=True,
               also=((4561, "markets"), (89, "resolution dates (clusters)"))),
            _n("Kalshi S&P 500 / Nasdaq-100 minus options, Brier (deep books match options)", 0.0013, 0.0001, 0.0025,
               CI90_DATE, 2609, "Kalshi rows", FA, confirmatory=True, also=((215, "dates"),),
               note="H3 verdict EQUIVALENT within the pre-set +/-0.003 margin."),
        ],
        "caveats": [
            "A statement about prices, not traders: the Polymarket series is per-minute and can be a stale last price.",
            "The Polymarket price series is older than the option quote on average, and where it is freshest the gap "
            "is not significant (note/NOTE.md section 2).",
            "An accuracy gap is not an executable edge; the arb scan found 0 executable gaps (5 verified).",
        ],
        "forward_test": None,
    },
    {
        "id": "ladders",
        "name": "Date ladders that break their own logic",
        "status": LEAD,
        "claim": ("An earlier-date rung can never be worth more than the same contract for a later date; when it "
                  "traded above and both legs printed, the pair paid, but the registered fresh test is NULL."),
        "actions_allowed": {"mode": "proposals_with_approval", "trade": True, "proposals": True,
                            "requires_approval": True, "requires_acknowledgement": False,
                            "text": ("Proposals only, each needs approval. Only for a pair that shares the same event "
                                     "definition and resolution source, with each rung's year re-derived.")},
        "numbers": [
            _n("Fresh ladders, rule as registered: net per trade", 2.47, -1.14, 6.26, CI95_DATES, 650, "trades", LR,
               confirmatory=True, unit=PTS, also=((221, "dates"),),
               note="Confirmatory verdict: NULL (74 losing trades, all from 3 ladders with the year read wrong)."),
            _n("Fresh ladders, year parsed correctly: net per trade", 8.82, 6.73, 11.13, CI95_DATES, 562, "trades", LR,
               confirmatory=False, unit=PTS, also=((211, "dates"),),
               note="Post hoc: the year check was chosen after seeing the losers. 0 losing trades."),
            _n("Same, from 22 July 2026: net per trade", 9.20, 4.86, 14.01, CI95_DATES, 102, "trades", LR,
               confirmatory=False, unit=PTS, also=((41, "dates"),), note="Post hoc (year check)."),
            _n("Seen data (S11), print-verified violations: net per trade at 1x costs", 3.89, 2.49, 5.43, CI95_DATES,
               99, "trades", S11, confirmatory=False, unit=PTS, also=((71, "dates"),),
               note="Seen data; 11 out-of-sample trades."),
            _census("Live sweep of open date ladders: violations net of fees", 0, 34, "date ladders", LR_LIVE,
                    confirmatory=False, unit="violations", also=((61, "adjacent pairs"),),
                    note="One snapshot, 2026-10-04 01:57 ET; median pair 10.5 points from an arbitrage."),
            _census("Fresh pairs sharing event definition and source (registered rule)", 680, 861, "fresh pairs", LR,
                    confirmatory=True, unit="pairs nested"),
        ],
        "caveats": [
            "The result that clears zero depends on a correction chosen after the run.",
            "Most of the dollars come from 30 of 562 trades where the event fell between the two dates; without them "
            "the mean is 3.4 points.",
            "Fills are simulated from public prints, not our own orders; printed size bounds capacity.",
            "No market risk if held to resolution, but settlement-rule risk and capital lock-up remain.",
        ],
        "forward_test": {"file": "research/ladder_replay/live.py", "starts": FORWARD_START,
                         "method": "research/ladder_replay/METHOD.md"},
        "engine_preset": {"family": "ladder_pair", "index": 4,
                          "params": {"min_edge": 1.0, "max_age_s": 60.0, "cap": 100.0},
                          "why": ("METHOD.md: 60 s max age; one tick per leg plus both taker fees. ladder_pair counts "
                                  "one tick, so min_edge 1 point stands in for the second tick; cap 100 is the "
                                  "replay's contract cap.")},
    },
    {
        "id": "touch",
        "name": "\"Will it hit\" tickets above the options reference",
        "status": OPEN_LEAD,
        "claim": ("In past data, stock and S&P 500 touch tickets priced well above an options-derived reference lost "
                  "money for their buyers; a fresh test could not confirm it."),
        "actions_allowed": {"mode": "proposals_behind_acknowledgement", "trade": True, "proposals": True,
                            "requires_approval": True, "requires_acknowledgement": True,
                            "side": "sell_yes", "sell_threshold_points": 5.0,
                            "hedge_offered": False,
                            "text": ("Proposals only, behind the acknowledgement gate: unvalidated. No option-spread "
                                     "hedge is offered (tested in S25, it raised risk).")},
        "engine_preset": {"family": "touch_ticket_reference", "index": 0, "params": {"threshold": 5.0},
                          "why": "threshold 5 points = S21 book B0; validated False (unvalidated): proposals only."},
        "numbers": [
            _n("Seen data (S21): YES buyers paying 10+ points above the central reference", -29.76, -40.10, -18.29,
               CI95_EVENT, 53, "markets", S21, confirmatory=False, unit=PTS, also=((29, "events"),),
               note="Exploratory: in-sample, only 2 markets out of sample."),
            _n("Seen data (S21): sell YES 5+ points above the reference", 22.27, 10.35, 33.14, CI95_EVENT, 60,
               "markets", S21, confirmatory=False, unit=PTS, also=((33, "events"),), note="Exploratory."),
            _n("Seen data (S21): sold minus left", 19.19, 5.82, 31.45, CI95_EVENT, 60, "markets sold", S21,
               confirmatory=False, unit=PTS, also=((217, "markets left"),), note="Exploratory."),
            _census("Fresh test: eligible markets (needed 30 markets in 15 events)", 32, 32, "markets", TF,
                    confirmatory=True, unit="markets", also=((4, "events"),),
                    note="Confirmatory verdict: INSUFFICIENT; the test could not run."),
            _n("Fresh secondary sample R: sell rule", -15.38, -48.82, 21.82, CI95_EVENT, 7, "markets", TF,
               confirmatory=False, unit=PTS, also=((7, "events"),),
               note="INSUFFICIENT by its own book minimum (10 markets in 5 events)."),
            _n("Fresh secondary sample R: unfiltered seller book", -2.60, -18.95, 11.52, CI95_EVENT, 38, "markets", TF,
               confirmatory=False, unit=PTS, also=((28, "events"),)),
            _n("Fresh secondary sample R: unfiltered book, delta-hedged", 10.50, -0.10, 20.00, CI95_EVENT, 37,
               "markets", TF, confirmatory=False, unit=PTS, also=((27, "events"),),
               note="Much of the premium is compensation for market exposure."),
        ],
        "caveats": [
            "The touch reference rests on modelling choices (barrier versus terminal probability; option expiry later "
            "than the ticket window).",
            "Fresh point estimates lean against the S21 result; the samples are too thin to decide.",
            "Selling tickets carries tail risk when the level is hit; correlated tickets on one underlying lose together.",
        ],
        "forward_test": {"file": "research/touch_fresh/FORWARD.md", "starts": FORWARD_START,
                         "code": "research/touch_fresh/forward.py"},
    },
    {
        "id": "ticket_option_hedge",
        "name": "Option-spread hedge for sold tickets (S25)",
        "status": FAILED,
        "claim": ("Buying the matching option spread against a sold touch ticket, at real Monday quotes, cost more "
                  "than it paid back and raised the risk instead of cutting it."),
        "actions_allowed": {"mode": "none", "trade": False, "proposals": False, "requires_approval": False,
                            "requires_acknowledgement": False,
                            "text": "Never offered: tested and it raised risk."},
        "numbers": [
            _n("Rule subset: SD of P&L per market, hedged / unhedged (H2 needed below 1)", 1.33, 0.88, 1.93,
               "95% interval", 52, "markets", S25, confirmatory=True, unit="ratio", also=((29, "events"),),
               note="Pre-registered H2: not met. Markets were S21's (seen); 2 of 52 out of sample.", ref=S25_REF),
            _n("All hedged markets: SD of P&L per market, hedged / unhedged", 1.49, 1.33, 1.67, "95% interval", 252,
               "markets", S25, confirmatory=True, unit="ratio", also=((57, "events"),), ref=S25_REF),
            _n("All hedged markets: hedged P&L per ticket", -9.35, -18.36, -1.68, "95% interval", 252, "markets", S25,
               confirmatory=True, unit="points per ticket", also=((57, "events"),),
               note="Unhedged on the same markets: +5.50 [+1.45, +9.59].", ref=S25_REF),
        ],
        "caveats": [
            "The spread pays when the stock finishes beyond the level; the ticket loses when it touches it.",
            "S25 is not cited in note/NOTE.md; its result file is on branch r/weekend-options.",
        ],
        "forward_test": None,
    },
    {
        "id": "btc_15min",
        "name": "15-minute Bitcoin markets against spot",
        "status": WATCH_ONLY,
        "claim": "Watched only, never traded: the gap to spot closes too fast to act on.",
        "actions_allowed": {"mode": "watch_only", "trade": False, "proposals": False, "requires_approval": False,
                            "requires_acknowledgement": False, "text": "Watch only, never trade."},
        "numbers": [],
        "caveats": [
            "No result file in research/results measures this gap, so no number is shown; the watch-only rule comes "
            "from the product brief of 2026-10-04.",
        ],
        "forward_test": None,
    },
    {
        "id": "generic_ai_fit",
        "name": "Generic AI fit (preset selection and tuning)",
        "status": UNVALIDATED_AVAILABLE,
        "claim": ("The AI-chosen preset did not beat a static hedge out of sample: its walk-forward test failed."),
        "actions_allowed": {"mode": "available_unvalidated", "trade": True, "proposals": True,
                            "requires_approval": True, "requires_acknowledgement": True,
                            "text": ("Available, labelled unvalidated: the walk-forward test failed, so every fit "
                                     "needs the acknowledgement and an approval, whatever the market's own gap "
                                     "evidence says; it is never auto-approved.")},
        "numbers": [
            _census("Test window: markets where the chosen preset beat a static hedge", 19, 122, "markets", FIT,
                    confirmatory=True, unit="markets better",
                    note="72 worse, 31 tied; one-sided sign p = 1.000. Pre-registered criterion: FAIL."),
            _census("Test window: markets where the chosen preset did worse than a static hedge", 72, 122, "markets",
                    FIT, confirmatory=True, unit="markets worse"),
            _n("Test window: median vs_static of the chosen preset", -0.0040, -0.0040, -0.0040, NO_INTERVAL, 122,
               "markets", FIT, confirmatory=True, note="One-sided Wilcoxon p = 1.000; train median was +0.0138."),
        ],
        "caveats": ["In-sample the same presets looked good (98 of 122 better on train): picked on the data they "
                    "were scored on."],
        "forward_test": None,
    },
    {
        "id": "other",
        "name": "Everything else",
        "status": NO_TESTED_MECHANISM,
        "claim": "No tested mechanism: about 40 pre-registered tests, none of the others passed its own rule.",
        "actions_allowed": {"mode": "none", "trade": False, "proposals": False, "requires_approval": False,
                            "requires_acknowledgement": False,
                            "text": "No tested mechanism: no trade is proposed."},
        "numbers": [],
        "caveats": ["Full list of what failed: note/NOTE.md section 6 and research/results/WEEKEND_SCORECARD.md."],
        "forward_test": None,
    },
)

SYSTEM_NUMBERS: tuple[dict, ...] = (
    _n("Receive to decision, live Polymarket feed (median and p99)", 40.0, 40.0, 1805.0, PERCENTILES, 548990,
       "book-update decisions", LATENCY, confirmatory=False, unit="microseconds",
       note="Network time excluded; weekend reference is Friday's close, so these are latency, not trades.",
       ref=LATENCY_REF),
    _n("C++ stale-quote detector call (isolated)", 208, 208, 208, NO_INTERVAL, 1, "isolated benchmark", LATENCY,
       confirmatory=False, unit="nanoseconds per call", note="Includes the pybind11 call; Python twin 292 ns.",
       ref=LATENCY_REF),
)

MICRO_BENCH: tuple[dict, ...] = tuple(
    {"family": fam, "mean_ns": mean, "step_mean_ns": step, "p50_ns": 42, "p99_ns": 42, "p999_ns": 84,
     "sample": "1,000,000 ticks, one run, one thread", "tape": tape, "result_file": "engine/hedgecore/BENCH.md",
     "note": "Synthetic tape, not recorded market data; on_tick only (no network, no Python bridge)."}
    for fam, mean, step, tape in (
        ("ladder_pair", 26.5, 5.5, "synthetic ladder tape (LCG seed 42): rich bid 0.50 + 0.08 z vs cheap ask 0.47, "
                                   "fee rate 0.02, tick 0.01, quote age 0 to 89 s"),
        ("touch_ticket_reference", 26.3, 3.5, "synthetic ticket tape (LCG seed 42): bid 0.30 + 0.10 z, central "
                                              "reference 0.28, validated on every other tick")))

CONTRACT_MECHANISM = {
    "ladder_rung": "ladders",
    "touch_ticket": "touch",
    "close_above_ticket": "other",
    "btc_15min": "btc_15min",
    "btc_15m_watch": "btc_15min",
    "other": "other",
}
REFERENCE_FOR = {"close_above_ticket": "foundation"}
TOUCH_SELL_THRESHOLD_POINTS = 5.0


def contract_key(res: dict | None) -> str:
    res = res or {}
    if res.get("mechanism") == "btc_15m_watch":
        return "btc_15min"
    return str(res.get("type") or "other")


def _with_disk(n: dict) -> dict:
    return {**n, "result_file_on_disk": (REPO / n["result_file"]).is_file()}


def _served(m: dict) -> dict:
    return {**m, "status_label": STATUS_LABELS[m["status"]], "numbers": [_with_disk(n) for n in m["numbers"]],
            "caveats": list(m["caveats"])}


def mechanisms() -> list[dict]:
    return [_served(m) for m in MECHANISMS]


def mechanism(mechanism_id: str) -> dict | None:
    for m in MECHANISMS:
        if m["id"] == mechanism_id:
            return _served(m)
    return None


def mechanism_for(contract_type: str | None) -> dict:
    mid = CONTRACT_MECHANISM.get((contract_type or "other").strip().lower(), "other")
    m = mechanism(mid)
    assert m is not None
    return {**m, "contract_type": contract_type or "other",
            "trade_mechanism": bool(m["actions_allowed"]["trade"]) and m["status"] != FAILED}


def system_numbers() -> list[dict]:
    return [_with_disk(n) for n in SYSTEM_NUMBERS]


def registry() -> dict:
    return {"source_of_truth": "note/NOTE.md", "statuses": dict(STATUS_LABELS), "mechanisms": mechanisms(),
            "system": system_numbers(), "contract_types": dict(CONTRACT_MECHANISM),
            "reference_for": dict(REFERENCE_FOR), "touch_sell_threshold_points": TOUCH_SELL_THRESHOLD_POINTS,
            "micro_bench": [dict(b) for b in MICRO_BENCH],
            "forward_tests_start": FORWARD_START}
