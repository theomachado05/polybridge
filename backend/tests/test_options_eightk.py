import asyncio
import datetime as dt
import json
import math

import pytest

from app.options import eightk as ek

AS_OF = "2025-06-30"


def f(ticker, date, *tags):
    return {"ticker": ticker, "filing_date": date, "tags": list(tags), "accession_number": f"{ticker}-{date}"}


def test_family_mapping_matches_research_rules():
    from polybridge_research.schema import H1_TAGS, H2_TAGS, assign_family
    assert ek.H1_TAGS == H1_TAGS and ek.H2_TAGS == H2_TAGS
    for tags in (["material_litigation"], ["workforce_reduction"], ["goodwill_impairment", "restructuring_plan"],
                 ["settlement_agreement"], []):
        fam = assign_family(tags)
        assert ek.family_of(tags) == (fam.value if fam else None)


def test_hedge_tag_negative_opportunity_tag_positive_on_filing_day():
    assert ek.eightk_score("XYZ", AS_OF, filings=[f("XYZ", AS_OF, "class_action_filing")]) == -1.0
    assert ek.eightk_score("XYZ", AS_OF, filings=[f("XYZ", AS_OF, "restructuring_plan")]) == 1.0


def test_linear_decay_over_window():
    rows = [f("XYZ", "2025-06-15", "workforce_reduction")]
    assert ek.eightk_score("XYZ", AS_OF, 30, rows) == pytest.approx(0.5)
    assert ek.eightk_score("XYZ", AS_OF, 60, rows) == pytest.approx(0.75)
    assert ek.eightk_score("XYZ", AS_OF, 10, rows) == 0.0


def test_most_recent_qualifying_filing_wins():
    rows = [f("XYZ", "2025-06-01", "material_litigation"), f("XYZ", "2025-06-27", "facility_closure"),
            f("XYZ", "2025-06-29", "settlement_agreement"),
            f("XYZ", "2025-06-29", "asset_impairment", "restructuring_plan"),
            f("XYZ", "2025-07-02", "cybersecurity_incident")]
    assert ek.eightk_score("XYZ", AS_OF, 30, rows) == pytest.approx(0.9)
    d = ek.eightk_detail("xyz", AS_OF, 30, rows)
    assert d["filing"]["family"] == "opportunity" and d["filing"]["filing_date"] == "2025-06-27"
    assert d["ticker"] == "XYZ" and d["score"] == pytest.approx(0.9)


def test_zero_when_none_or_bad_input():
    assert ek.eightk_score("XYZ", AS_OF, filings=[]) == 0.0
    assert ek.eightk_score("ABC", AS_OF, filings=[f("XYZ", AS_OF, "material_litigation")]) == 0.0
    assert ek.eightk_score("XYZ", AS_OF, filings=[{"ticker": "XYZ", "filing_date": "bad", "tags": ["x"]}]) == 0.0
    assert ek.eightk_score("XYZ", AS_OF, filings=[None]) == 0.0
    assert ek.eightk_score("XYZ", AS_OF, window_days=0, filings=[f("XYZ", AS_OF, "material_litigation")]) == 0.0
    assert ek.eightk_detail("XYZ", AS_OF, 30, [])["filing"] is None


def test_share_class_normalisation():
    assert ek.eightk_score("BRK.B", AS_OF, filings=[f("BRK/B", AS_OF, "material_litigation")]) == -1.0


def test_rows_to_filings_groups_tags_per_accession_and_ticker():
    rows = [{"tickers": ["AAA", "aaa.b"], "accession_number": "1", "filing_date": "2025-01-02", "tertiary_category": "asset_impairment"},
            {"tickers": ["AAA"], "accession_number": "1", "filing_date": "2025-01-02", "tertiary_category": "restructuring_plan"},
            {"ticker": "BBB", "accession_number": "2", "filing_date": "2025-01-03", "tertiary_category": "workforce_reduction"},
            {"tickers": ["CCC"], "accession_number": "", "filing_date": "2025-01-03", "tertiary_category": "x"}]
    out = ek.rows_to_filings(rows)
    by = {(r["ticker"], r["accession_number"]): r for r in out}
    assert by[("AAA", "1")]["tags"] == ["asset_impairment", "restructuring_plan"] and by[("AAA", "1")]["family"] is None
    assert by[("AAA.B", "1")]["family"] == "hedge"
    assert by[("BBB", "2")]["family"] == "opportunity"
    assert len(out) == 3


