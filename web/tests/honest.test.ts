import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { aiLabel, aiStatus, aiTitle, classifiedByGemini, classifiedByLlm, classifyLead, fitNoun, mappingLabel, modelName, RULES_LABEL } from "../src/lib/ai.ts";
import { buildClientTools, callAgentTool, CONFIRM_TOOLS, ORB_FOR, replyForAgent, SECRET_REFUSED, startedBridgeId, VOICE_TOOLS, voiceEnabled, voicePhase } from "../src/lib/voice.ts";
import { WEEKEND_REPLAY, isRecordedOnly, isWeekendReplay, weekendPick, weekendQuestion } from "../src/lib/markets.ts";
import { hedgeTerms } from "../src/lib/realBridge.ts";
import { fitSteps, type PipeContext } from "../src/lib/pipeline.ts";
import type { FitOut, Market } from "../src/lib/api.ts";

const SRC = new URL("../src/", import.meta.url).pathname;
const files = (dir: string): string[] => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(f) ? [p] : [];
});

describe("no prototype simulator or sample data", () => {
  const all = files(SRC).map((p) => ({ p, s: readFileSync(p, "utf8") }));
  it("the demo data and simulator modules are gone", () => {
    assert.equal(existsSync(join(SRC, "lib/demo.ts")), false);
    assert.equal(existsSync(join(SRC, "lib/sim.ts")), false);
  });
  it("nothing imports them, seeds demo bridges, or offers a demo bridge", () => {
    const banned = [/lib\/demo["']/, /lib\/sim["']/, /\.\/demo(\.ts)?["']/, /\.\/sim(\.ts)?["']/, /seedDemo/, /addDemoBridge/, /stepSim|initSim|simPnl/,
      /Watch a demo bridge/i, /demo=1/, /kind: "demo"/, /DemoTag/, /\bQUESTIONS\b|demoImpacts|(?<!HEDGE_)INSTRUMENTS\(/];
    for (const { p, s } of all) for (const re of banned) assert.ok(!re.test(s), `${p.replace(SRC, "src/")} matches ${re}`);
  });
  it("no screen falls back to the prototype's numbers", () => {
    const banned = [/prototype.s (scripted|sample|simulator)/i, /showing samples/i, /sample hedge menu/i, /sample holdings/i, /scripted demo steps/i];
    for (const { p, s } of all) for (const re of banned) assert.ok(!re.test(s), `${p.replace(SRC, "src/")} matches ${re}`);
  });
  it("the landing's second button is the weekend replay", () => {
    const landing = readFileSync(join(SRC, "app/page.tsx"), "utf8");
    assert.match(landing, /Watch the weekend replay/);
    assert.match(landing, /openWeekendReplay/);
  });
});

describe("AI labels come from backend fields only", () => {
  it("says AI · Gemini <model> only when llm names Gemini or ai.live is true", () => {
    assert.deepEqual(aiStatus({ llm: "rules" }), { live: false, model: null });
    assert.equal(aiLabel(aiStatus({ llm: "rules" })), "Rules + C++ replay");
    assert.equal(aiLabel(aiStatus({ llm: "gemini:gemini-2.5-flash" })), "AI · Gemini 2.5 Flash");
    assert.equal(aiLabel(aiStatus({ llm: "gemini" })), "AI · Gemini");
    assert.equal(aiLabel(aiStatus({ llm: "rules", ai: { live: true, model: "gemini-2.5-flash", steps: { classify: "rules", explain: "gemini" } } })), "AI · Gemini 2.5 Flash");
    assert.equal(aiLabel(aiStatus({ llm: "rules", ai: { live: false, provider: "rules", model: null } })), RULES_LABEL);
    assert.equal(aiLabel(aiStatus(null)), RULES_LABEL);
    assert.equal(aiLabel(aiStatus({})), RULES_LABEL, "no field at all is not AI");
    assert.equal(aiLabel(aiStatus({ ai: { live: true } })), "AI · Gemini");
  });
  it("never uses the word AI in the rules label, and says what each step did", () => {
    assert.doesNotMatch(RULES_LABEL, /\bAI\b/);
    assert.doesNotMatch(aiTitle(aiStatus({ llm: "rules" })), /\bGemini\b/);
    assert.match(aiTitle(aiStatus({ llm: "rules", ai: { live: true, model: "gemini-2.5-flash", steps: { classify: "rules", explain: "gemini" } } })), /wrote the rationale/);
    assert.doesNotMatch(aiTitle(aiStatus({ llm: "rules", ai: { live: true, model: "m", steps: { classify: "rules", explain: "gemini" } } })), /classified/);
    assert.equal(fitNoun(aiStatus({ llm: "rules" })), "fit");
    assert.equal(fitNoun(aiStatus({ llm: "gemini:gemini-2.5-flash" })), "AI fit");
    assert.equal(modelName("models/gemini-2.5-flash-lite"), "2.5 Flash Lite");
  });
  it("labels OpenAI from the backend fields (same role as Gemini)", () => {
    const fit = { llm: "openai:gpt-5.6-sol", ai: { provider: "openai", model: "gpt-5.6-sol", live: true, steps: { classify: "openai", explain: "openai" } } };
    assert.equal(aiLabel(aiStatus(fit)), "AI · OpenAI gpt-5.6-sol");
    assert.equal(aiLabel(aiStatus({ llm: "openai:gpt-5.6-sol" })), "AI · OpenAI gpt-5.6-sol", "llm prefix alone");
    assert.equal(classifiedByLlm(fit), true);
    assert.equal(classifyLead(aiStatus(fit)), "OpenAI classifies the event");
    assert.match(aiTitle(aiStatus(fit)), /^OpenAI \(gpt-5\.6-sol\) classified the event and wrote the rationale/);
    assert.match(aiTitle(aiStatus(fit)), /The LLM did not select them/);
    const mixed = { llm: "openai:gpt-5.6-sol", ai: { provider: "gemini", model: "gemini-flash-lite-latest", live: true, steps: { classify: "openai", explain: "gemini" } } };
    assert.match(aiLabel(aiStatus(mixed)), /^AI · Gemini/);
    const partial = { llm: "rules", ai: { provider: "openai", model: "gpt-5.6-sol", live: true, steps: { classify: "rules", explain: "openai" } } };
    assert.equal(classifiedByLlm(partial), false);
    assert.doesNotMatch(aiTitle(aiStatus(partial)), /classified/);
    assert.equal(aiLabel(aiStatus({ llm: "rules", ai: { provider: "rules", live: false } })), RULES_LABEL);
    const ml = mappingLabel("ai_live:openai:gpt-5.6-sol")!;
    assert.equal(ml.text, "AI (OpenAI, live)");
    assert.match(ml.title, /^OpenAI \(gpt-5\.6-sol\)/);
    assert.equal(mappingLabel("ai_live:gemini:gemini-2.5-flash")!.text, "AI (Gemini, live)");
    assert.equal(modelName("gpt-5.6-sol", "openai"), "gpt-5.6-sol");
  });
  it("credits Gemini with the classification only when Gemini produced the event class", () => {
    const ctx: PipeContext = { question: "Will the Fed cut rates?", venues: ["Kalshi"], yes: 62, vol: "2.4M", ticker: "SPY", held: 10, move: -0.9, rev: 0, brand: 0, why: "" };
    const partial: FitOut = { event_class: "macro_fed", division: "hedge", family: "macro_fed_hedge", preset_index: 0, params: {}, score: null, alternatives: [], rationale: "Rules picked it.", llm: "rules", ticks_source: "replay", n_ticks: 700,
      ai: { provider: "gemini", model: "gemini-2.5-flash", live: true, steps: { classify: "rules", explain: "gemini" } } };
    const classifyText = fitSteps(partial, ctx).find((s) => s.key === "classify")!.text;
    assert.match(classifyText, /\(keyword rules\)/);
    assert.doesNotMatch(classifyText, /Gemini/);
    assert.equal(classifiedByGemini(partial), false);
    assert.equal(classifiedByGemini(aiStatus(partial)), false, "the store's AiStatus keeps the steps");
    assert.doesNotMatch(classifyLead(aiStatus(partial)), /Gemini classifies/);
    assert.match(aiLabel(aiStatus(partial)), /^AI · Gemini/, "the rationale did come from Gemini");
    const both: FitOut = { ...partial, llm: "gemini:gemini-2.5-flash", ai: { ...partial.ai, steps: { classify: "gemini", explain: "gemini" } } };
    assert.match(fitSteps(both, ctx).find((s) => s.key === "classify")!.text, /\(Gemini 2\.5 Flash\)/);
    assert.equal(classifyLead(aiStatus(both)), "Gemini classifies the event");
    assert.equal(classifiedByGemini({ llm: "gemini:gemini-2.5-flash" }), true);
    assert.equal(classifiedByGemini({ llm: "rules" }), false);
    assert.doesNotMatch(classifyLead({ live: true, model: "gemini-2.5-flash" }), /Gemini classifies/);
    assert.equal(classifyLead(aiStatus({ llm: "rules" })), "Keyword rules classify the event");
  });
  it("labels mappings by the backend's source: precomputed vs Gemini live, nothing for none", () => {
    assert.equal(mappingLabel("ai_precomputed")?.text, "AI estimate (precomputed)");
    assert.equal(mappingLabel("precomputed")?.text, "AI estimate (precomputed)", "older backend");
    assert.equal(mappingLabel("ai_live:gemini:gemini-2.5-flash")?.text, "AI (Gemini, live)");
    assert.match(mappingLabel("ai_live:gemini:gemini-2.5-flash")!.title, /gemini-2\.5-flash/);
    assert.equal(mappingLabel("none"), null);
    assert.equal(mappingLabel(null), null);
  });
});

describe("voice agent", () => {
  it("is hidden without an agent id", () => {
    assert.equal(voiceEnabled(undefined), false);
    assert.equal(voiceEnabled(""), false);
    assert.equal(voiceEnabled("   "), false);
    assert.equal(voiceEnabled("agent_123"), true);
    const btn = readFileSync(join(SRC, "components/voice/VoiceButton.tsx"), "utf8");
    assert.match(btn, /if \(!voiceEnabled\(agentId\)\) return null;/);
    assert.match(btn, /NEXT_PUBLIC_ELEVENLABS_AGENT_ID/);
  });
  it("uses the official React SDK with client tools, not the embed widget", () => {
    const agent = readFileSync(join(SRC, "components/voice/VoiceAgent.tsx"), "utf8");
    assert.match(agent, /from "@elevenlabs\/react"/);
    assert.match(agent, /useConversation\(/);
    assert.match(agent, /clientTools=\{clientTools\}/);
    assert.match(agent, /getUserMedia/);
    for (const p of files(SRC)) assert.ok(!/convai-widget-embed|elevenlabs-convai/.test(readFileSync(p, "utf8")), p);
  });
  it("posts the agent's arguments unchanged (confirm included) to /agent/tool/{name}, never with a secret", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fake = async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ ok: true, tool: "approve", summary: "Proposal p1 is approved.", data: { id: "p1" } }), { status: 200 });
    };
    const r = await callAgentTool("approve", { proposal_id: "p1", confirm: true }, fake, "http://localhost:8000");
    assert.equal(calls[0].url, "http://localhost:8000/agent/tool/approve");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { proposal_id: "p1", confirm: true });
    const headers = new Headers(calls[0].init?.headers);
    assert.equal(headers.has("x-agent-secret"), false);
    assert.deepEqual(r, { ok: true, tool: "approve", summary: "Proposal p1 is approved.", data: { id: "p1" } });
    await callAgentTool("start_bridge", { proposal_id: "p1", confirm: "true" }, fake, "http://x");
    assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { proposal_id: "p1", confirm: "true" });
  });
  it("turns failures into speakable replies and never throws", async () => {
    const r401 = await callAgentTool("account", {}, async () => new Response(JSON.stringify({ detail: "Missing or wrong X-Agent-Secret." }), { status: 401 }), "http://x");
    assert.deepEqual(r401, { ok: false, tool: "account", status: 401, summary: SECRET_REFUSED });
    const down = await callAgentTool("account", {}, async () => { throw new TypeError("fetch failed"); }, "http://x");
    assert.equal(down.ok, false);
    assert.match(down.summary, /cannot reach/);
    const gated = await callAgentTool("approve", { proposal_id: "p" }, async () => new Response(JSON.stringify({ ok: false, tool: "approve", summary: "I need your explicit yes.", needs_confirmation: true, data: null }), { status: 200 }), "http://x");
    assert.equal(gated.needs_confirmation, true);
  });
  it("registers one client tool per backend tool and reports start/end", async () => {
    const seen: string[] = [];
    const tools = buildClientTools(async (name) => ({ ok: true, tool: name, summary: `did ${name}`, data: name === "start_bridge" ? { bridge_id: "b9" } : null }),
      { onStart: (n) => seen.push(`start:${n}`), onEnd: (n) => seen.push(`end:${n}`) });
    assert.deepEqual(Object.keys(tools).sort(), [...VOICE_TOOLS].sort());
    assert.deepEqual([...CONFIRM_TOOLS].sort(), ["approve", "start_bridge"]);
    const out = await tools.start_bridge({ proposal_id: "p", confirm: true });
    assert.match(out, /^ok: true\nsummary: did start_bridge\ndata \(ids for your next tool call; do not read aloud\): \{"bridge_id":"b9"\}$/);
    assert.deepEqual(seen, ["start:start_bridge", "end:start_bridge"]);
    assert.equal(startedBridgeId("start_bridge", { ok: true, tool: "start_bridge", summary: "", data: { bridge_id: "b9" } }), "b9");
    assert.equal(startedBridgeId("start_bridge", { ok: false, tool: "start_bridge", summary: "", data: null }), null);
  });
  it("passes market ids back from a search (top five) so the agent can fit and propose", () => {
    const markets = Array.from({ length: 8 }, (_, i) => ({ source: "polymarket", id: String(i), token_id: `t${i}`, question: `Q${i}?`, yes_price: 0.5, volume_24h: 1, url: "u", end_date: null, recorded: null }));
    const out = replyForAgent({ ok: true, tool: "search_markets", summary: "I found 8 markets.", data: { markets, stale: false } });
    const data = JSON.parse(out.split("do not read aloud): ")[1]);
    assert.equal(data.markets.length, 5);
    assert.deepEqual(Object.keys(data.markets[0]).sort(), ["end_date", "id", "question", "recorded", "source", "token_id", "yes_price"].sort());
    assert.equal(replyForAgent({ ok: false, tool: "approve", summary: "Need a yes.", needs_confirmation: true }), "ok: false (needs the user's explicit yes)\nsummary: Need a yes.");
  });
  it("shows listening, thinking and speaking from the SDK status", () => {
    assert.equal(voicePhase({ status: "disconnected", isSpeaking: false, toolBusy: false }), "idle");
    assert.equal(voicePhase({ status: "disconnected", isSpeaking: false, toolBusy: false, askingMic: true }), "permission");
    assert.equal(voicePhase({ status: "connecting", isSpeaking: false, toolBusy: false }), "connecting");
    assert.equal(voicePhase({ status: "connected", isSpeaking: false, toolBusy: false }), "listening");
    assert.equal(voicePhase({ status: "connected", isSpeaking: true, toolBusy: false }), "speaking");
    assert.equal(voicePhase({ status: "connected", isSpeaking: true, toolBusy: true }), "thinking");
    assert.equal(voicePhase({ status: "error", isSpeaking: false, toolBusy: false }), "error");
    assert.equal(ORB_FOR.listening, "listening");
    assert.equal(ORB_FOR.thinking, "working");
    assert.equal(ORB_FOR.speaking, "composing");
  });
});

