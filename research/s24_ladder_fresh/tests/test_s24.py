"""S24: the fresh-set rules, prints in YES terms, detection from two prints, the trade at 1x and 2x, the out-of-sample cut."""
import json

import numpy as np
import pandas as pd

from s24_ladder_fresh import config as cfg
from s24_ladder_fresh import engine as en
from s24_ladder_fresh import run as rn
from s24_ladder_fresh import universe as uni
from s24_ladder_fresh.pull import compact

NOFEE = (0.0, 1.0)
T0 = 1_750_000_000          # 2025-06-15 15:06:40 UTC = 11:06:40 New York


def raw_market(i, q, vol=100_000.0, start="2025-03-01T00:00:00Z", outcomes='["Yes", "No"]', **kw):
    return {"id": i, "question": q, "volume": vol, "startDate": start, "endDate": "2025-12-31T00:00:00Z", "conditionId": f"0x{i:064x}",
            "clobTokenIds": json.dumps([f"y{i}", f"n{i}"]), "outcomes": outcomes, "bestBid": 0.4, "lastTradePrice": 0.41,
            "outcomePrices": '["0.4", "0.6"]', **kw}


def ev(markets, **kw):
    return {"id": 1, "slug": "e", "title": "E", "volume": 1e6, "startDate": "2025-03-01T00:00:00Z", "markets": markets, **kw}


# ---------------------------------------------------------------- the lists

def test_strip_drops_every_price_field():
    m = uni.strip(raw_market(1, "X by May 31?"))
    assert not {"bestBid", "lastTradePrice", "outcomePrices"} & set(m)
    assert m["outcomes"] == ["Yes", "No"] and m["token"] == "y1"


def test_set_membership_by_listing_date_and_volume():
    a = uni.strip(raw_market(1, "q", vol=50_000.0, start="2025-09-30T23:00:00Z"))
    assert uni.in_set(a, "a") and not uni.in_set(a, "b")
    assert not uni.in_set(uni.strip(raw_market(1, "q", vol=49_999.0, start="2025-09-30T23:00:00Z")), "a")
    assert not uni.in_set(uni.strip(raw_market(1, "q", vol=60_000.0, start="2023-12-31T23:00:00Z")), "a")
    b = uni.strip(raw_market(1, "q", vol=10_000.0, start="2025-10-01T00:00:00Z"))
    assert uni.in_set(b, "b") and not uni.in_set(b, "a")
    assert not uni.in_set(uni.strip(raw_market(1, "q", vol=50_000.0, start="2025-10-01T00:00:00Z")), "b")     # S11's floor is not fresh
    assert not uni.in_set(uni.strip(raw_market(1, "q", vol=9_999.0, start="2026-01-01T00:00:00Z")), "b")


def test_date_ladder_built_and_s11_markets_removed():
    ms = [raw_market(1, "Ceasefire by April 30?"), raw_market(2, "Ceasefire by May 31?"), raw_market(3, "Ceasefire by June 30?")]
    bs, meta = uni.event_ladders(ev(ms), set(), set())
    assert len(bs) == 1 and bs[0]["set"] == "a" and bs[0]["kind"] == "date"
    assert bs[0]["pairs"] == [["1", "2"], ["2", "3"]]                 # [rich = earlier, cheap = later]
    bs, _ = uni.event_ladders(ev(ms), {"2"}, set())                   # market 2 was used by S11
    assert bs[0]["legs"] == ["1", "3"] and bs[0]["pairs"] == [["1", "3"]]
    bs, _ = uni.event_ladders(ev(ms), set(), {f"0x{2:064x}"})         # the same by condition id
    assert bs[0]["legs"] == ["1", "3"]
    assert all("bestBid" not in m and "outcomePrices" not in m for m in meta.values())


