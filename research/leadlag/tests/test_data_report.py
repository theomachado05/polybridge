import json

import pandas as pd
import requests

from leadlag.data import fetch_equity_minutes, fetch_pm_history
from leadlag.report import robust_reading, verdict

S = pd.Timestamp("2025-03-19 14:00:00", tz="UTC")
E = S + pd.Timedelta(hours=3)


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url, **kw):
        self.calls += 1
        return self.responses.pop(0)


def test_pm_fetch_parses_caches_and_does_not_refetch(tmp_path):
    sess = FakeSession([FakeResp(200, {"history": [{"t": 1742392800, "p": 0.31}, {"t": 1742392860, "p": 0.32}]})])
    pts = fetch_pm_history("tok", S, E, tmp_path, session=sess, sleep=lambda s: None)
    assert pts == [(1742392800, 0.31), (1742392860, 0.32)] and sess.calls == 1
    again = fetch_pm_history("tok", S, E, tmp_path, session=FakeSession([]), sleep=lambda s: None)
    assert again == pts


def test_pm_fetch_retries_on_429_then_succeeds(tmp_path):
    sess = FakeSession([FakeResp(429), FakeResp(503), FakeResp(200, {"history": [{"t": 1, "p": 0.5}]})])
    sleeps = []
    pts = fetch_pm_history("tok2", S, E, tmp_path, session=sess, sleep=sleeps.append)
    assert pts == [(1, 0.5)] and sess.calls == 3 and len(sleeps) == 2


def test_pm_fetch_400_is_empty_history_not_a_crash(tmp_path):
    sess = FakeSession([FakeResp(400, text='{"error":"no data"}')])
    assert fetch_pm_history("tok3", S, E, tmp_path, session=sess, sleep=lambda s: None) == []


class FakeMassive:
    def __init__(self, rows):
        self.rows, self.paths = rows, []

    def get_all(self, path, params=None):
        self.paths.append((path, params))
        return self.rows


def test_equity_fetch_builds_utc_close_frame_and_uses_ms_range():
    c = FakeMassive([{"t": 1742392800000, "c": 100.0, "v": 5}, {"t": 1742392860000, "c": 100.5, "v": 7}])
    df = fetch_equity_minutes(c, "SPY", S, E)
    assert list(df["close"]) == [100.0, 100.5] and str(df.index.tz) == "UTC"
    path, params = c.paths[0]
    assert path == f"/v2/aggs/ticker/SPY/range/1/minute/{int(S.timestamp() * 1000)}/{int(E.timestamp() * 1000)}"
    assert params["adjusted"] == "true"
    empty = fetch_equity_minutes(FakeMassive([]), "SPY", S, E)
    assert len(empty) == 0


def _tests(pm_p, eq_p, pm_hac=0.5, eq_hac=0.5):
    g = {}
    for pp in (10, 30):
        g[("pm_to_eq", pp)] = dict(F=3.0, F_p=pm_p, hac_wald_p=pm_hac)
        g[("eq_to_pm", pp)] = dict(F=2.0 if eq_p < 0.05 else 1.0, F_p=eq_p, hac_wald_p=eq_hac)
    return {"subsets": {"all usable": dict(granger=g)}}


def test_decision_rule_branches():
    assert verdict(_tests(0.001, 0.5))[0] == "supports PM leading"
    assert verdict(_tests(0.001, 0.001))[0] == "supports PM leading"     # reverse significant but weaker (F 2 < 3)
    assert verdict(_tests(0.5, 0.001))[0] == "points the other way"
    assert verdict(_tests(0.5, 0.5))[0] == "no evidence"
    both = _tests(0.001, 0.001)
    both["subsets"]["all usable"]["granger"][("eq_to_pm", 10)]["F"] = 9.0
    assert verdict(both)[0] == "mixed"
    assert verdict({"subsets": {"all usable": None}})[0] == "no verdict"


def test_robust_reading_flags_when_hac_kills_significance():
    assert "no direction is significant" in robust_reading(_tests(0.5, 0.0001, pm_hac=0.6, eq_hac=0.2))
    assert "stays significant" in robust_reading(_tests(0.5, 0.0001, pm_hac=0.6, eq_hac=0.01))
