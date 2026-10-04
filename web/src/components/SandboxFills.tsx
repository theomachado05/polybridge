"use client";

// Portfolio: fills of UI-started replay bridges. A replay bridge sends its orders to an isolated in-memory sim (the
// replay sandbox), never the account, so they never appear in GET /orders. This reads them from each bridge's own
// summary and SSE stream (the server replays the stream's history on connect) and lists them apart from the account.
import { getBridge } from "@/lib/api";
import { prettyId } from "@/lib/fmt";
import { useAsync } from "@/lib/hooks";
import { sandboxFills, useBridgeStream } from "@/lib/useBridgeStream";
import { Glass, Label, Tag } from "@/components/pb";
import { fillBadges, gateCounts } from "@/lib/risk";

/** At most this many bridges are streamed at once (each holds one SSE connection to the backend). */
const MAX_STREAMS = 4;

export function SandboxFillsPanel({ bridgeIds, onOpen }: { bridgeIds: string[]; onOpen: (id: string) => void }) {
  if (!bridgeIds.length) return null;
  const shown = bridgeIds.slice(-MAX_STREAMS).reverse();
  return (
    <Glass style={{ padding: "22px 26px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Label>Replay sandbox fills</Label>
        <Tag tone="replay" title="Replay bridges trade an isolated simulated account on recorded market history. These fills are not in your account, your positions, or the totals above.">not your account</Tag>
      </div>
      <div style={{ fontSize: 12, color: "#5A627A", marginTop: 8, lineHeight: 1.45 }}>
        Bridges on a recorded replay fill orders in a separate sandbox. The sandbox usually uses the current quote, or
        the recorded price when no quote is available. These fills never go to the account above.
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 12 }}>
        {shown.map((id) => <BridgeFills key={id} id={id} onOpen={onOpen} />)}
        {bridgeIds.length > shown.length && <div style={{ fontSize: 11.5, color: "#8A92A8" }}>This list shows the {shown.length} newest of {bridgeIds.length} bridges.</div>}
      </div>
    </Glass>
  );
}

function BridgeFills({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  const summary = useAsync(`sbx:${id}`, () => getBridge(id));
  const st = useBridgeStream(id, summary.data?.source ?? null);
  const sum = summary.data;
  const ticker = sum?.ticker ?? "Bridge";
  const fills = sandboxFills(st.log);
  const scope = sum?.account_scope ?? (fills.length ? "replay_sandbox" : null);
  const filled = fills.filter((f) => f.status === "filled");
  // The live stream's position events carry the hedge as it moves; the summary is a one-time snapshot (fallback only).
  const hedge = st.brokerHedge ?? sum?.broker_hedge ?? null;
  // The client log is bounded, so on a long run the oldest fills drop out: then the count is the latest N, not a total.
  const capped = st.fills > st.log.filter((l) => l.fill).length;
  const head = (
    <button type="button" onClick={() => onOpen(id)} style={{ all: "unset", cursor: "pointer", display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13, width: "100%" }}>
      <span className="pb-ellipsis" style={{ minWidth: 0 }}><span style={{ fontWeight: 600 }}>{ticker}</span> <span style={{ color: "#5A627A", marginLeft: 4 }}>{sum?.label ?? `bridge ${id}`}</span></span>
      <span style={{ fontSize: 11.5, color: "#5A627A", flex: "none" }}>Status: {st.status}</span>
    </button>
  );
  if (summary.error && !fills.length) {
    return <div>{head}<div style={{ fontSize: 12, color: "#8A92A8", marginTop: 4 }}>The bridge summary is not available ({summary.error}). Open the bridge to try again.</div></div>;
  }
  if (scope === "account") {
    const c = gateCounts(st.log.map((l) => l.fill), sum);
    return <div>{head}<div style={{ fontSize: 12, color: "#5A627A", marginTop: 4 }}>This bridge does not use the sandbox. Its orders go to the account and show in Recent fills.{c.liquidity || c.capital ? ` The participation caps decreased ${c.liquidity} order${c.liquidity === 1 ? "" : "s"}, and the capital budget refused ${c.capital}.` : ""}</div></div>;
  }
  return (
    <div>
      {head}
      <div style={{ fontSize: 11.5, color: "#5A627A", marginTop: 3 }}>
        {capped ? "latest " : ""}{filled.length} sandbox {filled.length === 1 ? "fill" : "fills"}{hedge != null ? `, sandbox hedge ${hedge.toLocaleString("en-US")} sh short` : ""}{sum?.broker ? `, ${sum.broker}` : ""}
      </div>
      <div style={{ display: "flex", flexDirection: "column", marginTop: 4 }}>
        {!fills.length && <div style={{ fontSize: 12, color: "#8A92A8", padding: "6px 0" }}>{st.decisions ? `No fills yet (${st.decisions} decisions).` : "No stream data yet. Wait for the stream."}</div>}
        {fills.slice(0, 5).map((f) => (
          <div key={f.n} style={{ display: "grid", gridTemplateColumns: "44px 44px minmax(0,1fr)", gap: 12, alignItems: "center", padding: "7px 0", borderBottom: "1px solid rgba(15,22,38,.07)", fontSize: 12.5 }}>
            <span className="pb-mono" style={{ fontSize: 11.5, color: "#5A627A" }}>#{f.n}</span>
            <span style={{ fontSize: 11, fontWeight: 600, color: f.side === "SELL" ? "#C8323F" : "#15804F" }}>{f.side === "SELL" ? "Sell" : "Buy"}</span>
            <span className="pb-ellipsis" style={{ minWidth: 0 }}>
              {f.qty.toLocaleString("en-US")} {f.what === "sh" ? ticker : f.what}{f.px != null ? ` @ ${f.px.toFixed(2)}` : ""}
              <span style={{ color: "#5A627A" }}>{f.status !== "filled" ? `, ${f.status}` : ""}{f.family ? `, ${prettyId(f.family)}${f.preset != null ? ` #${f.preset}` : ""}` : ", engine"}{f.fee ? `, fee $${f.fee.toFixed(2)}` : ""}</span>
              {f.priceNote?.startsWith("recorded price") && <span title={f.priceNote} style={{ color: "#8A6A1F" }}>, recorded price</span>}
              {fillBadges({ gates: f.gates, reject_reason: f.reject, evidence: f.evidence }).map((b) => <span key={b.text} style={{ marginLeft: 6 }}><Tag tone={b.tone} title={b.title}>{b.text}</Tag></span>)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
