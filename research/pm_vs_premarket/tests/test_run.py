"""End-to-end on synthetic tables and a fake Massive client: no network, no key, no real data."""
import json
import zlib

import numpy as np
import pandas as pd
import pytest

from pm_vs_premarket import run
from pm_vs_premarket.config import Params, TZ


def _u(day: str, salt: str) -> float:
    return (zlib.crc32(f"{day}{salt}".encode()) % 10_000) / 10_000 - 0.5


class FakeClient:
    """SPY/QQQ: flat RTH at P_d, pre-market 07:00-09:29 at Q_d. Futures endpoint not entitled."""

    def __init__(self):
        self.calls = []

    def get_all(self, path, params=None):
        self.calls.append(path)
        if path.startswith("/futures/"):
            raise RuntimeError("403 not entitled")
        parts = path.split("/")
        tk, a, b = parts[3], int(parts[-2]), int(parts[-1])
        days = pd.bdate_range(pd.Timestamp(a, unit="ms").normalize(), pd.Timestamp(b, unit="ms").normalize())
        rows = []
        lvl = 100.0
        for d in pd.bdate_range("2024-01-01", days[-1] if len(days) else "2024-01-02"):
            ds = d.strftime("%Y-%m-%d")
            q = lvl * (1 + 0.01 * _u(ds, tk + "b"))
            p = q * (1 + 0.001 * _u(ds, tk + "r"))
            if d >= days[0]:
                for t in pd.date_range(f"{ds} 07:00", f"{ds} 09:29", freq="5min").append(pd.DatetimeIndex([pd.Timestamp(f"{ds} 09:24")])):
                    rows.append((t, q))
                for t in pd.date_range(f"{ds} 09:30", f"{ds} 15:59", freq="1min"):
                    rows.append((t, p))
            lvl = p
        out = []
        for t, px in sorted(rows):
            ms = int(pd.Timestamp(t, tz=TZ).timestamp() * 1000)
            if a <= ms <= b:
                out.append({"t": ms, "o": px, "c": px, "v": 10})
        return out


def pm_fetch(token, c):
    ds = c.open_day.strftime("%Y-%m-%d")
    t_close = int(c.nominal_close.timestamp())
    t8 = int(pd.Timestamp(f"{ds} 07:00", tz=TZ).timestamp())
    p0, p1 = 0.5, 0.5 + 0.02 * _u(ds, "SPYb") * (1 if token == "1" else -1)
    pts = [(t_close - 600 + 60 * i, p0) for i in range(20)]
    pts += [(t8 + 60 * i, p1) for i in range(0, 160, 5)]
    return pts


def _inputs(tmp_path):
    days = pd.bdate_range("2024-04-01", periods=46)
    rows = []
    for i in range(45):
        rows.append({"closure": days[i].strftime("%Y-%m-%d"), "open_day": days[i + 1].strftime("%Y-%m-%d"),
                     "kind": "overnight", "market": "election" if i < 25 else "recession", "sign": 1 if i < 25 else -1,
                     "pm_close": 50.0, "dpm_o_pp": 1.0 * (i % 3 - 1), "dpm_early_o_pp": 1.0 * (i % 3 - 1),
                     "gap_bp": 10.0 * (i % 5 - 2) + i % 3, "resid_bp": float(i % 7 - 3), "gap_qqq_bp": 0.0,
                     "reason": "", "news": i == 7})
    a = tmp_path / "closures_all.csv"
    pd.DataFrame(rows).to_csv(a, index=False)
    ev = tmp_path / "events.yaml"
    ev.write_text("markets:\n  election: {market_slug: e, token_id: '1', sign: 1}\n  recession: {market_slug: r, token_id: '2', sign: -1}\n")
    b = tmp_path / "results.csv"
    brows = [{"market": m, "sign": s, "closure": r["closure"], "open_day": r["open_day"], "kind": "overnight",
              "pm_close": 50.0, "gap_spy_bp": r["gap_bp"], "reason": ""} for r in rows[:30] for m, s in (("m1", 1), ("m2", -1))]
    pd.DataFrame(brows).to_csv(b, index=False)
    mk = tmp_path / "markets.json"
    mk.write_text(json.dumps({"candidates": [{"market_slug": "m1", "token_id": "1", "sign": 1},
                                             {"market_slug": "m2", "token_id": "2", "sign": -1}]}))
    return ["--primary-csv", str(a), "--events", str(ev), "--secondary-csv", str(b), "--markets", str(mk)]


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(run, "PARAMS", Params(n_perm=49, n_boot=49))
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)


def test_missing_key_runs_arm_k_only_then_refuses_second_arm_k(tmp_path):
    out = tmp_path / "out"
    args = _inputs(tmp_path) + ["--out-dir", str(out), "--env-file", str(tmp_path / "none.env")]
    assert run.main(args) == 2
    for f in ("SUMMARY.md", "tests.json", "rows.csv", ".done"):
        assert (out / "arm_k" / f).exists()
    assert not (out / ".done").exists()
    t = json.loads((out / "arm_k" / "tests.json").read_text())
    assert t["n_rows"] == 44 and t["k_0800"]["n"] == 44
    before = (out / "arm_k" / "tests.json").read_text()
    assert run.main(args) == 2
    assert (out / "arm_k" / "tests.json").read_text() == before
    log = (out / "RUN_LOG.md").read_text()
    assert log.count("arm K already run") == 1 and "needs MASSIVE_API_KEY" in log


def test_arm_m_with_fake_client_falls_back_to_spy(tmp_path):
    out = tmp_path / "out"
    args = _inputs(tmp_path) + ["--out-dir", str(out)]
    client = FakeClient()
    assert run.main(args, client=client, pm_fetch=pm_fetch) == 0
    t = json.loads((out / "tests.json").read_text())
    assert t["benchmark"] == "SPY"
    p = t["primary_0925"]
    assert p["n"] == 44 and p["r2_reduced"] > 0.9
    assert t["tests"]["s2_0925"]["n"] == 60 and t["tests"]["s2_0925"]["n_dates"] == 30
    assert "max abs difference" in t["consistency"]
    s = (out / "SUMMARY.md").read_text()
    assert "Verdict under the pre-set rule" in s and "SPY" in s
    n_calls = len(client.calls)
    assert run.main(args, client=client, pm_fetch=pm_fetch) == 0
    assert len(client.calls) == n_calls


def test_load_key_reads_only_given_env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("OTHER=1\nMASSIVE_API_KEY='abc'\n")
    assert run.load_key(f) == "abc"
    assert run.load_key(tmp_path / "missing.env") == ""