def test_sets_never_mix_in_one_ladder():
    ms = [raw_market(1, "X by April 30?"), raw_market(2, "X by May 31?"),
          raw_market(3, "X by June 30?", vol=20_000.0, start="2025-11-01T00:00:00Z"),
          raw_market(4, "X by July 31?", vol=20_000.0, start="2025-11-01T00:00:00Z")]
    bs, _ = uni.event_ladders(ev(ms), set(), set())
    assert sorted((b["set"], tuple(b["legs"])) for b in bs) == [("a", ("1", "2")), ("b", ("3", "4"))]


def test_only_yes_no_markets_are_rungs():
    ms = [raw_market(1, "Total over 3.5?", outcomes='["Over", "Under"]'), raw_market(2, "Total over 4.5?", outcomes='["Over", "Under"]')]
    assert uni.event_ladders(ev(ms), set(), set())[0] == []


def test_strike_ladder_needs_one_date_phrase():
    ms = [raw_market(1, "Will Bitcoin reach $100,000 by June 30?"), raw_market(2, "Will Bitcoin reach $120,000 by December 31?")]
    bs, _ = uni.event_ladders(ev(ms), set(), set())
    assert [b for b in bs if b["kind"] == "strike"] == []             # different deadlines: no logical order
    ms = [raw_market(1, "Will Bitcoin reach $100,000 by June 30?"), raw_market(2, "Will Bitcoin reach $120,000 by June 30?")]
    bs, _ = uni.event_ladders(ev(ms), set(), set())
    assert bs[0]["kind"] == "strike" and bs[0]["pairs"] == [["2", "1"]]      # the higher level is the rich rung


def test_or_lower_contradicting_the_direction_is_left_out():
    ms = [raw_market(1, "Will the Fed's lower bound reach 3.0% or lower before 2027?"),
          raw_market(2, "Will the Fed's lower bound reach 3.5% or lower before 2027?")]
    assert uni.event_ladders(ev(ms), set(), set())[0] == []
    ms = [raw_market(1, "Will the Fed's upper bound reach 4.0% or higher before 2027?"),
          raw_market(2, "Will the Fed's upper bound reach 4.5% or higher before 2027?")]
    assert uni.event_ladders(ev(ms), set(), set())[0][0]["pairs"] == [["2", "1"]]


def test_pull_order_is_largest_event_first():
    a = {"event_volume": 5.0, "event": "x", "kind": "date", "legs": ["1"]}
    b = {"event_volume": 9.0, "event": "y", "kind": "date", "legs": ["2"]}
    assert sorted([a, b], key=uni.order_key) == [b, a]


# ---------------------------------------------------------------- prints

def test_yes_terms():
    p, s = en.yes_terms([0.30, 0.30, 0.30, 0.30], [1, -1, 1, -1], [1, 1, 0, 0])
    assert np.allclose(p, [0.30, 0.30, 0.70, 0.70])
    assert list(s) == [1, -1, -1, 1]          # a taker who buys NO sells YES; a taker who sells NO buys YES


def test_compact_sorts_and_drops_duplicates():
    x = {"transactionHash": "h", "asset": "a", "timestamp": 20, "price": 0.5, "size": 3, "side": "BUY", "outcome": "Yes", "proxyWallet": "w"}
    y = dict(x, transactionHash="g", timestamp=10, side="SELL", outcome="No")
    a = compact([x, y, dict(x)])
    assert list(a["t"]) == [10, 20] and list(a["side"]) == [-1, 1] and list(a["out"]) == [0, 1]


# ---------------------------------------------------------------- detection

