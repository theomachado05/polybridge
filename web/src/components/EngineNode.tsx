import { quantile } from "@/lib/useBridgeStream";
import { Glass } from "./ui";

const us = (ns: number | null) => (ns == null ? "n/a" : ns >= 1000 ? `${(ns / 1000).toFixed(1)} µs` : `${ns} ns`);

export function EngineNode({ lat, decisions, status }: { lat: number[]; decisions: number; status: string }) {
  return (
    <Glass className="flex flex-col items-center justify-center space-y-2 text-center">
      <div className={`flex h-20 w-20 items-center justify-center rounded-full border-2 border-indigo-300 bg-white/80 text-sm font-semibold ${status === "running" ? "animate-pulse" : ""}`}>hedgecore</div>
      <p className="text-xs text-slate-600">{decisions} decisions · {status}</p>
      <p className="text-sm">p50 <strong>{us(quantile(lat, 0.5))}</strong> · p99 <strong>{us(quantile(lat, 0.99))}</strong></p>
      <p className="text-xs text-slate-500">decision latency inside the engine</p>
    </Glass>
  );
}
