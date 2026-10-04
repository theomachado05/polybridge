"use client";

import { useState } from "react";
import Link from "next/link";
import { getLadders } from "@/lib/api";
import { useAsync, useRetry } from "@/lib/hooks";
import { actionPlan, engineLine, mechanismFor, pairGapText, pairState, pct, rungsInOrder, sortLadders, type Ladder, type LadderPair, type Mechanism } from "@/lib/micro";
import { Unavailable } from "@/components/pb";
import { PageHead, ProposalPanel, StatusTag, useRegistry } from "@/components/micro/parts";

const STATE_TAG: Record<ReturnType<typeof pairState>, { text: string; tone: string }> = {
  actionable: { text: "violation after fees · nested", tone: "up" },
  violation_not_nested: { text: "violation, but nesting fails", tone: "warn" },
  nested: { text: "in order", tone: "neutral" },
  not_nested: { text: "nesting fails", tone: "warn" },
  no_book: { text: "no two-sided book", tone: "neutral" },
};

/** Ladder board: live Polymarket date ladders, rungs in date order, the nesting checks, and violations after fees. */
export default function LadderBoard() {
  const reg = useRegistry();
  const [n, retry] = useRetry();
  const lad = useAsync(`ladders:${n}`, getLadders);
  const mech = mechanismFor(reg.data, "ladder_rung");
  const d = lad.data;
  const ladders = d?.ok ? sortLadders(d.ladders) : [];
  const c = d?.counts;

  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: "var(--sp-8)", display: "flex", flexDirection: "column", gap: "var(--sp-5)" }}>
      <PageHead kicker="01 · Ladder board" title="Date ladders" tag={<StatusTag m={mech} />}>
        {mech ? mech.claim : null}{" "}
        <Link href="/tested#ladders" className="pb-small" style={{ color: "var(--accent)" }}>What we tested</Link>
      </PageHead>
      {reg.error && <Unavailable what="The evidence registry (GET /evidence/mechanisms)" error={reg.error} onRetry={reg.retry} compact />}
      {mech && <div className="pb-small pb-pretty" data-testid="ladder-actions" style={{ maxWidth: 880 }}>{mech.actions_allowed.text}</div>}

      {lad.loading && <div className="pb-small">Reading the open date ladders and their books…</div>}
      {lad.error && <Unavailable what="The ladder board (GET /ladders)" error={lad.error} onRetry={retry} />}
      {d && !d.ok && <Unavailable what="The ladder board (GET /ladders)" error={d.error} onRetry={retry} />}
      {d?.ok && (
        <div className="pb-small pb-num" style={{ display: "flex", gap: "var(--sp-4)", flexWrap: "wrap", alignItems: "center" }}>
          <span>{c?.ladders ?? ladders.length} ladders</span>
          <span>{c?.pairs ?? 0} adjacent pairs</span>
          <span>{c?.nested_pairs ?? 0} nested</span>
          <span style={{ color: c?.violations ? "var(--up-ink)" : undefined }}>{c?.violations ?? 0} violations after fees</span>
          <span>{c?.actionable ?? 0} actionable</span>
          {d.as_of && <span>as of {d.as_of.replace("T", " ").slice(0, 19)} UTC{d.stale ? " (cached)" : ""}</span>}
          <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={retry}>Refresh</button>
        </div>
      )}
      {d?.ok && !ladders.length && <div className="pb-card pb-list-note">No open date ladder passed the volume floor right now.</div>}
      {ladders.map((l) => <LadderCard key={l.ladder_id} l={l} mech={mech} />)}
    </main>
  );
}

