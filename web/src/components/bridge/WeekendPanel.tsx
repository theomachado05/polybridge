"use client";

// Closed-market mode on the Bridge screen (docs/design.md, section 2): the closed-market
// banner, and the weekend panel (PM move since the close, the evidence-gated expected gap, staged hedge B with
// Approve plan / Cancel, the handoff timeline, hedge A only when opted in, and the research-only Opportunity card).
import { useEffect, useState } from "react";
import { approveStaged, cancelStaged, getBridge, getClosedOpportunity, type BridgeSummary, type ClosedOpportunityOut } from "@/lib/api";
import {
  appendTimeline, bandText, closedHeadline, currentGap, executionText, fmtBp, fmtEt, fmtPp, gapBadge, hedgeAView, mergeOrders,
  opportunityView, pnlRows, pnlTotals, sessionClosed, sessionPill, splitOrders, stagedActions, stagedStatusText, timelineTitle,
  type GapView, type SessionView, type StagedOrder, type TimelineRow,
} from "@/lib/closed";
import { fmtMoney } from "@/lib/fmt";
import type { StreamState } from "@/lib/useBridgeStream";
import { Glass, Label, Switch, Tag, upColor } from "@/components/pb";
import { stagedBadges } from "@/lib/risk";

const sub = { padding: "12px 0", minWidth: 0 } as const;
const k = { fontSize: 11, color: "#5A627A" } as const;
const v = { fontSize: 18, fontWeight: 600, letterSpacing: "-.02em", marginTop: 2 } as const;
const small = { fontSize: 11.5, color: "#5A627A", lineHeight: 1.45, marginTop: 3 } as const;
const pillBtn = (dark: boolean) => ({ padding: "6px 12px", borderRadius: 999, fontSize: 12, fontWeight: 600, cursor: "pointer", border: dark ? 0 : "1px solid rgba(15,22,38,.14)", background: dark ? "#0F1626" : "rgba(255,255,255,.7)", color: dark ? "#fff" : "#0F1626" });

export function GapBadge({ gap }: { gap: GapView | null }) {
  const b = gapBadge(gap);
  return <Tag tone={b.validated ? "measured" : "caution"} title={b.reason}>{b.text}</Tag>;
}

/** U1: "Market closed · reopens Mon 09:30 ET / pre-market 04:00", with the session pill. A replay shows its recorded
 *  time (a replayed Saturday is a Saturday); a live bridge, the wall clock. */
export function ClosedBanner({ session, replay, hold }: { session: SessionView | null; replay: boolean; hold: boolean }) {
  const head = closedHeadline(session);
  const pill = sessionPill(session);
  if (!head || !session) return null;
  return (
    <div role="status" data-testid="closed-banner" className="pb-glass" style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", padding: "14px 20px", borderRadius: 22 }}>
      {pill && <span title={pill.title} style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "5px 12px", borderRadius: 999, background: "#0F1626", color: "#fff", fontSize: 12, fontWeight: 600 }}><span aria-hidden="true" style={{ width: 7, height: 7, borderRadius: "50%", background: pill.dot }} />{pill.text}</span>}
      <span className="pb-serif" style={{ fontSize: 22, letterSpacing: "-.01em" }}>{head}</span>
      <span style={{ fontSize: 12, color: "#5A627A", marginLeft: "auto", display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {hold && <Tag tone="neutral" title="The regular session is closed, so the equity algo stops and sends no equity orders. Hedge B (staged order) covers the open.">equity algo holds</Tag>}
        {replay ? <Tag tone="replay" title="The session comes from the recorded time of the replayed tick.">replay time: {fmtEt(session.at, true)}</Tag> : <span>{fmtEt(session.at)}</span>}
      </span>
    </div>
  );
}

