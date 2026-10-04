"""Forward tests wired to the frozen research runners: offline, with fakes. Rules are never reimplemented here, and
nothing may be written under research/."""
import csv
import json
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.forward import ladders, paths, status, touch
from app.main import create_app

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
FIELDS = ["event", "rich", "cheap", "nested", "reason", "bid_rich", "ask_cheap", "edge_top", "contracts", "locked_usd", "has_books"]


def pair(rich="A by Jan 15", cheap="A by Jan 16", nested=True, edge=-0.1, contracts=0, locked=0.0, books=True):
    return {"event": "A", "rich": rich, "cheap": cheap, "nested": nested, "reason": "same event", "bid_rich": 0.5, "ask_cheap": 0.6,
            "edge_top": edge, "contracts": contracts, "locked_usd": locked, "has_books": books}


class FakeLive:
    """Stands in for ladder_replay.live: writes live_pairs.csv and live_totals.json to its (redirected) OUT."""

    def __init__(self, rows, fail=False):
        self.OUT, self.rows, self.fail, self.seen_out = Path("/nonexistent/research/results"), rows, fail, None

    def main(self):
        self.seen_out = self.OUT
        print("noise that must not reach the terminal")
        if self.fail:
            raise RuntimeError("gamma down")
        self.OUT.mkdir(parents=True, exist_ok=True)
        with (self.OUT / "live_pairs.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(self.rows)
        viol = [r for r in self.rows if r["contracts"] > 0]
        (self.OUT / "live_totals.json").write_text(json.dumps({
            "snapshot_utc": NOW.isoformat(), "events_read": 7, "date_ladders": 3, "pairs": len(self.rows),
            "pairs_with_books": sum(r["has_books"] for r in self.rows), "nested_pairs": sum(r["nested"] for r in self.rows),
            "violations_net_of_fees": len(viol), "violations_nested": sum(r["nested"] for r in viol),
            "locked_usd": sum(r["locked_usd"] for r in viol), "locked_usd_nested": 0.0, "median_gap_points_to_arb": 10.0}))
        return 0


def test_ladder_run_redirects_output_and_summarises(tmp_path):
    rows = [pair(edge=-0.05), pair(edge=-0.10), pair(edge=-0.30), pair(edge=0.02, contracts=12, locked=1.5), pair(books=False, edge=0)]
    live = FakeLive(rows)
    original = live.OUT
    rec = ladders.run(now=NOW, base=tmp_path, live=live)
    assert live.seen_out.is_relative_to(tmp_path) and live.OUT == original  # redirected during the run, restored after
    assert rec["pairs"] == 5 and rec["pairs_with_books"] == 4 and rec["violations_net_of_fees"] == 1
    v = rec["violations"][0]
    assert v["contracts"] == 12 and v["locked_usd"] == 1.5 and v["nested"] is True and v["edge_top_points"] == 2.0
    g = rec["gap_points_to_arb"]  # sample and range travel with the median
    assert g["n_pairs"] == 4 and g["min"] == -2.0 and g["max"] == 30.0 and g["p10"] <= g["median"] <= g["p90"]
    saved = json.loads((tmp_path / "ladders" / "snapshots" / "20261004T150000Z.json").read_text())
    assert saved["stamp"] == "20261004T150000Z" and (tmp_path / "ladders" / "raw" / "20261004T150000Z" / "live_pairs.csv").is_file()
    assert {f["file"] for f in saved["frozen"]} == set(paths.LADDER_FILES)


def test_ladder_failure_is_recorded_not_hidden(tmp_path):
    live = FakeLive([], fail=True)
    rec = ladders.run(now=NOW, base=tmp_path, live=live)
    assert "gamma down" in rec["error"] and "violations" not in rec
    assert (tmp_path / "ladders" / "snapshots" / "20261004T150000Z.json").is_file()
    assert status.ladders(tmp_path)["state"] == "last run failed"


def test_gap_stats_empty_and_bad_rows():
    assert ladders.gap_stats([]) is None
    assert ladders.gap_stats([{"has_books": "True", "edge_top": "nan"}, {"has_books": "False", "edge_top": "-0.1"}]) is None


def listed(i, title, question, label, sign, start, vol=None):
    return {"id": str(i), "event": "E1", "event_title": title, "asset_class": "stock", "question": question, "label": label,
            "sign": sign, "start": start, "condition": f"0x{i}", "fee_rate": 0.0, "fee_exponent": 1.0}


def test_touch_list_state_eligibility(tmp_path):
    mods = touch._modules()
    month = "What will NVIDIA (NVDA) hit in October 2026?"
    week = "What will NVIDIA (NVDA) hit Week of October 5 2026?"
    mk = [listed(1, month, "Will NVIDIA (NVDA) reach $250 in October?", "↑ 250", 1, "2026-10-05T14:00:00Z"),
          listed(2, month, "Will NVIDIA (NVDA) dip to $90 in October?", "↓ 90", -1, "2026-10-05T14:00:00Z"),
          listed(3, "NVIDIA (NVDA) weird title", "Will NVIDIA (NVDA) reach $250?", "↑ 250", 1, "2026-10-05T14:00:00Z"),
          # a weekly window ends on its own first Friday: not after it, so not eligible
          listed(4, week, "Will NVIDIA (NVDA) reach $260 on October 5-9?", "↑ 260", 1, "2026-10-05T14:00:00Z")]
    rec = touch.list_state(now=NOW, base=tmp_path, open_markets=lambda: mk, mods=mods)
    assert rec["markets_listed"] == 4 and rec["parsed"] == 3 and rec["eligible_first_weekend"] == 2
    assert [m["id"] for m in rec["eligible"]] == ["1", "2"] and rec["eligible"][0]["entry_day"] == "2026-10-09"
    assert rec["eligible"][0]["end_session"] == "2026-10-30" and rec["eligible_events"] == 1  # Oct 31 2026 is a Saturday
    assert rec["by_entry_day"] == {"2026-10-09": 2}
    assert "window ends on or before" in " ".join(rec["not_eligible_reasons"])
    assert rec["not_eligible_reasons"]  # why the rest were left out is recorded
    assert rec["pending"]["verdict_needs"]["markets"] == 30 and rec["pending"]["verdict_needs"]["events"] == 15
    assert (tmp_path / "touch" / "raw" / "state_20261004T150000Z.json").is_file()


def test_touch_list_state_empty_before_first_listing(tmp_path):
    rec = touch.list_state(now=NOW, base=tmp_path, open_markets=lambda: [], mods=touch._modules())
    assert rec["markets_listed"] == 0 and rec["eligible"] == [] and rec["first_listing_et"] == "2026-10-05 00:00"
    t = status.touch(tmp_path)
    assert t["latest"]["eligible_first_weekend"] == 0 and "unvalidated" in t["status"]


def test_touch_stage_redirects_runner_dirs(tmp_path):
    """The frozen runner logs to forward.LOG and builds its cache from forward.HERE: both point under base during a stage."""
    seen = {}
    fw = types.SimpleNamespace(HERE=Path("/research/touch_fresh"), LOG=Path("/research/touch_fresh/forward_log"))

    def snapshot():
        seen["here"], seen["log"] = fw.HERE, fw.LOG
        fw.LOG.mkdir(parents=True, exist_ok=True)
        (fw.LOG / "snapshot.jsonl").write_text('{"id": "1"}\n')
        print("snap ok")
        return 0

    fw.snapshot = snapshot
    mods = {"forward": fw, "fc": types.SimpleNamespace(LOG_DIR="forward_log")}
    rec = touch.run_stage("snapshot", base=tmp_path, mods=mods, now=NOW)
    assert seen["here"] == tmp_path / "touch" and seen["log"] == tmp_path / "touch" / "forward_log"
    assert fw.HERE == Path("/research/touch_fresh") and fw.LOG == Path("/research/touch_fresh/forward_log")  # restored
    assert rec["output"].strip() == "snap ok" and rec["log_rows"] == {"snapshot": 1, "prints": 0}
    with pytest.raises(ValueError):
        touch.run_stage("trade", base=tmp_path, mods=mods)


def test_frozen_info_labels_real_rule_files():
    for group in (paths.LADDER_FILES, paths.TOUCH_FILES):
        info = paths.frozen_info(group)
        assert all(i["sha256"] and len(i["sha256"]) == 64 for i in info), info


def test_status_route_empty_and_after_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYBRIDGE_FORWARD_DIR", str(tmp_path))
    monkeypatch.setenv("POLYBRIDGE_RECORDER_DIR", str(tmp_path / "no_recorder"))
    c = TestClient(create_app())
    r = c.get("/forward/status").json()
    assert r["label"] == "forward test, rules frozen" and r["recorder"] is None
    assert r["ladders"]["latest"] is None and "make forward-ladders" in r["ladders"]["state"]
    assert r["touch"]["latest"] is None
    assert "research/ladder_replay/live.py @" in r["ladders"]["label"] and r["ladders"]["label"].startswith("forward test, rules frozen (")
    ladders.run(now=NOW, base=tmp_path, live=FakeLive([pair(edge=-0.2), pair(edge=0.01, contracts=5, locked=0.4)]))
    touch.list_state(now=NOW, base=tmp_path, open_markets=lambda: [], mods=touch._modules())
    (tmp_path / "hb").mkdir()
    (tmp_path / "hb" / "heartbeat_twins.json").write_text('{"cycles": 3, "rows": 9, "errors": 0}')
    monkeypatch.setenv("POLYBRIDGE_RECORDER_DIR", str(tmp_path / "hb"))
    r = c.get("/forward/status").json()
    lt = r["ladders"]["latest"]
    assert lt["violations_net_of_fees"]["count"] == 1 and lt["violations_net_of_fees"]["of_pairs_with_books"] == 2
    assert lt["gap_points_to_arb"]["n_pairs"] == 2
    # NOW (2026-10-04) is before the forward start: a pre-start check, not counted as a forward-test snapshot
    assert r["ladders"]["snapshots_taken"] == 0 and r["ladders"]["pre_start_checks"] == 1
    assert lt["phase"] == "pre-start check (not part of the forward test)"
    assert r["touch"]["latest"]["markets_listed"] == 0 and r["touch"]["snapshots_taken"] == 0
    assert r["touch"]["pre_start_checks"] == 1 and r["touch"]["latest"]["phase"].startswith("pre-start check")
    assert r["forward_starts"] == "2026-10-05"
    assert r["recorder"]["heartbeats"]["twins"]["cycles"] == 3


def test_nothing_writes_under_research(tmp_path):
    """Output dirs are never under research/ (the frozen studies and research/results stay untouched)."""
    assert not paths.DEFAULT_DIR.is_relative_to(paths.RESEARCH)
    assert paths.DEFAULT_DIR == paths.REPO / "backend" / "data_forward"


def test_forward_counting_starts_2026_10_05_new_york(tmp_path):
    from app.forward import status
    before = datetime(2026, 10, 5, 3, 59, 59, tzinfo=timezone.utc)      # 23:59:59 New York on 4 October
    after = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)            # 00:00 New York on 5 October
    assert status.phase(before) == status.PRE_START and status.phase(after) == status.IN_TEST
    for t in (NOW, before, after, datetime(2026, 10, 9, 19, 55, tzinfo=timezone.utc)):
        ladders.run(now=t, base=tmp_path, live=FakeLive([pair(edge=-0.2)]))
        touch.list_state(now=t, base=tmp_path, open_markets=lambda: [], mods=touch._modules())
    out = status.build(tmp_path)
    for k in ("ladders", "touch"):
        assert out[k]["snapshots_taken"] == 2 and out[k]["pre_start_checks"] == 2, k
        assert out[k]["latest"]["phase"] == "forward test"
