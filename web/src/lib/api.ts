// Mirrors docs/contracts.md (HTTP API). Change both together, by PR.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Family = "hedge" | "opportunity";
export type ProposalStatus = "proposed" | "approved" | "rejected";

export interface ClassifyOut {
  family: Family | null;
  strategy: string | null;
}

export interface Proposal {
  id: string;
  ticker: string;
  family: Family;
  strategy: string;
  shares_held: number;
  target_coverage: number;
  status: ProposalStatus;
  created_at: string;
  decided_at: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} failed with ${res.status}`);
  return res.json() as Promise<T>;
}

export const getHealth = () => request<{ status: string }>("/health");
export const listProposals = () => request<Proposal[]>("/proposals");
export const approveProposal = (id: string) => request<Proposal>(`/proposals/${id}/approve`, { method: "POST" });
