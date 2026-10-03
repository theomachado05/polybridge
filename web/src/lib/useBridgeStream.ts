"use client";

import { useEffect, useReducer } from "react";
import { API_URL } from "./api";

export const REASONS = ["stale", "below_sigma", "inside_band", "below_fees", "rebalance", "risk_capped"] as const;
export interface LogEntry { n: number; p: number | null; action: string; reason: string; qty: number; target: number; current: number; ns: number }
export interface StreamState {
  prices: number[];
  lastP: number | null;
  reasons: Record<string, number>;
  lastReason: string | null;
  lat: number[];
  hedge: number;
  coverage: number;
  log: LogEntry[];
  decisions: number;
  status: "connecting" | "running" | "reconnecting" | "finished" | "stopped";
  source: string | null;
  error: string | null;
}
type Ev =
  | { k: "open" } | { k: "drop" }
  | { k: "tick"; p: number }
  | { k: "decision"; d: { action: string; reason: string; order_qty: number; target_hedge: number; current_hedge: number; latency_ns: number } }
  | { k: "position"; hedge: number; coverage: number }
  | { k: "status"; status: string; source?: string }
  | { k: "error"; message: string };

const init: StreamState = { prices: [], lastP: null, reasons: {}, lastReason: null, lat: [], hedge: 0, coverage: 0, log: [], decisions: 0, status: "connecting", source: null, error: null };
const cap = <T,>(a: T[], n: number) => (a.length > n ? a.slice(a.length - n) : a);

function reduce(s: StreamState, e: Ev): StreamState {
  switch (e.k) {
    case "open": return { ...init, status: "running", source: s.source };  // the server replays history on connect
    case "drop": return s.status === "finished" || s.status === "stopped" ? s : { ...s, status: "reconnecting" };
    case "tick": return { ...s, prices: cap([...s.prices, e.p], 300), lastP: e.p };
    case "decision": {
      const d = e.d;
      const entry: LogEntry = { n: s.decisions + 1, p: s.lastP, action: d.action, reason: d.reason, qty: d.order_qty, target: d.target_hedge, current: d.current_hedge, ns: d.latency_ns };
      return { ...s, decisions: s.decisions + 1, lastReason: d.reason, reasons: { ...s.reasons, [d.reason]: (s.reasons[d.reason] ?? 0) + 1 }, lat: cap([...s.lat, d.latency_ns], 2000), log: cap([...s.log, entry], 200) };
    }
    case "position": return { ...s, hedge: e.hedge, coverage: e.coverage };
    case "status": return { ...s, status: e.status === "finished" ? "finished" : e.status === "stopped" ? "stopped" : "running", source: e.source ?? s.source };
    case "error": return { ...s, error: e.message };
  }
}

export function quantile(xs: number[], f: number): number | null {
  if (!xs.length) return null;
  const a = [...xs].sort((x, y) => x - y);
  return a[Math.min(a.length - 1, Math.floor(f * a.length))];
}

export function useBridgeStream(id: string, initialSource: string | null): StreamState {
  const [s, dispatch] = useReducer(reduce, { ...init, source: initialSource });
  useEffect(() => {
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let done = false;
    const json = (m: MessageEvent) => JSON.parse(m.data);
    const connect = () => {
      es = new EventSource(`${API_URL}/bridges/${id}/stream`);
      es.onopen = () => dispatch({ k: "open" });
      es.addEventListener("tick", (m) => dispatch({ k: "tick", p: json(m as MessageEvent).p }));
      es.addEventListener("decision", (m) => dispatch({ k: "decision", d: json(m as MessageEvent) }));
      es.addEventListener("position", (m) => dispatch({ k: "position", ...json(m as MessageEvent) }));
      es.addEventListener("error", (m) => { if ("data" in m && (m as MessageEvent).data) dispatch({ k: "error", message: json(m as MessageEvent).message }); });
      es.addEventListener("status", (m) => {
        const d = json(m as MessageEvent);
        dispatch({ k: "status", status: d.status, source: d.source });
        if (d.status === "finished" || d.status === "stopped") { done = true; es?.close(); }
      });
      es.onerror = () => {
        if (done) return;
        void fetch(`${API_URL}/bridges/${id}`).then((r) => {
          if (r.status === 404) {
            done = true; clearTimeout(timer); es?.close();
            dispatch({ k: "error", message: "Bridge not found (404); check the id." });
            dispatch({ k: "status", status: "stopped" });
          }
        }, () => {});
        dispatch({ k: "drop" });
        if (es && es.readyState === EventSource.CLOSED) { timer = setTimeout(connect, 2000); }  // the browser retries CONNECTING itself
      };
    };
    connect();
    return () => { done = true; clearTimeout(timer); es?.close(); };
  }, [id]);
  return s;
}
