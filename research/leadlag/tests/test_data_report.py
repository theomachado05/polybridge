import json

import pandas as pd
import requests

from leadlag.data import fetch_equity_minutes, fetch_pm_history
from leadlag.report import _rel, _session, robust_reading, verdict

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


def _reg(wald_p=0.5, cum=0.0, cum_t=0.0):
    return (None, dict(wald_p=wald_p, cum=cum, cum_t=cum_t, n=100, events=3))


def _tests(pm_p, eq_p, pm_hac=0.5, eq_hac=0.5, A=None, B=None, extra=None):
    g = {}
    for pp in (10, 30):
        g[("pm_to_eq", pp)] = dict(F=3.0, F_p=pm_p, hac_wald_p=pm_hac)
        g[("eq_to_pm", pp)] = dict(F=2.0 if eq_p < 0.05 else 1.0, F_p=eq_p, hac_wald_p=eq_hac)
    subsets = {"all usable": dict(granger=g, A=A or _reg(), B=B or _reg())}
    subsets.update(extra or {})
    return {"subsets": subsets}


def test_decision_rule_branches():
    assert verdict(_tests(0.001, 0.5))[0] == "supports PM leading"
    assert verdict(_tests(0.001, 0.001))[0] == "supports PM leading"     # reverse significant but weaker (F 2 < 3)
    assert verdict(_tests(0.5, 0.001))[0] == "points the other way"
    assert verdict(_tests(0.5, 0.5))[0] == "no evidence"
    both = _tests(0.001, 0.001)
    both["subsets"]["all usable"]["granger"][("eq_to_pm", 10)]["F"] = 9.0
    assert verdict(both)[0] == "mixed"
    assert verdict({"subsets": {"all usable": None}})[0] == "no verdict"


def test_robust_reading_no_pm_lead_when_nothing_significant():
    rob, plain = robust_reading(_tests(0.5, 0.0001, pm_hac=0.6, eq_hac=0.2))
    assert "0 of 4 significant" in rob
    assert "no HAC statistic supports prediction markets leading" in plain
    assert "No equity-to-PM HAC statistic is significant either" in plain


def test_robust_reading_does_not_claim_nothing_is_significant_when_reg_tests_are():
    """Reviewer case: Granger HAC not significant, but Reg B cumulative t=2.29 and a curated-subset Wald p=0.003 both ways."""
    t = _tests(0.5, 0.0001, pm_hac=0.88, eq_hac=0.07, A=_reg(0.74, -0.08, -1.2), B=_reg(0.14, 0.20, 2.29),
               extra={"curated": dict(granger={}, A=_reg(0.003, -0.04, -0.45), B=_reg(0.002, 0.41, 3.16))})
    rob, plain = robust_reading(t)
    assert "nothing is significant" not in plain and "nothing is significant" not in rob
    assert "+2.29" in rob and "0.003" in plain and "0.002" in plain
    assert "not significant at 5%" in plain  # HAC Granger tests
    assert "oversized" in plain
    assert "no HAC statistic supports prediction markets leading" in plain


def test_robust_reading_notes_pm_lead_when_a_positive_pm_statistic_is_significant():
    t = _tests(0.001, 0.5, A=_reg(0.01, 0.3, 2.5))
    _, plain = robust_reading(t)
    assert "mixed rather than absent" in plain


def test_anchor_relative_and_session_helpers():
    anchor = pd.Timestamp("2025-03-19 18:00:00", tz="UTC")
    assert _rel(pd.Timestamp("2025-03-19 17:45:00", tz="UTC"), anchor) == "-15"
    assert _rel(pd.Timestamp("2025-03-19 18:02:00", tz="UTC"), anchor) == "+2"
    assert _rel(None, anchor) == "n/a" and _rel(anchor, None) == "n/a"
    assert _session(pd.Timestamp("2026-01-28 19:00:00", tz="UTC")) == "RTH"   # 14:00 ET
    assert _session(pd.Timestamp("2026-01-28 21:01:00", tz="UTC")) == "ext"   # 16:01 ET, after the close
    assert _session(None) == ""
