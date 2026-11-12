import type { CardState } from "@/components/CardArt";
import type { CardStatus } from "./types";

export const STATUS_TONE: Record<CardStatus, "gray" | "blue" | "green" | "amber" | "red"> = {
  unassigned: "gray", assigned: "blue", active: "green", deactivated: "amber", lost: "red", paused: "amber",
};

/** How a card's status reads in the UI: one dot colour, one plain-language label. */
export const CARD_STATUS: Record<CardStatus, { tone: "ok" | "info" | "warn" | "bad" | "idle"; label: string }> = {
  unassigned: { tone: "idle", label: "Not assigned" }, assigned: { tone: "info", label: "Assigned" }, active: { tone: "ok", label: "Live" },
  deactivated: { tone: "warn", label: "Deactivated" }, lost: { tone: "bad", label: "Reported lost" }, paused: { tone: "warn", label: "Paused" },
};

export const cardState = (s: CardStatus): CardState => (s === "active" || s === "assigned" ? "live" : s === "unassigned" ? "unassigned" : "inactive");

/** A card resolves for customers only while assigned or active. */
export const isLive = (s: CardStatus) => s === "active" || s === "assigned";

export async function copyText(t: string) {
  try { await navigator.clipboard.writeText(t); }
  catch { const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select(); document.execCommand("copy"); document.body.removeChild(a); }
}
