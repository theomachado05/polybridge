// Honest AI labels. The UI says "AI" only when the backend says an LLM actually answered: a fit's `llm` field
// ("gemini:<model>", or legacy "gemini") or its `ai` block (`ai.live`, docs/contracts.md "AI provenance"). Otherwise
// keyword rules and the C++ replay (hedgecore) did the work, and the label says exactly that, with no "AI" wording.
// Pure, so the labels are unit-tested offline.

/** What a backend response may say about the LLM: a fit (`llm`, `ai`) or a status block (`ai`). */
export interface AiSource {
  ai?: { live?: boolean | null; model?: string | null; provider?: string | null; cached?: boolean | null; steps?: { classify?: string | null; explain?: string | null } | null } | null;
  llm?: string | null;
  model?: string | null;
}
export interface AiStatus { live: boolean; model: string | null; steps?: { classify?: string | null; explain?: string | null } | null }

export const RULES_LABEL = "Rules + C++ replay";
export const NO_AI: AiStatus = { live: false, model: null };

/** Live when the backend says so: `ai.live` (Gemini answered for this response) or `llm` naming Gemini (it produced
 *  the event class, possibly served from the fit cache). Anything else, including no answer at all, is not AI. */
export function aiStatus(src: AiSource | null | undefined): AiStatus {
  if (!src) return NO_AI;
  const llm = typeof src.llm === "string" ? src.llm.trim() : "";
  const live = src.ai?.live === true || llm.toLowerCase().startsWith("gemini");
  if (!live) return NO_AI;
  const fromLlm = /^gemini:(.+)$/i.exec(llm)?.[1] ?? (/^gemini-/i.test(llm) ? llm : null);
  const model = src.ai?.model || src.model || fromLlm;
  return { live: true, model: model || null, ...(src.ai?.steps ? { steps: src.ai.steps } : {}) };
}

/** True only when Gemini produced the event class for this response: the backend's `ai.steps.classify` says
 *  "gemini", or (no steps given) `llm` names Gemini, which the backend sets only when Gemini classified. `ai.live`
 *  alone is not enough: it is also true when classify fell back to the keyword rules and only the rationale came from
 *  Gemini. Accepts a fit (`AiSource`) or an `AiStatus` (which keeps the steps when a fit supplied them). */
export function classifiedByGemini(src: AiSource | AiStatus | null | undefined): boolean {
  if (!src) return false;
  const steps = "ai" in src && src.ai && typeof src.ai === "object" ? src.ai.steps : (src as AiStatus).steps;
  if (steps && typeof steps.classify === "string") return steps.classify === "gemini";
  const llm = "llm" in src && typeof src.llm === "string" ? src.llm.trim().toLowerCase() : "";
  return llm.startsWith("gemini");
}

/** Who classifies the event, in running text, from what the backend has said so far: Gemini only when it produced the
 *  event class (`classifiedByGemini`); when Gemini answered but the classify step is unknown (or fell back to the
 *  rules), neutral wording that claims no Gemini classification; keyword rules when no LLM answered. */
export function classifyLead(st: AiStatus): string {
  if (classifiedByGemini(st)) return "Gemini classifies the event";
  if (st.live) return "Gemini helps to classify the event and explain the fit, and keyword rules do each step that Gemini does not do";
  return "Keyword rules classify the event";
}

/** "gemini-2.5-flash" → "2.5 Flash"; "models/gemini-2.5-flash-lite" → "2.5 Flash Lite". */
export function modelName(model: string): string {
  const bare = model.trim().replace(/^models\//i, "").replace(/^gemini-?/i, "");
  return bare.split("-").filter(Boolean).map((w) => (/^[a-z]/i.test(w) ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

/** "AI · Gemini 2.5 Flash" when an LLM answered, else "Rules + C++ replay". */
export function aiLabel(st: AiStatus): string {
  if (!st.live) return RULES_LABEL;
  const m = st.model ? modelName(st.model) : "";
  return `AI · Gemini${m ? ` ${m}` : ""}`;
}

/** Hover text for the fit label: what the LLM did (per the backend's `ai.steps` when given), and what it did not
 *  (the family and preset always come from the replay). */
export function aiTitle(st: AiStatus): string {
  if (!st.live) return "No LLM gave an answer. Keyword rules classified the event. The C++ engine (hedgecore) replayed the presets and selected the family and preset. A template wrote the rationale.";
  const did = st.steps
    ? [st.steps.classify === "gemini" ? "classified the event" : null, st.steps.explain === "gemini" ? "wrote the rationale from the structured result" : null].filter(Boolean).join(" and ")
    : "classified the event and wrote the rationale from the structured result";
  return `Gemini${st.model ? ` (${st.model})` : ""} ${did || "gave an answer"}. The C++ engine (hedgecore) replayed the presets and selected the family and preset. The LLM did not select them.`;
}

/** The word for a fitted algo in running text: "AI fit" only when an LLM took part. */
export const fitNoun = (st: AiStatus) => (st.live ? "AI fit" : "fit");

/** The label for a POST /map mapping, from its `source`: "ai_precomputed" (generated by an LLM ahead of time, the
 *  bundled library) or "ai_live:gemini:<model>" (Gemini, for this question, now). null when there is no mapping
 *  ("none"). Older backends said "precomputed". */
export function mappingLabel(source: string | null | undefined): { text: string; live: boolean; title: string } | null {
  const s = (source ?? "").trim().toLowerCase();
  if (!s || s === "none") return null;
  if (s.startsWith("ai_live") || s.startsWith("gemini") || s === "live") {
    const model = /gemini:(.+)$/.exec((source ?? "").trim())?.[1];
    return { text: "AI (Gemini, live)", live: true, title: `Gemini${model ? ` (${model})` : ""} made this mapping for this market and compared it with the list of known tickers. It is an estimate, not a measurement.` };
  }
  return { text: "AI estimate (precomputed)", live: false, title: "An LLM made this mapping before and the backend keeps it in its mapping library. It is an estimate, not a measurement." };
}
