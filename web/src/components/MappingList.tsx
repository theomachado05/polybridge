"use client";

import { useState } from "react";
import type { Async } from "@/lib/hooks";
import type { MapOut } from "@/lib/api";
import { Badge, ErrorText, Loading } from "./ui";

export function MappingList({ map, selected, onPick }: { map: Async<MapOut>; selected: string | null; onPick: (t: string) => void }) {
  const [manual, setManual] = useState("");
  const m = map.data;
  return (
    <div className="space-y-2">
      {map.loading && <Loading what="stock mapping" />}
      {map.error && <ErrorText>Mapping failed: {map.error}</ErrorText>}
      {m && m.source === "precomputed" && (
        <>
          <div className="flex flex-wrap items-center gap-2"><Badge tone="warn">{m.label}</Badge>
            {m.match_type === "fuzzy" && <Badge tone="neutral">closest match: {m.matched_question} ({m.score})</Badge>}
          </div>
          {m.items.length === 0 && <p className="text-sm text-slate-500">This market was analysed and no stock is meaningfully affected.</p>}
          {m.items.map((i) => (
            <button key={i.ticker} onClick={() => onPick(i.ticker)} className={`w-full rounded-2xl border bg-white/80 p-3 text-left hover:bg-white ${selected === i.ticker ? "border-indigo-400 ring-2 ring-indigo-200" : "border-white/70"}`}>
              <span className="font-semibold">{i.ticker}</span>{" "}
              <span className="text-xs text-slate-600">{i.direction.replaceAll("_", " ")}{i.impact_pct != null && ` · ~${i.impact_pct}% move`}</span>
              {i.rationale && <p className="mt-1 text-xs text-slate-600">{i.rationale}</p>}
            </button>
          ))}
        </>
      )}
      {m && m.source === "none" && (
        <>
          <p className="text-sm text-slate-600">{m.note ?? "No precomputed mapping."}</p>
          {m.candidates.map((c) => (
            <p key={c.source_key} className="text-xs text-slate-500">Possible: {c.matched_question} ({c.score})</p>
          ))}
        </>
      )}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (manual.trim()) onPick(manual.trim().toUpperCase()); }}>
        <input aria-label="Pick a stock manually" value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Or type a ticker" className="w-36 rounded-full border border-white/80 bg-white/80 px-3 py-1 text-sm outline-none" />
        <button className="text-sm text-indigo-700 hover:underline">Use</button>
      </form>
    </div>
  );
}
