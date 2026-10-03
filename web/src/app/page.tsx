"use client";

import { useCallback, useEffect, useState } from "react";
import { approveProposal, getHealth, listProposals, type Proposal } from "@/lib/api";

export default function Home() {
  const [status, setStatus] = useState("checking");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      setStatus((await getHealth()).status);
      setProposals(await listProposals());
      setError(null);
    } catch (e) {
      setStatus("offline");
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const approve = useCallback(async (id: string) => {
    setPending((s) => new Set(s).add(id));
    try {
      await approveProposal(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await listProposals().then(setProposals, () => {});  // show the real state (e.g. already decided)
    } finally {
      setPending((s) => { const n = new Set(s); n.delete(id); return n; });
    }
  }, [refresh]);

  // Initial fetch on mount: syncs state with an external system (the API).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-6">
      <h1 className="text-3xl font-semibold">PolyBridge</h1>
      <p>Backend: <strong>{status}</strong></p>
      {error && <p className="text-red-600">Backend error: {error}. If it is not running, start it with <code>make setup-backend</code> and <code>uv run uvicorn app.main:app</code>.</p>}
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Hedge proposals</h2>
        {proposals.length === 0 && <p>No proposals yet. POST one to /proposals.</p>}
        {proposals.map((p) => (
          <div key={p.id} className="flex items-center justify-between rounded border p-3">
            <span>{p.ticker} · {p.strategy} · {p.status}</span>
            {p.status === "proposed" && (
              <button className="rounded border px-3 py-1 disabled:opacity-50" disabled={pending.has(p.id)} onClick={() => void approve(p.id)}>
                Approve
              </button>
            )}
          </div>
        ))}
      </section>
    </main>
  );
}
