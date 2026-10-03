"use client";

import { useParams } from "next/navigation";
import { BridgeScreen } from "@/components/bridge/BridgeScreen";

/** A backend engine bridge by id (live or replay over SSE), shown in the multi-bridge screen. */
export default function BridgeByIdPage() {
  const { id } = useParams<{ id: string }>();
  return <BridgeScreen routeBridgeId={id} />;
}
