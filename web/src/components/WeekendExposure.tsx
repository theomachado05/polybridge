"use client";

// Portfolio, closed-market mode (U3): each holding's exposure to the expected open gap (expected gap x position), its
// staged hedges (hedge B) and the evidence badge. Real holdings read GET /closed/expected-gap for their mapped market;
// bridges opened this session report their own (a replay bridge: the recorded weekend, labelled as such).
import { useEffect, useState } from "react";
import { getBridge, getExpectedGap, listStaged, type BridgeSummary, type Holding } from "@/lib/api";
import { bandText, currentGap, exposureTotal, fmtBp, gapBadge, normalizeGap, sessionClosed, stagedHedgeText, weekendExposure, type GapView, type SessionView, type StagedOrder } from "@/lib/closed";
import { fmtMoney } from "@/lib/fmt";
import { Glass, Label, Tag, upColor } from "@/components/pb";
import { GapBadge } from "@/components/bridge/WeekendPanel";

interface Row { key: string; kind: "holding" | "bridge"; marketId: string | null; ticker: string; what: string; shares: number; value: number | null; gap: GapView | null; orders: StagedOrder[]; replay: boolean; bridgeId: string | null; note?: string }

const cols = "minmax(0,1.3fr) 96px 120px minmax(150px,1fr)";
const num = { fontFamily: "var(--mono)", fontSize: 12.5, textAlign: "right" as const };

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
          note: g ? undefined : "expected gap unavailable",
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
    <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
      <div data-testid="weekend-exposure" style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Label>07 · WEEKEND EXPOSURE · EXPECTED GAP × POSITION</Label>
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          {session && <Tag tone={closedNow ? "caution" : "live"} title={session.label ?? undefined}>{closedNow ? "equities closed" : "market open"}</Tag>}
          {total && (
            <span data-testid="weekend-total" style={{ display: "inline-flex", gap: 6, alignItems: "center" }} title={total.validated ? "Every gap in this total is validated for its market" : "At least one gap in this total is an unvalidated estimate (pooled rate or no passing out-of-sample record)"}>
              <span className="pb-mono" style={{ fontSize: 12, color: upColor(total.usd) }}>{fmtMoney(total.usd, true)} expected</span>
              {total.lo != null && total.hi != null && <span className="pb-mono" style={{ fontSize: 11, color: "#5A627A" }}>band {fmtMoney(total.lo, true)} to {fmtMoney(total.hi, true)}</span>}
              <Tag tone={total.validated ? "measured" : "caution"}>{total.validated ? "validated" : "unvalidated estimate"}</Tag>
            </span>
          )}
        </span>
      </div>
      {!closedNow && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>{session?.label ?? "Market open"}: the expected open gap applies only while US equities are closed{list?.length ? "; bridges below show their last closure" : ""}.</div>}
      {closedNow && !holdings && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Sample holdings have no mapped market, so there is no expected gap to show. Bridges started this session appear here.</div>}
      {rows?.error && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Weekend exposure unavailable: {rows.error}</div>}
      {list == null && (closedNow || bridgeIds.length > 0) && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Reading expected gaps…</div>}
      {list && list.length > 0 && (
        <div className="pb-table-scroll">
          <div style={{ minWidth: 560 }}>
            <div style={{ display: "grid", gridTemplateColumns: cols, gap: 12, padding: "14px 0 8px", borderBottom: "1px solid rgba(15,22,38,.14)", fontSize: 11, color: "#5A627A" }}>
              <span>Holding · market</span><span style={{ textAlign: "right" }}>Expected gap</span><span style={{ textAlign: "right" }}>Exposure</span><span>Staged hedge</span>
            </div>
            {list.map((r) => {
              const x = weekendExposure(r.value, r.gap);
              const h = stagedHedgeText(r.orders);
              return (
                <div key={r.key} data-testid="weekend-row" style={{ display: "grid", gridTemplateColumns: cols, gap: 12, alignItems: "center", padding: "12px 0", borderBottom: "1px solid rgba(15,22,38,.07)", cursor: r.bridgeId ? "pointer" : undefined }} onClick={r.bridgeId ? () => onOpen(r.bridgeId!) : undefined}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.02em" }}>{r.ticker}</span>
                      <span style={{ fontSize: 11.5, color: "#5A627A" }}>{r.shares.toLocaleString("en-US")} sh</span>
                      <GapBadge gap={r.gap} />
                      {r.replay && <Tag tone="replay" title="This bridge replays a recorded weekend: its gap and hedges are the recording's, not today's">recorded weekend</Tag>}
                    </div>
                    <div className="pb-ellipsis" style={{ fontSize: 11.5, color: "#5A627A", marginTop: 2 }} title={gapBadge(r.gap).reason}>{r.what}{r.gap ? ` · ${bandText(r.gap)}` : r.note ? ` · ${r.note}` : ""}</div>
                  </div>
                  <span style={{ ...num, color: r.gap?.bp == null ? "#8A92A8" : upColor(r.gap.bp) }}>{fmtBp(r.gap?.bp)}</span>
                  <span style={{ ...num, color: x == null ? "#8A92A8" : upColor(x.usd) }} title={x && x.lo != null && x.hi != null ? `band ${fmtMoney(x.lo, true)} to ${fmtMoney(x.hi, true)}` : undefined}>{x == null ? "—" : fmtMoney(x.usd, true)}</span>
                  <div style={{ minWidth: 0 }}>
                    <span className="pb-ellipsis" style={{ display: "inline-block", maxWidth: "100%", padding: "3px 9px", borderRadius: 999, fontSize: 11, fontWeight: 600, background: h.state === "awaiting" ? "rgba(154,74,0,.10)" : "rgba(15,22,38,.06)", color: h.state === "awaiting" ? "#9A4A00" : "#3C4458" }} title={h.badge}>{h.badge}</span>
                    <div className="pb-ellipsis" style={{ fontSize: 11, color: "#5A627A", marginTop: 3 }} title={h.text}>{h.text}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {list && list.length === 0 && closedNow && holdings && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>No holding has a mapped market, so no expected gap applies.</div>}
      <div className="pb-pretty" style={{ fontSize: 11.5, color: "#5A627A", marginTop: 12, lineHeight: 1.45 }}>
        Expected gap = the market&apos;s rate × the PM move since the close, with its 80% band. It reads validated only for a market whose own out-of-sample record passes; every other number is an unvalidated estimate, shown with its band and the closures behind it. Exposure is expected gap × position value, the total too (bridges already counted as a holding and recorded weekends are left out). Staged hedges (hedge B) execute only after you approve them, at the first tradable moment: after the gap has formed, so they do not recover it; R1 found they cut the variance that follows the open, by timing.
      </div>
    </Glass>
  );
}
