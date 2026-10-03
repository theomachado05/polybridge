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
    assert (cfg.baseline_bucket, cfg.otm_pct, cfg.entry, cfg.cost_haircut, cfg.n_placebo) == ("3-6m", 0.05, "post", 0.05, 120)
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
