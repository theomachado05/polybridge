import type { EquityCard } from "@/lib/api";
import { money, pct } from "@/lib/hooks";
import { VerdictBadge } from "./VerdictCard";

export function EquityPanel({ card, filingIdx, onPickFiling }: { card: EquityCard; filingIdx: number | null; onPickFiling: (i: number) => void }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="text-lg font-semibold">{card.ticker} <span className="text-sm font-normal text-slate-600">{card.name}</span></p>
        {card.implied_move ? (
          <p className="text-sm text-slate-700">Implied move ±{pct(card.implied_move.value, 1)} to {card.implied_move.expiry} (spot {money(card.implied_move.spot)}, as of {card.implied_move.as_of})</p>
        ) : <p className="text-sm text-slate-500">No implied move available.</p>}
      </div>
      <div className="space-y-1.5">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent 8-K filings</p>
        {card.filings.length === 0 && <p className="text-sm text-slate-500">No recent filings.</p>}
        {card.filings.slice(0, 6).map((fl, i) => (
          <button key={`${fl.date}-${fl.accession ?? i}`} onClick={() => onPickFiling(i)} className={`w-full rounded-xl border bg-white/80 px-3 py-2 text-left text-xs hover:bg-white ${filingIdx === i ? "border-indigo-400 ring-2 ring-indigo-200" : "border-white/70"}`}>
            <div className="flex items-center justify-between gap-2"><span>{fl.date} · {fl.tags.slice(0, 2).join(", ")}</span><VerdictBadge v={fl.verdict} /></div>
          </button>
        ))}
      </div>
      {card.notes.map((n) => <p key={n} className="text-xs text-amber-700">{n}</p>)}
    </div>
  );
}
