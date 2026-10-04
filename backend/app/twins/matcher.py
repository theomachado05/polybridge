from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .claims import Claim, days_between, stem

MAX_DEADLINE_GAP_CANDIDATE = 7
MAX_DEADLINE_GAP_VERIFIED = 1
MIN_CANDIDATE_SCORE = 0.40
MIN_VERIFY_SCORE = 0.50
TOP_K = 5
MAX_DF = 3000


NEUTRAL = frozenset(stem(w) for w in ("when", "become", "next", "about", "another", "new", "again", "still", "also",
                                      "ever", "yet", "case", "market", "question", "official", "officially",
                                      "interest"))
EQUIVALENT = [frozenset(stem(w) for w in g) for g in (
    ("out", "depart", "departure", "leave", "resign", "resignation", "exit"),
    ("accept", "hear", "grant"),
    ("win", "nominee", "nomination", "won"),
    ("best", "top"),
)]


def uncovered(a: Claim, b: Claim) -> list[str]:
    miss = []
    for t in sorted(a.tokens - b.tokens):
        if t.isdigit() or t in NEUTRAL or t in b.rules_tokens:
            continue
        if any(t in g and g & b.tokens for g in EQUIVALENT):
            continue
        miss.append(t)
    return miss


@dataclass
class Check:
    name: str
    ok: bool
    severity: str
    detail: str

    def as_dict(self) -> dict:
        return {"ok": self.ok, "detail": self.detail}


@dataclass
class Verdict:
    status: str
    score: float
    checks: list[Check] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def note(self) -> str:
        return "; ".join(f"{c.name}: {c.detail}" for c in self.checks)


def idf_table(claims: list[Claim]) -> dict[str, float]:
    df: dict[str, int] = defaultdict(int)
    for c in claims:
        for t in c.tokens:
            df[t] += 1
    n = max(len(claims), 1)
    return {t: math.log((n + 1) / (d + 1)) + 1.0 for t, d in df.items()}


def similarity(a: Claim, b: Claim, idf: dict[str, float]) -> float:
    union = a.tokens | b.tokens
    if not union:
        return 0.0
    w = lambda t: idf.get(t, math.log(2) + 1.0)
    inter = sum(w(t) for t in a.tokens & b.tokens)
    return inter / sum(w(t) for t in union)


def verify(poly: Claim, kal: Claim, score: float) -> Verdict:
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str, severity: str = "soft") -> bool:
        checks.append(Check(name, ok, "ok" if ok else severity, detail))
        return ok

    shared = sorted((poly.tokens & kal.tokens) - {str(y) for y in poly.years | kal.years})
    add("event", score >= MIN_VERIFY_SCORE and len(shared) >= 2,
        f"question similarity {score:.2f}, shared: {' '.join(shared[:8]) or 'none'}",
        "hard" if score < MIN_CANDIDATE_SCORE or len(shared) < 2 else "soft")

    miss_p = sorted(e for e in poly.entities if e not in kal.tokens and e not in kal.rules_tokens)
    miss_k = sorted(e for e in kal.entities if e not in poly.tokens and e not in poly.rules_tokens)
    add("subject", not miss_p and not miss_k,
        "entities agree" if not (miss_p or miss_k) else
        f"polymarket-only {miss_p or '-'}, kalshi-only {miss_k or '-'}", "hard")

    cp = sorted(e for e in poly.cond_entities if e not in kal.tokens and e not in kal.rules_tokens)
    ck = sorted(e for e in kal.cond_entities if e not in poly.tokens and e not in poly.rules_tokens)
    add("criteria", not cp and not ck,
        "resolution conditions name the same things" if not (cp or ck) else
        f"polymarket condition names {cp or '-'}, kalshi condition names {ck or '-'}, absent from the other side",
        "soft")

    up, uk = uncovered(poly, kal), uncovered(kal, poly)
    add("predicate", not up and not uk,
        "wording agrees" if not (up or uk) else
        f"polymarket-only words {up or '-'} / kalshi-only words {uk or '-'} not found in the other's resolution text",
        "soft")

    if poly.numbers and kal.numbers:
        same = poly.numbers == kal.numbers
        add("threshold", same, f"{_fmt_nums(poly.numbers)} vs {_fmt_nums(kal.numbers)}", "hard")
    elif poly.numbers or kal.numbers:
        add("threshold", False, f"threshold on one side only ({_fmt_nums(poly.numbers or kal.numbers)})", "soft")
    else:
        add("threshold", True, "no numeric threshold (event question)")

    if poly.periods and kal.periods:
        add("period", poly.periods == kal.periods, f"{sorted(poly.periods)} vs {sorted(kal.periods)}", "hard")
    elif poly.dates and kal.dates:
        ok = (all(any(days_between(d, e) <= MAX_DEADLINE_GAP_VERIFIED for e in kal.dates) for d in poly.dates)
              and all(any(days_between(d, e) <= MAX_DEADLINE_GAP_VERIFIED for e in poly.dates) for d in kal.dates))
        add("period", ok, f"{_fmt_dates(poly.dates)} vs {_fmt_dates(kal.dates)}", "hard")
    elif poly.periods or kal.periods or poly.dates or kal.dates:
        add("period", True, "a date is written in one question only (the deadline check covers it)")
    else:
        add("period", True, "no explicit date in either question")

    if poly.deadline and kal.deadline:
        gap = days_between(poly.deadline, kal.deadline)
        add("deadline", gap <= MAX_DEADLINE_GAP_VERIFIED,
            f"polymarket {poly.deadline} vs kalshi {kal.deadline} (gap {gap}d)",
            "soft" if gap <= MAX_DEADLINE_GAP_CANDIDATE else "hard")
    else:
        add("deadline", False, "a resolution deadline is unknown", "soft")

    pd, kd = set(poly.directions), set(kal.directions)
    if pd == kd:
        add("direction", True, f"both {'/'.join(sorted(pd)) or 'no direction word'}")
    elif pd and kd and pd.isdisjoint(kd):
        add("direction", False, f"direction_inverted: polymarket {'/'.join(sorted(pd))} vs kalshi "
                               f"{'/'.join(sorted(kd))} (refused: YES means a different outcome)", "soft")
    else:
        add("direction", False, f"direction unclear: polymarket {'/'.join(sorted(pd)) or '-'} vs kalshi "
                               f"{'/'.join(sorted(kd)) or '-'}", "soft")
    if poly.negated != kal.negated:
        add("negation", False, "direction_inverted: one question is negated, the other is not (refused)", "soft")
    if (poly.inclusive is not None and kal.inclusive is not None and poly.inclusive != kal.inclusive
            and pd == kd and pd & {"up", "down"}):
        add("boundary", False, "one threshold is inclusive (at or above), the other exclusive (above)", "soft")

    common = poly.sources & kal.sources
    if poly.sources and kal.sources and not common:
        add("source", False, f"resolution sources differ: {sorted(poly.sources)} vs {sorted(kal.sources)}", "soft")
    elif (poly.price_like or kal.price_like) and not common:
        add("source", False, "price/index market with no shared named resolution source (snapshot source or time "
                             "may differ)", "soft")
    else:
        add("source", True, f"shared source {sorted(common)}" if common else "neither text names a source")

    if poly.clock and kal.clock and poly.clock.isdisjoint(kal.clock):
        add("snapshot_time", False, f"snapshot times differ: polymarket {sorted(poly.clock)} vs kalshi "
                                    f"{sorted(kal.clock)} ET", "soft")

    r_union = poly.rules_tokens | kal.rules_tokens
    r_sim = len(poly.rules_tokens & kal.rules_tokens) / len(r_union) if r_union else 0.0
    checks.append(Check("rules_overlap", True, "ok", f"resolution-text word overlap {r_sim:.2f}"))

    failed = [c for c in checks if not c.ok]
    if any(c.severity == "hard" for c in failed):
        return Verdict("rejected", score, checks, [c.name for c in failed])
    if failed:
        return Verdict("ambiguous", score, checks, [_reason(c) for c in failed])
    return Verdict("verified", score, checks, [])


