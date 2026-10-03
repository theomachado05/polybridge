"use client";

// The voice agent itself, on the official ElevenLabs React SDK (@elevenlabs/react): ConversationProvider +
// useConversation. Its client tools call our backend's POST /agent/tool/{name} from the browser (lib/voice.ts);
// the orb follows the SDK: listening (wave), thinking while one of our tools runs (orbits), speaking (ribbon).
import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { Orb } from "@/components/pb";
import { buildClientTools, CONFIRM_TOOLS, micErrorText, ORB_FOR, PHASE_LABEL, startedBridgeId, voicePhase, type ToolReply, type VoiceToolName } from "@/lib/voice";
import "./voice.css";

export function VoiceAgent({ agentId }: { agentId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(0);
  const [note, setNote] = useState<{ tone: "info" | "error"; text: string } | null>(null);

  // Stable for the provider's lifetime (the app router instance does not change); the hooks only touch state setters.
  const clientTools = useMemo(() => buildClientTools(undefined, {
    onStart: () => setBusy((n) => n + 1),
    onEnd: (name: VoiceToolName, reply: ToolReply) => {
      setBusy((n) => Math.max(0, n - 1));
      if (reply.needs_confirmation && CONFIRM_TOOLS.includes(name)) setNote({ tone: "info", text: "The agent needs your spoken “yes” before it approves or starts anything." });
      else if (!reply.ok && reply.status === 401) setNote({ tone: "error", text: reply.summary });
      const bridge = startedBridgeId(name, reply);
      if (bridge) router.push(`/bridge/${bridge}`);
    },
  }), [router]);

  return (
    <ConversationProvider agentId={agentId} clientTools={clientTools}
      onError={(message: string) => setNote({ tone: "error", text: `Voice error: ${message}` })}>
      <VoicePill toolBusy={busy > 0} note={note} setNote={setNote} />
    </ConversationProvider>
  );
}

function VoicePill({ toolBusy, note, setNote }: { toolBusy: boolean; note: { tone: "info" | "error"; text: string } | null; setNote: (n: { tone: "info" | "error"; text: string } | null) => void }) {
  const convo = useConversation();
  const [askingMic, setAskingMic] = useState(false);
  const [failed, setFailed] = useState(false);
  const phase = voicePhase({ status: convo.status, isSpeaking: convo.isSpeaking, toolBusy, askingMic, failed });
  const active = convo.status === "connected" || convo.status === "connecting";

  const start = useCallback(async () => {
    if (askingMic || active) return;
    setFailed(false);
    setNote(null);
    // Ask for the microphone first, so a refusal gets a clear message instead of a silent failed session.
    setAskingMic(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error("no mediaDevices"), { name: "NotFoundError" });
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
    } catch (e) {
      setAskingMic(false);
      setFailed(true);
      setNote({ tone: "error", text: micErrorText(e) });
      return;
    }
    setAskingMic(false);
    convo.startSession();
  }, [askingMic, active, convo, setNote]);

  const stop = useCallback(() => { convo.endSession(); setNote(null); }, [convo, setNote]);

  const label = PHASE_LABEL[phase];
  return (
    <div className="pb-voice" data-phase={phase}>
      {askingMic && <div className="pb-voice-note" role="status">Allow microphone access to talk to PolyBridge. Audio is used only during the call.</div>}
      {note && <div className="pb-voice-note" data-tone={note.tone} role={note.tone === "error" ? "alert" : "status"}>{note.text}</div>}
      {active && <button type="button" className="pb-voice-end" onClick={stop}>End call</button>}
      <button type="button" className="pb-voice-pill pb-navpill" onClick={active ? stop : () => void start()} aria-pressed={active} aria-label={active ? `${label}. End the call` : label}>
        <Orb state={ORB_FOR[phase]} size={28} />
        <span>{label}</span>
      </button>
    </div>
  );
}
