import pytest

from arbscan import verify as vf
from arbscan.costs import PolyFee


def test_needed_price_for_both_trades_includes_fee_and_commission():
    fee = PolyFee(rate=0.04)
    a = vf.needed_price("A_sell_yes_buy_spread", p_lo=0.4, p_hi=0.5, width=2.0, fee=fee)
    b = vf.needed_price("B_buy_yes_sell_spread", p_lo=0.4, p_hi=0.5, width=2.0, fee=fee)
    assert a is not None and b is not None
    assert a > 0.5 + 0.01 and b < 0.4 - 0.01                  # strictly beyond the bound by edge + fee + commission
    assert a - fee.per_share(a) - 0.5 - 0.0065 >= 0.01 - 1e-9
    assert vf.needed_price("A_sell_yes_buy_spread", 0.4, 0.995, 2.0, fee) is None     # bound too high: unreachable
    assert vf.needed_price("B_buy_yes_sell_spread", 0.005, 0.1, 2.0, fee) is None


def T(ts, side, outcome, price, size=10):
    return {"timestamp": ts, "side": side, "outcome": outcome, "price": price, "size": size}


def test_verify_row_yes_and_no_equivalence_and_window():
    snap = 10_000
    sell_yes = T(snap + 30, "SELL", "Yes", 0.70)
    buy_no = T(snap - 60, "BUY", "No", 0.28)                    # = sell Yes at 0.72
    assert vf.verify_row([sell_yes], snap, "A_sell", 0.69) == {"verified": True, "verify_n": 1, "verify_size": 10.0}
    assert vf.verify_row([buy_no], snap, "A_sell", 0.71)["verified"]
    assert not vf.verify_row([sell_yes], snap, "A_sell", 0.71)["verified"]           # price not good enough
    assert not vf.verify_row([T(snap, "BUY", "Yes", 0.99)], snap, "A_sell", 0.7)["verified"]   # wrong side (buyer, not a bid)
    assert not vf.verify_row([T(snap + 601, "SELL", "Yes", 0.9)], snap, "A_sell", 0.7)["verified"]   # outside +/-10 min
    # trade B: we buy Yes at <= needed; taker bought Yes cheap, or sold No dear
    assert vf.verify_row([T(snap, "BUY", "Yes", 0.30)], snap, "B_buy", 0.31)["verified"]
    assert vf.verify_row([T(snap, "SELL", "No", 0.72)], snap, "B_buy", 0.30)["verified"]   # sell No at .72 = buy Yes at .28
    assert not vf.verify_row([T(snap, "BUY", "Yes", 0.35)], snap, "B_buy", 0.31)["verified"]
    # two qualifying prints add up
    r = vf.verify_row([sell_yes, buy_no], snap, "A_sell", 0.69)
    assert r["verify_n"] == 2 and r["verify_size"] == 20.0
    assert vf.verify_row([sell_yes], snap, "A_sell", None)["verified"] is False


def test_fetch_trades_pages_until_short_page(tmp_path):
    from arbscan.datasrc import Http

    class R:
        status_code, headers = 200, {}

        def __init__(self, p):
            self.p = p

        def json(self):
            return self.p

    class S:
        def __init__(self):
            self.urls = []
            self.pages = [[{"i": i} for i in range(vf.PAGE)], [{"i": 1}] * 3]

        def get(self, url, **kw):
            self.urls.append(url)
            return R(self.pages.pop(0))

    s = S()
    out = vf.fetch_trades(Http(tmp_path, session=s), "0xabc")
    assert len(out) == vf.PAGE + 3 and len(s.urls) == 2


def test_snapshot_meta_is_true_utc_and_verify_windows_on_it():
    """Regression: an ET wall-clock was once written with a 'Z' suffix, shifting the verification window by 4 hours."""
    from datetime import date, datetime, timezone
    from arbscan.run import ET, et_dt, snapshot_meta, utc_iso
    m = dict(venue="polymarket", id="1", event="e", question="q", underlying="NVDA", kind="close", res_date=date(2026, 9, 2))
    snap = et_dt(date(2026, 9, 2), 12, 0)                          # EDT = UTC-4
    meta = snapshot_meta(m, "S2", snap, "2026-09-02")
    assert meta["snap_utc"] == "2026-09-02T16:00:00Z"
    assert utc_iso(et_dt(date(2026, 1, 15), 15, 45)) == "2026-01-15T20:45:00Z"      # EST = UTC-5
    true_ts = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc).timestamp()
    assert meta["snap_epoch"] == true_ts
    # the string and the epoch agree, and a pre-market print four hours earlier is outside the window
    assert datetime.fromisoformat(meta["snap_utc"].replace("Z", "+00:00")).timestamp() == true_ts
    early = T(true_ts - 4 * 3600 + 34, "BUY", "Yes", 0.71)         # 07:55 ET
    near = T(true_ts + 60, "BUY", "Yes", 0.99)
    assert not vf.verify_row([early], meta["snap_epoch"], "B_buy", 0.955)["verified"]
    assert not vf.verify_row([early, near], meta["snap_epoch"], "B_buy", 0.955)["verified"]     # 0.99 is above the needed price
    assert vf.verify_row([near], meta["snap_epoch"], "B_buy", 0.995)["verified"]


def test_contract_map_keeps_only_pm_settled_index_roots():
    from arbscan.datasrc import contract_map
    rows = [dict(ticker="O:SPX260918C07000000", strike_price=7000), dict(ticker="O:SPXW260918C07000000", strike_price=7000),
            dict(ticker="O:SPXW260918C07005000", strike_price=7005), dict(ticker="O:NDX260918C25000000", strike_price=25000),
            dict(ticker="O:NDXP260918C25000000", strike_price=25000)]
    assert contract_map("SPX", rows) == {7000.0: "O:SPXW260918C07000000", 7005.0: "O:SPXW260918C07005000"}
    assert contract_map("NDX", rows) == {25000.0: "O:NDXP260918C25000000"}
    assert contract_map("NVDA", [dict(ticker="O:NVDA260918C00200000", strike_price=200),
                                 dict(ticker="O:NVDA1260918C00100000", strike_price=100, shares_per_contract=10)]) == {200.0: "O:NVDA260918C00200000"}
