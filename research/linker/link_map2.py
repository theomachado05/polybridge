"""The link map, version 2: every scored link on a question that is still open, in a file the backend can serve in place
of `backend/app/data/ai_map.json`, with one option contract per trusted link.

Sources, newest linker first (for the same market, ticker and direction the version-3 row wins):
    results/linker/heldout2_links.csv, dev_v3_links.csv   version 3, by event (read when they exist)
    results/linker/benchmark_scored.csv                   S4 and S5 (version-1 score in score_full_model)
    results/linker/heldout_links.csv                      the first held-out test
A link is **trusted** by the rule of LINKER.md: two models agree, the prices do not contradict it, and either the
prices confirm it or its score is 0.5 or more (score_v2 where the row has one, else the version-1 score). Clusters
where both version-3 labellers answered "no listed instrument" are kept as items with no mapping, so the product can
say so instead of guessing. SPY is never a link; the Brazil probe is kept and marked.

Writes results/linker/link_map_v2.json and a copy at backend/app/data/link_map.json (loader: backend/app/link_map.py).

Run from `research/`:  python -m linker.link_map2 [--no-options]     (--no-options skips the Massive contract calls)
"""
from __future__ import annotations

import glob
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from .benchmark import OUT

AS_OF = "2026-10-02"
TODAY = "2026-10-04"
TRUST_SCORE = 0.5
HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
BACKEND_COPY = RESEARCH.parent / "backend" / "app" / "data" / "link_map.json"
GENERATOR = "link agent v3 (two blind labellers, trained scorer, price benchmark)"
V3_FILES = ("heldout2_links.csv", "dev_v3_links.csv")
V3_SETS = ("heldout2", "dev")
Resolver = Callable[[str, str, str], "dict | None"]


def _pm(x) -> str:
    x = str(x)
    return x if ":" in x else f"polymarket:{x}"


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _flag(x) -> bool:
    return str(x).strip().lower() in ("1", "1.0", "true", "yes")


