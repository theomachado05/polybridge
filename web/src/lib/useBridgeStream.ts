"use client";

import { useEffect, useReducer } from "react";
import { API_URL } from "./api";

import { init, reduce, type StreamState } from "./bridgeStream.ts";

export { quantile, REASONS, sandboxFills, type FillInfo, type LogEntry, type OptionLegFill, type OptionsView, type SandboxFill, type StreamState } from "./bridgeStream.ts";

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
      es.addEventListener("tick", (m) => { const d = json(m as MessageEvent); dispatch({ k: "tick", p: d.p, options: d.options ?? null, closed: d.closed ?? null }); });
      es.addEventListener("decision", (m) => dispatch({ k: "decision", d: json(m as MessageEvent) }));
      es.addEventListener("position", (m) => dispatch({ k: "position", ...json(m as MessageEvent) }));
      es.addEventListener("fill", (m) => dispatch({ k: "fill", f: json(m as MessageEvent) }));
      es.addEventListener("staged", (m) => dispatch({ k: "staged", d: json(m as MessageEvent) }));
      es.addEventListener("session", (m) => dispatch({ k: "session", d: json(m as MessageEvent) }));
      es.addEventListener("handoff", (m) => dispatch({ k: "handoff", d: json(m as MessageEvent) }));
      es.addEventListener("hedge_a", (m) => dispatch({ k: "hedge_a", d: json(m as MessageEvent) }));
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
            dispatch({ k: "error", message: "The backend did not find this bridge (404). Make sure that the bridge ID is correct." });
            dispatch({ k: "status", status: "stopped" });
          }
        }, () => {});
        dispatch({ k: "drop" });
        if (es && es.readyState === EventSource.CLOSED) { timer = setTimeout(connect, 2000); }
      };
    };
    connect();
    return () => { done = true; clearTimeout(timer); es?.close(); };
  }, [id]);
  return s;
}
