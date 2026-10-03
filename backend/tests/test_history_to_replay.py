import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from history_to_replay import parse_history  # noqa: E402


def test_parse_history_api_shape():
    payload = {"history": [{"t": 1700000120, "p": 0.31}, {"t": 1700000060, "p": 0.3}, {"t": 1700000060, "p": 0.3},
                           {"t": 1700000180, "p": 1.5}, {"t": "x", "p": 0.2}, {"p": 0.2}]}
    assert parse_history(payload) == [{"ts_ns": 1700000060 * 10**9, "p": 0.3}, {"ts_ns": 1700000120 * 10**9, "p": 0.31}]
    assert parse_history({}) == [] and parse_history({"history": None}) == []
