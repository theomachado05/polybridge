"use client";

import { useEffect, useState } from "react";
import { approveStaged, cancelStaged, getBridge, getClosedOpportunity, type BridgeSummary, type ClosedOpportunityOut } from "@/lib/api";
import {
  appendTimeline, bandText, closedHeadline, currentGap, executionText, fmtBp, fmtEt, fmtPp, gapBadge, hedgeAView, mergeOrders,
  opportunityView, pnlRows, pnlTotals, sessionClosed, sessionPill, splitOrders, stagedActions, stagedStatusText, timelineTitle,
  type GapView, type SessionView, type StagedOrder, type TimelineRow,
} from "@/lib/closed";
import { fmtMoney } from "@/lib/fmt";
import type { StreamState } from "@/lib/useBridgeStream";
import { Btn, Switch, Tag } from "@/components/pb";
import { SectionHead } from "./parts";
import { stagedBadges } from "@/lib/risk";

const v = { fontSize: "var(--fs-20)", fontWeight: 600, marginTop: "var(--sp-1)", color: "var(--ink)" } as const;
const small = { fontSize: "var(--fs-12)", color: "var(--faint)", lineHeight: 1.5, marginTop: "var(--sp-1)" } as const;
const pad = { padding: "var(--sp-5)", minWidth: 0 } as const;
const rule = "1px solid var(--border)";
const signColor = (n: number) => (n >= 0 ? "var(--up)" : "var(--down)");

export function GapBadge({ gap }: { gap: GapView | null }) {
  const b = gapBadge(gap);
  return <Tag tone={b.validated ? "measured" : "caution"} title={b.reason}>{b.text}</Tag>;
}

export function ClosedBanner({ session, replay, hold }: { session: SessionView | null; replay: boolean; hold: boolean }) {
  const head = closedHeadline(session);
  const pill = sessionPill(session);
  if (!head || !session) return null;
  return (
    <div role="status" data-testid="closed-banner" className="pb-card" style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)", flexWrap: "wrap", padding: "var(--sp-3) var(--sp-4)" }}>
      {pill && <span className="pb-tag pb-tag-warn" title={pill.title}>{pill.text}</span>}
      <span style={{ fontSize: "var(--fs-14)", fontWeight: 500, color: "var(--ink)" }}>{head}</span>
      <span className="pb-small" style={{ marginLeft: "auto", display: "inline-flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
        {hold && <Tag tone="neutral" title="The regular session is closed, so the equity algo stops and sends no equity orders. Hedge B (staged order) covers the open.">equity algo holds</Tag>}
        {replay ? <Tag tone="replay" title="The session comes from the recorded time of the replayed tick.">replay time: {fmtEt(session.at, true)}</Tag> : <span className="pb-num">{fmtEt(session.at)}</span>}
      </span>
    </div>
  );
}

function useSummary(id: string, initial: BridgeSummary | null, running: boolean, bump: number): BridgeSummary | null {
  const [data, setData] = useState<BridgeSummary | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => getBridge(id).then((d) => alive && setData(d), () => {});
    load();
    const t = running ? setInterval(load, 3000) : undefined;
    return () => { alive = false; clearInterval(t); };
  }, [id, running, bump]);
  return data ?? initial;
}

