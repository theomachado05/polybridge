"use client";

// "Talk to PolyBridge": a glass pill that opens the ElevenLabs Conversational AI widget.
// Renders nothing unless NEXT_PUBLIC_ELEVENLABS_AGENT_ID is set; the widget script (official CDN) loads on first click.
import { useCallback, useEffect, useState } from "react";
import { Orb } from "@/components/pb";
import "./voice.css";

const AGENT_ID = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID;
const WIDGET_SRC = "https://unpkg.com/@elevenlabs/convai-widget-embed";
const SCRIPT_ID = "elevenlabs-convai-embed";

function loadWidgetScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      if (customElements.get("elevenlabs-convai")) resolve();
      else {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener("error", () => reject(new Error("widget script failed")), { once: true });
      }
      return;
    }
    const s = document.createElement("script");
    s.id = SCRIPT_ID;
    s.src = WIDGET_SRC;
    s.async = true;
    s.type = "text/javascript";
    s.onload = () => resolve();
    s.onerror = () => {
      s.remove(); // let a later click retry
      reject(new Error("widget script failed"));
    };
    document.head.appendChild(s);
  });
}

type Phase = "idle" | "loading" | "listening" | "error";

export function VoiceButton({ agentId = AGENT_ID }: { agentId?: string }) {
  const [phase, setPhase] = useState<Phase>("idle");

  const toggle = useCallback(async () => {
    if (phase === "listening") return setPhase("idle");
    if (phase === "loading") return;
    setPhase("loading");
    try {
      await loadWidgetScript();
      setPhase("listening");
    } catch {
      setPhase("error");
    }
  }, [phase]);

  useEffect(() => {
    if (phase !== "error") return;
    const t = setTimeout(() => setPhase("idle"), 4000);
    return () => clearTimeout(t);
  }, [phase]);

  if (!agentId) return null;

  const label =
    phase === "listening" ? "Listening. Tap to hide"
    : phase === "loading" ? "Connecting"
    : phase === "error" ? "Voice unavailable. Retry"
    : "Talk to PolyBridge";
  const orbState = phase === "listening" ? "listening" : phase === "loading" ? "connecting" : "breathing";

  return (
    <div className="pb-voice" data-phase={phase}>
      {phase === "listening" ? <elevenlabs-convai agent-id={agentId} variant="expanded" /> : null}
      <button type="button" className="pb-voice-pill pb-navpill" onClick={toggle} aria-pressed={phase === "listening"} aria-label={label}>
        <Orb state={orbState} size={28} />
        <span>{label}</span>
      </button>
    </div>
  );
}