function LadderCard({ l, mech }: { l: Ladder; mech: Mechanism | null }) {
  const rungs = rungsInOrder(l);
  const q = (id: string) => l.rungs.find((r) => r.id === id);
  return (
    <section className="pb-card" style={{ overflow: "hidden" }} aria-label={l.event_title}>
      <div style={{ padding: "var(--sp-4) var(--sp-5)", display: "flex", gap: "var(--sp-3)", alignItems: "center", flexWrap: "wrap", borderBottom: "1px solid var(--border)" }}>
        <h2 className="pb-h4 pb-pretty" style={{ margin: 0, minWidth: 0 }}>{l.event_title}</h2>
        <span className={`pb-tag pb-tag-${l.valid ? "neutral" : "warn"}`}>{l.valid ? `${rungs.length} rungs` : "ladder invalid"}</span>
      </div>
      {!l.valid && l.reasons.length > 0 && <div className="pb-list-note" style={{ color: "var(--warn)" }}>{l.reasons.join("; ")}</div>}
      <div className="pb-list">
        <div className="pb-mm-row pb-mm-rung pb-label" style={{ paddingTop: "var(--sp-2)", paddingBottom: "var(--sp-2)" }}>
          <span>Date</span><span>Rung</span><span style={{ textAlign: "right" }}>Bid</span><span style={{ textAlign: "right" }}>Ask</span>
        </div>
        {rungs.map((r) => (
          <div key={r.id} className="pb-mm-row pb-mm-rung">
            <span className="pb-num" style={{ fontSize: "var(--fs-13)" }}>
              {r.date ?? "undated"}
              {r.year_corrected && <span className="pb-tag pb-tag-warn" title={`Year re-derived (${r.year_source ?? "creation date"}); the inherited rule read it differently.`} style={{ marginLeft: 4 }}>year fixed</span>}
            </span>
            <span className="pb-pretty" style={{ fontSize: "var(--fs-13)", minWidth: 0 }}>{r.question}</span>
            <span className="pb-num" style={{ textAlign: "right", fontSize: "var(--fs-13)" }}>{pct(r.best_bid)}</span>
            <span className="pb-num" style={{ textAlign: "right", fontSize: "var(--fs-13)" }}>{pct(r.best_ask)}</span>
          </div>
        ))}
      </div>
      {l.pairs.length > 0 && (
        <div className="pb-list" style={{ borderTop: "1px solid var(--border-strong)" }}>
          <div className="pb-label" style={{ padding: "var(--sp-3) var(--sp-5) var(--sp-1)" }}>Adjacent pairs: sell the earlier rung at its bid, buy the later rung at its ask</div>
          {l.pairs.map((p) => <PairRow key={`${p.rich}-${p.cheap}`} p={p} valid={l.valid} mech={mech} richQ={q(p.rich)?.question ?? p.rich} cheapQ={q(p.cheap)?.question ?? p.cheap} />)}
        </div>
      )}
    </section>
  );
}

function PairRow({ p, valid, mech, richQ, cheapQ }: { p: LadderPair; valid: boolean; mech: Mechanism | null; richQ: string; cheapQ: string }) {
  const [open, setOpen] = useState(false);
  const [showChecks, setShowChecks] = useState(false);
  const st = pairState(p, valid);
  const tag = STATE_TAG[st];
  const plan = actionPlan(mech);
  const canPropose = st === "actionable" && plan.propose;
  return (
    <div className={st === "actionable" ? "pb-mm-hl" : undefined} data-testid={`pair-${st}`}>
      <div className="pb-mm-row pb-mm-pair">
        <div style={{ minWidth: 0, fontSize: "var(--fs-13)" }}>
          <span className="pb-num">{p.rich_date ?? "?"} → {p.cheap_date ?? "?"}</span>{" "}
          <button type="button" className="pb-chip pb-chip-sm" data-on={showChecks} onClick={() => setShowChecks((x) => !x)}>
            nesting {p.nested ? "pass" : "fail"} ({p.checks.filter((c) => c.ok).length}/{p.checks.length})
          </button>
          {!p.nested && p.reasons.length > 0 && <div className="pb-small" style={{ color: "var(--warn)", marginTop: 2 }}>{p.reasons.join("; ")}</div>}
        </div>
        <div className="pb-num" style={{ fontSize: "var(--fs-13)" }}>
          bid {pct(p.bid_rich)} / ask {pct(p.ask_cheap)}
          <div className="pb-small">{pairGapText(p)}</div>
          {p.engine && <div className="pb-small" data-testid="pair-engine" style={{ color: p.engine.source === "engine" ? undefined : "var(--warn)" }}>{engineLine(p.engine, mech)}</div>}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
          <span className={`pb-tag pb-tag-${tag.tone}`}>{tag.text}</span>
          {canPropose && !open && <button type="button" className="pb-btn pb-btn-sm pb-btn-secondary" onClick={() => setOpen(true)}>Draft proposal</button>}
        </div>
      </div>
      {showChecks && (
        <div className="pb-list-note" style={{ paddingTop: 0 }}>
          {p.checks.map((c) => (
            <div key={c.check} className="pb-small"><span style={{ color: c.ok ? "var(--up-ink)" : "var(--down-ink)" }}>{c.ok ? "pass" : "fail"}</span> · {c.check}{c.detail ? `: ${c.detail}` : ""}</div>
          ))}
        </div>
      )}
      {open && (
        <div style={{ padding: "0 var(--sp-5) var(--sp-4)" }}>
          <ProposalPanel plan={plan} mechanism={mech} title="Ladder pair proposal" onClose={() => setOpen(false)} lines={[
            `Sell YES on the earlier rung at ${pct(p.bid_rich)}: ${richQ}`,
            `Buy YES on the later rung at ${pct(p.ask_cheap)}: ${cheapQ}`,
            `Edge after one tick and both fees: ${pairGapText(p)}. Held to resolution.`,
            ...(p.engine?.sizes ? [`Size per leg (C++ ladder_pair): ${p.engine.sizes.rich} / ${p.engine.sizes.cheap} contracts.`] : []),
            ...(p.engine ? [engineLine(p.engine, mech)!] : []),
          ]} />
        </div>
      )}
    </div>
  );
}
