import type { Market } from "@/lib/api";
import { money, pct } from "@/lib/hooks";
import { Badge } from "./ui";

export function MarketCard({ market, selected, onSelect }: { market: Market; selected: boolean; onSelect: () => void }) {
  return (
    <button onClick={onSelect} className={`w-full rounded-2xl border bg-white/80 p-3 text-left transition hover:bg-white ${selected ? "border-indigo-400 ring-2 ring-indigo-200" : "border-white/70"}`}>
      <p className="text-sm font-medium">{market.question}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <Badge tone={market.source === "polymarket" ? "info" : "good"}>{market.source}</Badge>
        <span>Yes {pct(market.yes_price)}</span>
        <span>24h vol {money(market.volume_24h)}</span>
        {market.end_date && <span>ends {market.end_date.slice(0, 10)}</span>}
      </div>
    </button>
  );
}
