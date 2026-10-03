import numpy as np
import pandas as pd
import yaml

from leadlag.events import Event, parse_event
from leadlag.pipeline import analyse_event

START = pd.Timestamp("2025-03-19 17:00:00", tz="UTC")   # 13:00 ET: inside the regular session
END = START + pd.Timedelta(minutes=210)


def make_event(sign=1, primary="SPY"):
    return Event(id="syn", name="synthetic", family="curated", selection="curated", anchor=None, start=START, end=END,
                 token_id="tok", market_slug="m", condition_id="c", question="q?", expected_sign=sign,
                 instruments=(primary, "QQQ"))


def pm_points(jump_at, jump=0.10, seed=0):
    """One CLOB point per minute from 4h before the window; price jumps at `jump_at` minutes after START."""
    rng = np.random.default_rng(seed)
    t = START - pd.Timedelta(minutes=190)
    pts, p = [], 0.40
    for i in range(190 + 210):
        ts = t + pd.Timedelta(minutes=i)
        if ts == START + pd.Timedelta(minutes=jump_at):
            p += jump
        pts.append((int(ts.timestamp()) + 1, round(p + rng.choice([0.0, 0.0, 0.001, -0.001]), 4)))
    return pts


def bars(jump_at, seed=1, sd=0.00015, drop=0.004):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(START - pd.Timedelta(minutes=190), END, freq="1min")
    r = rng.normal(0, sd, len(idx))
    r[idx.get_indexer([START + pd.Timedelta(minutes=jump_at)])[0]] += drop
    px = 450 * np.exp(np.cumsum(r))
    return pd.DataFrame({"close": px, "volume": 1000.0}, index=idx)


def test_pm_first_by_six_minutes_is_measured_and_usable():
    ev = make_event(sign=1)
    res = analyse_event(ev, pm_points(jump_at=60), {"SPY": bars(66), "QQQ": bars(66, seed=2)})
    assert res.usable, res.drop_reasons
    prim = res.primary
    assert res.pm_move is not None and prim.eq_move is not None
    assert 5 <= prim.lead <= 7 and prim.lead_cls == "PM first"
    assert prim.xc.peak_lag is not None
    assert set(res.instruments) == {"SPY", "QQQ"}


def test_equity_first_is_kept_and_classified():
    ev = make_event(sign=1)
    res = analyse_event(ev, pm_points(jump_at=100), {"SPY": bars(90), "QQQ": bars(90, seed=2)})
    assert res.usable
    assert res.primary.lead < -8 and res.primary.lead_cls == "equity first"


def test_simultaneous_move():
    ev = make_event()
    res = analyse_event(ev, pm_points(jump_at=80), {"SPY": bars(80), "QQQ": bars(80, seed=2)})
    assert res.primary.lead_cls == "simultaneous"


def test_empty_pm_history_is_dropped_with_reason():
    ev = make_event()
    res = analyse_event(ev, [], {"SPY": bars(60), "QQQ": bars(60)})
    assert not res.usable and "no minute history" in res.drop_reasons[0]


def test_flat_pm_is_dropped():
    ev = make_event()
    pts = [(int((START - pd.Timedelta(minutes=190) + pd.Timedelta(minutes=i)).timestamp()) + 1, 0.5) for i in range(400)]
    res = analyse_event(ev, pts, {"SPY": bars(60), "QQQ": bars(60)})
    assert not res.usable and "PM too flat" in res.drop_reasons[0]


def test_missing_equity_bars_are_dropped_as_thin():
    ev = make_event()
    res = analyse_event(ev, pm_points(60), {"QQQ": bars(60)})
    assert not res.usable and any("thin equity data for SPY" in r for r in res.drop_reasons)


def test_parse_event_validates_sign_and_window():
    d = yaml.safe_load("""
id: x
name: n
family: f
selection: curated
anchor_utc: null
window_start_utc: '2025-01-01T14:00:00Z'
window_end_utc: '2025-01-01T16:00:00Z'
pm: {token_id: '1', market_slug: s, condition_id: c, question: q}
expected_sign: -1
instruments: [SPY, QQQ]
""")
    ev = parse_event(d)
    assert ev.primary == "SPY" and ev.expected_sign == -1 and ev.anchor is None
    d["expected_sign"] = 0
    try:
        parse_event(d)
        raise AssertionError("expected_sign 0 must be rejected")
    except ValueError:
        pass


def test_committed_events_file_parses_and_has_enough_events():
    from leadlag.events import load_events
    evs = load_events()
    assert len(evs) >= 25
    assert all(e.token_id and e.start < e.end for e in evs)
    assert len({e.id for e in evs}) == len(evs)