describe("weekend replay preset", () => {
  const row: Market = { source: "polymarket", id: "516710", question: "US recession in 2025?", yes_price: 0.005, volume_24h: 0, end_date: "2026-02-28T00:00:00Z", url: null, token_id: WEEKEND_REPLAY.token_id, recorded: WEEKEND_REPLAY.recorded };
  it("uses the backend's own search row when it returns one", () => {
    const q = weekendQuestion([{ ...row, id: "1", question: "Other?" }, row]);
    assert.equal(q.id, "polymarket:516710");
    assert.equal(q.real.yes_price, 0.005);
    assert.ok(isRecordedOnly(q.real, Date.parse("2026-10-03")));
    assert.deepEqual(q.touches, ["SPY"]);
  });
  it("falls back to the recording's identity with no invented price", () => {
    const q = weekendQuestion(null);
    assert.equal(q.real.id, "516710");
    assert.equal(q.real.token_id, WEEKEND_REPLAY.token_id);
    assert.equal(q.real.recorded, WEEKEND_REPLAY.recorded);
    assert.equal(q.real.yes_price, null);
    assert.ok(isWeekendReplay(q.real));
  });
  it("hedges SPY down on YES, labelled as the recording's direction, sized from the real holding", () => {
    const pick = weekendPick({ name: "SPDR S&P 500", spot: 571.2, shares: 300 });
    assert.equal(pick.t, "SPY");
    assert.equal(pick.direction, "down_on_yes");
    assert.equal(pick.directionSource, "recording");
    assert.equal(pick.move, 0, "no impact size is invented");
    assert.equal(pick.held, 300);
    assert.equal(weekendPick(null).held, 0);
    const t = hedgeTerms(weekendQuestion(null), weekendPick(null), "100%");
    assert.deepEqual(t.market, { source: "polymarket", id: "516710", token_id: WEEKEND_REPLAY.token_id });
    assert.equal(t.direction, "down_on_yes");
    assert.equal(t.shares_held, 500);
  });
});
