# PolyBridge Research Pipeline Implementation Plan (plan #2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the pre-registered hypothesis into the scored deliverable: a notebook that, from a clean kernel with only `MASSIVE_API_KEY`, builds the H1/H2 event tables, prices every event from the option chain, measures strategy P&L and the parity ratio against a placebo, evaluates the pre-registered pass rule, runs the exploratory atlas, and costs the trade. It stops before the out-of-sample run, which happens once after the method freeze.

**Architecture:** The Massive starter's notebook logic is ported into small, tested modules of `polybridge_research` (config, calendar, events, timing, pricing, evaluate, analysis, costs, atlas, pipeline). Module functions take a `MassiveClient`, a `TradingCalendar` and a `StudyConfig` explicitly instead of reading notebook globals, so every piece is testable offline with a fake client. A generated notebook (`research/polybridge_8k.ipynb`) only orchestrates and displays.

**Tech Stack:** Python ≥ 3.10, pandas, numpy, requests, matplotlib (the starter's floors), `concurrent.futures` for parallel pricing, `nbformat` (ships with jupyterlab) to generate the notebook, pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-polybridge-design.md` (v3), `research/HYPOTHESIS.md`, `research/HYPOTHESIS_TAGS.md`, `docs/contracts.md`. The starter notebook `research/starter/gqh-massive-8k-starter/gator-quant-hacks-8k-options-challenge.ipynb` is the reference implementation being ported.

## Global Constraints

- Nothing in `research/` imports `hedgecore` or calls an LLM. The notebook needs only `MASSIVE_API_KEY` (an optional `SEC_USER_AGENT` improves timing but is never required).
- Python ≥ 3.10; dependencies stay `pandas>=2.2`, `numpy>=2.0`, `requests>=2.31`, `matplotlib>=3.8` (+ `ipykernel`, `jupyterlab` for running).
- Fixed by pre-registration (HYPOTHESIS.md §3): universe `TOP_100` (the starter's list); in-sample 2024-01-01 → 2025-12-31; OOS 2026-01-01 → 2026-08-31; headline bucket `3-6m` = (90, 180, 120) days; put 5% OTM; entry `"post"`; horizons `1, 2, 3, 5, 10, 21, 42, 63` + `"exp"`; headline horizons 21, 42, expiry; costs 5% of premium per side and 2×.
- Families: H1 hedge = `material_litigation, class_action_filing, regulatory_investigation, cybersecurity_incident, goodwill_impairment, asset_impairment, investment_impairment` → `protective_put`; H2 opportunity = `restructuring_plan, workforce_reduction, facility_closure, business_line_exit` → `cash_secured_put`. A filing (accession number) carrying tags from both families is excluded from both and counted.
- Parity: `implied = (C_K + P_K) / S_entry` read on `t_pre` (entry `"pre"` slice); `implied_scaled = implied * sqrt(sessions_held / dte_sessions)`; `ratio = |S_exit / S_entry − 1| / implied_scaled`.
- Pass rule (HYPOTHESIS.md §4): event-minus-placebo edge of the family's strategy has a **97.5%** bootstrap CI excluding zero in the predicted direction (H1 > 0, H2 > 0 for the strategy's P&L) at ≥ 2 of {21, 42, exp}; and the ratio condition in the predicted direction (H1 above placebo, H2 below) at those same horizons.
- The OOS window is never run by any task in this plan. The notebook's OOS cell is guarded by `RUN_OOS = False`.
- No raw API responses, `.massive_cache/`, `.env` or licensed data are committed. Derived aggregate tables and figures may be committed under `research/results/`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Decisions this plan needs from the human (defaults used until answered)

| ID | Decision | Default in this plan |
|---|---|---|
| D1 | SEC `User-Agent` contact for EDGAR acceptance times (sent to sec.gov) | Unset → conservative timing: every filing is treated as after the close, so `t_0` = next session. No lookahead, slightly later entries. |
| D2 | Placebo size per family | 200 ordinary days (starter: 120) |
| D3 | Atlas scope | All 119 tags, baseline spec only, capped at 30 events per tag (seeded sample), one shared 300-day placebo over `TOP_100` |
| D4 | Ratio condition of the pass rule | Point estimate in the predicted direction at the same horizons (literal reading of §4); the CI is reported alongside |
| D5 | Costs | Real half-spreads from Massive options quotes at entry and exit for the headline strategies, next to the pre-registered 5% haircut (1× and 2×) |
| D6 | Notebook smoke test in CI with a repo secret | No secret in CI; the clean-kernel run is done locally |
| D7 | Method freeze | Human decision after reviewing in-sample results (Task 12 stops there) |

When D1, D2 or D4 is answered differently from the default, the controller applies it before Task 12 runs. Any answer to D4 is also written into the `research/HYPOTHESIS.md` change log as a clarification, committed before any H1/H2 result exists.

## Review Focus

- **The API returns nothing for a tag, a ticker or a window** (rare tags, sealed windows with no events): every stage returns an empty DataFrame with the right columns and the notebook prints "no events", never a `KeyError`. Pinned in Tasks 3 and 9.
- **A filing accepted after 16:00 ET or on a weekend**: `t_0` never lands on the filing day's close. Pinned in Task 4.
- **Illiquid or missing option legs**: the event is dropped with a reason, never priced at 0. Pinned in Task 5.
- **Parallel pricing with a shared on-disk cache**: two threads writing the same URL never corrupt the cache. Pinned in Task 5.
- **Horizons that have not resolved yet** (events near the window end, or after today): those rows are absent, not zero. Pinned in Task 6.

---

## File structure

```
research/polybridge_research/
  config.py      StudyConfig, TOP_100, EXPIRY_BUCKETS, HORIZONS
  calendar.py    NYSEHolidays, TradingCalendar
  events.py      fetch_disclosures, build_confirmatory_events, build_tag_events
  timing.py      fetch_acceptance_time, apply_filing_session
  pricing.py     option_bars, fetch_chain, locate_spot, pick_expiry, select_strikes, Leg, PricedEvent, price_event, price_events
  evaluate.py    evaluate
  analysis.py    slice_results, scoreboard, difference_board, sample_placebo, decay_table, pass_check
  costs.py       half_spread, cost_table
  atlas.py       run_atlas, count_variants
  pipeline.py    run_family_study
  massive.py     (modified: unique temp file per write, thread-safe sessions)
research/tests/
  fakes.py       FakeClient: disclosures, chains and option bars from formulas
  test_config.py test_calendar.py test_events.py test_timing.py test_pricing.py
  test_evaluate.py test_analysis.py test_costs.py test_atlas.py test_pipeline.py test_notebook.py
research/make_notebook.py      generates research/polybridge_8k.ipynb (no outputs)
research/polybridge_8k.ipynb   the judged notebook
research/results/in_sample/    derived tables + figures from the in-sample run (Task 12)
```

---

### Task 1: Pipeline and entitlement check (no code)

**Files:** none committed except `research/results/pipeline_check.md`.

**Interfaces:** Produces a written record that the key reaches disclosures, contracts, aggregates and quotes, and that the starter runs end to end on a tag that is not ours.

- [ ] **Step 1: Run the starter on its own example, small**

Run:
```bash
cd research/starter/gqh-massive-8k-starter
cp ../../.env .env   # gitignored by the starter's .gitignore
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt nbconvert
sed -e 's/^MAX_EVENTS = None/MAX_EVENTS = 8/' -e 's/^RUN_PLACEBO = True/RUN_PLACEBO = False/' -e 's/^FETCH_ACCEPTANCE_TIMES = True/FETCH_ACCEPTANCE_TIMES = False/' \
  gator-quant-hacks-8k-options-challenge.ipynb > /tmp/starter_check.ipynb
.venv/bin/jupyter nbconvert --to notebook --execute /tmp/starter_check.ipynb --output /tmp/starter_check_out.ipynb --ExecutePreprocessor.timeout=1200 2>&1 | tail -3
rm .env
```
Expected: `[NbConvertApp] Writing ... starter_check_out.ipynb`. The tag is `cfo_appointment`, which is in neither H1 nor H2, so no confirmatory result is seen.

Note: the starter's out-of-sample section runs on `cfo_appointment` only. That is not our hypothesis's OOS window being peeked at, because the tag is outside both families.

- [ ] **Step 2: Record the check**

`research/results/pipeline_check.md`:
```markdown
# Pipeline check (2026-10-02)

- Starter notebook executed end to end on `cfo_appointment` (not an H1/H2 tag), MAX_EVENTS=8, placebo off.
- Endpoints reached with the team key: 8-K disclosures, disclosure taxonomy, options contracts, option daily aggregates, option quotes (`/v3/quotes/{optionTicker}`).
- No H1/H2 event, price or result was fetched or viewed.
```

- [ ] **Step 3: Commit**

```bash
git add research/results/pipeline_check.md
git commit -m "Research: pipeline and entitlement check on a non-hypothesis tag

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Study configuration and trading calendar

**Files:**
- Create: `research/polybridge_research/config.py`, `research/polybridge_research/calendar.py`
- Test: `research/tests/test_config.py`, `research/tests/test_calendar.py`

**Interfaces:**
- Produces:
  - `TOP_100: tuple[str, ...]` (100 unique tickers, the starter's list), `EXPIRY_BUCKETS: dict[str, tuple[int, int, int]]`, `HORIZONS: tuple[int, ...]`
  - `@dataclass(frozen=True) StudyConfig` with fields and defaults listed in Step 3, plus `validate() -> None` and `with_window(start: str, end: str) -> StudyConfig`
  - `class TradingCalendar(start="2021-06-01", end="2027-12-31")` with `sessions: pd.DatetimeIndex`, `on_or_after(day)`, `before(day)`, `after(day)`, `between(a, b) -> int`, `offset(day, n) -> pd.Timestamp | None`, `last_completed(today=None) -> pd.Timestamp`

- [ ] **Step 1: Write the failing tests**

`research/tests/test_config.py`:
```python
import pytest

from polybridge_research.config import EXPIRY_BUCKETS, HORIZONS, TOP_100, StudyConfig


def test_universe_and_fixed_values_match_preregistration():
    assert len(TOP_100) == 100 and len(set(TOP_100)) == 100
    assert "BRK.B" in TOP_100 and "AAPL" in TOP_100
    assert HORIZONS == (1, 2, 3, 5, 10, 21, 42, 63)
    assert EXPIRY_BUCKETS["3-6m"] == (90, 180, 120)
    cfg = StudyConfig()
    assert (cfg.study_start, cfg.study_end, cfg.oos_start, cfg.oos_end) == (
        "2024-01-01", "2025-12-31", "2026-01-01", "2026-08-31")
    assert (cfg.baseline_bucket, cfg.otm_pct, cfg.entry, cfg.cost_haircut) == ("3-6m", 0.05, "post", 0.05)
    assert cfg.headline_horizons == (21, 42, "exp")
    assert cfg.confirmatory_level == 0.975
    cfg.validate()


def test_validate_rejects_impossible_dates_and_bad_choices():
    with pytest.raises(ValueError, match="study_end"):
        StudyConfig(study_end="2025-06-31").validate()
    with pytest.raises(ValueError, match="before"):
        StudyConfig(study_start="2026-01-01", study_end="2025-01-01").validate()
    with pytest.raises(ValueError, match="otm_pct"):
        StudyConfig(otm_pct=0.07).validate()


def test_with_window_keeps_everything_else():
    cfg = StudyConfig().with_window("2023-06-01", "2023-08-31")
    assert (cfg.study_start, cfg.study_end) == ("2023-06-01", "2023-08-31")
    assert cfg.otm_pct == 0.05
```

`research/tests/test_calendar.py`:
```python
import pandas as pd

from polybridge_research.calendar import TradingCalendar

CAL = TradingCalendar()
T = pd.Timestamp


def test_nyse_specific_closures_and_openings():
    s = set(CAL.sessions)
    assert T("2025-01-09") not in s          # national day of mourning, President Carter
    assert T("2024-03-29") not in s          # Good Friday
    assert T("2024-10-14") in s              # Columbus Day: NYSE open
    assert T("2024-11-11") in s              # Veterans Day: NYSE open
    assert T("2024-07-04") not in s


def test_navigation():
    assert CAL.on_or_after("2024-06-08") == T("2024-06-10")   # Saturday -> Monday
    assert CAL.on_or_after("2024-06-10") == T("2024-06-10")
    assert CAL.before("2024-06-10") == T("2024-06-07")
    assert CAL.after("2024-06-07") == T("2024-06-10")
    assert CAL.between("2024-06-07", "2024-06-12") == 3
    assert CAL.offset("2024-06-07", 2) == T("2024-06-11")
    assert CAL.offset("2027-12-30", 10) is None


def test_last_completed_session():
    assert CAL.last_completed(T("2024-06-09")) == T("2024-06-07")   # Sunday -> Friday
    assert CAL.last_completed(T("2024-06-10")) == T("2024-06-10")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd research && .venv/bin/python -m pytest tests/test_config.py tests/test_calendar.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`research/polybridge_research/config.py`:
```python
"""Study configuration. Defaults are the pre-registered values (HYPOTHESIS.md §3) and the starter's mechanics."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import pandas as pd

TOP_100: tuple[str, ...] = tuple("""
AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY BRK.B C
CAT CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR FDX GD GE GILD
GM GOOGL GS HD HON IBM INTC INTU ISRG JNJ JPM KO LIN LLY LMT LOW MA MCD MDLZ MDT
MET META MMM MO MRK MS MSFT NEE NFLX NKE NOW NVDA ORCL PEP PFE PG PLTR PM PYPL QCOM
RTX SBUX SCHW SO T TGT TMO TMUS TSLA TXN UBER UNH UNP UPS USB V VZ WFC WMT XOM
""".split())

EXPIRY_BUCKETS: dict[str, tuple[int, int, int]] = {"1m": (21, 45, 30), "2m": (46, 80, 60), "3-6m": (90, 180, 120)}
HORIZONS: tuple[int, ...] = (1, 2, 3, 5, 10, 21, 42, 63)


@dataclass(frozen=True)
class StudyConfig:
    study_start: str = "2024-01-01"
    study_end: str = "2025-12-31"
    oos_start: str = "2026-01-01"
    oos_end: str = "2026-08-31"
    universe: tuple[str, ...] = TOP_100
    buckets: dict = field(default_factory=lambda: dict(EXPIRY_BUCKETS))
    baseline_bucket: str = "3-6m"
    horizons: tuple[int, ...] = HORIZONS
    headline_horizons: tuple = (21, 42, "exp")
    otm_pct: float = 0.05
    otm_grid: tuple[float, ...] = (0.03, 0.05, 0.10)
    entry: str = "post"
    risk_free: float = 0.04
    strike_window: float = 0.25
    max_stale_sessions: int = 3
    n_placebo: int = 200
    placebo_gap_days: int = 30
    cost_haircut: float = 0.05
    confirmatory_level: float = 0.975

    def validate(self) -> None:
        for name in ("study_start", "study_end", "oos_start", "oos_end"):
            try:
                pd.Timestamp(getattr(self, name))
            except ValueError:
                raise ValueError(f"{name} = {getattr(self, name)!r} is not a real date") from None
        if not (self.study_start < self.study_end and self.oos_start < self.oos_end):
            raise ValueError("each window's start must be before its end")
        if self.otm_pct not in self.otm_grid:
            raise ValueError("otm_pct must be one of otm_grid")
        if self.baseline_bucket not in self.buckets:
            raise ValueError("baseline_bucket must be one of buckets")
        if self.entry not in ("pre", "post"):
            raise ValueError("entry must be 'pre' or 'post'")

    def with_window(self, start: str, end: str) -> "StudyConfig":
        return dataclasses.replace(self, study_start=start, study_end=end)
```

`research/polybridge_research/calendar.py`:
```python
"""NYSE trading calendar without a stock feed (Massive starter, section 3)."""
from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay, USThanksgivingDay, nearest_workday)
from pandas.tseries.offsets import CustomBusinessDay


class NYSEHolidays(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=lambda d: d + pd.Timedelta(days=1) if d.weekday() == 6 else d),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
        Holiday("National day of mourning, President Carter", year=2025, month=1, day=9),
    ]


class TradingCalendar:
    def __init__(self, start: str = "2021-06-01", end: str = "2027-12-31"):
        hol = NYSEHolidays().holidays(pd.Timestamp(start) - pd.Timedelta(days=7), pd.Timestamp(end) + pd.Timedelta(days=7))
        self.sessions = pd.bdate_range(start, end, freq=CustomBusinessDay(holidays=hol))

    def on_or_after(self, day) -> pd.Timestamp:
        return self.sessions[self.sessions.searchsorted(pd.Timestamp(day), side="left")]

    def before(self, day) -> pd.Timestamp:
        return self.sessions[self.sessions.searchsorted(pd.Timestamp(day), side="left") - 1]

    def after(self, day) -> pd.Timestamp:
        return self.sessions[self.sessions.searchsorted(pd.Timestamp(day), side="right")]

    def between(self, a, b) -> int:
        """Sessions strictly after `a` up to and including `b`."""
        return int(self.sessions.searchsorted(pd.Timestamp(b), side="right")
                   - self.sessions.searchsorted(pd.Timestamp(a), side="right"))

    def offset(self, day, n: int) -> pd.Timestamp | None:
        i = self.sessions.searchsorted(pd.Timestamp(day), side="left") + n
        return self.sessions[i] if 0 <= i < len(self.sessions) else None

    def last_completed(self, today=None) -> pd.Timestamp:
        today = pd.Timestamp.today().normalize() if today is None else pd.Timestamp(today)
        return self.sessions[self.sessions.searchsorted(today, side="right") - 1]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_config.py tests/test_calendar.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/config.py research/polybridge_research/calendar.py research/tests/test_config.py research/tests/test_calendar.py
git commit -m "Research: study config (pre-registered values) and NYSE trading calendar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Fake client and confirmatory event tables

**Files:**
- Create: `research/tests/fakes.py`, `research/polybridge_research/events.py`
- Test: `research/tests/test_events.py`

**Interfaces:**
- Consumes: `schema.H1_TAGS`, `H2_TAGS`, `assign_family`, `normalize_ticker`; `TradingCalendar`.
- Produces:
  - `DISCLOSURES = "/stocks/filings/8-K/vX/disclosures"`
  - `fetch_disclosures(client, tag: str, start: str, end: str) -> pd.DataFrame`
  - `build_confirmatory_events(client, start, end, universe, cal) -> tuple[pd.DataFrame, pd.DataFrame]`: (events, excluded). `events` columns: `ticker, cik, filing_date, accession_number, filing_url, supporting_text, tags (frozenset), family ("hedge"|"opportunity"), t_0, t_pre`. `excluded` columns: `accession_number, ticker, filing_date, tags`.
  - `build_tag_events(client, tag, start, end, universe, cal) -> pd.DataFrame` with the same columns minus `family` (for the atlas).
  - Both return empty DataFrames with those columns when nothing matches.
  - `t_0`/`t_pre` here are the naive starter values (first session on or after the filing date); Task 4's `apply_filing_session` refines them.
  - `tests/fakes.py`: `FakeClient(disclosures: dict[str, list[dict]] = None, market: FakeMarket | None = None)` with `get_all(path, params=None, max_pages=500)` and `get(path_or_url, params=None)`; `FakeMarket` is added in Task 5.

- [ ] **Step 1: Write the fake client and failing tests**

`research/tests/fakes.py`:
```python
"""Offline stand-in for MassiveClient. Disclosures come from a dict keyed by tag; market data from FakeMarket."""
from __future__ import annotations


def disclosure(accession: str, cik: str, tickers: list[str], filing_date: str, text: str = "") -> dict:
    return {"accession_number": accession, "cik": cik, "tickers": tickers, "filing_date": filing_date,
            "filing_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt", "supporting_text": text}


class FakeClient:
    def __init__(self, disclosures: dict[str, list[dict]] | None = None, market=None):
        self.disclosures = disclosures or {}
        self.market = market
        self.calls: list[tuple[str, dict]] = []

    def get_all(self, path: str, params: dict | None = None, max_pages: int = 500) -> list[dict]:
        params = params or {}
        self.calls.append((path, params))
        if path == "/stocks/filings/8-K/vX/disclosures":
            rows = self.disclosures.get(params["tertiary_category"], [])
            lo, hi = params.get("filing_date.gte", "0000"), params.get("filing_date.lte", "9999")
            return [r for r in rows if lo <= r["filing_date"] <= hi]
        if self.market is not None:
            return self.market.get_all(path, params)
        return []

    def get(self, path_or_url: str, params: dict | None = None) -> dict:
        return {"results": self.get_all(path_or_url, params)}
```

`research/tests/test_events.py`:
```python
import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.events import build_confirmatory_events, build_tag_events
from tests.fakes import FakeClient, disclosure

CAL = TradingCalendar()
UNIVERSE = ("AAPL", "MSFT", "BRK.B")


def _client():
    return FakeClient({
        "material_litigation": [disclosure("a1", "1", ["AAPL"], "2024-03-01"),
                                disclosure("a9", "9", ["ZZZZ"], "2024-03-01")],          # outside the universe
        "class_action_filing": [disclosure("a1", "1", ["AAPL"], "2024-03-01")],          # same filing, second H1 tag
        "restructuring_plan": [disclosure("a2", "2", ["MSFT"], "2024-05-04"),            # a Saturday
                               disclosure("a3", "3", ["BRK/B"], "2024-06-03")],
        "asset_impairment": [disclosure("a3", "3", ["BRK/B"], "2024-06-03")],            # a3 is cross-family
    })


def test_one_event_per_filer_date_family_and_tag_union():
    ev, excluded = build_confirmatory_events(_client(), "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert list(ev.ticker) == ["AAPL", "MSFT"]
    aapl = ev.iloc[0]
    assert aapl.family == "hedge" and aapl.tags == frozenset({"material_litigation", "class_action_filing"})
    assert ev.iloc[1].family == "opportunity"


def test_cross_family_filing_is_excluded_and_counted():
    ev, excluded = build_confirmatory_events(_client(), "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert "BRK.B" not in set(ev.ticker)
    assert list(excluded.accession_number) == ["a3"]
    assert excluded.iloc[0].ticker == "BRK.B"


def test_naive_sessions_from_filing_date():
    ev, _ = build_confirmatory_events(_client(), "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    msft = ev[ev.ticker == "MSFT"].iloc[0]
    assert msft.t_0 == pd.Timestamp("2024-05-06") and msft.t_pre == pd.Timestamp("2024-05-03")


def test_window_filter_and_empty_result_has_columns():
    ev, excluded = build_confirmatory_events(_client(), "2025-01-01", "2025-12-31", UNIVERSE, CAL)
    assert ev.empty and excluded.empty
    assert {"ticker", "family", "t_0", "t_pre", "tags"} <= set(ev.columns)


def test_build_tag_events_single_tag():
    ev = build_tag_events(_client(), "restructuring_plan", "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert list(ev.ticker) == ["MSFT", "BRK.B"]
    empty = build_tag_events(_client(), "cfo_appointment", "2024-01-01", "2024-12-31", UNIVERSE, CAL)
    assert empty.empty and "t_0" in empty.columns
```

- [ ] **Step 2: Make `tests` importable and run to verify failure**

Create empty `research/tests/__init__.py` (so `from tests.fakes import ...` works; pytest runs from `research/`). Then add to `research/pyproject.toml` under `[tool.pytest.ini_options]`: `pythonpath = ["."]`.

Run: `cd research && .venv/bin/python -m pytest tests/test_events.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybridge_research.events'`

- [ ] **Step 3: Implement**

`research/polybridge_research/events.py`:
```python
"""8-K event tables (Massive starter, section 4), with the pre-registered family rules (HYPOTHESIS_TAGS.md)."""
from __future__ import annotations

import pandas as pd

from .calendar import TradingCalendar
from .schema import H1_TAGS, H2_TAGS, assign_family, normalize_ticker

DISCLOSURES = "/stocks/filings/8-K/vX/disclosures"
_BASE_COLS = ["ticker", "cik", "filing_date", "accession_number", "filing_url", "supporting_text", "tags", "t_0", "t_pre"]


def fetch_disclosures(client, tag: str, start: str, end: str) -> pd.DataFrame:
    rows = client.get_all(DISCLOSURES, {"tertiary_category": tag, "filing_date.gte": start, "filing_date.lte": end,
                                        "limit": 1000, "sort": "filing_date.asc"})
    df = pd.DataFrame(rows)
    if not df.empty:
        df["filing_date"] = pd.to_datetime(df["filing_date"])
        df["tag"] = tag
    return df


def _in_universe(raw: pd.DataFrame, universe) -> pd.DataFrame:
    ex = raw.explode("tickers").rename(columns={"tickers": "ticker"})
    ex["ticker"] = ex["ticker"].map(normalize_ticker)
    return ex[ex["ticker"].isin(set(universe))]


def _per_filing(ex: pd.DataFrame) -> pd.DataFrame:
    return (ex.sort_values(["cik", "filing_date"])
              .groupby("accession_number", as_index=False)
              .agg(ticker=("ticker", "first"), cik=("cik", "first"), filing_date=("filing_date", "first"),
                   filing_url=("filing_url", "first"), supporting_text=("supporting_text", "first"),
                   tags=("tag", lambda s: frozenset(s))))


def _collapse(per_filing: pd.DataFrame, keys: list[str], cal: TradingCalendar) -> pd.DataFrame:
    ev = (per_filing.sort_values(["cik", "filing_date", "accession_number"])
                    .groupby(keys, as_index=False)
                    .agg(ticker=("ticker", "first"), accession_number=("accession_number", "first"),
                         filing_url=("filing_url", "first"), supporting_text=("supporting_text", "first"),
                         tags=("tags", lambda s: frozenset().union(*s)))
                    .sort_values(["filing_date", "ticker"]).reset_index(drop=True))
    ev["t_0"] = ev["filing_date"].map(cal.on_or_after)
    ev["t_pre"] = ev["t_0"].map(cal.before)
    return ev


def build_confirmatory_events(client, start: str, end: str, universe, cal: TradingCalendar) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = [f for f in (fetch_disclosures(client, t, start, end) for t in sorted(H1_TAGS | H2_TAGS)) if not f.empty]
    empty_ev = pd.DataFrame(columns=_BASE_COLS + ["family"])
    empty_ex = pd.DataFrame(columns=["accession_number", "ticker", "filing_date", "tags"])
    if not frames:
        return empty_ev, empty_ex
    ex = _in_universe(pd.concat(frames, ignore_index=True), universe)
    if ex.empty:
        return empty_ev, empty_ex
    pf = _per_filing(ex)
    fam = pf["tags"].map(assign_family)
    excluded = pf[fam.isna()][["accession_number", "ticker", "filing_date", "tags"]].reset_index(drop=True)
    keep = pf[fam.notna()].assign(family=fam[fam.notna()].map(lambda f: f.value))
    if keep.empty:
        return empty_ev, excluded
    ev = _collapse(keep, ["cik", "filing_date", "family"], cal)
    return ev[_BASE_COLS + ["family"]], excluded


def build_tag_events(client, tag: str, start: str, end: str, universe, cal: TradingCalendar) -> pd.DataFrame:
    raw = fetch_disclosures(client, tag, start, end)
    if raw.empty:
        return pd.DataFrame(columns=_BASE_COLS)
    ex = _in_universe(raw, universe)
    if ex.empty:
        return pd.DataFrame(columns=_BASE_COLS)
    return _collapse(_per_filing(ex), ["cik", "filing_date"], cal)[_BASE_COLS]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_events.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add research/tests/__init__.py research/tests/fakes.py research/polybridge_research/events.py research/tests/test_events.py research/pyproject.toml
git commit -m "Research: confirmatory event tables with filing-level cross-family exclusion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Filing-session timing without lookahead

**Files:**
- Create: `research/polybridge_research/timing.py`
- Test: `research/tests/test_timing.py`

**Interfaces:**
- Consumes: `TradingCalendar`.
- Produces:
  - `fetch_acceptance_time(filing_url: str, user_agent: str, cache_dir: Path, session=None, sleep=time.sleep) -> pd.Timestamp | None` (US/Eastern wall time, naive)
  - `apply_filing_session(events: pd.DataFrame, cal: TradingCalendar, accepted_at: pd.Series | None = None) -> pd.DataFrame` returning a copy with `t_0`, `t_pre` recomputed and a new `timing` column: `"edgar"` when an acceptance time is known, `"conservative"` otherwise.
  - Rule with an acceptance time `a`: `t_0 = on_or_after(a.date())`; if `a.date()` is a session and `a.time() >= 16:00`, `t_0 = after(a.date())`.
  - Conservative rule (no acceptance time): if `filing_date` is a session, `t_0 = after(filing_date)`; else `t_0 = on_or_after(filing_date)`. `t_pre = before(t_0)` always.

- [ ] **Step 1: Write the failing tests**

`research/tests/test_timing.py`:
```python
import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.timing import apply_filing_session, fetch_acceptance_time

CAL = TradingCalendar()
T = pd.Timestamp


def _events():
    return pd.DataFrame({"ticker": ["A", "B", "C"],
                         "filing_date": [T("2024-06-05"), T("2024-06-05"), T("2024-06-08")],   # Wed, Wed, Sat
                         "t_0": [T("2024-06-05")] * 2 + [T("2024-06-10")],
                         "t_pre": [T("2024-06-04")] * 2 + [T("2024-06-07")]})


def test_edgar_before_and_after_the_close():
    acc = pd.Series([T("2024-06-05 09:15"), T("2024-06-05 16:30"), pd.NaT])
    out = apply_filing_session(_events(), CAL, acc)
    assert list(out.t_0) == [T("2024-06-05"), T("2024-06-06"), T("2024-06-10")]
    assert list(out.t_pre) == [T("2024-06-04"), T("2024-06-05"), T("2024-06-07")]
    assert list(out.timing) == ["edgar", "edgar", "conservative"]


def test_conservative_without_acceptance_times():
    out = apply_filing_session(_events(), CAL, None)
    assert list(out.t_0) == [T("2024-06-06"), T("2024-06-06"), T("2024-06-10")]   # weekday -> next session; weekend -> Monday
    assert set(out.timing) == {"conservative"}


def test_does_not_mutate_input():
    ev = _events()
    apply_filing_session(ev, CAL, None)
    assert ev.t_0.iloc[0] == T("2024-06-05")


class _Resp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass
    def iter_content(self, n, decode_unicode=True): yield self.text


class _Session:
    def __init__(self, text): self.text, self.calls = text, 0
    def get(self, url, headers, timeout, stream):
        self.calls += 1
        assert headers["User-Agent"] == "Team x@y.edu"
        return _Resp(self.text)


def test_fetch_acceptance_time_parses_and_caches(tmp_path):
    s = _Session("<SEC-HEADER>\n<ACCEPTANCE-DATETIME>20240605163012\n")
    url = "https://www.sec.gov/Archives/edgar/data/1/a1.txt"
    assert fetch_acceptance_time(url, "Team x@y.edu", tmp_path, session=s, sleep=lambda x: None) == T("2024-06-05 16:30:12")
    assert fetch_acceptance_time(url, "Team x@y.edu", tmp_path, session=s, sleep=lambda x: None) == T("2024-06-05 16:30:12")
    assert s.calls == 1


def test_fetch_acceptance_time_missing_header_is_none(tmp_path):
    s = _Session("no header here")
    assert fetch_acceptance_time("https://x/y.txt", "Team x@y.edu", tmp_path, session=s, sleep=lambda x: None) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_timing.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`research/polybridge_research/timing.py`:
```python
"""When could a filing first be traded? EDGAR acceptance time when known; otherwise assume after the close.

The conservative fallback means the notebook never needs anything but the Massive key and never trades on
information before it was public. An optional SEC_USER_AGENT enables acceptance times (sec.gov asks for a
contact in the User-Agent and at most 10 requests per second).
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import pandas as pd
import requests

from .calendar import TradingCalendar

_CLOSE = pd.Timestamp("16:00").time()


def fetch_acceptance_time(filing_url: str, user_agent: str, cache_dir: Path, session=None,
                          sleep=time.sleep) -> pd.Timestamp | None:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_dir / ("sec_" + hashlib.sha1(filing_url.encode()).hexdigest() + ".txt")
    if key.exists():
        head = key.read_text()
    else:
        resp = (session or requests).get(filing_url, headers={"User-Agent": user_agent}, timeout=30, stream=True)
        resp.raise_for_status()
        head = next(resp.iter_content(4096, decode_unicode=True))
        key.write_text(head)
        sleep(0.12)
    m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", head)
    return pd.Timestamp(m.group(1)) if m else None


def _t0(filing_date: pd.Timestamp, accepted: pd.Timestamp | None, cal: TradingCalendar) -> tuple[pd.Timestamp, str]:
    sessions = set(cal.sessions)
    if accepted is not None and not pd.isna(accepted):
        day = accepted.normalize()
        if day in sessions and accepted.time() >= _CLOSE:
            return cal.after(day), "edgar"
        return cal.on_or_after(day), "edgar"
    day = pd.Timestamp(filing_date).normalize()
    return (cal.after(day) if day in sessions else cal.on_or_after(day)), "conservative"


def apply_filing_session(events: pd.DataFrame, cal: TradingCalendar, accepted_at: pd.Series | None = None) -> pd.DataFrame:
    out = events.copy()
    acc = list(accepted_at) if accepted_at is not None else [None] * len(out)
    pairs = [_t0(fd, a, cal) for fd, a in zip(out["filing_date"], acc)]
    out["t_0"] = [p[0] for p in pairs]
    out["timing"] = [p[1] for p in pairs]
    out["t_pre"] = out["t_0"].map(cal.before)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_timing.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/timing.py research/tests/test_timing.py
git commit -m "Research: filing-session timing (EDGAR acceptance, conservative fallback, no lookahead)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pricing from the option chain, in parallel, with a thread-safe cache

**Files:**
- Create: `research/polybridge_research/pricing.py`
- Modify: `research/polybridge_research/massive.py` (unique temp file per write; one `requests.Session` per thread), `research/tests/fakes.py` (add `FakeMarket`)
- Test: `research/tests/test_pricing.py`, add one test to `research/tests/test_massive.py`

**Interfaces:**
- Consumes: `TradingCalendar`, `StudyConfig`, a client with `get_all`.
- Produces (ported from the starter, section 5, with explicit arguments instead of globals):
  - `option_bars(client, opt_ticker, start, end) -> pd.DataFrame` (index `session`, columns `close`, `volume`)
  - `fetch_chain(client, ticker, as_of, dte_lo, dte_hi) -> pd.DataFrame` (columns `ticker, contract_type, strike_price, expiration_date, dte`)
  - `locate_spot(client, chain, day, risk_free, max_iter=8) -> dict | None` (`spot, strike, expiry, dte`)
  - `pick_expiry(chain, lo, hi, target) -> pd.Timestamp | None`
  - `select_strikes(e, spot, otm_pcts, strike_window) -> dict[str, float] | None` (keys `K`, `U{pct}`, `L{pct}`)
  - `@dataclass Leg(ticker, kind, strike, bars, cal, max_stale)` with `mark(day) -> float` and `volume_on(day) -> float`
  - `@dataclass PricedEvent(ticker, event_date, t_pre, t_0, bucket, expiry, expiry_session, spot_pre, strikes, legs, risk_free, family=None)` with `marks(day)` and `synthetic_spot(day, m=None)`
  - `price_event(client, row, cal, cfg, buckets) -> tuple[list[PricedEvent], list[str]]` where `row` has `ticker, t_pre, t_0, filing_date` and optional `family`
  - `price_events(client, events, cal, cfg, buckets=None, max_workers=8, label="events") -> tuple[list[PricedEvent], pd.DataFrame]` (dropped: `ticker, t_0, reason`); output order is the input order regardless of thread completion order.
  - `FakeMarket(spot_by_ticker: dict[str, float], start="2023-01-02", end="2026-12-31")`: chains with strikes spot±40% in 5% steps, weekly expiries plus monthlies to 200 days, and every leg trading every session at `max(intrinsic, 0) + 1.0`. A ticker named `"ILLQ"` has a chain but no bars.

- [ ] **Step 1: Add FakeMarket to the fakes**

Append to `research/tests/fakes.py`:
```python
import datetime as _dt

import pandas as _pd


def _occ(underlying: str, expiry: _pd.Timestamp, kind: str, strike: float) -> str:
    return f"O:{underlying}{expiry:%y%m%d}{'C' if kind == 'call' else 'P'}{int(round(strike * 1000)):08d}"


class FakeMarket:
    """Deterministic option market: flat spot per ticker; every leg trades at intrinsic + 1.0 each session."""

    def __init__(self, spot_by_ticker: dict[str, float], start: str = "2023-01-02", end: str = "2026-12-31"):
        self.spot = spot_by_ticker
        self.days = _pd.bdate_range(start, end)

    def _expiries(self, as_of: _pd.Timestamp) -> list[_pd.Timestamp]:
        fridays = _pd.date_range(as_of, as_of + _pd.Timedelta(days=200), freq="W-FRI")
        return list(fridays)

    def _contracts(self, underlying: str, as_of: _pd.Timestamp, lo: _pd.Timestamp, hi: _pd.Timestamp) -> list[dict]:
        s = self.spot[underlying]
        strikes = [round(s * (1 + k / 100), 2) for k in range(-40, 41, 5)]
        out = []
        for exp in self._expiries(as_of):
            if not (lo <= exp <= hi):
                continue
            for k in strikes:
                for kind in ("call", "put"):
                    out.append({"ticker": _occ(underlying, exp, kind, k), "contract_type": kind, "strike_price": k,
                                "expiration_date": exp.strftime("%Y-%m-%d"), "shares_per_contract": 100})
        return out

    def _bars(self, opt: str, start: _pd.Timestamp, end: _pd.Timestamp) -> list[dict]:
        body = opt[2:]
        und = body[: len(body) - 15]
        if und == "ILLQ":
            return []
        kind = "call" if body[-9] == "C" else "put"
        strike = int(body[-8:]) / 1000
        s = self.spot[und]
        price = max(s - strike, 0.0) + 1.0 if kind == "call" else max(strike - s, 0.0) + 1.0
        rows = []
        for d in self.days[(self.days >= start) & (self.days <= end)]:
            ms = int(_dt.datetime(d.year, d.month, d.day, 20, 0, tzinfo=_dt.timezone.utc).timestamp() * 1000)
            rows.append({"t": ms, "c": price, "v": 50})
        return rows

    def get_all(self, path: str, params: dict) -> list[dict]:
        if path == "/v3/reference/options/contracts":
            return self._contracts(params["underlying_ticker"], _pd.Timestamp(params["as_of"]),
                                   _pd.Timestamp(params["expiration_date.gte"]), _pd.Timestamp(params["expiration_date.lte"]))
        if path.startswith("/v2/aggs/ticker/"):
            parts = path.split("/")
            return self._bars(parts[4], _pd.Timestamp(parts[8]), _pd.Timestamp(parts[9]))
        return []
```

Note on the aggs path: `/v2/aggs/ticker/{opt}/range/1/day/{start}/{end}` splits into `['', 'v2', 'aggs', 'ticker', opt, 'range', '1', 'day', start, end]`, so `parts[4]` is the option ticker and `parts[8]`, `parts[9]` are the dates. The `ILLQ` underlying has 4 letters, matching the `len(body) - 15` slice (6 date + 1 type + 8 strike digits).

- [ ] **Step 2: Write the failing tests**

`research/tests/test_pricing.py`:
```python
import math

import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.pricing import fetch_chain, locate_spot, price_events, select_strikes
from tests.fakes import FakeClient, FakeMarket

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def _client():
    return FakeClient(market=FakeMarket({"AAPL": 100.0, "MSFT": 400.0, "ILLQ": 50.0}))


def test_locate_spot_recovers_price_from_parity():
    c = _client()
    chain = fetch_chain(c, "AAPL", T("2024-06-03"), 2, 180)
    loc = locate_spot(c, chain, T("2024-06-03"), CFG.risk_free)
    assert loc is not None and abs(loc["spot"] / 100.0 - 1) < 0.01


def test_select_strikes_atm_and_otm():
    c = _client()
    chain = fetch_chain(c, "AAPL", T("2024-06-03"), 90, 180)
    e = chain[chain.expiration_date == chain.expiration_date.min()]
    s = select_strikes(e, 100.0, [0.05], CFG.strike_window)
    assert s["K"] == 100.0 and s["U0.05"] == 105.0 and s["L0.05"] == 95.0


def test_price_events_all_buckets_and_input_order():
    ev = pd.DataFrame({"ticker": ["MSFT", "AAPL"], "filing_date": [T("2024-06-04")] * 2,
                       "t_0": [T("2024-06-04")] * 2, "t_pre": [T("2024-06-03")] * 2, "family": ["hedge", "opportunity"]})
    priced, dropped = price_events(_client(), ev, CAL, CFG, max_workers=4)
    assert dropped.empty
    assert [p.ticker for p in priced][:3] == ["MSFT"] * 3
    assert {p.bucket for p in priced} == {"1m", "2m", "3-6m"}
    pe = next(p for p in priced if p.ticker == "AAPL" and p.bucket == "3-6m")
    assert pe.family == "opportunity"
    assert set(pe.legs) == {"C_K", "P_K", "C_U0.03", "P_L0.03", "C_U0.05", "P_L0.05", "C_U0.1", "P_L0.1"}
    assert abs(pe.synthetic_spot(T("2024-06-04")) / 100.0 - 1) < 0.02


def test_illiquid_underlying_is_dropped_with_reason_not_priced_at_zero():
    ev = pd.DataFrame({"ticker": ["ILLQ"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")], "t_pre": [T("2024-06-03")]})
    priced, dropped = price_events(_client(), ev, CAL, CFG, max_workers=1)
    assert priced == []
    assert len(dropped) == 1 and "spot" in dropped.reason.iloc[0]


def test_stale_mark_is_nan():
    ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")], "t_pre": [T("2024-06-03")]})
    priced, _ = price_events(_client(), ev, CAL, CFG, max_workers=1)
    leg = priced[0].legs["C_K"]
    leg.bars = leg.bars.loc[: T("2024-06-03")]
    assert math.isnan(leg.mark(T("2024-06-12")))      # 7 sessions old > max_stale_sessions = 3
    assert not math.isnan(leg.mark(T("2024-06-05")))


def test_empty_events_returns_empty():
    ev = pd.DataFrame(columns=["ticker", "filing_date", "t_0", "t_pre"])
    priced, dropped = price_events(_client(), ev, CAL, CFG)
    assert priced == [] and dropped.empty and list(dropped.columns) == ["ticker", "t_0", "reason"]
```

Add to `research/tests/test_massive.py`:
```python
def test_concurrent_writes_same_url_never_corrupt_cache(tmp_path):
    import threading

    class SlowSession:
        def __init__(self):
            self.headers = {}
        def get(self, url, timeout):
            return FakeResponse(200, {"results": list(range(1000))})

    client = MassiveClient("k", cache_dir=tmp_path, session=SlowSession(), sleep=lambda s: None)
    threads = [threading.Thread(target=client.get, args=("/same",)) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    files = list(tmp_path.glob("*"))
    assert len(files) == 1 and files[0].suffix == ".json"
    assert json.loads(files[0].read_text()) == {"results": list(range(1000))}
```

- [ ] **Step 3: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_pricing.py tests/test_massive.py -q`
Expected: FAIL (`ModuleNotFoundError: polybridge_research.pricing`; the concurrency test may fail on leftover `.tmp` files or `FileNotFoundError` from a shared temp name).

- [ ] **Step 4: Make the cache write thread-safe**

In `research/polybridge_research/massive.py`, add `import threading` and `import uuid`; in `MassiveClient.get`, replace the temp-file name so each write is unique:
```python
        tmp = cache_file.with_name(f"{cache_file.stem}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, cache_file)
```
(Keep everything else in `get` unchanged. `os.replace` is atomic, so concurrent writers of the same URL each replace the file with a complete payload.)

- [ ] **Step 5: Implement pricing**

`research/polybridge_research/pricing.py`:
```python
"""Price each event from the option chain alone (Massive starter, section 5), with explicit arguments and threads."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .calendar import TradingCalendar
from .config import StudyConfig

CONTRACTS = "/v3/reference/options/contracts"


def option_bars(client, opt_ticker: str, start, end) -> pd.DataFrame:
    rows = client.get_all(f"/v2/aggs/ticker/{opt_ticker}/range/1/day/{pd.Timestamp(start):%Y-%m-%d}/{pd.Timestamp(end):%Y-%m-%d}",
                          {"adjusted": "false", "sort": "asc", "limit": 50000})
    if not rows:
        return pd.DataFrame(columns=["close", "volume"], index=pd.DatetimeIndex([], name="session"))
    idx = (pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True)
             .tz_convert("America/New_York").normalize().tz_localize(None))
    return pd.DataFrame({"close": [float(r["c"]) for r in rows], "volume": [float(r.get("v") or 0) for r in rows]},
                        index=pd.DatetimeIndex(idx, name="session"))


def fetch_chain(client, ticker: str, as_of: pd.Timestamp, dte_lo: int, dte_hi: int) -> pd.DataFrame:
    rows = client.get_all(CONTRACTS, {
        "underlying_ticker": ticker, "as_of": as_of.strftime("%Y-%m-%d"),
        "expiration_date.gte": (as_of + pd.Timedelta(days=dte_lo)).strftime("%Y-%m-%d"),
        "expiration_date.lte": (as_of + pd.Timedelta(days=dte_hi)).strftime("%Y-%m-%d"),
        "limit": 1000,
    })
    chain = pd.DataFrame(rows)
    if chain.empty:
        return chain
    if "shares_per_contract" in chain:
        chain = chain[chain["shares_per_contract"].fillna(100) == 100]
    chain = chain[["ticker", "contract_type", "strike_price", "expiration_date"]].copy()
    chain["expiration_date"] = pd.to_datetime(chain["expiration_date"])
    chain["dte"] = (chain["expiration_date"] - as_of).dt.days
    chain["strike_price"] = chain["strike_price"].astype(float)
    return chain.reset_index(drop=True)


def _paired_strikes(e: pd.DataFrame) -> np.ndarray:
    both = e.groupby("strike_price")["contract_type"].nunique()
    return both[both == 2].index.to_numpy(dtype=float)


def _contract(e: pd.DataFrame, strike: float, kind: str) -> str:
    return e[(e.strike_price == strike) & (e.contract_type == kind)]["ticker"].iloc[0]


def _last_close(client, opt_ticker: str, day: pd.Timestamp, lookback_days: int = 7) -> float | None:
    bars = option_bars(client, opt_ticker, day - pd.Timedelta(days=lookback_days), day)
    return float(bars["close"].iloc[-1]) if len(bars) else None


def locate_spot(client, chain: pd.DataFrame, day: pd.Timestamp, risk_free: float, max_iter: int = 8) -> dict | None:
    near = chain[chain.dte >= 3]
    if near.empty:
        return None
    near = near[near.dte == near.dte.min()]
    strikes = _paired_strikes(near)
    if len(strikes) < 3:
        return None
    T = near.dte.iloc[0] / 365
    k, tried, est = float(np.median(strikes)), set(), None
    k = strikes[np.abs(strikes - k).argmin()]
    for _ in range(max_iter):
        tried.add(k)
        c = _last_close(client, _contract(near, k, "call"), day)
        p = _last_close(client, _contract(near, k, "put"), day)
        if c is None or p is None:
            rest = [s for s in strikes if s not in tried]
            if not rest:
                break
            k = rest[int(np.abs(np.array(rest) - k).argmin())]
            continue
        est = k * np.exp(-risk_free * T) + c - p
        k_new = strikes[np.abs(strikes - est).argmin()]
        if k_new == k or k_new in tried:
            break
        k = k_new
    if est is None:
        return None
    return {"spot": float(est), "strike": float(k), "expiry": near.expiration_date.iloc[0], "dte": int(near.dte.iloc[0])}


def pick_expiry(chain: pd.DataFrame, lo: int, hi: int, target: int) -> pd.Timestamp | None:
    cand = chain[(chain.dte >= lo) & (chain.dte <= hi)]
    if cand.empty:
        return None
    dte_of = cand.groupby("expiration_date")["dte"].first()
    ok = [x for x, g in cand.groupby("expiration_date") if len(_paired_strikes(g)) >= 3]
    if not ok:
        return None
    return min(ok, key=lambda x: abs(dte_of[x] - target))


def select_strikes(e: pd.DataFrame, spot: float, otm_pcts, strike_window: float) -> dict[str, float] | None:
    both = _paired_strikes(e)
    both = both[(both >= spot * (1 - strike_window)) & (both <= spot * (1 + strike_window))]
    if len(both) == 0:
        return None
    calls = np.sort(e.loc[e.contract_type == "call", "strike_price"].unique())
    puts = np.sort(e.loc[e.contract_type == "put", "strike_price"].unique())
    out = {"K": float(both[np.abs(both - spot).argmin()])}
    for pct in otm_pcts:
        up, dn = calls[calls >= spot * (1 + pct)], puts[puts <= spot * (1 - pct)]
        out[f"U{pct}"] = float(up.min()) if len(up) else float(calls.max())
        out[f"L{pct}"] = float(dn.max()) if len(dn) else float(puts.min())
    return out


@dataclass
class Leg:
    ticker: str
    kind: str
    strike: float
    bars: pd.DataFrame
    cal: TradingCalendar = field(repr=False)
    max_stale: int = 3

    def mark(self, day) -> float:
        b = self.bars.loc[: pd.Timestamp(day)]
        if b.empty or self.cal.between(b.index[-1], day) > self.max_stale:
            return np.nan
        return float(b["close"].iloc[-1])

    def volume_on(self, day) -> float:
        return float(self.bars["volume"].get(pd.Timestamp(day), 0.0))


@dataclass
class PricedEvent:
    ticker: str
    event_date: pd.Timestamp
    t_pre: pd.Timestamp
    t_0: pd.Timestamp
    bucket: str
    expiry: pd.Timestamp
    expiry_session: pd.Timestamp
    spot_pre: float
    strikes: dict[str, float]
    legs: dict[str, Leg]
    risk_free: float
    family: str | None = None

    def marks(self, day) -> dict[str, float]:
        return {name: leg.mark(day) for name, leg in self.legs.items()}

    def synthetic_spot(self, day, m: dict[str, float] | None = None) -> float:
        m = m if m is not None else self.marks(day)
        T = max((self.expiry - pd.Timestamp(day)).days, 0) / 365
        return self.strikes["K"] * np.exp(-self.risk_free * T) + m["C_K"] - m["P_K"]


def price_event(client, row, cal: TradingCalendar, cfg: StudyConfig, buckets: dict) -> tuple[list[PricedEvent], list[str]]:
    t_pre, t_0 = pd.Timestamp(row.t_pre), pd.Timestamp(row.t_0)
    family = getattr(row, "family", None)
    dte_hi = max(b[1] for b in buckets.values())
    chain = fetch_chain(client, row.ticker, t_pre, 2, dte_hi)
    if chain.empty:
        return [], ["no option chain as of the pre-event session"]
    loc = locate_spot(client, chain, t_pre, cfg.risk_free)
    if loc is None:
        return [], ["could not recover spot from the chain (no liquid near-dated pair)"]
    priced, notes = [], []
    for name, (lo, hi, target) in buckets.items():
        expiry = pick_expiry(chain, lo, hi, target)
        if expiry is None:
            notes.append(f"{name}: no expiry {lo}-{hi} days out")
            continue
        e = chain[chain.expiration_date == expiry]
        strikes = select_strikes(e, loc["spot"], cfg.otm_grid, cfg.strike_window)
        if strikes is None:
            notes.append(f"{name}: no paired strikes near spot")
            continue
        wanted = {"C_K": ("call", strikes["K"]), "P_K": ("put", strikes["K"])}
        for pct in cfg.otm_grid:
            wanted[f"C_U{pct}"] = ("call", strikes[f"U{pct}"])
            wanted[f"P_L{pct}"] = ("put", strikes[f"L{pct}"])
        legs = {}
        for key, (kind, k) in wanted.items():
            tk = _contract(e, k, kind)
            legs[key] = Leg(tk, kind, k, option_bars(client, tk, t_pre - pd.Timedelta(days=10), expiry), cal, cfg.max_stale_sessions)
        exp_session = cal.sessions[cal.sessions.searchsorted(expiry, side="right") - 1]
        pe = PricedEvent(row.ticker, pd.Timestamp(row.filing_date), t_pre, t_0, name, expiry, exp_session,
                         loc["spot"], strikes, legs, cfg.risk_free, family)
        if np.isnan(pe.legs["C_K"].mark(t_pre)) or np.isnan(pe.legs["P_K"].mark(t_pre)):
            notes.append(f"{name}: ATM pair did not trade on or near the pre-event session")
            continue
        priced.append(pe)
    return priced, notes


def price_events(client, events: pd.DataFrame, cal: TradingCalendar, cfg: StudyConfig, buckets: dict | None = None,
                 max_workers: int = 8, label: str = "events") -> tuple[list[PricedEvent], pd.DataFrame]:
    buckets = buckets or cfg.buckets
    rows = list(events.itertuples(index=False))
    if not rows:
        return [], pd.DataFrame(columns=["ticker", "t_0", "reason"])
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        results = list(pool.map(lambda r: price_event(client, r, cal, cfg, buckets), rows))
    priced, dropped = [], []
    for row, (got, notes) in zip(rows, results):
        priced += got
        dropped += [(row.ticker, row.t_0, note) for note in notes]
    print(f"{label}: {len(rows)} events -> {len(priced)} priced (event, bucket) pairs; {len(dropped)} drops")
    return priced, pd.DataFrame(dropped, columns=["ticker", "t_0", "reason"])
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_pricing.py tests/test_massive.py -q`
Expected: `6 passed` (pricing) and all massive tests passing (now 10).

- [ ] **Step 7: Commit**

```bash
git add research/polybridge_research/pricing.py research/polybridge_research/massive.py research/tests/fakes.py research/tests/test_pricing.py research/tests/test_massive.py
git commit -m "Research: chain pricing ported from the starter, parallel, with a thread-safe cache

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Results table with P&L and the parity ratio

**Files:**
- Create: `research/polybridge_research/evaluate.py`
- Test: `research/tests/test_evaluate.py`

**Interfaces:**
- Consumes: `PricedEvent`, `strategies.strategy_pnl`, `strategies.STRATEGIES`, `parity.implied_scaled`, `TradingCalendar`, `StudyConfig`.
- Produces: `evaluate(priced, cal, cfg, last_session: pd.Timestamp) -> pd.DataFrame`, one row per (event, bucket, entry, OTM, horizon) with columns `ticker, family, event_date, t_0, bucket, expiry, entry, entry_date, horizon, exit_date, sessions_held, dte_sessions, S_entry, S_exit, realized, implied_move, implied_scaled, otm, ratio` plus one column per name in `STRATEGIES`. Horizons after `expiry_session` or after `last_session` are absent. Empty input → empty DataFrame with those columns.

- [ ] **Step 1: Write the failing tests**

`research/tests/test_evaluate.py`:
```python
import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.evaluate import evaluate
from polybridge_research.pricing import price_events
from polybridge_research.strategies import STRATEGIES
from tests.fakes import FakeClient, FakeMarket

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def _priced():
    ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")],
                       "t_pre": [T("2024-06-03")], "family": ["hedge"]})
    priced, _ = price_events(FakeClient(market=FakeMarket({"AAPL": 100.0})), ev, CAL, CFG, max_workers=1)
    return priced


def test_columns_rows_and_flat_market_values():
    res = evaluate(_priced(), CAL, CFG, last_session=T("2026-09-30"))
    assert set(STRATEGIES) <= set(res.columns) and {"ratio", "family", "implied_scaled"} <= set(res.columns)
    base = res[(res.bucket == "3-6m") & (res.entry == "post") & (res.otm == 0.05)]
    assert set(base.horizon) == {0, 1, 2, 3, 5, 10, 21, 42, 63, "exp"}
    assert (base.family == "hedge").all()
    h21 = base[base.horizon == 21].iloc[0]
    assert abs(h21["stock"]) < 5e-3                  # flat fake market: only carry decay in K·e^(−rT) moves it
    assert abs(h21["protective_put"]) < 5e-3


def test_unresolved_horizons_are_absent():
    res = evaluate(_priced(), CAL, CFG, last_session=T("2024-06-20"))
    base = res[(res.bucket == "3-6m") & (res.entry == "post") & (res.otm == 0.05)]
    assert 21 not in set(base.horizon) and 10 in set(base.horizon)
    assert "exp" not in set(base.horizon)


def test_empty_input():
    res = evaluate([], CAL, CFG, last_session=T("2026-09-30"))
    assert res.empty and "ratio" in res.columns
```

- [ ] **Step 2: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_evaluate.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`research/polybridge_research/evaluate.py`:
```python
"""Long results table (Massive starter, section 6) with the parity ratio (section 7)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import TradingCalendar
from .config import StudyConfig
from .parity import implied_scaled
from .strategies import STRATEGIES, strategy_pnl

COLUMNS = ["ticker", "family", "event_date", "t_0", "bucket", "expiry", "entry", "entry_date", "horizon", "exit_date",
           "sessions_held", "dte_sessions", "S_entry", "S_exit", "realized", "implied_move", "implied_scaled", "otm",
           *STRATEGIES, "ratio"]


def evaluate(priced, cal: TradingCalendar, cfg: StudyConfig, last_session: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for pe in priced:
        exits = {0: pe.t_0}
        for h in cfg.horizons:
            d = cal.offset(pe.t_0, h)
            if d is not None and d <= pe.expiry_session:
                exits[h] = d
        exits["exp"] = pe.expiry_session
        for entry, e_day in (("pre", pe.t_pre), ("post", pe.t_0)):
            m_e = pe.marks(e_day)
            S_e = pe.synthetic_spot(e_day, m_e)
            if np.isnan(S_e):
                continue
            implied = (m_e["C_K"] + m_e["P_K"]) / S_e
            dte_sessions = cal.between(e_day, pe.expiry_session)
            for h, x_day in exits.items():
                if x_day > last_session:
                    continue
                m_x = pe.marks(x_day)
                S_x = pe.synthetic_spot(x_day, m_x)
                held = cal.between(e_day, x_day)
                base = {"ticker": pe.ticker, "family": pe.family, "event_date": pe.event_date, "t_0": pe.t_0,
                        "bucket": pe.bucket, "expiry": pe.expiry, "entry": entry, "entry_date": e_day, "horizon": h,
                        "exit_date": x_day, "sessions_held": held, "dte_sessions": dte_sessions, "S_entry": S_e,
                        "S_exit": S_x, "realized": S_x / S_e - 1, "implied_move": implied,
                        "implied_scaled": implied_scaled(implied, held, dte_sessions)}
                for otm in cfg.otm_grid:
                    rows.append(dict(base, otm=otm, **strategy_pnl(m_e, m_x, S_e, S_x, otm)))
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    res = pd.DataFrame(rows)
    res["ratio"] = res["realized"].abs() / res["implied_scaled"]
    return res[COLUMNS]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_evaluate.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/evaluate.py research/tests/test_evaluate.py
git commit -m "Research: long results table with strategy P&L and parity ratio

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Placebo, scoreboards, decay and the pre-registered pass check

**Files:**
- Create: `research/polybridge_research/analysis.py`
- Test: `research/tests/test_analysis.py`

**Interfaces:**
- Consumes: `stats.bootstrap_ci`, `TradingCalendar`, `StudyConfig`, `STRATEGIES`, `schema.STRATEGY_FOR_FAMILY`, `schema.Family`.
- Produces:
  - `slice_results(res, bucket, entry, otm) -> pd.DataFrame`
  - `scoreboard(res, cfg, level=0.95, bucket=None, entry=None, otm=None, horizons=None, strategies=STRATEGIES) -> pd.DataFrame` (columns `strategy, horizon, n, mean, ci_lo, ci_hi, median, hit_rate`)
  - `difference_board(res_a, res_b, cfg, level=0.95, column=None, entry=None, bucket=None, otm=None, strategies=STRATEGIES, seed=1, n_boot=4000) -> pd.DataFrame` (columns `strategy, horizon, n_a, n_b, mean_a, mean_b, difference, ci_lo, ci_hi, p_value`); when `column` is given (e.g. `"ratio"`) it compares that column instead of the strategies, with `strategy` set to the column name. `p_value` is the two-sided bootstrap p: `2 * min(P(d ≤ 0), P(d ≥ 0))`, floored at `1 / n_boot`.
  - `sample_placebo(events, n, start, end, cal, gap_days, seed=7) -> pd.DataFrame` (columns `ticker, filing_date, t_0, t_pre`, plus `family` copied when present in `events`)
  - `decay_table(res, cfg, entry="pre") -> pd.DataFrame` indexed by horizon with `n, mean_ratio, ci_lo, ci_hi, median_ratio, share_above_1` for the baseline bucket and OTM
  - `pass_check(events_res, placebo_res, family: str, cfg) -> dict` with keys `family, strategy, pnl (DataFrame for headline horizons), ratio (DataFrame), horizons_pnl_ok (list), horizons_ratio_ok (list), passed (bool)`. Rule: the strategy is `STRATEGY_FOR_FAMILY[family]`; a headline horizon is "pnl ok" when the `confirmatory_level` CI on events-minus-placebo P&L (entry `cfg.entry`) has `ci_lo > 0`; "ratio ok" when the events-minus-placebo mean ratio (entry `"pre"`) is `> 0` for hedge or `< 0` for opportunity (decision D4: point estimate); `passed` when at least 2 headline horizons are both pnl ok and ratio ok.

- [ ] **Step 1: Write the failing tests**

`research/tests/test_analysis.py`:
```python
import numpy as np
import pandas as pd

from polybridge_research.analysis import decay_table, difference_board, pass_check, sample_placebo, scoreboard
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.strategies import STRATEGIES

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def _res(n, pp_mean, csp_mean, ratio_mean, seed):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        for entry in ("pre", "post"):
            for h in (5, 21, 42, "exp"):
                row = {"ticker": f"T{i % 7}", "bucket": "3-6m", "entry": entry, "otm": 0.05, "horizon": h,
                       "ratio": rng.normal(ratio_mean, 0.05)}
                for s in STRATEGIES:
                    row[s] = rng.normal(0.0, 0.01)
                row["protective_put"] = rng.normal(pp_mean, 0.01)
                row["cash_secured_put"] = rng.normal(csp_mean, 0.01)
                rows.append(row)
    return pd.DataFrame(rows)


def test_hedge_passes_when_edge_and_ratio_point_the_right_way():
    events = _res(80, pp_mean=0.03, csp_mean=0.0, ratio_mean=1.4, seed=1)
    placebo = _res(200, pp_mean=0.0, csp_mean=0.0, ratio_mean=1.0, seed=2)
    out = pass_check(events, placebo, "hedge", CFG)
    assert out["strategy"] == "protective_put"
    assert out["horizons_pnl_ok"] == [21, 42, "exp"] and out["horizons_ratio_ok"] == [21, 42, "exp"]
    assert out["passed"] is True


def test_opportunity_needs_ratio_below_placebo():
    events = _res(80, pp_mean=0.0, csp_mean=0.03, ratio_mean=1.4, seed=3)   # ratio points the wrong way
    placebo = _res(200, pp_mean=0.0, csp_mean=0.0, ratio_mean=1.0, seed=4)
    out = pass_check(events, placebo, "opportunity", CFG)
    assert out["strategy"] == "cash_secured_put"
    assert out["horizons_pnl_ok"] == [21, 42, "exp"] and out["horizons_ratio_ok"] == []
    assert out["passed"] is False


def test_null_effect_fails():
    out = pass_check(_res(80, 0, 0, 1.0, 5), _res(200, 0, 0, 1.0, 6), "hedge", CFG)
    assert out["passed"] is False


def test_difference_board_level_and_p_value():
    a, b = _res(80, 0.03, 0, 1.0, 7), _res(200, 0, 0, 1.0, 8)
    d95 = difference_board(a, b, CFG, level=0.95)
    d975 = difference_board(a, b, CFG, level=0.975)
    r95 = d95[(d95.strategy == "protective_put") & (d95.horizon == 21)].iloc[0]
    r975 = d975[(d975.strategy == "protective_put") & (d975.horizon == 21)].iloc[0]
    assert r975.ci_lo < r95.ci_lo and r95.p_value < 0.01
    ratio = difference_board(a, b, CFG, column="ratio", entry="pre")
    assert set(ratio.strategy) == {"ratio"}


def test_scoreboard_and_decay_shapes():
    res = _res(30, 0, 0, 1.2, 9)
    sb = scoreboard(res, CFG)
    assert {"strategy", "horizon", "n", "mean", "ci_lo", "ci_hi"} <= set(sb.columns)
    dt = decay_table(res, CFG)
    assert list(dt.index) == [5, 21, 42, "exp"] and dt.loc[21, "n"] == 30


def test_sample_placebo_respects_gap_and_window():
    ev = pd.DataFrame({"ticker": ["AAPL"] * 3, "filing_date": [T("2024-03-01"), T("2024-07-01"), T("2024-11-01")],
                       "family": ["hedge"] * 3})
    pl = sample_placebo(ev, 50, "2024-01-01", "2024-12-31", CAL, gap_days=30, seed=1)
    assert len(pl) == 50 and set(pl.ticker) == {"AAPL"} and set(pl.family) == {"hedge"}
    for d in pl.filing_date:
        assert all(abs((d - a).days) > 30 for a in ev.filing_date)
        assert T("2024-01-01") <= d <= T("2024-12-31")
    assert (pl.t_pre < pl.t_0).all()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_analysis.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`research/polybridge_research/analysis.py`:
```python
"""Scoreboards, placebo, parity decay and the pre-registered pass check (HYPOTHESIS.md §4)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import TradingCalendar
from .config import StudyConfig
from .schema import STRATEGY_FOR_FAMILY, Family
from .stats import bootstrap_ci
from .strategies import STRATEGIES


def _horizons(cfg: StudyConfig, present) -> list:
    return [h for h in [*cfg.horizons, "exp"] if h in set(present)]


def slice_results(res: pd.DataFrame, bucket: str, entry: str, otm: float) -> pd.DataFrame:
    return res[(res.bucket == bucket) & (res.entry == entry) & (res.otm == otm)]


def scoreboard(res, cfg: StudyConfig, level: float = 0.95, bucket=None, entry=None, otm=None, horizons=None,
               strategies=STRATEGIES) -> pd.DataFrame:
    r = slice_results(res, bucket or cfg.baseline_bucket, entry or cfg.entry, otm or cfg.otm_pct)
    horizons = horizons or _horizons(cfg, r.horizon)
    rows = []
    for s in strategies:
        for h in horizons:
            x = r.loc[r.horizon == h, s].dropna()
            lo, hi = bootstrap_ci(x, level=level)
            rows.append({"strategy": s, "horizon": h, "n": len(x), "mean": x.mean(), "ci_lo": lo, "ci_hi": hi,
                         "median": x.median(), "hit_rate": (x > 0).mean() if len(x) else np.nan})
    return pd.DataFrame(rows)


def difference_board(res_a, res_b, cfg: StudyConfig, level: float = 0.95, column: str | None = None, entry=None,
                     bucket=None, otm=None, strategies=STRATEGIES, seed: int = 1, n_boot: int = 4000) -> pd.DataFrame:
    e = entry or cfg.entry
    a = slice_results(res_a, bucket or cfg.baseline_bucket, e, otm or cfg.otm_pct)
    b = slice_results(res_b, bucket or cfg.baseline_bucket, e, otm or cfg.otm_pct)
    cols = [column] if column else list(strategies)
    tail = (1 - level) / 2 * 100
    rng, rows = np.random.default_rng(seed), []
    for s in cols:
        for h in _horizons(cfg, set(a.horizon) & set(b.horizon)):
            xa = a.loc[a.horizon == h, s].dropna().to_numpy(float)
            xb = b.loc[b.horizon == h, s].dropna().to_numpy(float)
            row = {"strategy": s, "horizon": h, "n_a": len(xa), "n_b": len(xb)}
            if len(xa) >= 5 and len(xb) >= 5:
                d = rng.choice(xa, (n_boot, len(xa))).mean(1) - rng.choice(xb, (n_boot, len(xb))).mean(1)
                p = 2 * min((d <= 0).mean(), (d >= 0).mean())
                row.update(mean_a=xa.mean(), mean_b=xb.mean(), difference=xa.mean() - xb.mean(),
                           ci_lo=np.percentile(d, tail), ci_hi=np.percentile(d, 100 - tail), p_value=max(p, 1 / n_boot))
            rows.append(row)
    return pd.DataFrame(rows)


def sample_placebo(events: pd.DataFrame, n: int, start: str, end: str, cal: TradingCalendar, gap_days: int,
                   seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sessions = cal.sessions[(cal.sessions >= pd.Timestamp(start)) & (cal.sessions <= pd.Timestamp(end))]
    cols = ["ticker", "filing_date", "t_0", "t_pre"] + (["family"] if "family" in events else [])
    if events.empty or len(sessions) == 0:
        return pd.DataFrame(columns=cols)
    by_ticker = events.groupby("ticker")["filing_date"].apply(list)
    fam = events.groupby("ticker")["family"].first() if "family" in events else None
    rows = []
    for t in rng.choice(events["ticker"].to_numpy(), size=n, replace=True):
        for _ in range(50):
            d = sessions[rng.integers(len(sessions))]
            if all(abs((d - a).days) > gap_days for a in by_ticker.get(t, [])):
                row = {"ticker": t, "filing_date": d, "t_0": d, "t_pre": cal.before(d)}
                if fam is not None:
                    row["family"] = fam[t]
                rows.append(row)
                break
    return pd.DataFrame(rows, columns=cols)


def decay_table(res: pd.DataFrame, cfg: StudyConfig, entry: str = "pre") -> pd.DataFrame:
    r = slice_results(res, cfg.baseline_bucket, entry, cfg.otm_pct)
    rows = []
    for h in _horizons(cfg, r.horizon):
        x = r.loc[r.horizon == h, "ratio"].dropna()
        lo, hi = bootstrap_ci(x)
        rows.append({"horizon": h, "n": len(x), "mean_ratio": x.mean(), "ci_lo": lo, "ci_hi": hi,
                     "median_ratio": x.median(), "share_above_1": (x > 1).mean() if len(x) else np.nan})
    return pd.DataFrame(rows).set_index("horizon") if rows else pd.DataFrame(
        columns=["n", "mean_ratio", "ci_lo", "ci_hi", "median_ratio", "share_above_1"])


def pass_check(events_res, placebo_res, family: str, cfg: StudyConfig) -> dict:
    strategy = STRATEGY_FOR_FAMILY[Family(family)]
    heads = list(cfg.headline_horizons)
    pnl = difference_board(events_res, placebo_res, cfg, level=cfg.confirmatory_level, strategies=[strategy])
    pnl = pnl[pnl.horizon.isin(heads)].reset_index(drop=True)
    ratio = difference_board(events_res, placebo_res, cfg, level=cfg.confirmatory_level, column="ratio", entry="pre")
    ratio = ratio[ratio.horizon.isin(heads)].reset_index(drop=True)
    want_up = family == Family.HEDGE.value
    pnl_ok = [h for h in heads if not pnl[(pnl.horizon == h) & (pnl.get("ci_lo", pd.Series(dtype=float)) > 0)].empty]
    ratio_ok = [h for h in heads
                if not ratio[(ratio.horizon == h) & ((ratio.get("difference", pd.Series(dtype=float)) > 0) == want_up)
                             & ratio.get("difference", pd.Series(dtype=float)).notna()].empty]
    both = [h for h in heads if h in pnl_ok and h in ratio_ok]
    return {"family": family, "strategy": strategy, "pnl": pnl, "ratio": ratio,
            "horizons_pnl_ok": pnl_ok, "horizons_ratio_ok": ratio_ok, "passed": len(both) >= 2}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_analysis.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/analysis.py research/tests/test_analysis.py
git commit -m "Research: placebo, scoreboards, parity decay and the pre-registered pass check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Trade costs from real spreads, and capacity

**Files:**
- Create: `research/polybridge_research/costs.py`
- Test: `research/tests/test_costs.py`

**Interfaces:**
- Consumes: `PricedEvent`, `TradingCalendar`, `StudyConfig`, a client with `get`.
- Produces:
  - `LEGS_FOR_STRATEGY: dict[str, list[str]]` = `{"long_call": ["C_K"], "covered_call": ["C_U{otm}"], "protective_put": ["P_L{otm}"], "collar": ["C_U{otm}", "P_L{otm}"], "cash_secured_put": ["P_L{otm}"]}` (templates formatted with `otm`)
  - `half_spread(client, opt_ticker: str, day: pd.Timestamp) -> float | None`: the last quote at or before 16:00 ET on `day` via `/v3/quotes/{opt_ticker}` with params `{"timestamp.lte": <ns epoch of day 16:00 America/New_York>, "order": "desc", "sort": "timestamp", "limit": 1}`; returns `(ask - bid) / 2` or `None` when no quote or a non-positive bid/ask.
  - `cost_table(results, priced, strategy, horizon, cfg, client=None, multipliers=(1, 2)) -> pd.DataFrame` with one row per event (baseline bucket, `cfg.entry`, `cfg.otm_pct`, the given horizon) and columns `ticker, event_date, gross, premium_traded, haircut_cost_1x, haircut_cost_2x, net_haircut_1x, net_haircut_2x, spread_cost, net_spread, leg_volume`. Haircut cost = `premium_traded * cfg.cost_haircut * 2 * m` (in and out). Spread cost = sum of half-spreads at entry and exit over the strategy's legs, divided by `S_entry`; NaN when any quote is missing or `client` is None. `leg_volume` = contracts traded in the strategy's legs on the entry day.

- [ ] **Step 1: Write the failing tests**

`research/tests/test_costs.py`:
```python
import math

import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.costs import cost_table, half_spread
from polybridge_research.evaluate import evaluate
from polybridge_research.pricing import price_events
from tests.fakes import FakeClient, FakeMarket

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


class QuoteClient(FakeClient):
    def __init__(self, market, spread):
        super().__init__(market=market)
        self.spread = spread
        self.quote_params = []

    def get(self, path_or_url, params=None):
        if path_or_url.startswith("/v3/quotes/"):
            self.quote_params.append(params)
            if self.spread is None:
                return {"results": []}
            return {"results": [{"bid_price": 1.0, "ask_price": 1.0 + self.spread}]}
        return super().get(path_or_url, params)


def _setup(spread):
    c = QuoteClient(FakeMarket({"AAPL": 100.0}), spread)
    ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2024-06-04")], "t_0": [T("2024-06-04")],
                       "t_pre": [T("2024-06-03")], "family": ["hedge"]})
    priced, _ = price_events(c, ev, CAL, CFG, max_workers=1)
    return c, priced, evaluate(priced, CAL, CFG, last_session=T("2026-09-30"))


def test_half_spread_and_timestamp_bound():
    c, _, _ = _setup(0.10)
    assert math.isclose(half_spread(c, "O:X", T("2024-06-04")), 0.05)
    ts = c.quote_params[-1]["timestamp.lte"]
    assert ts == int(pd.Timestamp("2024-06-04 16:00", tz="America/New_York").value)


def test_cost_table_haircut_and_spread():
    c, priced, res = _setup(0.10)
    tbl = cost_table(res, priced, "protective_put", 21, CFG, client=c)
    row = tbl.iloc[0]
    assert math.isclose(row.premium_traded, 1.0 / row_spot(res), rel_tol=1e-6)
    assert math.isclose(row.haircut_cost_2x, 2 * row.haircut_cost_1x)
    assert math.isclose(row.spread_cost, (0.05 + 0.05) / row_spot(res), rel_tol=1e-6)
    assert row.leg_volume == 50
    assert math.isclose(row.net_spread, row.gross - row.spread_cost)


def test_missing_quotes_give_nan_spread_not_zero():
    c, priced, res = _setup(None)
    row = cost_table(res, priced, "protective_put", 21, CFG, client=c).iloc[0]
    assert math.isnan(row.spread_cost) and not math.isnan(row.haircut_cost_1x)


def row_spot(res):
    r = res[(res.bucket == "3-6m") & (res.entry == "post") & (res.otm == 0.05) & (res.horizon == 21)]
    return float(r.S_entry.iloc[0])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_costs.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`research/polybridge_research/costs.py`:
```python
"""What the trade costs: the pre-registered premium haircut (1x, 2x) and real half-spreads from Massive quotes."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StudyConfig

LEGS_FOR_STRATEGY = {"long_call": ["C_K"], "covered_call": ["C_U{otm}"], "protective_put": ["P_L{otm}"],
                     "collar": ["C_U{otm}", "P_L{otm}"], "cash_secured_put": ["P_L{otm}"]}


def half_spread(client, opt_ticker: str, day: pd.Timestamp) -> float | None:
    bound = int(pd.Timestamp(pd.Timestamp(day).strftime("%Y-%m-%d") + " 16:00", tz="America/New_York").value)
    rows = client.get(f"/v3/quotes/{opt_ticker}", {"timestamp.lte": bound, "order": "desc", "sort": "timestamp",
                                                   "limit": 1}).get("results") or []
    if not rows:
        return None
    bid, ask = float(rows[0].get("bid_price") or 0), float(rows[0].get("ask_price") or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (ask - bid) / 2


def cost_table(results: pd.DataFrame, priced, strategy: str, horizon, cfg: StudyConfig, client=None,
               multipliers=(1, 2)) -> pd.DataFrame:
    legs = [l.format(otm=cfg.otm_pct) for l in LEGS_FOR_STRATEGY[strategy]]
    by_key = {(pe.ticker, pe.event_date): pe for pe in priced if pe.bucket == cfg.baseline_bucket}
    r = results[(results.bucket == cfg.baseline_bucket) & (results.entry == cfg.entry) & (results.otm == cfg.otm_pct)
                & (results.horizon == horizon)]
    rows = []
    for x in r.itertuples(index=False):
        pe = by_key[(x.ticker, x.event_date)]
        m_e = pe.marks(x.entry_date)
        premium = sum(abs(m_e[l]) for l in legs) / x.S_entry
        row = {"ticker": x.ticker, "event_date": x.event_date, "gross": getattr(x, strategy), "premium_traded": premium,
               "leg_volume": sum(pe.legs[l].volume_on(x.entry_date) for l in legs)}
        for m in multipliers:
            row[f"haircut_cost_{m}x"] = premium * cfg.cost_haircut * 2 * m
            row[f"net_haircut_{m}x"] = row["gross"] - row[f"haircut_cost_{m}x"]
        spread = np.nan
        if client is not None:
            hs = [half_spread(client, pe.legs[l].ticker, d) for l in legs for d in (x.entry_date, x.exit_date)]
            if all(h is not None for h in hs):
                spread = sum(hs) / x.S_entry
        row["spread_cost"] = spread
        row["net_spread"] = row["gross"] - spread
        rows.append(row)
    cols = ["ticker", "event_date", "gross", "premium_traded", *[f"haircut_cost_{m}x" for m in multipliers],
            *[f"net_haircut_{m}x" for m in multipliers], "spread_cost", "net_spread", "leg_volume"]
    return pd.DataFrame(rows, columns=cols)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_costs.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/costs.py research/tests/test_costs.py
git commit -m "Research: trade costs from the pre-registered haircut and real Massive half-spreads, plus leg volume

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The exploratory atlas and the variant count

**Files:**
- Create: `research/polybridge_research/atlas.py`
- Test: `research/tests/test_atlas.py`

**Interfaces:**
- Consumes: `events.build_tag_events`, `pricing.price_events`, `evaluate.evaluate`, `analysis.difference_board`, `analysis.sample_placebo`, `stats.benjamini_hochberg`, `STRATEGIES`.
- Produces:
  - `count_variants(cfg, n_tags: int = 1, strategies=STRATEGIES) -> int` = `len(buckets) * 2 entries * len(otm_grid) * (len(horizons) + 1) * (len(strategies) - 1) * n_tags` (the stock row is a reference, not a variant)
  - `run_atlas(client, cal, cfg, tags, start, end, last_session, placebo_results, max_events_per_tag=30, seed=0, max_workers=8) -> pd.DataFrame` with one row per (tag, strategy, headline horizon): `tag, n_events, strategy, horizon, difference, ci_lo, ci_hi, p_value, q_value, exploratory` (`exploratory` is always `True`). Only the baseline bucket is priced (`buckets={cfg.baseline_bucket: cfg.buckets[cfg.baseline_bucket]}`). Tags with fewer than 5 priced events produce rows with NaN statistics. `q_value` is BH across every row with a finite p-value.

- [ ] **Step 1: Write the failing tests**

`research/tests/test_atlas.py`:
```python
import pandas as pd

from polybridge_research.analysis import sample_placebo
from polybridge_research.atlas import count_variants, run_atlas
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig, TOP_100
from polybridge_research.evaluate import evaluate
from polybridge_research.pricing import price_events
from tests.fakes import FakeClient, FakeMarket, disclosure

CAL = TradingCalendar()
CFG = StudyConfig()
T = pd.Timestamp


def test_count_variants():
    assert count_variants(CFG) == 3 * 2 * 3 * 9 * 5
    assert count_variants(CFG, n_tags=119) == 3 * 2 * 3 * 9 * 5 * 119


def test_run_atlas_rows_and_rare_tag():
    days = pd.bdate_range("2024-02-01", "2024-09-30")[::5][:12]
    disc = {"dividend_declaration": [disclosure(f"d{i}", "1", ["AAPL"], d.strftime("%Y-%m-%d")) for i, d in enumerate(days)],
            "going_concern": [disclosure("g1", "1", ["AAPL"], "2024-04-02")]}
    client = FakeClient(disc, FakeMarket({"AAPL": 100.0}))
    pl_ev = pd.DataFrame({"ticker": ["AAPL"], "filing_date": [T("2023-01-03")]})
    placebo = sample_placebo(pl_ev, 20, "2024-01-01", "2024-12-31", CAL, gap_days=0, seed=3)
    base = {CFG.baseline_bucket: CFG.buckets[CFG.baseline_bucket]}
    pl_priced, _ = price_events(client, placebo, CAL, CFG, buckets=base, max_workers=2)
    pl_res = evaluate(pl_priced, CAL, CFG, last_session=T("2026-09-30"))
    atlas = run_atlas(client, CAL, CFG, ["dividend_declaration", "going_concern"], "2024-01-01", "2024-12-31",
                      T("2026-09-30"), pl_res, max_events_per_tag=30, max_workers=2)
    assert set(atlas.tag) == {"dividend_declaration", "going_concern"}
    assert atlas.exploratory.all()
    assert len(atlas[atlas.tag == "dividend_declaration"]) == 5 * 3          # 5 strategies x 3 headline horizons
    rare = atlas[atlas.tag == "going_concern"]
    assert rare.p_value.isna().all() and rare.q_value.isna().all()
    common = atlas[atlas.tag == "dividend_declaration"]
    assert common.q_value.notna().all()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_atlas.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`research/polybridge_research/atlas.py`:
```python
"""Exploratory atlas (HYPOTHESIS.md §5): every tag, baseline spec, BH q-values. Never a headline."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .analysis import difference_board
from .config import StudyConfig
from .evaluate import evaluate
from .events import build_tag_events
from .pricing import price_events
from .stats import benjamini_hochberg
from .strategies import STRATEGIES


def count_variants(cfg: StudyConfig, n_tags: int = 1, strategies=STRATEGIES) -> int:
    return len(cfg.buckets) * 2 * len(cfg.otm_grid) * (len(cfg.horizons) + 1) * (len(strategies) - 1) * n_tags


def run_atlas(client, cal, cfg: StudyConfig, tags, start, end, last_session, placebo_results,
              max_events_per_tag: int = 30, seed: int = 0, max_workers: int = 8) -> pd.DataFrame:
    base = {cfg.baseline_bucket: cfg.buckets[cfg.baseline_bucket]}
    strategies = [s for s in STRATEGIES if s != "stock"]
    heads = list(cfg.headline_horizons)
    rows = []
    for tag in tags:
        ev = build_tag_events(client, tag, start, end, cfg.universe, cal)
        if len(ev) > max_events_per_tag:
            ev = ev.sample(max_events_per_tag, random_state=seed).sort_values("filing_date")
        priced, _ = price_events(client, ev, cal, cfg, buckets=base, max_workers=max_workers, label=tag)
        res = evaluate(priced, cal, cfg, last_session)
        n_events = len({(p.ticker, p.event_date) for p in priced})
        diff = (difference_board(res, placebo_results, cfg, strategies=strategies)
                if not res.empty else pd.DataFrame(columns=["strategy", "horizon"]))
        for s in strategies:
            for h in heads:
                hit = diff[(diff.strategy == s) & (diff.horizon == h)] if not diff.empty else diff
                rec = hit.iloc[0].to_dict() if len(hit) else {}
                rows.append({"tag": tag, "n_events": n_events, "strategy": s, "horizon": h,
                             "difference": rec.get("difference", np.nan), "ci_lo": rec.get("ci_lo", np.nan),
                             "ci_hi": rec.get("ci_hi", np.nan), "p_value": rec.get("p_value", np.nan)})
    out = pd.DataFrame(rows)
    out["q_value"] = benjamini_hochberg(out["p_value"].to_numpy(float)) if len(out) else []
    out["exploratory"] = True
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd research && .venv/bin/python -m pytest tests/test_atlas.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/atlas.py research/tests/test_atlas.py
git commit -m "Research: exploratory atlas with BH q-values and the variant count

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: One-call family study (the function judges' windows run through)

**Files:**
- Create: `research/polybridge_research/pipeline.py`
- Test: `research/tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run_family_study(client, cal, cfg, start, end, last_session, user_agent=None, cache_dir=Path(".massive_cache"), max_workers=8, placebo_seed=7) -> dict` with keys `events, excluded, priced, dropped, results, placebo_events, placebo_priced, placebo_results, checks (dict family -> pass_check dict), timing_counts (dict)`. Steps: `build_confirmatory_events` → acceptance times via `fetch_acceptance_time` when `user_agent` is given (failures count as unknown) → `apply_filing_session` → `price_events` → `evaluate` → per family: `sample_placebo(events of that family, cfg.n_placebo, start, end, cal, cfg.placebo_gap_days, seed=placebo_seed)` → price → evaluate → `pass_check`. Families with no events are absent from `checks`. An empty window returns empty frames and `checks == {}`.

- [ ] **Step 1: Write the failing tests**

`research/tests/test_pipeline.py`:
```python
import pandas as pd

from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.pipeline import run_family_study
from tests.fakes import FakeClient, FakeMarket, disclosure

CAL = TradingCalendar()
CFG = StudyConfig(n_placebo=12)
T = pd.Timestamp


def _client():
    days = pd.bdate_range("2024-02-01", "2024-08-30")[::7][:10]
    disc = {"material_litigation": [disclosure(f"m{i}", "1", ["AAPL"], d.strftime("%Y-%m-%d")) for i, d in enumerate(days)],
            "workforce_reduction": [disclosure("w1", "2", ["MSFT"], "2024-04-03")]}
    return FakeClient(disc, FakeMarket({"AAPL": 100.0, "MSFT": 400.0}))


def test_end_to_end_on_fake_market(tmp_path):
    out = run_family_study(_client(), CAL, CFG, "2024-01-01", "2024-12-31", T("2026-09-30"),
                           cache_dir=tmp_path, max_workers=2)
    assert set(out["events"].family) == {"hedge", "opportunity"}
    assert out["timing_counts"] == {"conservative": 11}
    assert set(out["checks"]) == {"hedge", "opportunity"}
    assert out["checks"]["hedge"]["strategy"] == "protective_put"
    assert isinstance(out["checks"]["hedge"]["passed"], bool)
    assert out["checks"]["opportunity"]["passed"] is False  # 1 event < 5: no CI, cannot pass
    assert not out["results"].empty and not out["placebo_results"].empty


def test_empty_window(tmp_path):
    out = run_family_study(_client(), CAL, CFG, "2022-01-01", "2022-03-31", T("2026-09-30"), cache_dir=tmp_path)
    assert out["events"].empty and out["results"].empty and out["checks"] == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`research/polybridge_research/pipeline.py`:
```python
"""The whole confirmatory study for one window: a pure function of (client, config, start, end)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analysis import pass_check, sample_placebo
from .evaluate import evaluate
from .events import build_confirmatory_events
from .pricing import price_events
from .timing import apply_filing_session, fetch_acceptance_time


def run_family_study(client, cal, cfg, start: str, end: str, last_session: pd.Timestamp, user_agent: str | None = None,
                     cache_dir: Path = Path(".massive_cache"), max_workers: int = 8, placebo_seed: int = 7) -> dict:
    events, excluded = build_confirmatory_events(client, start, end, cfg.universe, cal)
    accepted = None
    if user_agent and not events.empty:
        acc = []
        for url in events["filing_url"]:
            try:
                acc.append(fetch_acceptance_time(url, user_agent, cache_dir))
            except Exception:
                acc.append(None)
        accepted = pd.Series(acc, index=events.index)
    if not events.empty:
        events = apply_filing_session(events, cal, accepted)
    timing_counts = events["timing"].value_counts().to_dict() if "timing" in events else {}
    priced, dropped = price_events(client, events, cal, cfg, max_workers=max_workers, label="events")
    results = evaluate(priced, cal, cfg, last_session)
    pl_events, pl_priced, pl_frames, checks = [], [], [], {}
    for fam in sorted(set(events["family"])) if not events.empty else []:
        fam_ev = events[events.family == fam]
        pl = sample_placebo(fam_ev, cfg.n_placebo, start, end, cal, cfg.placebo_gap_days, seed=placebo_seed)
        p_priced, _ = price_events(client, pl, cal, cfg, max_workers=max_workers, label=f"placebo {fam}")
        p_res = evaluate(p_priced, cal, cfg, last_session)
        pl_events.append(pl)
        pl_priced += p_priced
        pl_frames.append(p_res)
        checks[fam] = pass_check(results[results.family == fam], p_res, fam, cfg)
    placebo_results = pd.concat(pl_frames, ignore_index=True) if pl_frames else results.iloc[0:0]
    return {"events": events, "excluded": excluded, "priced": priced, "dropped": dropped, "results": results,
            "placebo_events": pd.concat(pl_events, ignore_index=True) if pl_events else pd.DataFrame(),
            "placebo_priced": pl_priced, "placebo_results": placebo_results, "checks": checks,
            "timing_counts": timing_counts}
```

- [ ] **Step 4: Run the tests and the whole suite**

Run: `cd research && .venv/bin/python -m pytest -q`
Expected: all research tests pass (36 existing + the new ones from Tasks 2–10).

- [ ] **Step 5: Commit**

```bash
git add research/polybridge_research/pipeline.py research/tests/test_pipeline.py
git commit -m "Research: one-call family study for any window (in-sample, OOS, sealed)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The judged notebook

**Files:**
- Create: `research/make_notebook.py`, `research/polybridge_8k.ipynb` (generated), `research/README.md`
- Test: `research/tests/test_notebook.py`

**Interfaces:**
- Consumes: the package.
- Produces: a notebook with no outputs whose cells are, in order:
  1. Markdown: title, the pre-registration links, the two hypotheses in one sentence each, how to run (only `MASSIVE_API_KEY`; optional `SEC_USER_AGENT`).
  2. Code — configuration: `START, END = "2024-01-01", "2025-12-31"` (judges edit these), `RUN_OOS = False` (comment: flipped once, after the method freeze), `RUN_ATLAS = True`, `ATLAS_MAX_EVENTS = 30`, `MAX_WORKERS = 8`, `cfg = StudyConfig(); cfg.validate()`.
  3. Code — setup: `key = load_api_key(search_from=Path.cwd())`, `client = MassiveClient(key)`, `cal = TradingCalendar()`, `LAST = cal.last_completed()`, `UA = os.environ.get("SEC_USER_AGENT")`, print timing mode.
  4. Code — confirmatory study: `study = run_family_study(client, cal, cfg, START, END, LAST, user_agent=UA, max_workers=MAX_WORKERS)`; display event counts by family and year, the excluded cross-family count, timing counts, dropped reasons.
  5. Code — scoreboards: for each family, `scoreboard` of events and placebo; `difference_board` at 97.5%; a small-multiples plot (events vs placebo per strategy, CI band).
  6. Code — the pass check: a table per family with each headline horizon, the P&L CI, the ratio difference, ok flags, and a bold PASS / NULL line.
  7. Code — parity decay: `decay_table` for events and placebo per family, plotted.
  8. Code — sensitivity: for each family's strategy, the mean edge at h=21 across bucket × entry × OTM (the starter's grid), with `count_variants(cfg)` printed.
  9. Code — costs and capacity: `cost_table` for each family's strategy at h=21 and h=42, with summary lines (gross, haircut 1×/2×, spread, median leg volume).
  10. Code — atlas (if `RUN_ATLAS`): shared placebo of 300 days over `TOP_100` at the baseline spec, `run_atlas` on every taxonomy tag, a table of the 15 lowest q-values labeled EXPLORATORY, and `count_variants(cfg, n_tags=len(tags))`.
  11. Code — out-of-sample (only if `RUN_OOS`): `oos = run_family_study(..., cfg.oos_start, cfg.oos_end, ...)`, the in → out comparison table with same-sign marks; otherwise prints "Out-of-sample not run: it runs once, after the method freeze."
  12. Markdown + code — sealed window for judges: "Set START/END above to your window and rerun all cells"; nothing else needed.
  13. Markdown — known limitations (from the starter appendix) plus conservative timing when `SEC_USER_AGENT` is unset.
  - `research/README.md`: one command to reproduce: `pip install -r requirements.txt && jupyter nbconvert --to notebook --execute polybridge_8k.ipynb --ExecutePreprocessor.timeout=7200`, the `.env` instructions, and that only the Massive key is required.

- [ ] **Step 1: Write the failing test**

`research/tests/test_notebook.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generated_notebook_is_clean_and_safe():
    subprocess.run([sys.executable, str(ROOT / "make_notebook.py")], check=True)
    nb = json.loads((ROOT / "polybridge_8k.ipynb").read_text())
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert all(not c.get("outputs") and c.get("execution_count") is None for c in code)
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "RUN_OOS = False" in src
    assert 'START, END = "2024-01-01", "2025-12-31"' in src
    assert "hedgecore" not in src and "anthropic" not in src.lower()
    assert "run_family_study" in src and "pass_check" in src and "run_atlas" in src
    for c in code:
        compile("".join(c["source"]), "<cell>", "exec")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd research && .venv/bin/python -m pytest tests/test_notebook.py -q`
Expected: FAIL (`make_notebook.py` does not exist).

- [ ] **Step 3: Write `research/make_notebook.py`**

Controller note: this task's cell bodies are specified by behavior rather than transcribed in full, so dispatch it to a standard-or-better model.

The generator builds the 13 cells listed under Interfaces with `nbformat.v4.new_markdown_cell` / `new_code_cell` and writes `research/polybridge_8k.ipynb` with `nbformat.write`. Every code cell's source is a complete, runnable Python string that uses only the package's public functions named above and `pandas`, `numpy`, `matplotlib`, `os`, `pathlib`. Use these exact first lines for the configuration cell:

```python
# ---- Window. Judges: set your sealed window here and rerun all cells. ----
START, END = "2024-01-01", "2025-12-31"
RUN_OOS = False          # flipped once, after the method freeze (see research/HYPOTHESIS.md §4)
RUN_ATLAS = True         # exploratory atlas over every 8-K tag (HYPOTHESIS.md §5)
ATLAS_MAX_EVENTS = 30
MAX_WORKERS = 8

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from polybridge_research.analysis import decay_table, difference_board, pass_check, sample_placebo, scoreboard
from polybridge_research.atlas import count_variants, run_atlas
from polybridge_research.calendar import TradingCalendar
from polybridge_research.config import StudyConfig
from polybridge_research.costs import cost_table
from polybridge_research.evaluate import evaluate
from polybridge_research.massive import MassiveClient, load_api_key
from polybridge_research.pipeline import run_family_study
from polybridge_research.pricing import price_events

cfg = StudyConfig()
cfg.validate()
```

and this exact OOS cell:

```python
if RUN_OOS:
    oos = run_family_study(client, cal, cfg, cfg.oos_start, cfg.oos_end, LAST, user_agent=UA, max_workers=MAX_WORKERS)
    for fam, chk in oos["checks"].items():
        ins = study["checks"].get(fam)
        merged = ins["pnl"][["horizon", "difference"]].merge(chk["pnl"][["horizon", "difference"]], on="horizon",
                                                             suffixes=("_in", "_oos"))
        merged["same_sign"] = np.sign(merged.difference_in) == np.sign(merged.difference_oos)
        print(f"{fam}: in-sample -> out-of-sample edge of {chk['strategy']} (events minus placebo)")
        display(merged)
else:
    print("Out-of-sample not run: it runs once, after the method freeze.")
```

The atlas cell reads the taxonomy with `client.get_all("/stocks/taxonomies/vX/disclosures", {"limit": 1000})` and takes `sorted(t["tertiary_category"] for t in rows)`; its placebo is `sample_placebo(pd.DataFrame({"ticker": list(cfg.universe), "filing_date": [pd.Timestamp("1900-01-01")] * len(cfg.universe)}), 300, START, END, cal, gap_days=0, seed=11)` priced at the baseline bucket only.

- [ ] **Step 4: Generate, run the test, and write the README**

Run:
```bash
cd research && .venv/bin/python make_notebook.py && .venv/bin/python -m pytest tests/test_notebook.py -q
```
Expected: `1 passed`.

`research/README.md`:
```markdown
# PolyBridge research · Trade the 8-K

Pre-registration: [HYPOTHESIS.md](HYPOTHESIS.md) (19:38 ET, 2 Oct 2026) and [HYPOTHESIS_TAGS.md](HYPOTHESIS_TAGS.md) (20:08 ET), both committed before any event data was fetched.

## Reproduce (Python 3.10+, only a Massive API key)

```bash
cd research
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "MASSIVE_API_KEY=<your key>" > .env
jupyter nbconvert --to notebook --execute polybridge_8k.ipynb --ExecutePreprocessor.timeout=7200
```

Judges: edit `START, END` in the first code cell to your sealed window and rerun all cells. Optional: set `SEC_USER_AGENT="Name email"` to use EDGAR acceptance times; without it every filing is treated as public after the close (no lookahead).
```

- [ ] **Step 5: Commit**

```bash
git add research/make_notebook.py research/polybridge_8k.ipynb research/README.md research/tests/test_notebook.py
git commit -m "Research: the judged notebook (start/end inputs, OOS locked, atlas, costs)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: In-sample run and results — then stop for the method freeze

**Files:**
- Create: `research/results/in_sample/` (derived CSVs and PNGs only), `research/results/in_sample/SUMMARY.md`

**Interfaces:** Produces the in-sample evidence for the human's method-freeze decision. Does not run OOS.

- [ ] **Step 1: Execute the notebook on the in-sample window**

Run:
```bash
cd research && .venv/bin/jupyter nbconvert --to notebook --execute polybridge_8k.ipynb \
  --output /tmp/polybridge_in_sample.ipynb --ExecutePreprocessor.timeout=7200 2>&1 | tail -3
```
Expected: `Writing ... polybridge_in_sample.ipynb`. The executed copy goes to `/tmp`, so the committed notebook stays output-free.

- [ ] **Step 2: Export derived results**

Run a short script with the same package calls (or add an export cell guarded by `EXPORT_DIR = None`) that writes to `research/results/in_sample/`: per family `difference_board` (97.5%) as CSV, the pass-check table as CSV, decay tables as CSV, the sensitivity grid as CSV, the cost summary as CSV, the atlas table as CSV, and the scoreboard and decay figures as PNG. No raw API payloads.

- [ ] **Step 3: Write `research/results/in_sample/SUMMARY.md`**

Facts only, from the exported tables: events per family and year, excluded cross-family filings, dropped events by reason, timing mode, for each family the headline-horizon edges with 97.5% CIs and the pass/null verdict per HYPOTHESIS.md §4, the parity decay in one line, the sensitivity plateau or spike, costs (haircut 1×/2× and spread), median leg volume, total variants counted, and the five lowest atlas q-values marked EXPLORATORY.

- [ ] **Step 4: Commit, then stop**

```bash
git add research/results/in_sample
git commit -m "Research: in-sample results (confirmatory checks, decay, sensitivity, costs, exploratory atlas)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Stop here. The method freeze (decision D7) and the single out-of-sample run belong to the human and to the next plan.
