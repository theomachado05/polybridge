"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { Orb } from "@/components/pb";
import type { Market } from "@/lib/api";
import { useStore, type Store } from "@/lib/store";
import { buildClientTools, CONFIRM_TOOLS, micErrorText, ORB_FOR, PHASE_LABEL, voicePhase, type ToolReply, type VoiceToolName } from "@/lib/voice";
import { searchedMarkets, voiceDrive, voiceStartLabel } from "@/lib/voiceDrive";
import "./voice.css";

function scrollWhenReady(id: string, timeoutMs = 6000) {
  const until = Date.now() + timeoutMs;
  const tick = () => {
    const el = document.getElementById(id);
    if (el) {
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      return;
    }
    if (Date.now() < until) setTimeout(tick, 150);
  };
  setTimeout(tick, 120);
}

const live: { store: Store | null; markets: Market[] } = { store: null, markets: [] };

function driveScreen(name: VoiceToolName, params: Record<string, unknown>, reply: ToolReply, push: (route: string) => void): string {
  const d = voiceDrive(name, params, reply, live.markets);
  if (name === "search_markets" && reply.ok) live.markets = searchedMarkets(reply);
  void (async () => {
    if (d.storeUpdate && live.store) await live.store.applyVoice(d.storeUpdate).catch(() => {});
    if (d.route && window.location.pathname !== d.route) push(d.route);
    if (d.scrollTo) scrollWhenReady(d.scrollTo);
  })();
  return d.announcement;
}

export function VoiceAgent({ agentId }: { agentId: string }) {
  const router = useRouter();
  const store = useStore();
  useEffect(() => { live.store = store; });
  const [busy, setBusy] = useState(0);
  const [note, setNote] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [drive, setDrive] = useState<string | null>(null);

  const clientTools = useMemo(() => buildClientTools(undefined, {
    onStart: (name: VoiceToolName, params: Record<string, unknown>) => {
      setBusy((n) => n + 1);
      setDrive(voiceStartLabel(name, params));
    },
    onEnd: (name: VoiceToolName, reply: ToolReply, params: Record<string, unknown>) => {
      setBusy((n) => Math.max(0, n - 1));
      if (reply.needs_confirmation && CONFIRM_TOOLS.includes(name)) setNote({ tone: "info", text: "The agent waits for your spoken “yes” before it approves or starts an item." });
      else if (!reply.ok && reply.status === 401) setNote({ tone: "error", text: reply.summary });
      setDrive(driveScreen(name, params, reply, (route) => router.push(route)));
    },
  }), [router]);

  return (
    <ConversationProvider agentId={agentId} clientTools={clientTools}
      onError={(message: string) => setNote({ tone: "error", text: `Voice error: ${message}` })}>
      <VoicePill toolBusy={busy > 0} note={note} setNote={setNote} drive={drive} setDrive={setDrive} />
    </ConversationProvider>
  );
}

function VoicePill({ toolBusy, note, setNote, drive, setDrive }: {
  toolBusy: boolean; note: { tone: "info" | "error"; text: string } | null; setNote: (n: { tone: "info" | "error"; text: string } | null) => void;
  drive: string | null; setDrive: (d: string | null) => void;
}) {
  const convo = useConversation();
  const [askingMic, setAskingMic] = useState(false);
  const [failed, setFailed] = useState(false);
  const phase = voicePhase({ status: convo.status, isSpeaking: convo.isSpeaking, toolBusy, askingMic, failed });
  const active = convo.status === "connected" || convo.status === "connecting";

  const start = useCallback(async () => {
    if (askingMic || active) return;
    setFailed(false);
    setNote(null);
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

  const stop = useCallback(() => { convo.endSession(); setNote(null); setDrive(null); }, [convo, setNote, setDrive]);

  const label = PHASE_LABEL[phase];
  return (
    <div className="pb-voice" data-phase={phase}>
      {active && drive && (
        <div className="pb-voice-drive" role="status" aria-live="polite" data-busy={toolBusy || undefined}>
          <span className="pb-voice-drive-k">Voice control</span>
          <span className="pb-voice-drive-t">{drive}</span>
        </div>
      )}
      {askingMic && <div className="pb-voice-note" role="status">Click Allow in the browser to talk to PolyBridge. The app uses audio only during the call.</div>}
      {note && <div className="pb-voice-note" data-tone={note.tone} role={note.tone === "error" ? "alert" : "status"}>{note.text}</div>}
      {active && <button type="button" className="pb-voice-end" onClick={stop}>End call</button>}
      <button type="button" className="pb-voice-pill pb-navpill" onClick={active ? stop : () => void start()} aria-pressed={active} aria-label={active ? `${label}. End the call` : label}>
        <Orb state={ORB_FOR[phase]} size={28} />
        <span>{label}</span>
      </button>
    </div>
  );
}
