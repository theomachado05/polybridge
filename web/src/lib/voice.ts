// Voice agent plumbing (ElevenLabs React SDK client tools → our backend), kept pure so it is unit-tested offline.
//
// The agent's tools run in the browser: each client tool POSTs to the backend's POST /agent/tool/{name} on
// localhost. The browser never holds X-Agent-Secret. With AGENT_TOOL_SECRET set, the backend exempts /agent/tool/*
// only for a local request (loopback client, localhost Host, no proxy header) that carries the web app's Origin
// (backend/app/security.py is_local_web_app); the browser sets that Origin itself. Any local process could send the
// same header, so the secret protects tunnelled/remote callers only (docs/voice-agent.md "Security model"). The backend
// still refuses approve / start_bridge unless the agent sends confirm: true, which its prompt sets only after the
// user said yes; the client tool passes the agent's arguments through unchanged, confirm flag included.
import { API_URL } from "./api.ts";
import { navigateReply } from "./voiceDrive.ts";

export const VOICE_TOOLS = ["search_markets", "fit", "propose", "approve", "start_bridge", "bridge_status", "account", "positions", "navigate",
  "show_ladders", "show_tickets", "explain_ticket", "explain_mechanism", "what_we_tested"] as const;
/** Read-only tools for the micro-markets product (ladders, tickets, evidence): no confirmation, nothing is written. */
export const READ_ONLY_TOOLS: readonly VoiceToolName[] = ["show_ladders", "show_tickets", "explain_ticket", "explain_mechanism", "what_we_tested", "navigate", "bridge_status", "account", "positions", "search_markets", "fit"];
/** Tools the page answers itself, with no backend call (navigate: the screen moves, nothing is written). */
export const BROWSER_TOOLS: readonly VoiceToolName[] = ["navigate"];
export type VoiceToolName = (typeof VOICE_TOOLS)[number];
/** The tools the backend refuses without `confirm: true` (the user's spoken yes). */
export const CONFIRM_TOOLS: readonly VoiceToolName[] = ["approve", "start_bridge"];

/** The voice button renders only with an agent id (NEXT_PUBLIC_ELEVENLABS_AGENT_ID). */
export const voiceEnabled = (agentId: string | null | undefined): agentId is string => typeof agentId === "string" && agentId.trim().length > 0;

export interface ToolReply { ok: boolean; tool: string; summary: string; data?: unknown; needs_confirmation?: boolean; status?: number }

export const SECRET_REFUSED =
  "The backend rejected this call from the browser because the call needs the agent secret. The web app does not keep this secret. " +
  "Open the app on localhost. If the error continues, set the backend to accept local calls without the secret.";

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/** POST /agent/tool/{name} with the agent's arguments as a flat JSON body. Never throws: every failure is a
 *  speakable `{ok: false, summary}` (the backend's dispatcher answers the same way). No secret header, ever. */
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
  try { body = await res.json(); } catch { /* not JSON */ }
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

/** What the agent reads back: ok, the summary it speaks, and the data its next call needs (market ids from a search,
 *  the proposal id, the bridge id), marked as not for reading aloud. Search results are cut to the top five; any
 *  other data too long to pass keeps only its ids. */
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

/** One client tool per backend tool, for the SDK's `clientTools`. Arguments go through unchanged (confirm included).
 *  navigate never reaches the backend: the page answers it (lib/voiceDrive.ts) and moves the screen in onEnd. */
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

/** The bridge a successful start_bridge opened, to show it on screen. */
export function startedBridgeId(name: string, reply: ToolReply): string | null {
  if (name !== "start_bridge" || !reply.ok || !reply.data || typeof reply.data !== "object") return null;
  const id = (reply.data as { bridge_id?: unknown }).bridge_id;
  return typeof id === "string" && id ? id : null;
}

// ---------------------------------------------------------------- what the orb shows

export type VoicePhase = "idle" | "permission" | "connecting" | "listening" | "thinking" | "speaking" | "error";

/** The phase from the SDK's status ("disconnected" | "connecting" | "connected" | "error"), whether the agent is
 *  speaking (its mode), whether one of our tools is running, and whether the mic prompt is open. */
export function voicePhase(s: { status: string; isSpeaking: boolean; toolBusy: boolean; askingMic?: boolean; failed?: boolean }): VoicePhase {
  if (s.askingMic) return "permission";
  if (s.status === "connecting") return "connecting";
  if (s.status === "connected") return s.toolBusy ? "thinking" : s.isSpeaking ? "speaking" : "listening";
  if (s.status === "error" || s.failed) return "error";
  return "idle";
}

/** thinking-orb states (public/thinking-orbs.js): wave while listening, orbits while a tool runs, ribbon while speaking. */
export const ORB_FOR: Record<VoicePhase, string> = {
  idle: "breathing", permission: "connecting", connecting: "connecting", listening: "listening", thinking: "working", speaking: "composing", error: "breathing",
};

export const PHASE_LABEL: Record<VoicePhase, string> = {
  idle: "Talk to PolyBridge", permission: "Allow the microphone", connecting: "Connection starts…", listening: "Talk now",
  thinking: "Agent works…", speaking: "Agent talks", error: "Voice not available. Try again",
};

/** A readable reason for a failed microphone request (getUserMedia's DOMException names). */
export function micErrorText(e: unknown): string {
  const name = e && typeof e === "object" && "name" in e ? String((e as { name: unknown }).name) : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "The browser blocks the microphone. In the address bar, set the microphone to Allow for this site. Then try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "The app cannot find a microphone. Connect a microphone and try again.";
  if (name === "NotReadableError") return "Another app uses the microphone. Close that app and try again.";
  return "The app cannot open the microphone. Try again.";
}
