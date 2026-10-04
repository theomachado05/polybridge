"use client";

// "Talk to PolyBridge": the ElevenLabs voice agent (official React SDK, @elevenlabs/react). Renders nothing unless
// NEXT_PUBLIC_ELEVENLABS_AGENT_ID is set; the SDK is loaded only then, in the browser (dynamic import, no SSR).
import dynamic from "next/dynamic";
import { voiceEnabled } from "@/lib/voice";

const AGENT_ID = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID;
const VoiceAgent = dynamic(() => import("./VoiceAgent").then((m) => m.VoiceAgent), { ssr: false });

export function VoiceButton({ agentId = AGENT_ID }: { agentId?: string }) {
  if (!voiceEnabled(agentId)) return null;
  return <VoiceAgent agentId={agentId.trim()} />;
}
