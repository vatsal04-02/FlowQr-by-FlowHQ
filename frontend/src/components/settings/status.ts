import type { Integration } from "@/lib/agent";
import type { ChipKind } from "./parts";

/** What a connection's status says to an owner, in words. Colour is never the only signal. */
export const OWNER_WORD: Record<Integration["status"], { kind: ChipKind; label: string }> = {
  connected: { kind: "ok", label: "Connected" }, attention: { kind: "warn", label: "Needs attention" }, not_connected: { kind: "warn", label: "Not connected" },
  setup_required: { kind: "neutral", label: "Setup required" }, not_available: { kind: "neutral", label: "Not available yet" },
};
/** The same for the things FlowQR runs for the owner (email, AI, payments): nothing to set up on their side. */
export const MANAGED_WORD: Record<Integration["status"], { kind: ChipKind; label: string }> = {
  connected: { kind: "ok", label: "Working" }, attention: { kind: "warn", label: "Paused" }, not_connected: { kind: "neutral", label: "Being set up" },
  setup_required: { kind: "neutral", label: "Being set up" }, not_available: { kind: "neutral", label: "Being set up" },
};
