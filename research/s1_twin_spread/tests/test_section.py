import socket

import pytest


def test_s1_numbers_recompute_offline_and_match_the_committed_metrics(monkeypatch):
    def blocked(*a, **k):
        raise RuntimeError("network blocked")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    import twin_spread_section as tss

    try:
        data = tss.load()
    except FileNotFoundError:
        pytest.skip("S1 results are not committed yet")
    rec = tss.recompute(data)
    chk = tss.comparison(rec, data)
    assert chk["match"].all(), chk[~chk["match"]]
    summary = tss.summary(rec).set_index("finding")["verdict"]
    assert summary["Pre-registered success criterion"] == rec["verdict"]
    assert (rec["verdict"] == "pass") == all(rec["criteria"].values())
