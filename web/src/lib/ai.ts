export interface AiSource {
  ai?: { live?: boolean | null; model?: string | null; provider?: string | null; cached?: boolean | null; steps?: { classify?: string | null; explain?: string | null } | null } | null;
  llm?: string | null;
  model?: string | null;
}
export type LlmProvider = "openai" | "gemini";
export interface AiStatus { live: boolean; model: string | null; provider?: LlmProvider; steps?: { classify?: string | null; explain?: string | null } | null }

export const RULES_LABEL = "Rules + C++ replay";
export const NO_AI: AiStatus = { live: false, model: null };

const LLM_RE = /^(openai|gemini)\b/i;
const isLlmStep = (v: unknown) => typeof v === "string" && LLM_RE.test(v);

export const providerName = (p: LlmProvider | undefined) => (p === "openai" ? "OpenAI" : "Gemini");

export function aiStatus(src: AiSource | null | undefined): AiStatus {
  if (!src) return NO_AI;
  const llm = typeof src.llm === "string" ? src.llm.trim() : "";
  const fromLlmProvider = LLM_RE.exec(llm)?.[1]?.toLowerCase() as LlmProvider | undefined;
  const live = src.ai?.live === true || !!fromLlmProvider;
  if (!live) return NO_AI;
  const declared = (src.ai?.provider ?? "").toLowerCase();
  const provider: LlmProvider = declared === "openai" || declared === "gemini" ? declared : fromLlmProvider ?? "gemini";
  const fromLlm = /^(?:openai|gemini):(.+)$/i.exec(llm)?.[1] ?? (/^gemini-/i.test(llm) ? llm : null);
  const model = src.ai?.model || src.model || fromLlm;
  return { live: true, model: model || null, provider, ...(src.ai?.steps ? { steps: src.ai.steps } : {}) };
}

export function classifiedByLlm(src: AiSource | AiStatus | null | undefined): boolean {
  if (!src) return false;
  const steps = "ai" in src && src.ai && typeof src.ai === "object" ? src.ai.steps : (src as AiStatus).steps;
  if (steps && typeof steps.classify === "string") return isLlmStep(steps.classify);
  const llm = "llm" in src && typeof src.llm === "string" ? src.llm.trim() : "";
  return LLM_RE.test(llm);
}
export const classifiedByGemini = classifiedByLlm;

export function classifyLead(st: AiStatus): string {
  const who = providerName(st.provider);
  if (classifiedByLlm(st)) return `${who} classifies the event`;
  if (st.live) return `${who} helps to classify the event and explain the fit, and keyword rules do each step that ${who} does not do`;
  return "Keyword rules classify the event";
}

export function modelName(model: string, provider: LlmProvider = "gemini"): string {
  if (provider === "openai") return model.trim();
  const bare = model.trim().replace(/^models\//i, "").replace(/^gemini-?/i, "");
  return bare.split("-").filter(Boolean).map((w) => (/^[a-z]/i.test(w) ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

export function aiLabel(st: AiStatus): string {
  if (!st.live) return RULES_LABEL;
  const m = st.model ? modelName(st.model, st.provider) : "";
  return `AI · ${providerName(st.provider)}${m ? ` ${m}` : ""}`;
}

export function aiTitle(st: AiStatus): string {
  if (!st.live) return "No LLM gave an answer. Keyword rules classified the event. The C++ engine (hedgecore) replayed the presets and selected the family and preset. A template wrote the rationale.";
  const did = st.steps
    ? [isLlmStep(st.steps.classify) ? "classified the event" : null, isLlmStep(st.steps.explain) ? "wrote the rationale from the structured result" : null].filter(Boolean).join(" and ")
    : "classified the event and wrote the rationale from the structured result";
  return `${providerName(st.provider)}${st.model ? ` (${st.model})` : ""} ${did || "gave an answer"}. The C++ engine (hedgecore) replayed the presets and selected the family and preset. The LLM did not select them.`;
}

export const fitNoun = (st: AiStatus) => (st.live ? "AI fit" : "fit");

export function mappingLabel(source: string | null | undefined): { text: string; live: boolean; title: string } | null {
  const s = (source ?? "").trim().toLowerCase();
  if (!s || s === "none") return null;
  if (s.startsWith("ai_live") || s.startsWith("gemini") || s.startsWith("openai") || s === "live") {
    const hit = /(openai|gemini):(.+)$/i.exec((source ?? "").trim());
    const who = providerName(hit?.[1]?.toLowerCase() === "openai" ? "openai" : "gemini");
    const model = hit?.[2];
    return { text: `AI (${who}, live)`, live: true, title: `${who}${model ? ` (${model})` : ""} made this mapping for this market and compared it with the list of known tickers. It is an estimate, not a measurement.` };
  }
  return { text: "AI estimate (precomputed)", live: false, title: "An LLM made this mapping before and the backend keeps it in its mapping library. It is an estimate, not a measurement." };
}