def _reason(c: Check) -> str:
    if "direction_inverted" in c.detail:
        return "direction_inverted"
    return "wording_differs" if c.name == "predicate" else c.name


def _fmt_nums(nums) -> str:
    return ", ".join(f"{v:g}{u}" for v, u in sorted(nums))


def _fmt_dates(ds) -> str:
    return ",".join(d.isoformat() for d in sorted(ds))


@dataclass
class Pair:
    poly: Claim
    kalshi: Claim
    verdict: Verdict


def propose(polys: list[Claim], kals: list[Claim], idf: dict[str, float] | None = None) -> list[tuple[Claim, Claim, float]]:
    idf = idf or idf_table(polys + kals)
    index: dict[str, list[int]] = defaultdict(list)
    for i, k in enumerate(kals):
        for t in k.tokens:
            index[t].append(i)
    out: list[tuple[Claim, Claim, float]] = []
    for p in polys:
        votes: dict[int, float] = defaultdict(float)
        hits: dict[int, int] = defaultdict(int)
        for t in p.tokens:
            lst = index.get(t)
            if not lst or len(lst) > MAX_DF:
                continue
            for i in lst:
                votes[i] += idf.get(t, 1.0)
                hits[i] += 1
        scored = []
        for i, v in votes.items():
            if hits[i] < 2:
                continue
            k = kals[i]
            if p.deadline and k.deadline and days_between(p.deadline, k.deadline) > MAX_DEADLINE_GAP_CANDIDATE:
                continue
            s = similarity(p, k, idf)
            if s >= MIN_CANDIDATE_SCORE:
                scored.append((s, i))
        scored.sort(reverse=True)
        for s, i in scored[:TOP_K]:
            out.append((p, kals[i], s))
    return out


def match_all(polys: list[Claim], kals: list[Claim]) -> list[Pair]:
    idf = idf_table(polys + kals)
    pairs = [Pair(p, k, verify(p, k, s)) for p, k, s in propose(polys, kals, idf)]
    pairs = [x for x in pairs if x.verdict.status != "rejected"]
    verified = [x for x in pairs if x.verdict.status == "verified"]
    by_p: dict[str, list[Pair]] = defaultdict(list)
    by_k: dict[str, list[Pair]] = defaultdict(list)
    for x in verified:
        by_p[x.poly.id].append(x)
        by_k[x.kalshi.id].append(x)
    for group in list(by_p.values()) + list(by_k.values()):
        if len(group) < 2:
            continue
        group.sort(key=lambda x: x.verdict.score, reverse=True)
        best = group[0]
        close = [x for x in group if best.verdict.score - x.verdict.score < 0.10]
        if len(close) > 1:
            for x in close:
                if x.verdict.status == "verified":
                    x.verdict = Verdict("ambiguous", x.verdict.score, x.verdict.checks, ["multiple_counterparts"])
        else:
            for x in group[1:]:
                if x.verdict.status == "verified":
                    x.verdict = Verdict("ambiguous", x.verdict.score, x.verdict.checks, ["weaker_counterpart"])
    return pairs


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
