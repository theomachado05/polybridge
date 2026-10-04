import { API_URL } from "./api.ts";
import { navigateReply } from "./voiceDrive.ts";

export const VOICE_TOOLS = ["search_markets", "fit", "propose", "approve", "start_bridge", "bridge_status", "account", "positions", "navigate",
  "show_ladders", "show_tickets", "explain_ticket", "explain_mechanism", "what_we_tested"] as const;
export const READ_ONLY_TOOLS: readonly VoiceToolName[] = ["show_ladders", "show_tickets", "explain_ticket", "explain_mechanism", "what_we_tested", "navigate", "bridge_status", "account", "positions", "search_markets", "fit"];
export const BROWSER_TOOLS: readonly VoiceToolName[] = ["navigate"];
export type VoiceToolName = (typeof VOICE_TOOLS)[number];
export const CONFIRM_TOOLS: readonly VoiceToolName[] = ["approve", "start_bridge"];

export const voiceEnabled = (agentId: string | null | undefined): agentId is string => typeof agentId === "string" && agentId.trim().length > 0;

export interface ToolReply { ok: boolean; tool: string; summary: string; data?: unknown; needs_confirmation?: boolean; status?: number }

export const SECRET_REFUSED =
  "The backend rejected this call from the browser because the call needs the agent secret. The web app does not keep this secret. " +
  "Open the app on localhost. If the error continues, set the backend to accept local calls without the secret.";

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export async function callAgentTool(name: string, params: Record<string, unknown> | null | undefined,
  fetchImpl: Fetch = (i, init) => fetch(i, init), base: string = API_URL): Promise<ToolReply> {
  let res: Response;
  try {
    res = await fetchImpl(`${base}/agent/tool/${encodeURIComponent(name)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params ?? {}), cache: "no-store",
    });
  } catch {
    return { ok: false, tool: name, summary: "I cannot reach the PolyBridge backend right now. Is it running?" };
  }
  if (res.status === 401) return { ok: false, tool: name, status: 401, summary: SECRET_REFUSED };
  let body: unknown = null;
  try { body = await res.json(); } catch { }
  const b = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  if (!res.ok) {
    const detail = typeof b.detail === "string" ? b.detail : `the backend answered ${res.status}`;
    return { ok: false, tool: name, status: res.status, summary: `That did not work: ${detail}.` };
  }
  return {
    ok: b.ok === true, tool: typeof b.tool === "string" ? b.tool : name,
    summary: typeof b.summary === "string" ? b.summary : "The backend answered without a summary.",
    data: b.data, ...(b.needs_confirmation === true ? { needs_confirmation: true } : {}),
  };
}

const MAX_REPLY = 6000;
const IDS = ["filter", "above", "ticket", "mechanisms", "id", "proposal_id", "bridge_id", "status", "source", "ticker", "family", "preset_index", "event_class", "score", "llm"];

export function replyForAgent(r: ToolReply): string {
  let data = r.data;
  if (r.tool === "search_markets" && data && typeof data === "object" && Array.isArray((data as { markets?: unknown }).markets)) {
    data = { markets: ((data as { markets: Record<string, unknown>[] }).markets).slice(0, 5).map((m) => ({
      source: m.source, id: m.id, token_id: m.token_id, question: m.question, yes_price: m.yes_price, end_date: m.end_date, recorded: m.recorded })) };
  }
  const head = `ok: ${r.ok}${r.needs_confirmation ? " (needs the user's explicit yes)" : ""}\nsummary: ${r.summary}`;
  if (data == null) return head;
  let json = JSON.stringify(data);
  if (json.length > MAX_REPLY) {
    const d = typeof data === "object" && !Array.isArray(data) ? (data as Record<string, unknown>) : {};
    json = JSON.stringify(Object.fromEntries(IDS.filter((k) => k in d && (d[k] == null || typeof d[k] !== "object")).map((k) => [k, d[k]])));
  }
  return `${head}\ndata (ids for your next tool call; do not read aloud): ${json}`;
}

export interface ToolHooks {
  onStart?: (name: VoiceToolName, params: Record<string, unknown>) => void;
  onEnd?: (name: VoiceToolName, reply: ToolReply, params: Record<string, unknown>) => void;
}

export function buildClientTools(call: typeof callAgentTool = callAgentTool, hooks: ToolHooks = {}):
  Record<VoiceToolName, (params: Record<string, unknown>) => Promise<string>> {
  const entries = VOICE_TOOLS.map((name) => [name, async (params: Record<string, unknown>) => {
    const args = params ?? {};
    hooks.onStart?.(name, args);
    let reply: ToolReply;
    try { reply = BROWSER_TOOLS.includes(name) ? navigateReply(args) : await call(name, args); }
    catch { reply = { ok: false, tool: name, summary: "Something went wrong in the browser. Please try again." }; }
    hooks.onEnd?.(name, reply, args);
    return replyForAgent(reply);
  }] as const);
  return Object.fromEntries(entries) as Record<VoiceToolName, (params: Record<string, unknown>) => Promise<string>>;
}

export function startedBridgeId(name: string, reply: ToolReply): string | null {
  if (name !== "start_bridge" || !reply.ok || !reply.data || typeof reply.data !== "object") return null;
  const id = (reply.data as { bridge_id?: unknown }).bridge_id;
  return typeof id === "string" && id ? id : null;
}

export type VoicePhase = "idle" | "permission" | "connecting" | "listening" | "thinking" | "speaking" | "error";

export function voicePhase(s: { status: string; isSpeaking: boolean; toolBusy: boolean; askingMic?: boolean; failed?: boolean }): VoicePhase {
  if (s.askingMic) return "permission";
  if (s.status === "connecting") return "connecting";
  if (s.status === "connected") return s.toolBusy ? "thinking" : s.isSpeaking ? "speaking" : "listening";
  if (s.status === "error" || s.failed) return "error";
  return "idle";
}

export const ORB_FOR: Record<VoicePhase, string> = {
  idle: "breathing", permission: "connecting", connecting: "connecting", listening: "listening", thinking: "working", speaking: "composing", error: "breathing",
};

export const PHASE_LABEL: Record<VoicePhase, string> = {
  idle: "Talk to PolyBridge", permission: "Allow the microphone", connecting: "Connection starts…", listening: "Talk now",
  thinking: "Agent works…", speaking: "Agent talks", error: "Voice not available. Try again",
};

export function micErrorText(e: unknown): string {
  const name = e && typeof e === "object" && "name" in e ? String((e as { name: unknown }).name) : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "The browser blocks the microphone. In the address bar, set the microphone to Allow for this site. Then try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "The app cannot find a microphone. Connect a microphone and try again.";
  if (name === "NotReadableError") return "Another app uses the microphone. Close that app and try again.";
  return "The app cannot open the microphone. Try again.";
}
