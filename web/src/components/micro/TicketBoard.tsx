"use client";

import { useState } from "react";
import Link from "next/link";
import { getTickets } from "@/lib/api";
import { useAsync, useRetry } from "@/lib/hooks";
import {
  fmtSigned, mechanismById, mechanismFor, pct, referenceClosed, ticketActions, ticketField, ticketGap, ticketReference,
  ticketStrikes, touchProposal, engineLine, type Band, type Mechanism, type Registry, type Ticket,
} from "@/lib/micro";
import { Unavailable } from "@/components/pb";
import { ProposalPanel, StatusTag } from "./parts";

const band = (b: Band | null | undefined) => (b && b.mid != null ? `${pct(b.mid)} [${pct(b.lo)}, ${pct(b.hi)}]` : "—");

export function TicketBoard({ reg }: { reg: Registry | null }) {
  const [n, retry] = useRetry();
  const t = useAsync(`tickets:${n}`, getTickets);
  const d = t.data;
  const touch = mechanismFor(reg, "touch_ticket");
  const close = mechanismFor(reg, "close_above_ticket");
  const closeRef = mechanismById(reg, reg?.reference_for?.close_above_ticket ?? "");
  const rows = d?.ok ? [...d.tickets].sort((a, b) => Number(b.linkable) - Number(a.linkable) || (a.type < b.type ? 1 : -1)) : [];
  const touchRows = rows.filter((r) => r.type === "touch_ticket");
  const closeRows = rows.filter((r) => r.type !== "touch_ticket");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-5)" }}>
      {t.loading && <div className="pb-small">Reading open tickets, linking them to option contracts and pricing the reference…</div>}
      {t.error && <Unavailable what="The ticket board (GET /tickets)" error={t.error} onRetry={retry} />}
      {d && !d.ok && <Unavailable what="The ticket board (GET /tickets)" error={d.error} onRetry={retry} />}
      {d?.ok && (
        <div className="pb-small pb-num" style={{ display: "flex", gap: "var(--sp-4)", flexWrap: "wrap", alignItems: "center" }}>
          <span>{d.counts?.tickets ?? rows.length} tickets</span>
          <span>{d.counts?.linked ?? 0} linked to option contracts</span>
          {d.as_of && <span>as of {d.as_of.replace("T", " ").slice(0, 19)} UTC{d.stale ? " (cached)" : ""}</span>}
          <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={retry}>Refresh</button>
        </div>
      )}
      {d?.ok && d.hedge && <div className="pb-small" data-testid="no-hedge" style={{ color: "var(--text-2)" }}>Hedge: {d.hedge}.</div>}
      {d?.ok && (
        <>
          <Section title="Touch tickets" mech={touch} rows={touchRows} reg={reg} />
          <Section title="Close-above tickets" mech={close} rows={closeRows} reg={reg} refOnly={closeRef} />
        </>
      )}
    </div>
  );
}

function Section({ title, mech, rows, reg, refOnly }: {
  title: string; mech: Mechanism | null; rows: Ticket[]; reg: Registry | null; refOnly?: Mechanism | null;
}) {
  return (
    <section className="pb-card" style={{ overflow: "hidden" }} aria-label={title}>
      <div style={{ padding: "var(--sp-4) var(--sp-5)", display: "flex", gap: "var(--sp-3)", alignItems: "center", flexWrap: "wrap", borderBottom: "1px solid var(--border)" }}>
        <h2 className="pb-h4" style={{ margin: 0 }}>{title}</h2>
        <StatusTag m={mech} />
        {mech && <Link href={`/tested#${mech.id}`} className="pb-small" style={{ color: "var(--accent)" }}>evidence</Link>}
      </div>
      {mech && <div className="pb-list-note pb-pretty">{mech.actions_allowed.text}</div>}
      {refOnly && (
        <div className="pb-list-note pb-pretty" data-testid="reference-only">
          The finish-beyond reference on these rows is for information only, not a trade signal. Why options are the
          reference: <Link href={`/tested#${refOnly.id}`} style={{ color: "var(--accent)" }}>{refOnly.name}</Link>.
        </div>
      )}
      <div className="pb-list">
        <div className="pb-mm-row pb-mm-ticket pb-label" style={{ paddingTop: "var(--sp-2)", paddingBottom: "var(--sp-2)" }}>
          <span>Ticket · linked contracts</span><span>Polymarket bid / ask</span><span>Options reference</span><span style={{ textAlign: "right" }}>Gap</span>
        </div>
        {!rows.length && <div className="pb-list-note">No open ticket of this type right now.</div>}
        {rows.map((r) => <TicketRow key={r.id} t={r} reg={reg} />)}
      </div>
    </section>
  );
}

