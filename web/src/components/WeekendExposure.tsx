"use client";

// Portfolio, closed-market mode (U3): each holding's exposure to the expected open gap (expected gap x position), its
// staged hedges (hedge B) and the evidence badge. Real holdings read GET /closed/expected-gap for their mapped market;
// bridges opened this session report their own (a replay bridge: the recorded weekend, labelled as such).
import { useEffect, useState } from "react";
import { getBridge, getExpectedGap, listStaged, type BridgeSummary, type Holding } from "@/lib/api";
import { bandText, currentGap, exposureTotal, fmtBp, gapBadge, normalizeGap, sessionClosed, stagedHedgeText, weekendExposure, type GapView, type SessionView, type StagedOrder } from "@/lib/closed";
import { fmtMoney } from "@/lib/fmt";
import { Glass, Tag } from "@/components/pb";
import { GapBadge } from "@/components/bridge/WeekendPanel";

interface Row { key: string; kind: "holding" | "bridge"; marketId: string | null; ticker: string; what: string; shares: number; value: number | null; gap: GapView | null; orders: StagedOrder[]; replay: boolean; bridgeId: string | null; note?: string }

const cols = "minmax(0,1.3fr) 96px 120px minmax(150px,1fr)";
const num = { fontSize: "var(--fs-13)", textAlign: "right" as const };
const note = { fontSize: "var(--fs-13)", color: "var(--text-2)", marginTop: "var(--sp-3)" } as const;
const signColor = (n: number) => (n >= 0 ? "var(--up)" : "var(--down)");