def test_match_needs_gap_above_fees_and_window():
    # sale at 0.50, purchase at 0.47, 5 minutes apart: a match
    m = en.first_matches([T0], [0.50], [40], [T0 + 300], [0.47], [70], NOFEE, NOFEE, 600)
    assert len(m) == 1 and m[0]["t_entry"] == T0 + 300 and m[0]["sale_print"] == 0.50 and m[0]["buy_print"] == 0.47
    assert en.first_matches([T0], [0.50], [40], [T0 + 601], [0.47], [70], NOFEE, NOFEE, 600) == []     # too far apart
    assert en.first_matches([T0], [0.50], [40], [T0 + 300], [0.47], [70], NOFEE, NOFEE, 120) == []     # the 2-minute variant
    assert en.first_matches([T0], [0.47], [40], [T0 + 300], [0.50], [70], NOFEE, NOFEE, 600) == []     # in order: no trade
    assert en.first_matches([T0], [0.50], [40], [T0], [0.50], [70], NOFEE, NOFEE, 600) == []           # equal: no trade
    fee = (0.04, 1.0)                                                                                  # 1 point at 50%
    assert en.first_matches([T0], [0.50], [40], [T0 + 10], [0.49], [70], fee, fee, 600) == []          # gap 1 < fees 2
    assert len(en.first_matches([T0], [0.50], [40], [T0 + 10], [0.47], [70], fee, fee, 600)) == 1      # gap 3 > fees 2


def test_first_match_of_the_day_and_most_recent_partner():
    ta, pa, za = [T0, T0 + 4000], [0.50, 0.60], [10, 10]
    tb, pb, zb = [T0 - 500, T0 - 100, T0 + 3900, T0 + 90000], [0.40, 0.45, 0.30, 0.20], [5, 6, 7, 8]
    m = en.first_matches(ta, pa, za, tb, pb, zb, NOFEE, NOFEE, 600)
    assert len(m) == 1                              # one trade a day; the last purchase has no sale within 10 minutes
    assert m[0]["t_entry"] == T0 and m[0]["t_buy"] == T0 - 100 and m[0]["buy_print"] == 0.45     # the most recent partner
    assert m[0]["size_sale"] == 10 and m[0]["size_buy"] == 6


def test_one_trade_per_new_york_day():
    day = 86400
    ta, tb = [T0, T0 + 60, T0 + day], [T0 + 30, T0 + 90, T0 + day + 30]
    m = en.first_matches(ta, [0.5] * 3, [1] * 3, tb, [0.4] * 3, [1] * 3, NOFEE, NOFEE, 600)
    assert [x["t_entry"] for x in m] == [T0 + 30, T0 + day + 30]
    assert m[0]["date"] == "2025-06-15" and m[1]["date"] == "2025-06-16"


def test_range_queries_match_brute_force():
    rng = np.random.default_rng(0)
    ta, tb = np.sort(rng.integers(T0, T0 + 20000, 300)), np.sort(rng.integers(T0, T0 + 20000, 300))
    pa, pb = rng.uniform(0.3, 0.6, 300).round(2), rng.uniform(0.4, 0.7, 300).round(2)
    m = en.first_matches(ta, pa, np.ones(300), tb, pb, np.ones(300), NOFEE, NOFEE, 120)
    best = None
    for i in range(300):
        for j in range(300):
            if abs(ta[i] - tb[j]) <= 120 and pa[i] - pb[j] > 1e-12:
                t = max(ta[i], tb[j])
                if en.ny_date([t])[0] == m[0]["date"] and (best is None or t < best):
                    best = t
    assert m and m[0]["t_entry"] == best
    assert abs(m[0]["t_sale"] - m[0]["t_buy"]) <= 120 and m[0]["sale_print"] > m[0]["buy_print"]