function TicketRow({ t, reg }: { t: Ticket; reg: Registry | null }) {
  const [open, setOpen] = useState(false);
  const { plan, mechanism } = ticketActions(t, reg);
  const ref = t.reference;
  const b = ticketReference(t);
  const gap = ticketGap(t);
  const prop = plan.propose ? touchProposal(t, reg) : null;
  const touch = t.type === "touch_ticket";
  const under = ticketField(t, "underlying") ?? ticketField(t, "ticker");
  const lvl = ticketField(t, "level");
  const dir = ticketField(t, "direction");
  const end = ticketField(t, "window_end");
  return (
    <div data-testid={`ticket-${t.type}`}>
      <div className="pb-mm-row pb-mm-ticket">
        <div style={{ minWidth: 0 }}>
          <div className="pb-pretty" style={{ fontSize: "var(--fs-13)", fontWeight: 500 }}>{t.question}</div>
          <div className="pb-small pb-num">{[under, lvl && `${dir === "down" ? "≤" : "≥"} ${lvl}`, end && `by ${end}`].filter(Boolean).join(" · ")}</div>
          <div className="pb-small pb-num" style={{ color: t.contract?.ok ? undefined : "var(--warn)" }}>{ticketStrikes(t.contract)}</div>
          {!t.linkable && t.reasons.length > 0 && <div className="pb-small" style={{ color: "var(--warn)" }}>{t.reasons.join("; ")}</div>}
        </div>
        <div className="pb-num" style={{ fontSize: "var(--fs-13)" }}>{pct(t.best_bid)} / {pct(t.best_ask)}</div>
        <div style={{ fontSize: "var(--fs-13)", minWidth: 0 }}>
          {b ? (
            <>
              <div className="pb-num">{touch ? "touch" : t.reference_only ? "finish beyond (reference only)" : "finish beyond"} {band(b)}</div>
              {touch && <div className="pb-small pb-num">finish beyond {band(ref?.finish_beyond)}</div>}
              <div className="pb-small" style={{ color: referenceClosed(ref) ? "var(--warn)" : undefined }}>
                {ref?.session_label ?? (ref?.as_of ? `as of ${ref.as_of}` : "")}
              </div>
              {ref?.as_of && ref.session_label && <div className="pb-small pb-num">as of {ref.as_of}</div>}
            </>
          ) : (
            <div className="pb-small" style={{ color: "var(--warn)" }}>{ref?.reason ? `no reference: ${ref.reason}` : "no reference"}</div>
          )}
        </div>
        <div style={{ textAlign: "right", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          {gap ? (
            <>
              <span className="pb-num" style={{ fontWeight: 600 }}>{fmtSigned(gap.mid, 1)} pts</span>
              <span className="pb-small pb-num">[{fmtSigned(gap.lo, 1)}, {fmtSigned(gap.hi, 1)}]</span>
            </>
          ) : <span className="pb-small">—</span>}
          {t.engine && <span className="pb-small" data-testid="ticket-engine" style={{ color: t.engine.source === "engine" ? undefined : "var(--warn)" }}>{engineLine(t.engine, mechanism)}</span>}
          {prop && !open && (
            <button type="button" className="pb-btn pb-btn-sm pb-btn-secondary" onClick={() => setOpen(true)}>Draft proposal (Sell YES)</button>
          )}
        </div>
      </div>
      {open && prop && (
        <div style={{ padding: "0 var(--sp-5) var(--sp-4)" }}>
          <ProposalPanel plan={plan} mechanism={mechanism} title="Ticket proposal" onClose={() => setOpen(false)} lines={[
            `Sell YES at the bid ${pct(prop.price)}: ${t.question}`,
            `The bid is ${fmtSigned(prop.gapPoints, 1)} pts above the touch reference mid; the tested rule needs ${prop.threshold}+ pts.`,
            `Polymarket ${pct(t.best_bid)} / ${pct(t.best_ask)} against the ${touch ? "touch" : "finish-beyond"} reference ${band(b)}${ref?.session_label ? ` (${ref.session_label})` : ""}.`,
            `Linked contracts: ${ticketStrikes(t.contract)} (reference only, not a hedge).`,
          ]} />
        </div>
      )}
    </div>
  );
}
