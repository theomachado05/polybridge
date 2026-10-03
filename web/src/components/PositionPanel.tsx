import { pct } from "@/lib/hooks";
import { Glass } from "./ui";

export function PositionPanel({ shares, targetCoverage, hedge, coverage }: { shares: number | null; targetCoverage: number | null; hedge: number; coverage: number }) {
  return (
    <Glass className="space-y-2">
      <h2 className="font-semibold">Portfolio</h2>
      <p className="text-sm text-slate-700">Shares held {shares ?? "n/a"} · simulated hedge <strong>{Math.round(hedge)}</strong> shares</p>
      <div className="h-3 overflow-hidden rounded-full bg-white/70" role="progressbar" aria-valuenow={Math.round(coverage * 100)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-indigo-500 transition-all" style={{ width: `${Math.min(100, coverage * 100)}%` }} />
      </div>
      <p className="text-xs text-slate-600">Coverage {pct(coverage)}{targetCoverage != null && ` of target ${pct(targetCoverage)}`}. Orders are simulated.</p>
    </Glass>
  );
}
