import { REASONS } from "@/lib/useBridgeStream";

export function StagePills({ reasons, last }: { reasons: Record<string, number>; last: string | null }) {
  return (
    <div className="flex flex-wrap gap-2" aria-label="Decision stages">
      {REASONS.map((r) => {
        const n = reasons[r] ?? 0;
        const cls = r === last ? "bg-indigo-600 text-white shadow" : n > 0 ? "bg-indigo-100 text-indigo-700" : "bg-white/60 text-slate-400";
        return <span key={r} className={`rounded-full px-3 py-1 text-xs font-medium transition ${cls}`}>{r.replace("_", " ")}{n > 0 && ` · ${n}`}</span>;
      })}
    </div>
  );
}
