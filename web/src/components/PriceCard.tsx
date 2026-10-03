"use client";

import { useEffect, useRef, useState } from "react";
import { pct } from "@/lib/hooks";
import { Glass } from "./ui";
import { Sparkline } from "./Sparkline";

export function PriceCard({ prices, last, source, tickCount, running }: { prices: number[]; last: number | null; source: string | null; tickCount: number; running: boolean }) {
  const lastTick = useRef(0);
  const [quiet, setQuiet] = useState(false);
  const [waited, setWaited] = useState(false);
  useEffect(() => { lastTick.current = Date.now(); }, [tickCount]);
  useEffect(() => {
    const t = setInterval(() => {
      setQuiet(Date.now() - lastTick.current > 10_000);
      setWaited(true);
    }, 2000);
    return () => clearInterval(t);
  }, []);
  const hint = !running ? null : last == null && waited ? "no ticks yet" : quiet ? "stream stale (no tick for over 10 s)" : null;
  return (
    <Glass className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Prediction market</p>
      <p className="text-3xl font-semibold">{last == null ? "..." : pct(last, 1)}</p>
      <p className="text-xs text-slate-500">YES price, {source === "replay" ? "Historical replay (real Polymarket history, time-compressed)" : source === "live" ? "live midpoint" : "connecting…"}</p>
      {hint && <p role="status" className="text-xs text-amber-700">{hint}</p>}
      <Sparkline values={prices} />
    </Glass>
  );
}