def _clean(x):
    """JSON-safe: NaN and inf become null."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


# ---------------------------------------------------------------- inputs

OPTIONAL = ("score_v2", "score_v1", "cluster", "signal", "structure", "impact_pct", "mechanism_class", "alternative", "probe", "remembered",
            "verdict_since_cutoff")


def _with_optional(df: pd.DataFrame) -> pd.DataFrame:
    """The version-3 columns, empty on rows from older linkers."""
    df = df.copy()
    for c in OPTIONAL:
        if c not in df:
            df[c] = None
    return df


def gather(out: Path = OUT) -> pd.DataFrame:
    """Every scored link, one row per (market, ticker, direction), the version-3 row first. Columns added: version,
    score_used (score_v2 where present, else the version-1 score)."""
    frames = []
    for name in V3_FILES:
        if (out / name).exists():
            f = pd.read_csv(out / name)
            f["version"] = 3
            frames.append(f)
    b = pd.read_csv(out / "benchmark_scored.csv").rename(columns={"score_full_model": "score"})
    b["version"] = 1
    h = pd.read_csv(out / "heldout_links.csv")
    h["version"] = 1
    df = pd.concat(frames + [b, h], ignore_index=True)
    df = _with_optional(df)
    df["score_used"] = [s2 if _num(s2) is not None else s for s2, s in zip(df.score_v2, df.score)]
    df["score_used"] = pd.to_numeric(df.score_used, errors="coerce")
    return df.drop_duplicates(["market", "ticker", "direction"], keep="first").reset_index(drop=True)


def end_dates() -> dict[str, tuple[str, bool]]:
    """market id -> (the day the question ends, whether it has resolved), from every universe the links came from."""
    from s4_linked_assets import data as d4
    out: dict[str, tuple[str, bool]] = {}
    meta = d4.CACHE / "pull_meta.json"
    if meta.exists():
        for m in json.loads(meta.read_text())["markets"]:
            out[_pm(m["market"])] = (str(m["end"])[:10], bool(m["closed"]))
    for f in (RESEARCH / "s5_big_moves" / "universe.json", HERE / "heldout" / "universe.json"):
        for m in json.loads(f.read_text())["markets"]:
            out[_pm(m["id"])] = (str(m["end"])[:10], bool(m["closed"]))
    for s in V3_SETS:
        for m in roster(s).values():
            out[m["id"]] = (str(m.get("end") or "")[:10], bool(m.get("closed")))
    return out


def roster(set_name: str) -> dict[str, dict]:
    """market id -> {id, question, end, closed, cluster, probe} over every cluster of a version-3 universe (names and
    dates only; no price is read)."""
    f = HERE / set_name / "universe.json"
    if not f.exists():
        return {}
    out = {}
    for e in json.loads(f.read_text()).get("events", []):
        for m in e.get("markets", []):
            out[_pm(m["id"])] = {**m, "id": _pm(m["id"]), "cluster": e.get("cluster"), "probe": bool(e.get("probe"))}
    return out


def clusters(set_name: str) -> dict[str, dict]:
    """cluster id -> its universe entry, with `main` as a market id."""
    f = HERE / set_name / "universe.json"
    if not f.exists():
        return {}
    return {e["cluster"]: {**e, "main": _pm(e["main"])} for e in json.loads(f.read_text()).get("events", [])}


def v3_answers(set_name: str) -> dict[str, dict[str, dict]]:
    """cluster id -> {"P": answer, "S": answer} from labels_v3_<P|S>_<k>.json."""
    out: dict[str, dict[str, dict]] = {}
    for role in ("P", "S"):
        for f in sorted(glob.glob(str(HERE / set_name / f"labels_v3_{role}_*.json"))):
            for a in json.loads(Path(f).read_text()).get("answers", []):
                out.setdefault(a["cluster"], {})[role] = a
    return out


def v1_notes() -> tuple[dict, dict]:
    """The version-1 labellers' words: ((market, ticker, direction) -> {mechanism, impact, alternative} lists,
    market -> set of families named)."""
    notes: dict[tuple, dict] = {}
    fams: dict[str, set] = {}

    def add(mid, l, key="mechanism"):
        n = notes.setdefault((_pm(mid), l["ticker"], l["direction"]), {"mechanism": [], "impact": [], "alternative": []})
        if l.get(key):
            n["mechanism"].append(str(l[key]))
        if _num(l.get("impact_pct")):
            n["impact"].append(float(l["impact_pct"]))
        if l.get("alternative"):
            n["alternative"].append(str(l["alternative"]))

    files = sorted(glob.glob(str(RESEARCH / "s4_linked_assets" / "critic_*.json"))) + sorted(glob.glob(str(RESEARCH / "s5_big_moves" / "labels_*.json"))) \
        + sorted(glob.glob(str(HERE / "heldout" / "labels_*.json")))
    for f in files:
        for a in json.loads(Path(f).read_text()).get("answers", []):
            fams.setdefault(_pm(a["id"]), set()).add(a.get("family", "none"))
            for l in a.get("links", []):
                add(a["id"], l)
    ai = RESEARCH.parent / "backend" / "app" / "data" / "ai_map.json"
    if ai.exists():
        for k, e in json.loads(ai.read_text()).get("items", {}).items():
            for l in (e or {}).get("mappings") or []:
                add(k, l, "rationale")
    return notes, fams


# ---------------------------------------------------------------- rules

def is_trusted(df: pd.DataFrame) -> pd.Series:
    """Two models agree, prices do not contradict it, and prices confirm it or its score is 0.5 or more."""
    return (pd.to_numeric(df.two_models, errors="coerce") == 1) & (df.verdict != "contradicted") \
        & ((df.verdict == "confirmed") | (df.score_used >= TRUST_SCORE))


def open_only(df: pd.DataFrame, ends: dict[str, tuple[str, bool]], today: str = TODAY) -> pd.DataFrame:
    """Links on questions not resolved and ending on or after `today`; never SPY. Adds `ends`."""
    df = df.copy()
    df["ends"] = df.market.map(lambda m: ends.get(m, ("", True))[0])
    resolved = df.market.map(lambda m: ends.get(m, ("", True))[1])
    return df[(~resolved) & (df.ends >= today) & (df.ticker != "SPY")].copy()


def no_instrument(answers: dict[str, dict[str, dict]], cl: dict[str, dict]) -> list[dict]:
    """Clusters where both labellers answered "no listed instrument": [{cluster, main, reason, probe}]."""
    out = []
    for c, a in answers.items():
        if "P" in a and "S" in a and a["P"].get("no_instrument") and a["S"].get("no_instrument") and c in cl:
            why = " / ".join(dict.fromkeys(r for r in (a["P"].get("no_instrument_reason"), a["S"].get("no_instrument_reason")) if r))
            out.append({"cluster": c, "main": cl[c]["main"], "reason": why, "probe": bool(cl[c].get("probe"))})
    return out


def rationale(r: dict, mechanism: str | None) -> str:
    """The labellers' mechanism sentence, else a plain sentence from what the prices say."""
    if mechanism:
        return mechanism
    g, t, days = _num(r.get("gap_bp_per_point")), _num(r.get("gap_t")), int(_num(r.get("days")) or 0)
    side = "rises" if r["direction"] == "up_on_yes" else "falls"
    if r.get("verdict") == "confirmed" and g is not None and t is not None:
        return f"Prices confirm it: {r['ticker']} opened {g:.1f} bp further per point of odds (t = {t:.1f}, {days} days)."
    s = _num(r.get("score_used"))
    tail = f" Scorer: {s:.2f}." if s is not None else ""
    return f"Two models expect {r['ticker']} {side} as the odds rise; prices have not confirmed it yet ({r.get('verdict')}).{tail}"


