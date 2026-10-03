"""Propose candidate Polymarket <-> Kalshi pairs, then VERIFY each by comparing what the two markets resolve on.

Proposal is cheap and loose (idf-weighted word overlap + a deadline window). Verification is strict and explicit:
every check below must pass for a pair to enter the map.

  subject    every proper noun / ticker in one question appears on the other side
  threshold  the same numeric thresholds (value and unit); a threshold on one side only is not enough
  period     explicit dates / months in the questions agree
  deadline   resolution deadlines (America/New_York calendar date) within 1 day
  direction  same direction words (above/below/raise/cut/no change), same negation, same boundary inclusivity.
             An opposite direction is REFUSED (listed as ambiguous with reason ``direction_inverted``): the twin
             map only ever pairs markets whose YES means the same outcome, so ``p_other_venue`` needs no flip.
  source     the resolution sources both texts name (BLS, Fed, Binance, ...) overlap; price-snapshot markets
             (crypto, indices, commodities) additionally need a shared named source, because a different
             snapshot source or time is a different market.

A hard failure rejects the pair; a soft one (can't tell / inverted / off by a few days) makes it ``ambiguous``.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .claims import Claim, days_between

MAX_DEADLINE_GAP_CANDIDATE = 7      # days: wider than this is never even ambiguous
MAX_DEADLINE_GAP_VERIFIED = 1       # spec: same deadline within 1 day
MIN_CANDIDATE_SCORE = 0.40
MIN_VERIFY_SCORE = 0.50
TOP_K = 5
MAX_DF = 3000                       # tokens more common than this are not used to propose candidates


@dataclass
class Check:
    name: str
    ok: bool
    severity: str       # "hard" | "soft" (what a failure means); "ok" when it passed
    detail: str

    def as_dict(self) -> dict:
        return {"ok": self.ok, "detail": self.detail}


@dataclass
class Verdict:
    status: str                         # "verified" | "ambiguous" | "rejected"
    score: float
    checks: list[Check] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)   # names of failed checks (ambiguous/rejected)

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
    """idf-weighted Jaccard of the questions' content words."""
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

    # subject: proper nouns must be visible on the other side (its question or the start of its resolution text)
    miss_p = sorted(e for e in poly.entities if e not in kal.tokens and e not in kal.rules_tokens)
    miss_k = sorted(e for e in kal.entities if e not in poly.tokens and e not in poly.rules_tokens)
    add("subject", not miss_p and not miss_k,
        "entities agree" if not (miss_p or miss_k) else
        f"polymarket-only {miss_p or '-'}, kalshi-only {miss_k or '-'}", "hard")

    # threshold
    if poly.numbers and kal.numbers:
        same = poly.numbers == kal.numbers
        add("threshold", same, f"{_fmt_nums(poly.numbers)} vs {_fmt_nums(kal.numbers)}", "hard")
    elif poly.numbers or kal.numbers:
        add("threshold", False, f"threshold on one side only ({_fmt_nums(poly.numbers or kal.numbers)})", "soft")
    else:
        add("threshold", True, "no numeric threshold (event question)")

    # explicit dates / months written in the questions
    if poly.periods and kal.periods:
        add("period", poly.periods == kal.periods, f"{sorted(poly.periods)} vs {sorted(kal.periods)}", "hard")
    elif poly.dates and kal.dates:
        ok = (all(any(days_between(d, e) <= MAX_DEADLINE_GAP_VERIFIED for e in kal.dates) for d in poly.dates)
              and all(any(days_between(d, e) <= MAX_DEADLINE_GAP_VERIFIED for e in poly.dates) for d in kal.dates))
        add("period", ok, f"{_fmt_dates(poly.dates)} vs {_fmt_dates(kal.dates)}", "hard")
    elif poly.periods or kal.periods or poly.dates or kal.dates:
        add("period", False, "a date/month is written in one question only", "soft")
    else:
        add("period", True, "no explicit date in either question")

    # deadline
    if poly.deadline and kal.deadline:
        gap = days_between(poly.deadline, kal.deadline)
        add("deadline", gap <= MAX_DEADLINE_GAP_VERIFIED,
            f"polymarket {poly.deadline} vs kalshi {kal.deadline} (gap {gap}d)",
            "soft" if gap <= MAX_DEADLINE_GAP_CANDIDATE else "hard")
    else:
        add("deadline", False, "a resolution deadline is unknown", "soft")

    # direction
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

    # resolution source
    common = poly.sources & kal.sources
    if poly.sources and kal.sources and not common:
        add("source", False, f"resolution sources differ: {sorted(poly.sources)} vs {sorted(kal.sources)}", "soft")
    elif (poly.price_like or kal.price_like) and not common:
        add("source", False, "price/index market with no shared named resolution source (snapshot source or time "
                             "may differ)", "soft")
    else:
        add("source", True, f"shared source {sorted(common)}" if common else "neither text names a source")

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
    return "direction_inverted" if "direction_inverted" in c.detail else c.name


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
    """Candidate (poly, kalshi, score): shares >= 2 content words and a deadline within a week, top-K per Polymarket
    market by similarity."""
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
    """Propose + verify, then enforce one-to-one: a market that verifies against two different counterparts with
    near-equal scores is ambiguous on both (we cannot tell which is the twin)."""
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
    # a pair demoted via one side's group must stay demoted everywhere (it is the same object, so it already is)
    return pairs


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