def test_prints_after_a_close_or_without_a_fill_are_not_used():
    def P(t, price, side, out, size):
        yp, ys = en.yes_terms(price, side, out)
        return {"t": np.array(t), "price": np.array(price), "side": np.array(side), "out": np.array(out), "size": np.array(size),
                "yp": yp, "ys": ys, "ok": np.ones(len(t), bool)}
    a = P([T0, T0 + 50], [0.50, 0.40], [-1, 1], [1, 0], [10.0, 10.0])        # SELL Yes @0.50; BUY No @0.40 = sells YES at 0.60
    b = P([T0 + 20], [0.45], [1], [1], [10.0])
    ms, ia, ib = rn.pair_matches(a, b, NOFEE, NOFEE, None, 600)
    assert len(ms) == 1 and ms[0]["t_entry"] == T0 + 20 and ms[0]["sale_print"] == 0.50
    assert rn.pair_matches(a, b, NOFEE, NOFEE, T0 + 20, 600)[0] == []        # the purchase is at the close: not used
    ms, _, _ = rn.pair_matches(a, b, NOFEE, NOFEE, T0 + 21, 600)
    assert len(ms) == 1
    lo = P([T0], [0.02], [-1], [1], [10.0])                                  # a sale at 2 cents: no fill two cents lower
    assert rn.pair_matches(lo, P([T0], [0.01], [1], [1], [10.0]), NOFEE, NOFEE, None, 600)[0] == []
    hi = P([T0], [0.99], [-1], [1], [10.0])
    assert rn.pair_matches(hi, P([T0], [0.98], [1], [1], [10.0]), NOFEE, NOFEE, None, 600)[0] == []     # a purchase at 98: no fill at 100
    # a taker who SELLS YES on the cheap rung or BUYS YES on the rich rung proves nothing
    assert rn.pair_matches(P([T0], [0.5], [1], [1], [1.0]), P([T0], [0.4], [-1], [1], [1.0]), NOFEE, NOFEE, None, 600)[0] == []


# ---------------------------------------------------------------- the trade

def test_trade_at_1x_and_2x():
    t = en.trade(0.50, 0.45, NOFEE, NOFEE, 1.0, 0.0, 0.0)
    assert abs(t["sell_at"] - 0.49) < 1e-12 and abs(t["buy_at"] - 0.46) < 1e-12 and abs(t["edge"] - 0.03) < 1e-12
    assert abs(t["pnl"] - 0.03) < 1e-12 and abs(t["capital"] - 0.97) < 1e-12 and t["settled_by"] == "result"
    assert abs(en.trade(0.50, 0.45, NOFEE, NOFEE, 2.0, 0.0, 0.0)["edge"] - 0.01) < 1e-12              # one further cent on each price
    fee = (0.04, 1.0)
    t1, t2 = en.trade(0.50, 0.45, fee, fee, 1.0, 1.0, 1.0), en.trade(0.50, 0.45, fee, fee, 2.0, 1.0, 1.0)
    f1 = 0.04 * 0.49 * 0.51 + 0.04 * 0.46 * 0.54
    f2 = 2 * (0.04 * 0.48 * 0.52 + 0.04 * 0.47 * 0.53)
    assert abs(t1["pnl"] - (0.03 - f1)) < 1e-12 and abs(t2["pnl"] - (0.01 - f2)) < 1e-12


def test_trade_results():
    e = 0.03
    assert abs(en.trade(0.50, 0.45, NOFEE, NOFEE, 1.0, 0.0, 1.0)["pnl"] - (e + 1)) < 1e-12     # rich NO, cheap YES: pays $1 more
    assert abs(en.trade(0.50, 0.45, NOFEE, NOFEE, 1.0, 1.0, 1.0)["pnl"] - e) < 1e-12
    assert abs(en.trade(0.50, 0.45, NOFEE, NOFEE, 1.0, 1.0, 0.0)["pnl"] - (e - 1)) < 1e-12     # order violated at the result: loses $1
    t = en.trade(0.50, 0.45, NOFEE, NOFEE, 1.0, None, 1.0)
    assert abs(t["pnl"] - e) < 1e-12 and t["settled_by"].startswith("open")                    # no result yet: the entry edge alone
    assert en.trade(0.50, 0.49, NOFEE, NOFEE, 1.0, 0.0, 0.0)["pnl"] < 0                        # a 1-cent gap loses a cent after the haircut


def test_fills_exist():
    assert en.fills_exist(0.021, 0.979) and not en.fills_exist(0.020, 0.5) and not en.fills_exist(0.5, 0.98)


# ---------------------------------------------------------------- split and statistics

def test_oos_cut_is_the_most_recent_fifth_of_trade_dates():
    d = [f"2025-01-{i:02d}" for i in range(1, 11)]
    assert en.oos_cut(d + d) == "2025-01-09"                     # 10 dates: the last 2
    assert en.oos_cut(d[:6]) == "2025-01-05"                     # 6 dates: 1.2 rounds up to 2
    assert en.oos_cut([]) is None


