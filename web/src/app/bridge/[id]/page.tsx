"use client";

import { useParams } from "next/navigation";
import { BridgeScreen } from "@/components/bridge/BridgeScreen";

export default function BridgeByIdPage() {
  const { id } = useParams<{ id: string }>();
  return <BridgeScreen routeBridgeId={id} />;
}