def test_oos_window_is_never_read():
    with pytest.raises(ek.OOSWindowError):
        ek.check_window("2025-12-01", "2026-01-15")
    with pytest.raises(ek.OOSWindowError):
        ek.fetch_disclosure_rows(lambda *a: pytest.fail("must not call Massive"), "2026-03-01", "2026-03-31")
    ek.check_window("2024-01-01", "2025-12-31")
    ek.check_window("2026-09-01", "2026-10-03")


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_all(self, path, params):
        self.calls.append((path, params))
        if params["tertiary_category"] == "workforce_reduction":
            return [{"tickers": ["XYZ"], "accession_number": "9", "filing_date": "2026-09-28"}]
        return []


def test_fetch_recent_clamps_start_after_oos_window():
    c = FakeClient()
    out = ek.fetch_recent(c, as_of="2026-09-10", window_days=30)
    assert {p["filing_date.gte"] for _, p in c.calls} == {"2026-09-01"}
    assert len(c.calls) == len(ek.H1_TAGS | ek.H2_TAGS)
    assert out[0]["family"] == "opportunity"
    c2 = FakeClient()
    assert ek.fetch_recent(c2, as_of="2026-05-01") == [] and c2.calls == []


def test_bundled_file_is_in_sample_only():
    payload = json.loads(ek.DATA_FILE.read_text())
    rows = payload["filings"]
    assert len(rows) > 100
    dates = {r["filing_date"] for r in rows}
    assert min(dates) >= "2024-01-01" and max(dates) <= "2025-12-31"
    assert {r["family"] for r in rows} == {"hedge", "opportunity"}
    some = rows[-1]
    s = ek.eightk_score(some["ticker"], as_of=some["filing_date"])
    assert s == (1.0 if some["family"] == "opportunity" else -1.0) or abs(s) == 1.0
    assert math.isnan(ek.eightk_score(some["ticker"], as_of=dt.date(2030, 1, 1)))


@pytest.fixture
def no_live(monkeypatch):
    monkeypatch.setattr(ek, "_LIVE", {})


def test_no_data_is_nan_and_no_filing_is_zero(no_live):
    assert ek.eightk_coverage("2025-06-30") == "in_sample"
    assert ek.eightk_score("NO_SUCH_TICKER", "2025-06-30") == 0.0
    assert ek.eightk_coverage("2026-10-03") is None and math.isnan(ek.eightk_score("XYZ", "2026-10-03"))
    assert ek.eightk_coverage("2026-05-01") is None and math.isnan(ek.eightk_score("XYZ", "2026-05-01"))
    d = ek.eightk_detail("XYZ", "2026-10-03")
    assert d["coverage"] is None and d["score"] is None


def test_refresh_eightk_loads_live_store_used_by_score(no_live):
    c = FakeClient()
    assert asyncio.run(ek.refresh_eightk("2026-10-03", client=c)) == "live"
    assert ek.eightk_score("XYZ", "2026-10-03") == pytest.approx(1 - 5 / 30)
    assert ek.eightk_score("ABC", "2026-10-03") == 0.0
    assert ek.eightk_detail("XYZ", "2026-10-03")["coverage"] == "live"
    n = len(c.calls)
    assert asyncio.run(ek.refresh_eightk("2026-10-03", client=c)) == "live" and len(c.calls) == n
    assert math.isnan(ek.eightk_score("XYZ", "2026-10-05"))


def test_refresh_eightk_never_raises_and_never_reads_oos(no_live):
    class Boom:
        def get_all(self, *a):
            raise TimeoutError
    assert asyncio.run(ek.refresh_eightk("2026-10-03", client=Boom())) is None
    assert math.isnan(ek.eightk_score("XYZ", "2026-10-03"))
    assert asyncio.run(ek.refresh_eightk("2026-05-01", client=Boom())) is None
