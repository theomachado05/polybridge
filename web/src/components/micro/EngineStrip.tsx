"use client";

import Link from "next/link";
import { useStore } from "@/lib/store";
import { forwardCount, latencyView, recorderLine } from "@/lib/micro";
import { useForward, useRegistry } from "./parts";

/** Global engine strip: the C++ library size (GET /library), live latency (the registry's system number, with its
 *  range and sample), and the recorder and forward-test state (GET /forward/status). Each part hides when its source
 *  is not available; nothing is filled in. */
export function EngineStrip() {
  const s = useStore();
  const reg = useRegistry();
  const fw = useForward();
  const lib = s.library.status === "ok" && s.library.data ? s.library.data : null;
  const lat = latencyView(reg.data);
  const rec = fw.data ? recorderLine(fw.data) : null;
  const lad = fw.data?.ladders;
  if (!lib && !lat && !fw.data) return null;
  return (
    <div className="pb-engine" data-testid="engine-strip">
      <div className="pb-engine-inner">
        <span style={{ color: "var(--ink)", fontWeight: 500 }}>C++ engine</span>
        {lib && <span title={lib.source ?? "GET /library"}>{lib.total.toLocaleString("en-US")} presets · {lib.rows.length} families</span>}
        {lib && lib.micro.length > 0 && (
          <span data-testid="engine-micro" title={lib.micro.map((m) => `${m.id}: ${m.idea}`).join("\n")}>
            + {lib.microTotal} micro presets · {lib.micro.map((m) => `${m.id} (${m.status})`).join(" · ")}
          </span>
        )}
        {(reg.data?.micro_bench ?? []).map((b) => (
          <span key={b.family} data-testid="engine-micro-latency" title={`${b.result_file}, micro section. Tape: ${b.tape}. ${b.note ?? ""}`}>
            {b.family} on_tick {b.mean_ns} ns mean (p99 {b.p99_ns} ns) · {b.sample}, synthetic tape
          </span>
        ))}
        {lat && <span title={`${lat.label}. ${lat.rangeKind}. ${lat.note ?? ""} Source: ${lat.source}${lat.sourceNote ? ` (${lat.sourceNote})` : ""}`}>latency {lat.value} {lat.range} · {lat.sample}</span>}
        {rec && <span style={{ color: rec.ok ? "var(--up-ink)" : "var(--warn)" }}>{rec.text}</span>}
        {lad && <span title={lad.label} data-testid="forward-count">ladder forward test: {forwardCount(lad)}</span>}
        <Link href="/tested" style={{ color: "var(--accent)", marginLeft: "auto" }}>What we tested</Link>
      </div>
    </div>
  );
}