# ---------------------------------------------------------------- the map

def build(links: pd.DataFrame, ends: dict[str, tuple[str, bool]], notes: dict | None = None, fams: dict | None = None,
          v3: dict[str, tuple[dict, dict]] | None = None, resolve: Resolver | None = None, today: str = TODAY,
          as_of: str = AS_OF) -> dict:
    """The served map. `links` from gather(); `v3` is set name -> (answers, clusters); `resolve(ticker, direction,
    ends)` returns an options.resolve dict or None (None skips options)."""
    notes, fams, v3 = notes or {}, fams or {}, v3 or {}
    live = open_only(_with_optional(links), ends, today)
    live["trusted"] = is_trusted(live)
    live = live.sort_values(["trusted", "score_used"], ascending=[False, False], na_position="last")
    v3_text: dict[tuple, dict] = {}            # (market, ticker) -> v3 link answer; (market,) -> cluster answer
    for answers, cl in v3.values():
        for c, a in answers.items():
            if c not in cl:
                continue
            for role in ("P", "S"):
                ans = a.get(role) or {}
                v3_text.setdefault((cl[c]["main"],), ans)
                for l in ans.get("links", []):
                    v3_text.setdefault((cl[c]["main"], l["ticker"]), l)
    items: dict[str, dict] = {}
    cache: dict[tuple, dict | None] = {}
    for r in live.to_dict("records"):
        m, n = r["market"], notes.get((r["market"], r["ticker"], r["direction"]), {})
        l3 = v3_text.get((m, r["ticker"]), {}) if r["version"] == 3 else {}
        mech = l3.get("mechanism") or (n.get("mechanism") or [None])[0]
        imp = _num(r.get("impact_pct"))
        if imp is None and n.get("impact"):
            imp = sum(n["impact"]) / len(n["impact"])
        if imp is None and _num(r.get("gap_bp_per_point")) is not None:
            imp = abs(float(r["gap_bp_per_point"])) * 100 / 100      # measured bp per point x 100 points, in percent
        opt = None
        if r["trusted"] and resolve is not None:
            k = (r["ticker"], r["direction"], r["ends"])
            if k not in cache:
                try:
                    cache[k] = resolve(*k)
                except Exception:                     # message may carry the request; never printed
                    cache[k] = None
            c = cache[k]
            if c:
                opt = {"contract": c.get("directional_leg"), "expiry": c.get("expiry"), "strike": c.get("strike"), "call": c.get("call"), "put": c.get("put")}
        sig = json.loads(r["signal"]) if isinstance(r.get("signal"), str) and r["signal"].strip() else [[m, 1.0]]
        ans3 = v3_text.get((m,), {}) if r["version"] == 3 else {}
        kind = "event" if r["version"] == 3 else ("price proxy" if "spot_proxy" in fams.get(m, set()) else "event")
        it = items.setdefault(m, {"question": r["question"], "cluster": r["cluster"] if isinstance(r.get("cluster"), str) else None, "signal": sig,
                                  "alternative": r["alternative"] if isinstance(r.get("alternative"), str) else (ans3.get("alternative") or (n.get("alternative") or [""])[0]),
                                  "ends": r["ends"], "kind": kind, "mappings": [], "no_instrument": False, "no_instrument_reason": ""})
        it["mappings"].append({
            "ticker": r["ticker"], "direction": r["direction"], "impact_pct": round(imp, 2) if imp is not None else None,
            "rationale": rationale(r, mech), "confidence": _num(r.get("confidence")), "score": _num(r.get("score_used")), "verdict": r.get("verdict"),
            "gap_bp_per_point": _num(r.get("gap_bp_per_point")), "gap_t": _num(r.get("gap_t")), "days": int(_num(r.get("days")) or 0),
            "trusted": bool(r["trusted"]), "option": opt, "version": int(r["version"]), "source": r.get("source"), "probe": _flag(r.get("probe")),
            "mechanism_class": r["mechanism_class"] if isinstance(r.get("mechanism_class"), str) else l3.get("mechanism_class"),
            "verdict_since_cutoff": r["verdict_since_cutoff"] if isinstance(r.get("verdict_since_cutoff"), str) else None})
    conflicts = 0
    n_none = 0
    for s, (answers, cl) in v3.items():
        for x in no_instrument(answers, cl):
            end, closed = ends.get(x["main"], ("", True))
            if closed or end < today:
                continue
            n_none += 1
            if x["main"] in items:              # an older linker named instruments here: keep them, record the disagreement
                conflicts += 1
                items[x["main"]]["no_instrument_reason"] = f"version-3 labellers: no listed instrument ({x['reason']})"
                continue
            q = roster(s).get(x["main"], {}).get("question", "")
            items[x["main"]] = {"question": q, "cluster": x["cluster"], "signal": [], "alternative": "", "ends": end, "kind": "event", "mappings": [],
                                "no_instrument": True, "no_instrument_reason": x["reason"], "probe": x["probe"]}
    t = live[live.trusted]
    with_opt = sum(1 for it in items.values() for mp in it["mappings"] if mp["trusted"] and mp["option"] and mp["option"]["contract"])
    kinds = {m: it["kind"] for m, it in items.items()}
    from s5_big_moves import granular as g5
    summary = {"as_of": as_of, "today": today, "open_links": int(len(live)), "open_questions": int(live.market.nunique()), "trusted_links": int(len(t)),
               "trusted_questions": int(t.market.nunique()), "trusted_tickers": sorted(t.ticker.unique().tolist()),
               "trusted_confirmed_by_prices": int((t.verdict == "confirmed").sum()), "trusted_with_an_option_contract": with_opt,
               "trusted_event_links": int(sum(kinds[m] == "event" for m in t.market)),
               "trusted_event_questions": int(len({m for m in t.market if kinds[m] == "event"})),
               "trusted_price_proxy_links": int(sum(kinds[m] == "price proxy" for m in t.market)),
               "trusted_by_theme": (t.theme if "theme" in t else pd.Series(index=t.index, dtype=object)).fillna(t.question.map(g5.theme_of))
               .value_counts().to_dict(),
               "version3_links": int((live.version == 3).sum()), "trusted_version3_links": int((t.version == 3).sum()),
               "probe_links": int(live.probe.map(_flag).sum()),
               "no_instrument_items": int(sum(it["no_instrument"] for it in items.values())), "no_instrument_open_clusters": n_none,
               "no_instrument_but_older_links": conflicts}
    return _clean({"generated_at": datetime.now().isoformat(timespec="seconds"), "generator": GENERATOR, "as_of": as_of, "summary": summary, "items": items})


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    notes, fams = v1_notes()
    v3 = {s: (v3_answers(s), clusters(s)) for s in V3_SETS}
    resolve = None
    if "--no-options" not in argv:
        from s4_linked_assets import data as d4
        from . import options as op
        s, base = d4._massive_session()
        resolve = lambda tk, dr, ends: op.resolve(s, base, tk, dr, ends, AS_OF)  # noqa: E731
    m = build(gather(), end_dates(), notes, fams, v3, resolve)
    text = json.dumps(m, indent=1)
    (OUT / "link_map_v2.json").write_text(text)
    BACKEND_COPY.write_text(text)
    print(json.dumps(m["summary"], indent=1))
    for k, it in m["items"].items():
        for mp in it["mappings"]:
            if mp["trusted"]:
                print(f"{it['question'][:60]:60} | {mp['ticker']:5} {mp['direction']:11} | {it['kind']:11} | {mp['verdict']:11} | "
                      f"score {mp['score'] if mp['score'] is None else round(mp['score'], 2)} | {(mp['option'] or {}).get('contract')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