def test_boot_is_over_dates():
    df = pd.DataFrame({"date": ["d1"] * 50 + ["d2", "d3", "d4", "d5", "d6"], "x": [1.0] * 50 + [0.0] * 5})
    m, lo, hi, n, nd = en.boot(df, "x")
    assert n == 55 and nd == 6 and abs(m - 50 / 55) < 1e-12
    assert lo < 0.01 and hi > 0.97           # one date carries every win: the interval says so


def test_perf_books_at_the_result_and_locks_capital():
    tr = pd.DataFrame({"date": ["2025-01-01", "2025-01-02"], "settle_date": ["2025-01-05", "2025-01-03"], "p": [3.0, 1.0], "k": [100.0, 50.0]})
    pf = en.perf(tr, "p", "k", "result")
    assert pf["capital_base"] == 150.0 and pf["days"] == 5 and pf["net_pnl"] == 4.0
    assert pf["capital_days"] == 100.0 * 5 + 50.0 * 2
    assert pf["daily_pnl"].loc["2025-01-05"] == 3.0 and pf["daily_pnl"].loc["2025-01-03"] == 1.0
    pe = en.perf(tr, "p", "k", "entry")
    assert pe["capital_base"] == 100.0 and pe["daily_pnl"].loc["2025-01-01"] == 3.0


def test_config_is_the_brief():
    assert cfg.WINDOW_S == 600 and cfg.WINDOW_VARIANT_S == 120 and cfg.SIZE_CAP == 100
    assert cfg.COSTS[1.0] == {"fee_mult": 1.0, "haircut": 0.01} and cfg.COSTS[2.0] == {"fee_mult": 2.0, "haircut": 0.02}
    assert cfg.RATE <= 1.0 and cfg.MAX_REQUESTS <= 3000 and (cfg.MIN_OOS_TRADES, cfg.MIN_OOS_DATES) == (30, 10)


# ---------------------------------------------------------------- end to end on made-up prints

