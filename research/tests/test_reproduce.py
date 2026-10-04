"""reproduce.py and note_figures.py: offline, every section runs, and the recomputed ladder book equals the study's own stats."""
from __future__ import annotations

import json
import socket

import pytest

import note_figures
import reproduce as rp


def test_check_flags_a_difference_and_a_quote_missing_from_the_note():
    c = rp.Checks()
    c.add("t", "same", "7,111 scored rows", "7,111 scored rows", rp.NOTE, rp.REC)
    c.add("t", "differs", "7,111 scored rows", "7,112 scored rows", rp.NOTE, rp.REC, detail="unrounded")
    c.add("t", "not in the note", "no such text in the note", "no such text in the note", rp.NOTE, rp.REC)
    c.nosource("t", "no file", "x", "why")
    assert [r["status"] for r in c.rows] == ["MATCH", "MISMATCH", "MISMATCH", "NO SOURCE"]
    assert c.mismatches == 2 and c.rows[1]["got"].endswith("(unrounded)")


def test_network_is_blocked_inside_the_run_and_restored_after():
    before = socket.create_connection
    with rp.no_network():
        with pytest.raises(RuntimeError, match="offline"):
            socket.create_connection(("example.invalid", 80))
        with pytest.raises(RuntimeError, match="offline"):
            socket.getaddrinfo("example.invalid", 80)
    assert socket.create_connection is before


def test_every_section_runs_offline():
    c = rp.run(write=False)
    assert not [r for r in c.rows if r["claim"] == "section failed to run"], [r["got"] for r in c.rows if r["claim"] == "section failed to run"]
    secs = {r["sec"] for r in c.rows}
    assert {"accuracy", "S11", "ladder replay", "S21", "touch fresh", "what failed"} <= secs
    assert len(c.rows) >= 75 and {r["status"] for r in c.rows} <= {"MATCH", "MISMATCH", "NO SOURCE"}
    # The two rows of the note's ladder table and its "from 22 July 2026" row are recomputed from the trade lists.
    ladder = {r["claim"]: r for r in c.rows if r["sec"] == "ladder replay"}
    for k in ("rule as registered: trades / dates | net points, 95% date CI | losing trades",
              "year-checked: trades / dates | net points, 95% date CI | losing trades",
              "year-checked, from 22 July 2026: trades | net points, 95% date CI | losing trades"):
        assert ladder[k]["how"] == rp.REC and ladder[k]["status"] == "MATCH", ladder[k]


def books() -> dict:
    return {(rule, seg): rp.book(rp.split(rp.ladder_trades(p), seg), seg) for rule, p in rp.RULES.items() for seg in ("all", "in", "out")}


def test_ladder_book_from_the_trade_list_equals_the_committed_summary():
    b = books()
    for rule, path in rp.RULES.items():
        summ = json.loads((path.parent / "summary_all.json").read_text())["fresh"]["metrics"]
        for seg, key in (("all", "all"), ("in", "s11_IS"), ("out", "s11_OOS")):
            for k, v in summ[key].items():
                assert b[rule, seg][k] == pytest.approx(v, rel=1e-9, abs=1e-9), (rule, seg, k)
    assert sum(b[r, "in"]["trades"] + b[r, "out"]["trades"] == b[r, "all"]["trades"] for r in rp.RULES) == 2


def test_committed_tables_file_is_what_the_code_writes():
    assert rp.TABLES.read_text() == rp.tables(books())


def test_figures_render(tmp_path, monkeypatch):
    monkeypatch.setattr(note_figures, "OUT", tmp_path)
    paths = note_figures.main()
    assert [p.name for p in paths] == ["ladder_equity.png", "ladder_drawdown.png", "s21_buyers_by_gap.png", "scoreboard.png"]
    assert all(p.stat().st_size > 10_000 for p in paths)
    assert len(note_figures.verdicts()) == 15
