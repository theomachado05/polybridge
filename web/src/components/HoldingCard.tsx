import Link from "next/link";
import type { Holding } from "@/lib/api";
import { money, pct } from "@/lib/hooks";
import { VerdictBadge } from "./VerdictCard";
import { Badge, Glass } from "./ui";

const TONE = { none: "neutral", proposed: "warn", approved: "info", bridging: "good", rejected: "bad" } as const;

export function HoldingCard({ h }: { h: Holding }) {
  const ex = h.exposure;
  const href = `/build?ticker=${h.ticker}&shares=${h.shares}`;
  return (
    <Glass className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <Link href={href} className="text-lg font-semibold text-indigo-700 hover:underline">{h.ticker}</Link>
          <p className="text-xs text-slate-600">{h.name} · {h.shares.toLocaleString()} sh · {money(h.value)}</p>
        </div>
        <Badge tone={TONE[h.hedge.status]}>hedge: {h.hedge.status}</Badge>
      </div>
      {ex ? (
        <div className="rounded-xl bg-white/70 p-3 text-xs">
          <p className="text-base font-semibold">{money(ex.remaining_usd)} <span className="text-xs font-normal text-slate-600">remaining event exposure</span></p>
          <p className="text-slate-600">{ex.market.question} (Yes {pct(ex.market.yes_price)}), ~{ex.impact_pct}% move</p>
          <div className="mt-1 flex flex-wrap gap-1"><Badge tone="warn">{ex.label}</Badge>
            {ex.match_type === "fuzzy" && <Badge>closest match: {ex.matched_question} ({ex.score})</Badge>}</div>
        </div>
      ) : <p className="text-xs text-slate-500">No mapped event exposure found.</p>}
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Open markets</p>
        {h.markets.length === 0 && <p className="text-xs text-slate-500">None found.</p>}
        {h.markets.slice(0, 3).map((m) => <p key={`${m.source}:${m.id}`} className="truncate text-xs text-slate-700">{m.question} · Yes {pct(m.yes_price)} <Badge>{m.source}</Badge></p>)}
      </div>
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent filings</p>
        {h.filings.length === 0 && <p className="text-xs text-slate-500">None found.</p>}
        {h.filings.map((f) => <div key={`${f.date}-${f.accession}`} className="flex items-center justify-between gap-2 text-xs"><span className="truncate">{f.date} · {f.tags[0]}</span><VerdictBadge v={f.verdict} /></div>)}
      </div>
      {h.notes.map((n) => <p key={n} className="text-xs text-amber-700">{n}</p>)}
      <Link href={href} className="inline-block text-sm text-indigo-700 hover:underline">Open in Build</Link>
    </Glass>
  );
}