export function WeekendPanel({ id, summary, st, replay, ticker }: { id: string; summary: BridgeSummary | null; st: StreamState; replay: boolean; ticker: string | null }) {
  const [bump, setBump] = useState(0);
  const [local, setLocal] = useState<Record<string, StagedOrder>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [research, setResearch] = useState(false);
  const running = st.status === "running" || st.status === "connecting" || st.status === "reconnecting";
  const summ = useSummary(id, summary, running, bump);
  const cm = summ?.closed_mode ?? null;

  const session = st.closed?.session ?? summ?.session ?? null;
  const closure = st.closed?.closure ?? summ?.closure ?? null;
  const closed = sessionClosed(session);
  const { gap, past: gapIsPast } = currentGap((st.closed?.expected_gap ?? summ?.expected_gap) as Record<string, unknown> | null,
    cm?.last_expected_gap as Record<string, unknown> | null, closed, closure?.since);
  const orders = mergeOrders(cm?.staged_orders, cm?.plan ? [cm.plan] : null, st.staged, local);
  const timeline = (cm?.timeline ?? []).reduce<TimelineRow[]>((a, r) => appendTimeline(a, r), st.timeline)
    .sort((a, b) => a.at.localeCompare(b.at));
  const split = splitOrders(orders);
  const ha = hedgeAView(st.hedgeA ?? summ?.hedge_a);
  const pnl = cm?.pnl ?? null;
  const rows = pnlRows(pnl);
  const holds = st.reasons.session_closed ?? cm?.holds ?? 0;

  if (!closed && !orders.length && !timeline.length) return null;

  const act = async (o: StagedOrder, what: "approve" | "cancel") => {
    setBusy(o.id); setErr(null);
    try {
      const r = what === "approve" ? await approveStaged(o.id, o.qty) : await cancelStaged(o.id);
      setLocal((m) => ({ ...m, [r.id]: r }));
      setBump((n) => n + 1);
    } catch (e) {
      setErr(`The system did not ${what === "approve" ? "approve" : "cancel"} the plan: ${e instanceof Error ? e.message : String(e)}. Try again.`);
    } finally { setBusy(null); }
  };
  const labels = cm?.labels ?? null;
  const opp = opportunityView(labels?.opportunity);

  return (
    <section data-testid="weekend-panel" style={{ minWidth: 0 }}>
      <SectionHead title={`Closed-market mode: ${closed ? "equities closed" : "after the open"}`}>
        <GapBadge gap={gap} />
        {replay && <Tag tone="replay" title="Recorded weekend. The prices and times come from the recording.">replay</Tag>}
      </SectionHead>
      <div className="pb-card">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,220px),1fr))" }}>
          <div style={pad}>
            <div className="pb-label">PM move since the close</div>
            <div className="pb-num" style={v}>{fmtPp(closure?.pm_move_pp)}</div>
            <div className="pb-num" style={small}>{closure?.p_close != null && closure?.p_now != null ? `YES ${(closure.p_close * 100).toFixed(1)}¢ to ${(closure.p_now * 100).toFixed(1)}¢` : closure?.status ? closure.status.replaceAll("_", " ").toLowerCase() : "no closure yet"}{closure?.since ? `, since ${fmtEt(closure.since)}` : ""}</div>
          </div>
          <div style={{ ...pad, borderLeft: rule }}>
            <div className="pb-label">{gapIsPast ? "Expected open gap (before the open)" : "Expected open gap"}{ticker ? `, ${gap?.basis_ticker ?? ticker}` : ""}</div>
            <div className="pb-num" style={{ ...v, color: gap?.bp == null ? "var(--faint)" : signColor(gap.bp) }}>{fmtBp(gap?.bp)}</div>
            <div className="pb-num" style={small}>{bandText(gap)}</div>
          </div>
          <div style={{ ...pad, borderLeft: rule }}>
            <div className="pb-label">Equity algo</div>
            <div style={v}>{closed ? "Holds" : "Trades"}</div>
            <div style={small}>{closed ? `The session is closed, so the algo sends no equity orders${holds ? ` (${holds.toLocaleString("en-US")} ticks held)` : ""}.` : "Regular session. The algo controls the hedge, with the staged fills."}</div>
          </div>
        </div>
        <div className="pb-small pb-pretty" style={{ padding: "var(--sp-3) var(--sp-5)", borderTop: rule, background: "var(--surface-2)" }}>
          <span style={{ fontWeight: 600, color: "var(--ink)" }}>{gapBadge(gap).validated ? "Validated: " : "Unvalidated estimate: "}</span>{gapBadge(gap).reason}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,400px),1fr))", borderTop: rule }}>
          <div style={pad}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap" }}>
              <h3 className="pb-h4" style={{ fontSize: "var(--fs-14)" }}>Staged orders: hedge B (default)</h3>
              <Tag tone={split.active.some((o) => o.status === "staged") ? "caution" : "sim"} title={labels?.hedge_b?.label ?? "The order executes only after you approve it, at the next tradable session."}>{split.active.some((o) => o.status === "staged") ? "waits for your approval" : "executes only after approval"}</Tag>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)", marginTop: "var(--sp-3)" }}>
              {st.refusal && (
                <div role="status" data-testid="evidence-refusal" className="pb-small pb-pretty" style={{ color: "var(--warn-ink)" }}>
                  <Tag tone="caution" title={st.refusal.detail ?? undefined}>evidence gate: no plan</Tag>{" "}
                  The evidence gate refused a plan on this market ({st.refusal.reason}){st.refusal.detail ? `: ${st.refusal.detail}.` : "."} To stage a plan anyway, start a bridge with the override (Weekend mode on Build). Then approve it with the acknowledgement.
                </div>
              )}
              {split.active.length === 0 && split.folded === 0 && !st.refusal && <div className="pb-small">{cm?.plan_note ? `No plan: ${cm.plan_note}` : "No plan yet. When the expected gap is 10 bp or more against the position, the system stages a plan for your approval."}</div>}
              {split.active.map((o) => {
                const a = stagedActions(o);
                const g = o.current?.gap_bp ?? o.estimate?.gap_bp;
                const wait = busy === o.id;
                return (
                  <div key={o.id} style={{ padding: "var(--sp-4)", borderRadius: "var(--radius-sm)", background: "var(--surface-2)", border: rule, minWidth: 0 }} data-testid="staged-order">
                    <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap" }}>
                      <span className={`pb-tag ${o.side === "buy" ? "pb-tag-up" : "pb-tag-down"}`}>{o.side === "buy" ? "Buy" : "Sell"}</span>
                      <span className="pb-num" style={{ fontWeight: 600, color: "var(--ink)" }}>{o.qty.toLocaleString("en-US")} <span className="pb-ticker">{o.ticker ?? ticker ?? ""}</span></span>
                      <span className="pb-small">{stagedStatusText(o)}</span>
                      {stagedBadges(o).map((b) => <Tag key={b.text} tone={b.tone} title={b.title}>{b.text}</Tag>)}
                    </div>
                    <div className="pb-pretty" style={{ ...small, marginTop: "var(--sp-2)" }}>Executes at {executionText(o)}{o.session_target === "pre_market" ? " (the broker supports extended hours, but the R1 evidence is for the 09:30 order)" : ""}.{g != null ? ` The size comes from an expected gap of ${fmtBp(g)}${o.estimate?.status ? ` (${o.estimate.status})` : ""}.` : ""}</div>
                    {(a.approve || a.cancel) && (
                      <div style={{ display: "flex", gap: "var(--sp-2)", flexWrap: "wrap", marginTop: "var(--sp-3)" }}>
                        {a.approve && <Btn size="sm" kind={wait ? "disabled" : "primary"} onClick={() => act(o, "approve")}>{wait ? "Wait" : "Approve plan"}</Btn>}
                        {a.cancel && <Btn size="sm" kind={wait ? "disabled" : "secondary"} onClick={() => act(o, "cancel")}>Cancel plan</Btn>}
                      </div>
                    )}
                  </div>
                );
              })}
              {split.folded > 0 && <div style={{ ...small, marginTop: 0 }} title="The backend replaced these plans when the PM move changed. It cancels a plan when the move reverts. It skips a plan when the position already has a hedge.">Earlier plans in this closure: {split.foldedText}.</div>}
              {err && <div role="alert" className="pb-small" style={{ color: "var(--down)" }}>{err}</div>}
              <div className="pb-pretty" style={{ ...small, marginTop: 0 }}>{labels?.hedge_b?.label ?? "Hedge B is an equity order staged for the first tradable time. The system sends it only after you approve it. It works by timing, not direction, and cannot remove the gap."}</div>
            </div>

            {ha && (
              <div style={{ marginTop: "var(--sp-4)", paddingTop: "var(--sp-4)", borderTop: rule }} data-testid="hedge-a">
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ fontSize: "var(--fs-13)", fontWeight: 600, color: "var(--ink)" }}>{ha.title}</span>
                  <Tag tone="caution" title={ha.label}>estimate, simulated</Tag>
                </div>
                <div className="pb-num" style={small}>{ha.contracts.toLocaleString("en-US", { maximumFractionDigits: 0 })} adverse-YES contracts (≈ {Math.round(ha.equivShares).toLocaleString("en-US")} sh equivalent){ha.pnl != null ? `, ${fmtMoney(ha.pnl, true)} (estimate)` : ""}</div>
                <div className="pb-pretty" style={small}>{ha.label}</div>
              </div>
            )}
          </div>

          <div style={{ ...pad, borderLeft: rule }}>
            <h3 className="pb-h4" style={{ fontSize: "var(--fs-14)" }}>Handoff timeline</h3>
            <ol style={{ listStyle: "none", margin: "var(--sp-3) 0 0", padding: 0, display: "flex", flexDirection: "column" }}>
              {timeline.length === 0 && <li className="pb-small">No events yet. The timeline starts at the close.</li>}
              {(timeline.length > 10 ? [timeline[0], ...timeline.slice(-9)] : timeline).map((r) => (
                <li key={`${r.at}:${r.event}:${r.staged_id ?? ""}`} style={{ display: "grid", gridTemplateColumns: "96px minmax(0,1fr)", gap: "var(--sp-3)", padding: "var(--sp-2) 0" }}>
                  <span className="pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--faint)", paddingTop: 1 }}>{fmtEt(r.at)}</span>
                  <div style={{ minWidth: 0, paddingLeft: "var(--sp-3)", borderLeft: rule }}>
                    <div style={{ fontSize: "var(--fs-13)", fontWeight: 500, color: "var(--ink)" }}>{timelineTitle(r.event)}</div>
                    {r.detail && <div className="pb-pretty" style={small}>{r.detail}</div>}
                  </div>
                </li>
              ))}
            </ol>

            {rows.length > 0 && pnl && (
              <div style={{ marginTop: "var(--sp-5)", paddingTop: "var(--sp-4)", borderTop: rule }}>
                <h3 className="pb-h4" style={{ fontSize: "var(--fs-14)" }}>P&amp;L since the close, compared to no hedge</h3>
                <div style={{ marginTop: "var(--sp-2)" }}>
                  {rows.map((r) => (
                    <div key={r.k} style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", fontSize: "var(--fs-13)", padding: "var(--sp-1) 0" }}>
                      <span style={{ color: "var(--text-2)" }}>{r.k}{r.note ? <span style={{ color: "var(--faint)" }}> ({r.note})</span> : null}</span>
                      <span className="pb-num" style={{ color: signColor(r.v) }}>{fmtMoney(r.v, true)}</span>
                    </div>
                  ))}
                  {pnlTotals(pnl).map((t, i) => (
                    <div key={t.k} data-testid="pnl-total" style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", fontSize: "var(--fs-13)", fontWeight: i === 0 ? 600 : 500, color: i === 0 ? "var(--ink)" : "var(--warn)", padding: i === 0 ? "var(--sp-2) 0 0" : "var(--sp-1) 0 0", borderTop: i === 0 ? rule : undefined, marginTop: i === 0 ? "var(--sp-1)" : 0 }}>
                      <span>{t.k}</span>
                      <span className="pb-num" style={{ color: signColor(t.v) }}>{fmtMoney(t.v, true)}</span>
                    </div>
                  ))}
                  <div className="pb-pretty" style={{ ...small, marginTop: "var(--sp-2)" }}>Prices: {pnl.price_source} (<span className="pb-num">{pnl.s_close.toFixed(2)}</span> to <span className="pb-num">{pnl.s_now.toFixed(2)}</span>). {pnl.note}</div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div style={{ padding: "var(--sp-4) var(--sp-5)", borderTop: rule }}>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)", flexWrap: "wrap" }}>
            <Switch on={research} onClick={() => setResearch((x) => !x)} label="Research" />
            <span style={{ fontSize: "var(--fs-13)", fontWeight: 600, color: "var(--ink)" }}>Research</span>
            <span className="pb-small">Opportunity at the open compares options with the weekend PM move. Research only, not a trade.</span>
          </div>
          {research && <OpportunityResearch title={opp.title} text={opp.text} />}
        </div>
      </div>
    </section>
  );
}

function OpportunityResearch({ title, text }: { title: string; text: string }) {
  const [d, setD] = useState<ClosedOpportunityOut | null>(null);
  const [e, setE] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getClosedOpportunity().then((x) => alive && setD(x), (x) => alive && setE(x instanceof Error ? x.message : String(x)));
    return () => { alive = false; };
  }, []);
  const view = opportunityView({ label: text }, d?.research);
  return (
    <div style={{ marginTop: "var(--sp-4)", paddingTop: "var(--sp-4)", borderTop: rule, minWidth: 0 }} data-testid="opportunity-research">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: "var(--fs-13)", fontWeight: 600, color: "var(--ink)" }}>{title}</span>
        <span style={{ display: "inline-flex", gap: "var(--sp-2)" }}>
          <Tag tone="neutral" title={d?.research?.status ? `GET /closed/opportunity research status: ${d.research.status}` : undefined}>{view.verdict}</Tag>
          <Tag tone="caution">research only, not a trade</Tag>
        </span>
      </div>
      <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>{view.text}</div>
      {e && <div style={small}>The research status is not available ({e}). The card shows the committed R3 result.</div>}
    </div>
  );
}