def test_detect_settle_and_metrics_end_to_end(tmp_path, monkeypatch):
    from s24_ladder_fresh import report as rp
    here, cache, res = tmp_path / "pkg", tmp_path / "pkg" / ".cache", tmp_path / "res"
    (cache / "prints").mkdir(parents=True)
    res.mkdir()
    for name, val in (("HERE", here), ("CACHE", cache), ("PRINTS", cache / "prints"), ("RESULTS", res)):
        monkeypatch.setattr(rn, name, val)
    rn._mem.clear()

    def mkt(i, q, close):
        return {"id": i, "question": q, "conditionId": "0x" + i, "startDate": "2025-01-01T00:00:00Z", "closedTime": close,
                "fee_rate": 0.0, "fee_exponent": 1.0}
    day = 86400
    M = {"1": mkt("1", "X by June 30?", "2025-07-01 00:00:00+00"), "2": mkt("2", "X by July 31?", "2025-08-01 00:00:00+00"),
         "3": mkt("3", "Y above $2?", None), "4": mkt("4", "Y above $1?", None)}
    L = {"ladders": [{"set": "a", "kind": "date", "event": "x", "event_title": "X", "event_volume": 9.0, "legs": ["1", "2"], "pairs": [["1", "2"]]},
                     {"set": "b", "kind": "strike", "event": "y", "event_title": "Y", "event_volume": 5.0, "legs": ["4", "3"], "pairs": [["3", "4"]]}],
         "markets": M}
    (here / "ladders.json").write_text(json.dumps(L))
    (cache / "pull_state.json").write_text(json.dumps({"done": [0, 1], "used": {"a": 2, "b": 2}}))

    def save(i, rows):
        a = np.array(rows, float)
        np.savez_compressed(cache / "prints" / f"{i}.npz", t=a[:, 0].astype(np.int64), price=a[:, 1], side=a[:, 2].astype(np.int8),
                            out=a[:, 3].astype(np.int8), size=a[:, 4], served=np.array([len(rows)]), pages=np.array([len(rows)]))
    # pair 1>2: a sale of "June" at 0.50 and a purchase of "July" at 0.45 on six days; the last sale is a NO purchase at 0.50
    save("1", [(T0 + d * day, 0.50, -1, 1, 30) for d in range(5)] + [(T0 + 5 * day, 0.50, 1, 0, 30)])
    save("2", [(T0 + d * day + 60, 0.45, 1, 1, 500) for d in range(6)])
    # pair 3>4: one 1-cent gap; both rungs still open
    save("3", [(T0, 0.31, -1, 1, 5)])
    save("4", [(T0 + 5, 0.30, 1, 1, 5)])
    assert rn.detect() == 0
    cut = json.loads((res / "oos_cut.json").read_text())
    assert cut["a"]["trade_dates"] == 6 and cut["a"]["oos_start"] == "2025-06-19" and cut["b"]["trade_dates"] == 1
    (cache / "outcomes.json").write_text(json.dumps({"1": {"outcome": 0.0, "closedTime": "2025-07-01 00:00:00+00"},
                                                     "2": {"outcome": 1.0, "closedTime": "2025-08-01 00:00:00+00"},
                                                     "3": {"outcome": None, "closedTime": None}, "4": {"outcome": None, "closedTime": None}}))
    assert rn.settle() == 0
    T = pd.read_csv(res / "trades.csv", dtype={"rich": str, "cheap": str})
    p = T[T.variant == "W600"]
    a = p[p.set == "a"]
    assert len(a) == 6 and list(a.segment) == ["IS"] * 4 + ["OOS"] * 2
    assert np.allclose(a.pnl_1x, 0.03 + 1.0) and np.allclose(a.pnl_2x, 0.01 + 1.0) and (a.size_capped == 30).all()
    assert a.sale_raw.iloc[-1] == "BUY No @0.5000" and (a.settle_date == "2025-07-31").all() and not a.broken.any()
    b = p[p.set == "b"].iloc[0]
    assert abs(b.pnl_1x + 0.01) < 1e-9 and b.settled_by.startswith("open") and b.settle_date == rn.LAST_DAY and not b.locked_at_entry
    assert len(T[T.variant == "W120"]) == 7 and not T.print_after_close.any()
    Mx = rp.build_metrics(T)
    r = rp.get(Mx, scope="set a")
    assert r.trades == 6 and r.dates == 6 and abs(r.net_points_per_trade - 103.0) < 1e-6 and abs(r.usd_capped - 6 * 30 * 1.03) < 1e-6
    assert rp.get(Mx, scope="set a", segment="OOS").trades == 2 and rp.get(Mx, scope="resolved pairs only").trades == 6
    lines = rp.pass_lines(Mx)
    assert [ok for _, ok, _ in lines][2:] == [True, False]            # positive at 2x; too few out-of-sample trades
    # the audit and the report run on the same files and write every deliverable
    from s24_ladder_fresh import audit as au
    assert au.main() == 0
    a = json.loads((res / "audit.json").read_text())
    assert a["recheck"]["failed"] == 0 and a["result"]["rich NO, cheap YES (pays $1)"] == 6 and a["print_after_close"] == 0
    for name, val in (("HERE", here), ("CACHE", cache), ("RESULTS", res)):
        monkeypatch.setattr(rp, name, val)
    (cache / "requests.json").write_text(json.dumps({"n": 9, "by": {"prints_a": 2}, "pauses": []}))
    assert rp.main() == 0
    for name in ("SUMMARY.md", "metrics.csv", "capacity.md", "RUN_LOG.md", "equity_curve.png", "drawdown.png"):
        assert (res / name).exists() and (res / name).stat().st_size > 0
    text = (res / "SUMMARY.md").read_text()
    assert "NOT A PASS" in text and "4. At least 30 out-of-sample trades" in text


