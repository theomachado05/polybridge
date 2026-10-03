export function Sparkline({ values, w = 260, h = 64 }: { values: number[]; w?: number; h?: number }) {
  if (values.length < 2) return <div className="h-16 text-xs text-slate-400">waiting for ticks...</div>;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 4 - ((v - lo) / span) * (h - 8)).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-16 w-full" role="img" aria-label="Price sparkline">
      <polyline points={pts} fill="none" stroke="#6366f1" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}
