# Held-out test of the link agent (written before any label or price exists for these markets)

**Set.** The next 120 Polymarket markets by volume after S5's 240, under S5's universe rule
(`linker/heldout/universe.json`: $6.5 million down to $4.0 million, 87 events, 106 resolved). No study has used them.

**Two questions.**

1. **Does the trained scorer work on markets it has never seen?** The scorer of `results/linker/scorer.json`, trained
   on S4 and S5, scores every held-out link before its equity prices are pulled. Measure: AUC of the score against
   the benchmark verdict (confirmed or not), and the confirmed share in the top third against the base rate.
2. **Does linking by event beat linking by question?**
   - **Arm A, by question (the current linker).** Two blind labellers see a flat list of questions. Same prompt as S5.
   - **Arm B, by event (the revised linker).** Two blind labellers see the same questions grouped by event, with the
     rules of `LINKER.md` ("What breaks a link"): link the question that carries the event, one deadline per ladder,
     state the alternative for a multi-outcome event, pick an instrument the event would move by about 1% or more,
     class price-driven questions as spot proxies, no hindsight.
   - In both arms a link is a (ticker, direction) that both labellers named on a question both called an event.
   - Measure, per arm: links, testable links, share confirmed, number contradicted, share with the right sign.

**Scoring** is the benchmark's (`linker/benchmark.py`): the equity's excess opening gap on the overnight,
direction-signed move in odds; confirmed at t ≥ 2, contradicted at t ≤ −2, untestable under 30 days or on SPY.
Window 2025-10-01 to 2026-10-02.

**Reading the result.** With about 120 questions the arms will differ by a handful of links, so only a large gap
means anything. Arm B is better only if it has a higher confirmed share **and** no more contradicted links. Both arms
and the scorer result are reported whatever they show.

**Hindsight.** 106 of the 120 markets have resolved and the labellers' knowledge runs to June 2026. Both arms face
the same exposure, so the comparison between them is fair even where the level is inflated.
