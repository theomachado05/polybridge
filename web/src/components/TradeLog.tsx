"use client";

import { useState } from "react";
import type { LogEntry } from "@/lib/useBridgeStream";
import { pct } from "@/lib/hooks";
import { Glass } from "./ui";

export const PLAIN_REASON: Record<string, string> = {
  rebalance: "probability moved enough to resize the hedge",
  risk_capped: "resized, but capped at the risk limit",
  inside_band: "change too small to trade (inside the no-trade band)",
  below_sigma: "move looks like noise, not a real shift",
  below_fees: "trade would cost more in fees than it protects",
  stale: "price too old to act on",
  invalid: "hedge settings invalid, holding",
};
const plain = (r: string) => PLAIN_REASON[r] ?? r.replaceAll("_", " ");

export function TradeLog({ log }: { log: LogEntry[] }) {
  const [ordersOnly, setOrdersOnly] = useState(true);
  const rows = [...log].reverse().filter((r) => !ordersOnly || r.action === "order");
  return (
    <Glass className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Trades &amp; reasoning</h2>
        <label className="flex items-center gap-1 text-xs text-slate-600">
          <input type="checkbox" checked={ordersOnly} onChange={(e) => setOrdersOnly(e.target.checked)} /> Orders only
        </label>
      </div>
      {rows.length === 0 && <p className="text-sm text-slate-500">{ordersOnly && log.length ? "No orders yet (untick \"Orders only\" to see holds)." : "No decisions yet."}</p>}
      <ul className="max-h-72 space-y-1 overflow-auto text-xs">
        {rows.map((r) => (
          <li key={r.n} className={r.action === "order" ? "font-semibold text-indigo-700" : "text-slate-600"}>
            <span className="font-mono">#{r.n} {r.p != null && `p=${pct(r.p, 1)} `}{r.action === "order" ? `ORDER ${r.qty > 0 ? "+" : ""}${r.qty.toFixed(0)} sh` : "HOLD"}</span> · {plain(r.reason)} · <span className="font-mono">hedge {r.current.toFixed(0)}/{r.target.toFixed(0)} · {r.ns} ns</span>
          </li>
        ))}
      </ul>
    </Glass>
  );
}
