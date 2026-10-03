import type { TagVerdict } from "@/lib/api";
import { Badge } from "./ui";

const f = (x: number | null) => (x == null ? "n/a" : x.toFixed(4));

export function VerdictBadge({ v }: { v: TagVerdict | null }) {
  if (!v) return <Badge>no verdict</Badge>;
  const tone = v.label === "no_edge" ? "neutral" : v.label === "hedge" ? "info" : "good";
  return (
    <span className="inline-flex gap-1">
      <Badge tone={tone}>{v.label.replace("_", " ")}</Badge>
      <Badge tone={v.kind === "confirmatory" ? "good" : "warn"} title={v.note}>{v.kind}</Badge>
    </span>
  );
}

export function VerdictCard({ v }: { v: TagVerdict }) {
  const e = v.evidence;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2"><span className="text-sm font-medium">{v.tag}</span><VerdictBadge v={v} /></div>
      {v.kind === "none" ? <p className="text-sm text-slate-700">Not tested</p> : v.label === "no_edge" && <p className="text-sm text-slate-700">No edge found — try another event or stock.</p>}
      {v.kind === "exploratory" && <p className="text-xs text-amber-700">Exploratory atlas result: a hypothesis, not a confirmed finding.</p>}
      {e.strategy && (
        <p className="text-xs text-slate-600">
          {e.strategy} @ {e.horizon}: difference {f(e.difference)} (CI {f(e.ci_lo)} to {f(e.ci_hi)})
          {e.q_value != null && `, q = ${f(e.q_value)}`}
        </p>
      )}
      <p className="text-xs text-slate-500">{v.note}</p>
    </div>
  );
}
