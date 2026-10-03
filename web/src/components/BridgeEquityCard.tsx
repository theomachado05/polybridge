import type { Async } from "@/lib/hooks";
import type { EquityCard } from "@/lib/api";
import { money, pct } from "@/lib/hooks";
import { ErrorText, Glass, Loading } from "./ui";

export function BridgeEquityCard({ ticker, card }: { ticker: string | null; card: Async<EquityCard> }) {
  return (
    <Glass className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Equity</p>
      <p className="text-3xl font-semibold">{ticker ?? "..."}</p>
      {card.loading && <Loading what="equity" />}
      {card.error && <ErrorText>Equity lookup failed: {card.error}</ErrorText>}
      {card.data?.implied_move && <p className="text-sm text-slate-700">Spot {money(card.data.implied_move.spot)} · implied move ±{pct(card.data.implied_move.value, 1)}</p>}
      {card.data && !card.data.implied_move && <p className="text-sm text-slate-500">No options data. {card.data.notes[0]}</p>}
    </Glass>
  );
}
