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
