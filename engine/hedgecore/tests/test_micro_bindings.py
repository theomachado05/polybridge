"""Python surface of the micro families: catalog keys, the two algos, and both replays on the research files."""

import csv
import math
from pathlib import Path

import hedgecore

REPO = Path(__file__).resolve().parents[3]
LADDER_CSV = REPO / "research/results/ladder_replay/order_check/trades_fresh.csv"
S21_CSV = REPO / "research/results/s21_options_anchor/trades.csv"
S = 1_000_000_000


def test_catalog_lists_micro_families_with_status_words():
    c = hedgecore.catalog()
    assert c["n_families"] == 17 and c["total"] == 1386
    fams = {f["id"]: f for f in c["micro_families"]}
    assert set(fams) == {"ladder_pair", "touch_ticket_reference"}
    assert fams["ladder_pair"]["status"] == "lead"
    assert fams["touch_ticket_reference"]["status"] == "unvalidated"
    assert fams["ladder_pair"]["preset_count"] == 18
    assert fams["ladder_pair"]["grid"]["min_edge"] == [1.0, 2.0, 3.0]
    assert fams["ladder_pair"]["grid"]["max_age_s"] == [10.0, 30.0, 60.0]
    assert fams["ladder_pair"]["grid"]["cap"] == [100.0, 500.0]
    assert c["micro_total"] == 19
    assert {r["name"] for r in c["micro_reasons"].values()} >= {"not_nested", "leg_risk", "proposal"}


def _ladder_tick(**kw):
    t = dict(ts_ns=S, bid_rich=0.80, bid_rich_qty=40, ask_cheap=0.50, ask_cheap_qty=60, fee_rate_rich=0.0,
             fee_rate_cheap=0.0, tick=0.01, ts_rich_ns=S, ts_cheap_ns=S, nested=True, event_held=0)
    t.update(kw)
    return t


def test_ladder_pair_orders_both_legs_at_the_quotes_and_refuses_unnested():
    a = hedgecore.LadderPair({"min_edge": 1, "max_age_s": 30, "cap": 100})
    i = a.on_tick(_ladder_tick())
    assert i["action"] == "order" and i["reason"] == "entry"
    assert (i["rich"]["side"], i["rich"]["qty"], i["rich"]["limit_px"]) == (-1, 40.0, 0.80)
    assert (i["cheap"]["side"], i["cheap"]["qty"], i["cheap"]["limit_px"]) == (1, 40.0, 0.50)
    a.on_fill("rich", 40, 0.80)
    a.on_fill("cheap", 40, 0.50)
    assert a.held == 40 and abs(a.capital_locked - 40 * 0.70) < 1e-12
    for nested in (False, None):
        b = hedgecore.LadderPair()
        assert b.on_tick(_ladder_tick(nested=nested))["reason"] == "not_nested"
    c = hedgecore.LadderPair()
    t = _ladder_tick()
    del t["nested"]
    assert c.on_tick(t)["reason"] == "not_nested"


def test_touch_ticket_proposes_only_unless_validated():
    t = dict(ts_ns=S, bid=0.40, bid_qty=50, ask=0.42, ref_lower=0.25, ref_central=0.30, underlying_short=0,
             event_short=0)
    for v in (False, None):
        assert hedgecore.TouchTicketReference().on_tick({**t, "validated": v})["action"] == "propose"
    o = hedgecore.TouchTicketReference().on_tick({**t, "validated": True})
    assert (o["action"], o["side"], o["qty"], o["limit_px"]) == ("order", -1, 50.0, 0.40)


def test_replay_ladder_reproduces_fresh_order_check_trades():
    rows = list(csv.DictReader(LADDER_CSV.open()))
    pairs, events = {}, {}
    cols = {k: [] for k in ("now_ns", "bid_rich", "bid_rich_qty", "ask_cheap", "ask_cheap_qty", "fee_rate_rich",
                            "fee_rate_cheap", "tick", "ts_rich_ns", "ts_cheap_ns", "nested", "pair", "event",
                            "result_rich", "result_cheap")}
    for r in sorted(rows, key=lambda r: int(r["t_entry"])):
        rich, cheap, fr, fc = (float(r[k]) for k in ("fill_rich", "fill_cheap", "fee_rich", "fee_cheap"))
        cols["now_ns"].append(int(r["t_entry"]) * S)
        cols["bid_rich"].append(rich)
        cols["ask_cheap"].append(cheap)
        cols["bid_rich_qty"].append(float(r["print_size"]))
        cols["ask_cheap_qty"].append(float(r["print_size"]))
        cols["fee_rate_rich"].append(fr / (rich * (1 - rich)) if fr else 0.0)
        cols["fee_rate_cheap"].append(fc / (cheap * (1 - cheap)) if fc else 0.0)
        cols["tick"].append(0.0)  # the research's one tick per leg is already in the fill prices
        cols["ts_rich_ns"].append(int(r["t_print_rich"]) * S)
        cols["ts_cheap_ns"].append(int(r["t_print_cheap"]) * S)
        cols["nested"].append(True)
        cols["pair"].append(pairs.setdefault(r["pair"], len(pairs)))
        cols["event"].append(events.setdefault(r["event"], len(events)))
        settled = r["settled"] == "True"
        cols["result_rich"].append(float(r["result_rich"]) if settled else None)
        cols["result_cheap"].append(float(r["result_cheap"]) if settled else None)
    st = hedgecore.replay_ladder({"min_edge": 0, "max_age_s": 60, "cap": 100, "event_cap": 0, "cooldown_s": 3600},
                                 cols)
    research_mean = sum(float(r["pnl_points"]) for r in rows) / len(rows)
    assert st["n_trades"] == len(rows) == 562
    assert math.isclose(st["mean_pnl_points"], research_mean, abs_tol=1e-9)
    assert round(st["mean_pnl_points"], 2) == 8.82
    assert st["n_leg_rejects"] == 0 and st["min_pnl_minus_edge"] >= -1e-9


def test_replay_tickets_selects_s21_b0_markets_and_never_orders():
    rows = list(csv.DictReader(S21_CSV.open()))
    anchor = {r["market"]: float(r["anchor"]) for r in rows if r["book"] == "U"}
    b0 = {r["market"] for r in rows if r["book"] == "B0"}
    u_all = [r for r in rows if r["book"] == "U-all"]
    cols = {
        "now_ns": [S] * len(u_all),
        "bid": [float(r["traded_price"]) for r in u_all],
        "bid_qty": [float(r["printed_size"]) for r in u_all],
        "ref_central": [anchor.get(r["market"]) for r in u_all],
        "validated": [False] * len(u_all),
        "ticket": list(range(len(u_all))),
    }
    st = hedgecore.replay_tickets({"ticket_cap": 0, "underlying_cap": 0, "event_cap": 0}, cols)
    chosen = {u_all[d["ticket"]]["market"] for d in st["decisions"]}
    assert st["n_orders"] == 0 and st["n_fills"] == 0
    assert all(d["action"] == "propose" for d in st["decisions"])
    assert len(b0) == 60 and chosen == b0
