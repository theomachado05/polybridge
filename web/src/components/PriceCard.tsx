import { pct } from "@/lib/hooks";
import { Glass } from "./ui";
import { Sparkline } from "./Sparkline";

export function PriceCard({ prices, last, source }: { prices: number[]; last: number | null; source: string | null }) {
  return (
    <Glass className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Prediction market</p>
      <p className="text-3xl font-semibold">{last == null ? "..." : pct(last, 1)}</p>
      <p className="text-xs text-slate-500">YES price, {source === "replay" ? "recorded replay" : "live midpoint"}</p>
      <Sparkline values={prices} />
    </Glass>
  );
}
