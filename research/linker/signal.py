"""From two version-3 labellers' answers to links (linker/heldout2/PLAN.md sections 2.3 and 4).

1. An answer that breaks a hard rule of linker/prompts/labeller_v3.md (its last section) is discarded: its cluster gets
   no link. No answer is edited. "Exactly one answer, in the same order": a cluster a labeller answered more than once,
   in any chunk, loses every answer of that labeller; an answer placed after a cluster that comes later in its input
   file is discarded (only the answers out of place, so one swap costs one answer).
2. Orientation: the anchor is the highest-volume question with a non-zero weight in both signals. Each labeller whose
   weight on the anchor is negative is turned: weights, link directions and market_wide flip together. No anchor, no
   common signal.
3. The common signal: questions both weighted with the same sign, each with the mean of the two weights, scaled so the
   largest |weight| is 1. Valid only if it carries at least two thirds of each labeller's own total |weight|.
4. A link is a (cluster, ticker, direction) both named on a cluster both called an event (kind "event") or both called
   a price proxy (kind "price proxy"), with a valid common signal. SPY is never a link. Tickers are compared after
   linker.instruments.normalise. A ticker off the list is kept only when Massive validated it at pull time.
5. market_wide counts when both give the same direction after orientation and the common signal is valid.

series() turns a signal into odds: one question as is; several on the main leg's minute grid (NaN where the main leg's
last price is over 30 minutes old, the other legs carried at their last price and 0 before their first one, and 0
throughout when they never traded).

File faults (PLAN 2.2, the only grounds for a rerun): a labels file that is not JSON or has no answers list, or that
answers fewer than all clusters (or questions) of its input file. Everything else is a note.

Run from `research/`:  python -m linker.signal validate dev|heldout2
    (prints file faults, then notes; exit code 1 on a file fault)
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

from . import instruments as ins
from . import store

HERE = Path(__file__).resolve().parent
STUDIES = {"dev": HERE / "dev", "heldout2": HERE / "heldout2", "h1check": HERE / "heldout"}
LABELLERS = ("P", "S")
HEDGE = "SPY"
MAX_LINKS = 4
SHARE = 2 / 3
MIN_CONFIDENCE = 0.3          # a link needs at least this confidence from both labellers (PLAN 2.3)
FAMILIES = {"event", "spot_proxy", "none"}
KIND = {"event": "event", "spot_proxy": "price proxy"}
STRUCTURES = {"binary", "ladder", "multi_outcome"}
DIRECTIONS = {"up_on_yes", "down_on_yes"}
MECHANISMS = {"commodity_supply", "rates_policy", "fx_macro", "country_election", "regulation_sector", "company_specific",
              "crypto_policy", "war_geopolitics", "trade_tariffs", "other"}
ROLES = {"carrier", "duplicate", "tail", "none"}
RESOLVED = {"yes", "no", "unknown"}
MARKET_WIDE = {"up", "down", None}
FLIP = {"up_on_yes": "down_on_yes", "down_on_yes": "up_on_yes", "up": "down", "down": "up", None: None}
FIELDS = ("family", "structure", "signal", "signal_meaning", "alternative", "links", "no_instrument", "no_instrument_reason",
          "market_wide", "remembered")
LINK_FIELDS = ("ticker", "direction", "confidence", "impact_pct", "mechanism_class", "mechanism", "off_menu")
MAX_AGE_S = 1800


def study_dir(study: str | Path) -> Path:
    return STUDIES[study] if isinstance(study, str) and study in STUDIES else Path(study)


def universe(study: str | Path) -> dict:
    return json.loads((study_dir(study) / "universe.json").read_text())


def clusters(study: str | Path) -> dict[str, dict]:
    """cluster -> its universe event (main, structure, seen_ladder, probe, roster under `markets`)."""
    return {e["cluster"]: e for e in universe(study).get("events", [])}


def markets(study: str | Path) -> dict[str, dict]:
    """Every market the study knows by id: the test markets and every roster market."""
    u = universe(study)
    out = {m["id"]: m for e in u.get("events", []) for m in e["markets"]}
    out.update({m["id"]: {**out.get(m["id"], {}), **m} for m in u.get("markets", [])})
    return out


def _chunk(f: Path) -> str:
    return f.stem.rsplit("_", 1)[1]


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _f(x) -> float:
    return float(x) if _num(x) else float("nan")


def low(a, b) -> float:
    """The smaller of two numbers, NaN when either is not a number (Python's min is order-dependent with NaN)."""
    return float(np.minimum(_f(a), _f(b)))


# ---------------------------------------------------------------- hard rules

def discard(answer: dict, cluster: dict) -> str | None:
    """Why this answer breaks a hard rule of labeller_v3.md (its last section), or None. `cluster` is the universe event.
    The two order rules are marked on the answer by load_v3 ("_answered", "_out_of_order")."""
    if answer.get("_answered", 1) > 1:
        return f"answered {answer['_answered']} times"
    if answer.get("_out_of_order"):
        return "answered after a cluster that comes later in the input file"
    miss = [k for k in FIELDS if k not in answer]
    if miss:
        return f"missing field {', '.join(miss)}"
    links = answer["links"] if isinstance(answer["links"], list) else None
    if links is None or not isinstance(answer["signal"], list):
        return "signal or links is not a list"
    for l in links:
        lm = [k for k in LINK_FIELDS if not isinstance(l, dict) or k not in l]
        if lm:
            return f"a link misses {', '.join(lm)}"
    st, sig = answer["structure"], answer["signal"]
    if st in ("binary", "ladder"):
        if len(sig) != 1 or not isinstance(sig[0], dict) or sig[0].get("id") != cluster.get("main") \
                or not _num(sig[0].get("weight")) or sig[0]["weight"] != 1:
            return f"{st}: signal is not exactly the main question with weight 1"
    elif st == "multi_outcome":
        roster = {m["id"] for m in cluster.get("markets", [])}
        if any(not isinstance(s, dict) or s.get("id") not in roster for s in sig):
            return "multi_outcome: a signal id is not one of the cluster's questions"
        if any(not _num(s.get("weight")) or not -1 <= s["weight"] <= 1 for s in sig):
            return "multi_outcome: a weight is not a number in [-1, 1]"
        if not any(s["weight"] != 0 for s in sig):
            return "multi_outcome: no weight is non-zero"
    else:
        return f"structure {st!r} is not binary, ladder or multi_outcome"
    if links and (answer["no_instrument"] is True or answer["family"] == "none"):
        return "links given with no_instrument true or family none"
    if len(links) > MAX_LINKS:
        return f"{len(links)} links (at most {MAX_LINKS})"
    tks = [ins.normalise(l["ticker"]) for l in links]
    if len(tks) != len(set(tks)):
        return "a ticker appears twice"
    if HEDGE in tks:
        return "SPY named"
    return None


# ---------------------------------------------------------------- validation

def _labels_files(d: Path) -> list[Path]:
    return sorted(d.glob("labels_v3_*_*.json")) + sorted(d.glob("labels_control_*_*.json")) + sorted(d.glob("labels_recall_*_*.json"))


def _want(d: Path, f: Path) -> tuple[str, list[str] | None]:
    """(kind, the ids the file must answer, in order) from its input file; None when it has no input file."""
    kind, k = f.name.split("_")[1], _chunk(f)
    inp = d / f"input_{kind}_{k}.json"
    if not inp.exists():
        return kind, None
    src = json.loads(inp.read_text())
    if kind == "v3":
        return kind, [e["cluster"] for e in src["events"]]
    if kind == "control":
        return kind, [q["id"] for e in src["events"] for q in e["questions"]]
    return kind, [q["id"] for q in src.get("questions", [])]


def _key(kind: str) -> str:
    return "cluster" if kind == "v3" else "id"


def _parts(f: Path) -> tuple[str, str, str]:
    """(kind, labeller, chunk) from labels_<kind>_<labeller>_<chunk>.json."""
    parts = f.stem.split("_")
    return parts[1], "_".join(parts[2:-1]), parts[-1]


def _read(f: Path) -> tuple[list | None, str | None]:
    """(the answers list, None) or (None, the file fault)."""
    try:
        lab = json.loads(f.read_text())
    except ValueError as e:
        return None, f"not JSON ({str(e)[:80]})"
    if not isinstance(lab, dict) or not isinstance(lab.get("answers"), list):
        return None, "no answers list"
    return lab["answers"], None


def _ids(answers: list, kind: str) -> list:
    return [a.get(_key(kind)) for a in answers if isinstance(a, dict) and isinstance(a.get(_key(kind)), str)]


def validate(study: str | Path) -> list[str]:
    """File faults, the only grounds for a rerun (PLAN 2.2): not JSON, no answers list, or a cluster (question) of the
    input file with no answer. Empty when there is none."""
    d = study_dir(study)
    out: list[str] = []
    for f in _labels_files(d):
        kind = _parts(f)[0]
        answers, err = _read(f)
        if err:
            out.append(f"{f.name}: {err}")
            continue
        _, want = _want(d, f)
        seen = set(_ids(answers, kind))
        name = "cluster" if kind == "v3" else "question"
        out += [f"{f.name}: {name} {q} missing" for q in want or [] if q not in seen]
    return out


def _note_control(f: Path, a: dict, menu: set[str]) -> list[str]:
    q, out = a.get("id"), []
    for k in ("family", "role", "links", "remembered"):
        if k not in a:
            out.append(f"{f.name} {q}: missing field {k}")
    if a.get("family") not in FAMILIES:
        out.append(f"{f.name} {q}: bad family {a.get('family')!r}")
    if "role" in a and a["role"] not in ROLES:
        out.append(f"{f.name} {q}: bad role {a['role']!r}")
    for l in a.get("links") or []:
        tk = str(l.get("ticker", ""))
        if tk == HEDGE:
            out.append(f"{f.name} {q}: SPY named")
        elif menu and tk not in menu:
            out.append(f"{f.name} {q}: ticker {tk!r} is not on the list (ignored)")
        if l.get("direction") not in DIRECTIONS:
            out.append(f"{f.name} {q} {tk}: bad direction {l.get('direction')!r}")
        if not _num(l.get("confidence")) or not 0 <= l["confidence"] <= 1:
            out.append(f"{f.name} {q} {tk}: confidence {l.get('confidence')!r} outside [0, 1]")
    return out


def _note_recall(f: Path, a: dict) -> list[str]:
    q, out = a.get("id"), []
    if a.get("resolved") not in RESOLVED:
        out.append(f"{f.name} {q}: resolved {a.get('resolved')!r} is not yes, no or unknown")
    if not _num(a.get("confidence")) or not 0 <= a["confidence"] <= 1:
        out.append(f"{f.name} {q}: confidence {a.get('confidence')!r} outside [0, 1]")
    return out


def notes(study: str | Path) -> list[str]:
    """Everything that is not a file fault, no ground for a rerun: labeller or chunk unlike the file name, no input file,
    ids not in the input file (or not markets of the study), clusters or questions answered more than once (their
    answers are dropped), version-3 answers discarded by a hard rule (with the reason), control or recall answers out
    of their input order, and control or recall answers off their prompt's format."""
    d = study_dir(study)
    cl, known = clusters(d), set(markets(d))
    out: list[str] = []
    count: dict[tuple[str, str], dict[str, int]] = {}
    for f in _labels_files(d):
        kind, who, k = _parts(f)
        answers, err = _read(f)
        if err:
            continue
        lab = json.loads(f.read_text())
        if str(lab.get("labeller")) != who:
            out.append(f"{f.name}: labeller {lab.get('labeller')!r}, the file name says {who!r}")
        if str(lab.get("chunk")) != k:
            out.append(f"{f.name}: chunk {lab.get('chunk')!r}, the file name says {k}")
        _, want = _want(d, f)
        seen = _ids(answers, kind)
        name = "cluster" if kind == "v3" else "question"
        if want is None:
            if kind != "recall":
                out.append(f"{f.name}: no input file input_{kind}_{k}.json")
            out += [f"{f.name}: question {q} is not a market of this study" for q in sorted(set(seen) - known)]
        else:
            out += [f"{f.name}: {name} {q} is not in its input file" for q in sorted(set(seen) - set(want))]
            if kind != "v3" and [x for x in seen if x in want] != [x for x in want if x in seen]:
                out.append(f"{f.name}: answers are not in the input file's order")
        c = count.setdefault((kind, who), {})
        for q in seen:
            c[q] = c.get(q, 0) + 1
        menu = set(json.loads((d / f"input_control_{k}.json").read_text()).get("tickers", [])) \
            if kind == "control" and (d / f"input_control_{k}.json").exists() else set()
        for a in answers:
            if not isinstance(a, dict):
                out.append(f"{f.name}: an answer is not an object (ignored)")
            elif kind == "control":
                out += _note_control(f, a, menu)
            elif kind == "recall":
                out += _note_recall(f, a)
    for (kind, who), c in sorted(count.items()):
        out += [f"labels_{kind}_{who}: {'cluster' if kind == 'v3' else 'question'} {q} answered {n} times over its files: every answer "
                f"to it is dropped" for q, n in sorted(c.items()) if n > 1]
    for who in sorted({w for kind, w in count if kind == "v3"}):
        for c, a in sorted(load_v3(d, who).items()):
            why = discard(a, cl.get(c, {}))
            if why and a.get("_answered", 1) == 1:
                out.append(f"{a.get('_file', f'labels_v3_{who}')} {c}: discarded, {why}")
    return out


# ---------------------------------------------------------------- agreement

def load_v3(study: str | Path, labeller: str) -> dict[str, dict]:
    """cluster -> that labeller's answer, over all chunks, with the file name under "_file". A cluster answered more than
    once in any chunk maps to {"cluster", "_answered": n} (discarded, PLAN 2.3); an answer placed after a cluster that
    comes later in its input file carries "_out_of_order" (discarded). Clusters answered more than once and ids not in
    the input file are left out of the order check. Files that are not JSON or have no answers list give no answer."""
    d = study_dir(study)
    files = [(f, _read(f)[0]) for f in sorted(d.glob(f"labels_v3_{labeller}_*.json"))]
    files = [(f, [a for a in ans if isinstance(a, dict) and isinstance(a.get("cluster"), str)]) for f, ans in files if ans is not None]
    n: dict[str, int] = {}
    for _, ans in files:
        for a in ans:
            n[a["cluster"]] = n.get(a["cluster"], 0) + 1
    out: dict[str, dict] = {c: {"cluster": c, "_answered": k} for c, k in n.items() if k > 1}
    for f, ans in files:
        _, want = _want(d, f)
        pos = {c: i for i, c in enumerate(want or [])}
        top = -1
        for a in ans:
            c = a["cluster"]
            if n[c] > 1:
                continue
            late = c in pos and pos[c] < top
            top = max(top, pos.get(c, -1))
            out[c] = {**a, "_file": f.name, **({"_out_of_order": True} if late else {})}
    return out


def _weights(answer: dict) -> dict[str, float]:
    return {s["id"]: float(s["weight"]) for s in answer.get("signal") or [] if _num(s.get("weight")) and s["weight"] != 0}


def anchor(a: dict, b: dict, volume: dict[str, float]) -> str | None:
    """The highest-volume question with a non-zero weight in both signals (ties: the smaller id), or None."""
    both = _weights(a).keys() & _weights(b).keys()
    return min(both, key=lambda i: (-volume.get(i, 0.0), i)) if both else None


def turn(answer: dict) -> dict:
    """The answer with weights, link directions and market_wide flipped together."""
    return {**answer, "signal": [{**s, "weight": -s["weight"]} if _num(s.get("weight")) else s for s in answer.get("signal") or []],
            "links": [{**l, "direction": FLIP.get(l.get("direction"), l.get("direction"))} for l in answer.get("links") or []],
            "market_wide": FLIP.get(answer.get("market_wide"), answer.get("market_wide"))}


def orient(a: dict, b: dict, volume: dict[str, float]) -> tuple[dict, dict, str | None]:
    """Both answers turned so that the anchor has a positive weight in each; (a, b, None) unchanged without an anchor."""
    anc = anchor(a, b, volume)
    if anc is None:
        return a, b, None
    return (turn(a) if _weights(a)[anc] < 0 else a), (turn(b) if _weights(b)[anc] < 0 else b), anc


def common_signal(a: dict, b: dict, volume: dict[str, float] | None = None) -> tuple[list[tuple[str, float]], bool]:
    """(the common signal, valid) of two oriented answers. The signal: questions both weighted with the same sign, mean
    weight, scaled so the largest |weight| is 1, sorted with the main leg first (largest |weight|, then largest volume).
    Valid when it carries at least two thirds of each labeller's own total |weight|."""
    vol = volume or {}
    wa, wb = _weights(a), _weights(b)
    both = {i: (wa[i] + wb[i]) / 2 for i in wa.keys() & wb.keys() if np.sign(wa[i]) == np.sign(wb[i])}
    if not both:
        return [], False
    ok = all(sum(abs(w[i]) for i in both) >= SHARE * sum(abs(v) for v in w.values()) - 1e-12 for w in (wa, wb))
    top = max(abs(v) for v in both.values())
    return sorted(((i, v / top) for i, v in both.items()), key=lambda iv: (-round(abs(iv[1]), 12), -vol.get(iv[0], 0.0), iv[0])), ok


def signal_range_points(sig: list[tuple[str, float]] | list[list]) -> float:
    """100 x (sum of positive weights - sum of negative weights): the signal's span in points."""
    return 100.0 * sum(abs(float(w)) for _, w in sig)


def _links(answer: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for l in answer.get("links") or []:
        tk = ins.normalise(l.get("ticker", ""))
        if tk and tk != HEDGE and tk not in out and l.get("direction") in DIRECTIONS:
            out[tk] = l
    return out


def pair(a: dict | None, b: dict | None, ev: dict) -> dict:
    """Everything the two answers on one cluster give: discards, orientation, the common signal, agreed tickers."""
    vol = {m["id"]: float(m.get("volume") or 0.0) for m in ev.get("markets", [])}
    why = {lab: (discard(x, ev) if x is not None else "no answer") for lab, x in zip(LABELLERS, (a, b))}
    r = {"discarded": {k: v for k, v in why.items() if v}, "anchor": None, "signal": [], "valid": False, "kind": None,
         "agreed": [], "a": a, "b": b, "opposite": [], "by_one": []}
    if r["discarded"]:
        return r
    a, b, anc = orient(a, b, vol)
    sig, ok = common_signal(a, b, vol) if anc else ([], False)
    fam = a.get("family") if a.get("family") == b.get("family") else None
    la, lb = _links(a), _links(b)
    r.update(a=a, b=b, anchor=anc, signal=sig, valid=ok, kind=KIND.get(fam),
             opposite=sorted(t for t in la.keys() & lb.keys() if la[t]["direction"] != lb[t]["direction"]),
             by_one=sorted(la.keys() ^ lb.keys()))
    if r["kind"] and ok:
        r["agreed"] = sorted(t for t in la.keys() & lb.keys() if la[t]["direction"] == lb[t]["direction"])
    return r


def universe_name(study: str | Path) -> str:
    return study if isinstance(study, str) and study in STUDIES else study_dir(study).name


def merge(study: str | Path, off_menu: dict[str, dict] | None = None) -> tuple[list[dict], dict]:
    """Links both labellers named (event links and price-proxy links, told apart by `kind`), and counts of how they
    agreed. The probe cluster's links are returned (probe=True) but enter no count; its counts are under stats["probe"].

    off_menu: the pull's verdict on tickers off the list, {ticker: {"keep": bool, "note": str}}. None keeps every
    off-list link with off_menu=True (what the pull needs); otherwise an off-list ticker not kept is dropped and listed
    in stats["off_menu_dropped"]."""
    cl, mk = clusters(study), markets(study)
    a_all, b_all = load_v3(study, "P"), load_v3(study, "S")
    keys = ("clusters", "both_event", "both_spot_proxy", "no_instrument_by_one", "no_instrument_by_both", "discarded_clusters",
            "no_common_question", "signal_disagreement", "valid_signal", "market_wide_by_both", "market_wide_agreed_direction",
            "agreed_links", "price_proxy_links", "named_by_one_only", "opposite_direction", "clusters_with_link")
    stats = {k: 0 for k in keys} | {"probe": {k: 0 for k in keys}, "market_wide": [], "discarded_answers": [], "off_menu_dropped": [],
                                    "below_confidence_floor": []}
    links: list[dict] = []
    for c in sorted(a_all.keys() | b_all.keys()):
        ev = cl.get(c, {"main": None, "structure": "", "seen_ladder": False, "probe": False, "markets": []})
        st = stats["probe"] if ev.get("probe") else stats
        st["clusters"] += 1
        r = pair(a_all.get(c), b_all.get(c), ev)
        if r["discarded"]:
            st["discarded_clusters"] += 1
            stats["discarded_answers"] += [{"cluster": c, "labeller": k, "reason": v, "probe": bool(ev.get("probe"))} for k, v in r["discarded"].items()]
            continue
        a, b = r["a"], r["b"]
        st["both_event"] += r["kind"] == "event"
        st["both_spot_proxy"] += r["kind"] == "price proxy"
        ni = bool(a.get("no_instrument")) + bool(b.get("no_instrument"))
        st["no_instrument_by_one"] += ni == 1
        st["no_instrument_by_both"] += ni == 2
        if r["kind"]:
            st["no_common_question"] += r["anchor"] is None
            st["signal_disagreement"] += r["anchor"] is not None and not r["valid"]
            st["valid_signal"] += r["valid"]
        st["named_by_one_only"] += len(r["by_one"])
        st["opposite_direction"] += len(r["opposite"])
        sig = r["signal"]
        if a.get("market_wide") and b.get("market_wide"):
            st["market_wide_by_both"] += 1
            if a["market_wide"] == b["market_wide"] and r["valid"]:
                st["market_wide_agreed_direction"] += 1
                if not ev.get("probe"):
                    stats["market_wide"].append({"cluster": c, "direction": a["market_wide"], "signal": sig,
                                                 "family_p": a.get("family"), "family_s": b.get("family")})
        la, lb = _links(a), _links(b)
        agreed = []
        for tk in r["agreed"]:
            if off_menu is not None and not ins.on_menu(tk) and not off_menu.get(tk, {}).get("keep"):
                stats["off_menu_dropped"].append({"cluster": c, "ticker": tk, "probe": bool(ev.get("probe")),
                                                  "note": off_menu.get(tk, {}).get("note", "off the list and not validated at pull time")})
                continue
            conf = low(la[tk].get("confidence"), lb[tk].get("confidence"))
            if not conf >= MIN_CONFIDENCE:
                stats["below_confidence_floor"].append({"cluster": c, "ticker": tk, "kind": r["kind"], "probe": bool(ev.get("probe")),
                                                        "confidence": conf})
                continue
            agreed.append(tk)
        st["agreed_links" if r["kind"] == "event" else "price_proxy_links"] += len(agreed)
        st["clusters_with_link"] += bool(agreed) and r["kind"] == "event"
        if not agreed:
            continue
        lead = sig[0][0]
        for tk in agreed:
            pa, sb = la[tk], lb[tk]
            imp = [_f(pa.get("impact_pct")), _f(sb.get("impact_pct"))]
            links.append({"source": universe_name(study), "linker": "v3, by event", "kind": r["kind"], "cluster": c, "market": lead,
                          "question": mk.get(lead, {}).get("question", ""), "ticker": tk, "direction": pa["direction"],
                          "confidence": low(pa.get("confidence"), sb.get("confidence")), "two_models": 1,
                          "links_on_question": len(agreed), "signal": json.dumps([[i, round(w, 6)] for i, w in sig]),
                          "signal_range_points": signal_range_points(sig), "structure": ev.get("structure", ""),
                          "impact_pct": float(np.nanmean(imp)) if np.isfinite(imp).any() else float("nan"),
                          "mechanism_class": pa.get("mechanism_class", ""), "alternative": a.get("alternative", ""),
                          "seen_ladder": bool(ev.get("seen_ladder")), "probe": bool(ev.get("probe")),
                          "remembered": bool(a.get("remembered")) or bool(b.get("remembered")), "off_menu": not ins.on_menu(tk),
                          "main_market": ev.get("main")})
    return links, stats


# ---------------------------------------------------------------- the signal's odds

def _forward(grid: np.ndarray, t: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Last price at or before each grid time with no age limit; 0 before the first price."""
    idx = np.searchsorted(t, grid, side="right") - 1
    return np.where(idx >= 0, p[np.clip(idx, 0, None)], 0.0)


def series(components: list[tuple[str, float]] | list[list], main: str | None = None,
           max_age_s: int = MAX_AGE_S) -> tuple[np.ndarray, np.ndarray]:
    """Odds of a signal in probability units (100 x a change is points). One question: its own odds times the sign of
    its weight. Several: weights scaled so the largest |weight| is 1; the main leg is `main` or else the first
    component with the largest |weight| (merge puts the larger volume first among ties). The grid is every minute from
    the main leg's first price to the first minute it is over `max_age_s` old after its last price; the total is NaN
    wherever the main leg's last price is over `max_age_s` old, so an as-of lookup with the same age limit never reaches
    back past a stale minute. Every other leg is carried at its last price with no age limit, counts as 0 before its
    first price, and as 0 throughout when its pulled history is empty. Empty arrays when the main leg has no odds or a
    leg's file is absent (the pull failed)."""
    comps = [(str(i), float(w)) for i, w in components if float(w) != 0]
    empty = np.array([], dtype=np.int64), np.array([], dtype=float)
    if not comps:
        return empty
    top = max(abs(w) for _, w in comps)
    lead = main if main in {i for i, _ in comps} else next(i for i, w in comps if abs(w) == top)
    parts = {}
    for i, w in comps:
        pm = store.npz(f"pm_{re.sub(r'^polymarket:', '', i)}.npz")
        if pm is None or (i == lead and not len(pm["t"])):
            return empty
        if len(pm["t"]):
            parts[i] = (pm["t"].astype(np.int64), pm["p"].astype(float), w / top)
    if len(comps) == 1:
        t, p, w = parts[lead]
        return t, np.sign(w) * p
    t0, p0, w0 = parts[lead]
    grid = np.arange((int(t0[0]) + 59) // 60 * 60, int(t0[-1]) + max_age_s + 61, 60, dtype=np.int64)
    idx = np.searchsorted(t0, grid, side="right") - 1
    total = np.where(grid - t0[idx] <= max_age_s, w0 * p0[idx], np.nan)
    for i, (t, p, w) in parts.items():
        if i != lead:
            total = total + w * _forward(grid, t, p)
    return grid, total


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "validate" or argv[1] not in ("dev", "heldout2"):
        print("usage: python -m linker.signal validate dev|heldout2")
        return 2
    faults, other = validate(argv[1]), notes(argv[1])
    for p in faults:
        print("FAULT", p)
    for p in other:
        print("note ", p)
    files = len(_labels_files(study_dir(argv[1])))
    print(f"{files} labels files, {len(faults)} file faults (rerun grounds), {len(other)} answer-level notes (no rerun)")
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
