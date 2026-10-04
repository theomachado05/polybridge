"""The notebook's weekend-studies section: every recomputed number must match the committed metrics."""
import weekend_studies_section as wss


def test_every_recomputed_number_matches_the_committed_metrics():
    check = wss.recompute()
    assert len(check) >= 64
    assert check["match"].all(), check[~check["match"]].to_string()


def test_findings_cover_the_studies_and_read_real_numbers():
    f = wss.findings()
    assert {"S4", "S5", "S7", "S8", "S9", "S10", "S12", "S14", "S15", "S16", "S18"} <= set(f.study)
    assert not f.value.str.contains("nan").any()