# ---------------------------------------------------------------- amendment 1: the partner study's corrected rule (secondary)

def test_year_check_rederives_the_rung_year():
    from datetime import date

    from s24_ladder_fresh import nesting as ne
    assert str(ne.deadline({"question": "US strike on Syria by December 31?", "startDate": "2026-03-10T00:00:00Z"}, date(2025, 12, 31))) == "2026-12-31"
    assert str(ne.deadline({"question": "X by January 31?", "startDate": "2025-10-10T00:00:00Z"}, date(2025, 1, 31))) == "2026-01-31"
    assert str(ne.deadline({"question": "X by June 30, 2025?", "startDate": "2024-02-01T00:00:00Z"}, date(2025, 6, 30))) == "2025-06-30"
    b = {"legs": ["1", "2"], "keys": ["2025-12-31", "2026-01-10"]}          # S11's order: "December 31" read as 2025, the rich rung
    g = {"1": {"question": "Another strike by December 31?", "startDate": "2026-01-02T00:00:00Z"},
         "2": {"question": "Another strike by January 10?", "startDate": "2026-01-02T00:00:00Z"}}
    assert not ne.year_ok(b, "1", "2", g)                                   # really 2026-12-31: the later rung
    g["1"]["startDate"] = g["2"]["startDate"] = "2025-12-01T00:00:00Z"
    assert ne.year_ok(b, "1", "2", g)


def test_nesting_rule_as_the_partner_wrote_it():
    from s24_ladder_fresh import nesting as ne
    b = {"legs": ["1", "2"], "keys": ["2026-04-30", "2026-05-31"]}
    d = "This market resolves Yes if a ceasefire is announced by {}, 11:59 PM ET."
    g = {"1": {"question": "Ceasefire by April 30?", "startDate": "2026-03-01T00:00:00Z", "description": d.format("April 30, 2026"), "resolutionSource": ""},
         "2": {"question": "Ceasefire by May 31?", "startDate": "2026-03-01T00:00:00Z", "description": d.format("May 31, 2026"), "resolutionSource": ""}}
    assert ne.nested("date", b, "1", "2", g) == (True, "nested")
    g2 = {k: dict(v) for k, v in g.items()}
    g2["2"]["description"] += " A truce does not count."
    assert ne.nested("date", b, "1", "2", g2) == (False, "descriptions differ")
    g3 = {k: dict(v) for k, v in g.items()}
    g3["2"]["resolutionSource"] = "https://example.org"
    assert ne.nested("date", b, "1", "2", g3) == (False, "sources differ")
    c = "Resolves Yes if a strike happens between market creation and {}."
    g4 = {"1": dict(g["1"], description=c.format("April 30, 2026")), "2": dict(g["2"], description=c.format("May 31, 2026"), startDate="2026-03-05T00:00:00Z")}
    assert ne.nested("date", b, "1", "2", g4)[1] == "window starts at creation and the cheap rung was created later"
    g4["2"]["startDate"] = "2026-03-01T00:00:30Z"
    assert ne.nested("date", b, "1", "2", g4)[0]
    s = {"legs": ["1", "2"], "keys": [100000.0, 110000.0]}
    t = "This market resolves Yes if Bitcoin trades at or above ${} on Binance."
    gs = {"1": {"question": "q", "description": t.format("100,000"), "resolutionSource": "binance"}, "2": {"question": "q", "description": t.format("110,000"), "resolutionSource": "binance"}}
    assert ne.nested("strike", s, "2", "1", gs)[0]


def test_text_direction_post_hoc_check():
    from s24_ladder_fresh.secondary import text_direction
    assert text_direction('resolve to "Yes" if any Binance 1 minute candle has a final "Low" price of $65,000.00 or lower.') == -1
    assert text_direction('resolve to "Yes" if any Binance 1 minute candle has a final "High" price of $3,500.00 or higher.') == 1
    assert text_direction('resolve to "Yes" if the candle has a final "Close" price higher than $100,000.') == 0
    assert text_direction("") == 0
