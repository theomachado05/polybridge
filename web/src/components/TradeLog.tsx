import type { LogEntry } from "@/lib/useBridgeStream";
import { pct } from "@/lib/hooks";
import { Glass } from "./ui";

export function TradeLog({ log }: { log: LogEntry[] }) {
  const rows = [...log].reverse();
  return (
    <Glass className="space-y-2">
      <h2 className="font-semibold">Trades &amp; reasoning</h2>
      {rows.length === 0 && <p className="text-sm text-slate-500">No decisions yet.</p>}
      <ul className="max-h-72 space-y-1 overflow-auto font-mono text-xs">
        {rows.map((r) => (
          <li key={r.n} className={r.action === "order" ? "font-semibold text-indigo-700" : "text-slate-600"}>
            #{r.n} {r.p != null && `p=${pct(r.p, 1)} `}{r.action === "order" ? `ORDER ${r.qty > 0 ? "+" : ""}${r.qty.toFixed(0)} sh` : "HOLD"} · {r.reason.replace("_", " ")} · hedge {r.current.toFixed(0)}/{r.target.toFixed(0)} · {r.ns} ns
          </li>
        ))}
      </ul>
    </Glass>
  );
}
