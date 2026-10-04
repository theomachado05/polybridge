// Honest AI labels. The UI says "AI" only when the backend says an LLM actually answered: a fit's `llm` field
// ("openai:<model>" / "gemini:<model>", or legacy "gemini") or its `ai` block (`ai.live`, `ai.provider`,
// docs/contracts.md "AI provenance"). Which LLM (OpenAI or Gemini) comes only from those backend fields; an `ai` block
// without a provider is legacy Gemini. Otherwise keyword rules and the C++ replay (hedgecore) did the work, and the
// label says exactly that, with no "AI" wording. Pure, so the labels are unit-tested offline.

/** What a backend response may say about the LLM: a fit (`llm`, `ai`) or a status block (`ai`). */
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

/** The display name of a provider: "OpenAI" or "Gemini". */
export const providerName = (p: LlmProvider | undefined) => (p === "openai" ? "OpenAI" : "Gemini");

/** Live when the backend says so: `ai.live` (an LLM answered for this response) or `llm` naming OpenAI or Gemini (it
 *  produced the event class, possibly served from the fit cache). Anything else, including no answer, is not AI.
 *  The provider is `ai.provider` when it names an LLM, else the `llm` prefix, else Gemini (older backends). */
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

/** True only when an LLM (OpenAI or Gemini) produced the event class for this response: the backend's
 *  `ai.steps.classify` says "openai" / "gemini", or (no steps given) `llm` names one, which the backend sets only when
 *  that LLM classified. `ai.live` alone is not enough: it is also true when classify fell back to the keyword rules and
 *  only the rationale came from the LLM. Accepts a fit (`AiSource`) or an `AiStatus` (which keeps the steps). */
export function classifiedByLlm(src: AiSource | AiStatus | null | undefined): boolean {
  if (!src) return false;
  const steps = "ai" in src && src.ai && typeof src.ai === "object" ? src.ai.steps : (src as AiStatus).steps;
  if (steps && typeof steps.classify === "string") return isLlmStep(steps.classify);
  const llm = "llm" in src && typeof src.llm === "string" ? src.llm.trim() : "";
  return LLM_RE.test(llm);
}
/** Former name, kept for callers: true for OpenAI as well as Gemini. */
export const classifiedByGemini = classifiedByLlm;

/** Who classifies the event, in running text, from what the backend has said so far: the LLM only when it produced
 *  the event class (`classifiedByLlm`); when it answered but the classify step is unknown (or fell back to the rules),
 *  neutral wording that claims no LLM classification; keyword rules when no LLM answered. */
export function classifyLead(st: AiStatus): string {
  const who = providerName(st.provider);
  if (classifiedByLlm(st)) return `${who} classifies the event`;
  if (st.live) return `${who} helps to classify the event and explain the fit, and keyword rules do each step that ${who} does not do`;
  return "Keyword rules classify the event";
}

/** "gemini-2.5-flash" → "2.5 Flash"; "models/gemini-2.5-flash-lite" → "2.5 Flash Lite". OpenAI ids are shown as
 *  given ("gpt-5.6-sol"): they are not Gemini-style names. */
export function modelName(model: string, provider: LlmProvider = "gemini"): string {
  if (provider === "openai") return model.trim();
  const bare = model.trim().replace(/^models\//i, "").replace(/^gemini-?/i, "");
  return bare.split("-").filter(Boolean).map((w) => (/^[a-z]/i.test(w) ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

/** "AI · OpenAI gpt-5.6-sol" / "AI · Gemini 2.5 Flash" when an LLM answered, else "Rules + C++ replay". */
export function aiLabel(st: AiStatus): string {
  if (!st.live) return RULES_LABEL;
  const m = st.model ? modelName(st.model, st.provider) : "";
  return `AI · ${providerName(st.provider)}${m ? ` ${m}` : ""}`;
}

/** Hover text for the fit label: what the LLM did (per the backend's `ai.steps` when given), and what it did not
 *  (the family and preset always come from the replay). */
export function aiTitle(st: AiStatus): string {
  if (!st.live) return "No LLM gave an answer. Keyword rules classified the event. The C++ engine (hedgecore) replayed the presets and selected the family and preset. A template wrote the rationale.";
  const did = st.steps
    ? [isLlmStep(st.steps.classify) ? "classified the event" : null, isLlmStep(st.steps.explain) ? "wrote the rationale from the structured result" : null].filter(Boolean).join(" and ")
    : "classified the event and wrote the rationale from the structured result";
  return `${providerName(st.provider)}${st.model ? ` (${st.model})` : ""} ${did || "gave an answer"}. The C++ engine (hedgecore) replayed the presets and selected the family and preset. The LLM did not select them.`;
}

/** The word for a fitted algo in running text: "AI fit" only when an LLM took part. */
export const fitNoun = (st: AiStatus) => (st.live ? "AI fit" : "fit");

/** The label for a POST /map mapping, from its `source`: "ai_precomputed" (generated by an LLM ahead of time, the
 *  bundled library) or "ai_live:<openai|gemini>:<model>" (that LLM, for this question, now). null when there is no
 *  mapping ("none"). Older backends said "precomputed". */
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