/** The bridge summary, re-read while the bridge runs (staged orders, timeline, P&L live there) and after an action. */
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
  // After the open the gap service has no active gap: show the one it expected (kept by the backend), labelled so.
  // While closed, that kept gap counts only if it belongs to this closure (the backend does not clear it).
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
    <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
      <div data-testid="weekend-panel" style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Label>Closed-market mode: {closed ? "equities closed" : "after the open"}</Label>
        <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <GapBadge gap={gap} />
          {replay && <Tag tone="replay" title="Recorded weekend. The prices and times come from the recording.">replay</Tag>}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: 10, marginTop: 14 }}>
        <div style={sub}>
          <div style={k}>PM move since the close</div>
          <div className="pb-tab" style={v}>{fmtPp(closure?.pm_move_pp)}</div>
          <div style={small}>{closure?.p_close != null && closure?.p_now != null ? `YES ${(closure.p_close * 100).toFixed(1)}¢ to ${(closure.p_now * 100).toFixed(1)}¢` : closure?.status ? closure.status.replaceAll("_", " ").toLowerCase() : "no closure yet"}{closure?.since ? `, since ${fmtEt(closure.since)}` : ""}</div>
        </div>
        <div style={sub}>
          <div style={k}>{gapIsPast ? "Expected open gap (before the open)" : "Expected open gap"}{ticker ? `, ${gap?.basis_ticker ?? ticker}` : ""}</div>
          <div className="pb-tab" style={{ ...v, color: gap?.bp == null ? "#8A92A8" : upColor(gap.bp) }}>{fmtBp(gap?.bp)}</div>
          <div style={small}>{bandText(gap)}</div>
        </div>
        <div style={sub}>
          <div style={k}>Equity algo</div>
          <div style={v}>{closed ? "Holds" : "Trades"}</div>
          <div style={small}>{closed ? `The session is closed, so the algo sends no equity orders${holds ? ` (${holds.toLocaleString("en-US")} ticks held)` : ""}.` : "Regular session. The algo controls the hedge, with the staged fills."}</div>
        </div>
      </div>
      <div className="pb-pretty" style={{ fontSize: 12, color: "#3C4458", lineHeight: 1.5, marginTop: 10 }}>
        <span style={{ fontWeight: 600 }}>{gapBadge(gap).validated ? "Validated: " : "Unvalidated estimate: "}</span>{gapBadge(gap).reason}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))", gap: 16, marginTop: 18 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <Label>Staged orders: hedge B (default)</Label>
            <Tag tone={split.active.some((o) => o.status === "staged") ? "caution" : "sim"} title={labels?.hedge_b?.label ?? "The order executes only after you approve it, at the next tradable session."}>{split.active.some((o) => o.status === "staged") ? "waits for your approval" : "executes only after approval"}</Tag>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
            {st.refusal && (
              <div role="status" data-testid="evidence-refusal" style={{ fontSize: 12.5, color: "#9A4A00", lineHeight: 1.45 }}>
                <Tag tone="caution" title={st.refusal.detail ?? undefined}>evidence gate: no plan</Tag>{" "}
                The evidence gate refused a plan on this market ({st.refusal.reason}){st.refusal.detail ? `: ${st.refusal.detail}.` : "."} To stage a plan anyway, start a bridge with the override (Weekend mode on Build). Then approve it with the acknowledgement.
              </div>
            )}
            {split.active.length === 0 && split.folded === 0 && !st.refusal && <div style={{ fontSize: 12.5, color: "#5A627A" }}>{cm?.plan_note ? `No plan: ${cm.plan_note}` : "No plan yet. When the expected gap is 10 bp or more against the position, the system stages a plan for your approval."}</div>}
            {split.active.map((o) => {
              const a = stagedActions(o);
              const g = o.current?.gap_bp ?? o.estimate?.gap_bp;
              return (
                <div key={o.id} style={{ ...sub, borderTop: "1px solid rgba(15,22,38,.08)", display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 12, alignItems: "center" }} data-testid="staged-order">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: "-.01em" }}>
                      <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 999, fontSize: 10.5, color: "#fff", background: o.side === "buy" ? "#22A06B" : "#E0485A", marginRight: 8 }}>{o.side === "buy" ? "Buy" : "Sell"}</span>
                      {o.qty.toLocaleString("en-US")} {o.ticker ?? ticker ?? ""} <span style={{ color: "#5A627A", fontWeight: 400, marginLeft: 4 }}>{stagedStatusText(o)}</span>
                      {stagedBadges(o).map((b) => <span key={b.text} style={{ marginLeft: 6 }}><Tag tone={b.tone} title={b.title}>{b.text}</Tag></span>)}
                    </div>
                    <div style={small}>Executes at {executionText(o)}{o.session_target === "pre_market" ? " (the broker supports extended hours, but the R1 evidence is for the 09:30 order)" : ""}.{g != null ? ` The size comes from an expected gap of ${fmtBp(g)}${o.estimate?.status ? ` (${o.estimate.status})` : ""}.` : ""}</div>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                    {a.approve && <button type="button" style={pillBtn(true)} disabled={busy === o.id} onClick={() => act(o, "approve")}>{busy === o.id ? "Wait" : "Approve plan"}</button>}
                    {a.cancel && <button type="button" style={pillBtn(false)} disabled={busy === o.id} onClick={() => act(o, "cancel")}>Cancel plan</button>}
                  </div>
                </div>
              );
            })}
            {split.folded > 0 && <div style={{ ...small, marginTop: 0 }} title="The backend replaced these plans when the PM move changed. It cancels a plan when the move reverts. It skips a plan when the position already has a hedge.">Earlier plans in this closure: {split.foldedText}.</div>}
            {err && <div role="alert" style={{ fontSize: 12, color: "#C8323F" }}>{err}</div>}
            <div className="pb-pretty" style={{ ...small, marginTop: 2 }}>{labels?.hedge_b?.label ?? "Hedge B is an equity order staged for the first tradable time. The system sends it only after you approve it. It works by timing, not direction, and cannot remove the gap."}</div>
          </div>

          {ha && (
            <div style={{ ...sub, padding: "12px 14px", marginTop: 12, border: "1px dashed rgba(154,74,0,.35)", borderRadius: 12 }} data-testid="hedge-a">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{ha.title}</span>
                <Tag tone="caution" title={ha.label}>estimate, simulated</Tag>
              </div>
              <div style={small}>{ha.contracts.toLocaleString("en-US", { maximumFractionDigits: 0 })} adverse-YES contracts (≈ {Math.round(ha.equivShares).toLocaleString("en-US")} sh equivalent){ha.pnl != null ? `, ${fmtMoney(ha.pnl, true)} (estimate)` : ""}</div>
              <div className="pb-pretty" style={small}>{ha.label}</div>
            </div>
          )}
        </div>

        <div style={{ minWidth: 0 }}>
          <Label>Handoff timeline</Label>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 10 }}>
            {timeline.length === 0 && <div style={{ fontSize: 12.5, color: "#5A627A" }}>No events yet. The timeline starts at the close.</div>}
            {(timeline.length > 10 ? [timeline[0], ...timeline.slice(-9)] : timeline).map((r) => (
              <div key={`${r.at}:${r.event}:${r.staged_id ?? ""}`} style={{ display: "grid", gridTemplateColumns: "118px minmax(0,1fr)", gap: 12, padding: "8px 0", borderBottom: "1px solid rgba(15,22,38,.07)" }}>
                <span className="pb-mono" style={{ fontSize: 11, color: "#5A627A" }}>{fmtEt(r.at)}</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>{timelineTitle(r.event)}</div>
                  {r.detail && <div className="pb-pretty" style={{ ...small, marginTop: 1 }}>{r.detail}</div>}
                </div>
              </div>
            ))}
          </div>

          {rows.length > 0 && pnl && (
            <div style={{ marginTop: 14 }}>
              <Label>P&amp;L since the close, compared to no hedge</Label>
              <div style={{ marginTop: 8 }}>
                {rows.map((r) => (
                  <div key={r.k} style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12.5, padding: "4px 0" }}>
                    <span style={{ color: "#3C4458" }}>{r.k}{r.note ? <span style={{ color: "#5A627A" }}> ({r.note})</span> : null}</span>
                    <span className="pb-mono pb-tab" style={{ color: upColor(r.v) }}>{fmtMoney(r.v, true)}</span>
                  </div>
                ))}
                {pnlTotals(pnl).map((t, i) => (
                  <div key={t.k} data-testid="pnl-total" style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13, fontWeight: i === 0 ? 600 : 500, color: i === 0 ? undefined : "#9A4A00", padding: i === 0 ? "6px 0 0" : "3px 0 0", borderTop: i === 0 ? "1px solid rgba(15,22,38,.1)" : undefined, marginTop: i === 0 ? 4 : 0 }}>
                    <span>{t.k}</span>
                    <span className="pb-mono pb-tab" style={{ color: upColor(t.v) }}>{fmtMoney(t.v, true)}</span>
                  </div>
                ))}
                <div className="pb-pretty" style={small}>Prices: {pnl.price_source} ({pnl.s_close.toFixed(2)} to {pnl.s_now.toFixed(2)}). {pnl.note}</div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid rgba(15,22,38,.08)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Switch on={research} onClick={() => setResearch((x) => !x)} label="Research" />
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Research</span>
          <span style={{ fontSize: 12, color: "#5A627A" }}>Opportunity at the open compares options with the weekend PM move. Research only, not a trade.</span>
        </div>
        {research && <OpportunityResearch title={opp.title} text={opp.text} />}
      </div>
    </Glass>
  );
}

/** U5: the research card. It never offers an order: R3's net-of-cost gap is null. */
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
    <div style={{ ...sub, marginTop: 12, borderTop: "1px solid rgba(15,22,38,.08)" }} data-testid="opportunity-research">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{title}</span>
        <span style={{ display: "inline-flex", gap: 6 }}>
          <Tag tone="neutral" title={d?.research?.status ? `GET /closed/opportunity research status: ${d.research.status}` : undefined}>{view.verdict}</Tag>
          <Tag tone="caution">research only, not a trade</Tag>
        </span>
      </div>
      <div className="pb-pretty" style={{ ...small, fontSize: 12 }}>{view.text}</div>
      {e && <div style={small}>The research status is not available ({e}). The card shows the committed R3 result.</div>}
    </div>
  );
}
