import { pct } from "@/lib/hooks";
import { Glass } from "./ui";

const clampPct = (x: number) => (Number.isFinite(x) ? Math.max(0, Math.min(100, x * 100)) : 0);

export function PositionPanel({ shares, targetCoverage, hedge }: { shares: number | null; targetCoverage: number | null; hedge: number }) {
  // Coverage = simulated hedge shares / shares held, computed here from the summary's shares_held so the bar never
  // depends on a separate proposal lookup. The marker shows the target coverage (the most the engine will hedge).
  const coverage = shares && shares > 0 ? Math.abs(hedge) / shares : 0;
  return (
    <Glass className="space-y-2">
      <h2 className="font-semibold">Portfolio</h2>
      <p className="text-sm text-slate-700">Shares held {shares ?? "n/a"} · simulated hedge <strong>{Math.round(hedge)}</strong> shares</p>
      <div className="relative h-3 overflow-hidden rounded-full bg-white/70" role="progressbar" aria-valuenow={Math.round(clampPct(coverage))} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-indigo-500 transition-all" style={{ width: `${clampPct(coverage)}%` }} />
        {targetCoverage != null && <div className="absolute inset-y-0 w-0.5 bg-slate-700" style={{ left: `${clampPct(targetCoverage)}%` }} title="target coverage" />}
      </div>
      <p className="text-xs text-slate-600">Coverage {pct(coverage)}{targetCoverage != null && ` (target up to ${pct(targetCoverage)}, scaled by the event probability)`}. Orders are simulated.</p>
    </Glass>
  );
}