export function WeekendExposurePanel({ holdings, bridgeIds, session, onOpen }: { holdings: Holding[] | null; bridgeIds: string[]; session: SessionView | null; onOpen: (bridgeId: string) => void }) {
  const closedNow = sessionClosed(session);
  const exposed = (holdings ?? []).filter((h) => h.exposure);
  const key = `${closedNow}|${exposed.map((h) => `${h.ticker}:${h.exposure!.market.id}`).join(",")}|${bridgeIds.join(",")}`;
  const [rows, setRows] = useState<{ key: string; rows: Row[]; error: string | null } | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const staged = await listStaged().then((x) => x.orders, () => [] as StagedOrder[]);
      const real: Row[] = closedNow ? await Promise.all(exposed.map(async (h) => {
        const m = h.exposure!.market;
        const direction = h.exposure!.direction === "up_on_yes" ? "up_on_yes" : "down_on_yes";
        const g = await getExpectedGap({ market_source: m.source, market_id: m.id, ticker: h.ticker, direction, token_id: m.token_id }).catch(() => null);
        return {
          key: `h:${h.ticker}:${m.id}`, kind: "holding" as const, marketId: m.id, ticker: h.ticker, what: m.question, shares: h.shares, value: h.value ?? (h.spot != null ? h.spot * h.shares : null),
          gap: g ? normalizeGap(g.expected_gap) : null, orders: staged.filter((o) => o.ticker === h.ticker && o.clock !== "replay"), replay: false, bridgeId: null,
          note: g ? undefined : "expected gap not available",
        };
      })) : [];
      const sums = await Promise.all(bridgeIds.map((id) => getBridge(id).catch(() => null)));
      const fromBridges: Row[] = sums.filter((b): b is BridgeSummary => !!b && b.division !== "opportunity" && !!b.closed_mode && (sessionClosed(b.session) || !!b.closed_mode.timeline?.length))
        .map((b) => {
          const cm = b.closed_mode!;
          const { gap } = currentGap(b.expected_gap as Record<string, unknown> | null, cm.last_expected_gap as Record<string, unknown> | null,
            sessionClosed(b.session), b.closure?.since);
          const px = cm.pnl?.s_close ?? cm.pnl?.s_now ?? null;
          return {
            key: `b:${b.bridge_id}`, kind: "bridge" as const, marketId: b.market?.id ?? b.replay_market?.id ?? null, ticker: b.ticker, what: b.label ?? `bridge ${b.bridge_id}`, shares: b.shares_held, value: px != null ? px * b.shares_held : null,
            gap, orders: staged.filter((o) => o.bridge_id === b.bridge_id).length ? staged.filter((o) => o.bridge_id === b.bridge_id) : (cm.staged_orders ?? []),
            replay: b.source === "replay", bridgeId: b.bridge_id,
          };
        });
      if (alive) setRows({ key, rows: [...real, ...fromBridges], error: null });
    })().catch((e) => alive && setRows({ key, rows: [], error: e instanceof Error ? e.message : String(e) }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const list = rows && rows.key === key ? rows.rows : null;
  const total = exposureTotal(list ?? []);

  return (
    <Glass style={{ padding: "var(--sp-5)", minWidth: 0 }}>
      <div data-testid="weekend-exposure" style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
        <h2 className="pb-h4">Weekend exposure: expected gap × position</h2>
        <span style={{ display: "inline-flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
          {session && <Tag tone={closedNow ? "caution" : "live"} title={session.label ?? undefined}>{closedNow ? "equities closed" : "market open"}</Tag>}
          {total && (
            <span data-testid="weekend-total" style={{ display: "inline-flex", gap: "var(--sp-2)", alignItems: "center" }} title={total.validated ? "Each gap in this total is validated for its market." : "One or more gaps in this total are unvalidated estimates (pooled rate, or no out-of-sample record that passes)."}>
              <span className="pb-num" style={{ fontSize: "var(--fs-13)", fontWeight: 600, color: signColor(total.usd) }}>{fmtMoney(total.usd, true)} expected</span>
              {total.lo != null && total.hi != null && <span className="pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--faint)" }}>band {fmtMoney(total.lo, true)} to {fmtMoney(total.hi, true)}</span>}
              <Tag tone={total.validated ? "measured" : "caution"}>{total.validated ? "validated" : "unvalidated estimate"}</Tag>
            </span>
          )}
        </span>
      </div>
      {!closedNow && <div style={note}>{session?.label ?? "Market open"}. The expected open gap applies only when US equities are closed.{list?.length ? " The bridges below show their last closure." : ""}</div>}
      {closedNow && !holdings && <div style={note}>Holdings are not available (GET /portfolio), so this panel shows no expected gap for them. Bridges that you start in this session show here.</div>}
      {rows?.error && <div style={note}>Weekend exposure is not available: {rows.error}. Refresh the page to try again.</div>}
      {list == null && (closedNow || bridgeIds.length > 0) && <div style={note}>The system reads the expected gaps. Wait.</div>}
      {list && list.length > 0 && (
        <div className="pb-table-scroll">
          <div style={{ minWidth: 560 }}>
            <div style={{ display: "grid", gridTemplateColumns: cols, gap: "var(--sp-3)", alignItems: "end", height: 36, paddingBottom: "var(--sp-2)", boxSizing: "border-box", marginTop: "var(--sp-3)", borderBottom: "1px solid var(--border-strong)", fontSize: "var(--fs-12)", fontWeight: 500, color: "var(--faint)" }}>
              <span>Holding and market</span><span style={{ textAlign: "right" }}>Expected gap</span><span style={{ textAlign: "right" }}>Exposure</span><span>Staged hedge</span>
            </div>
            {list.map((r) => {
              const x = weekendExposure(r.value, r.gap);
              const h = stagedHedgeText(r.orders);
              return (
                <div key={r.key} data-testid="weekend-row" className={r.bridgeId ? "pb-row" : undefined} style={{ display: "grid", gridTemplateColumns: cols, gap: "var(--sp-3)", alignItems: "center", padding: "var(--sp-3) 0", borderBottom: "1px solid var(--border)", cursor: r.bridgeId ? "pointer" : undefined }} onClick={r.bridgeId ? () => onOpen(r.bridgeId!) : undefined}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
                      <span className="pb-ticker" style={{ fontSize: "var(--fs-14)" }}>{r.ticker}</span>
                      <span className="pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--faint)" }}>{r.shares.toLocaleString("en-US")} sh</span>
                      <GapBadge gap={r.gap} />
                      {r.replay && <Tag tone="replay" title="This bridge replays a recorded weekend. Its gap and hedges come from the recording, not from today.">recorded weekend</Tag>}
                    </div>
                    <div className="pb-ellipsis" style={{ fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: 2 }} title={gapBadge(r.gap).reason}>{r.what}{r.gap ? `, ${bandText(r.gap)}` : r.note ? `, ${r.note}` : ""}</div>
                  </div>
                  <span className="pb-num" style={{ ...num, color: r.gap?.bp == null ? "var(--faint)" : signColor(r.gap.bp) }}>{fmtBp(r.gap?.bp)}</span>
                  <span className="pb-num" style={{ ...num, fontWeight: 600, color: x == null ? "var(--faint)" : signColor(x.usd) }} title={x && x.lo != null && x.hi != null ? `band ${fmtMoney(x.lo, true)} to ${fmtMoney(x.hi, true)}` : undefined}>{x == null ? "n/a" : fmtMoney(x.usd, true)}</span>
                  <div style={{ minWidth: 0 }}>
                    <span className={`pb-tag pb-ellipsis ${h.state === "awaiting" ? "pb-tag-warn" : "pb-tag-neutral"}`} style={{ display: "inline-block", maxWidth: "100%", lineHeight: "20px" }} title={h.badge}>{h.badge}</span>
                    <div className="pb-ellipsis" style={{ fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: "var(--sp-1)" }} title={h.text}>{h.text}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {list && list.length === 0 && closedNow && holdings && <div style={note}>No holding has a mapped market, so no expected gap applies.</div>}
      <div className="pb-pretty" style={{ fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: "var(--sp-4)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)", lineHeight: 1.5 }}>
        Expected gap = market rate × PM move since the close, with its 80% band. A gap is validated only for a market whose own out-of-sample record passes. All other gaps are unvalidated estimates, shown with their band and closure count. Exposure = expected gap × position value. The total does not include recorded weekends or bridges that a holding row already counts. Staged hedges (hedge B) execute only after you approve them, at the first tradable time. They execute after the gap occurs, so they cannot remove it. By timing, they decrease the variance after the open (R1).
      </div>
    </Glass>
  );
}
