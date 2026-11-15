import type { CardState } from "@/components/CardArt";
import type { CardStatus } from "./types";

export const STATUS_TONE: Record<CardStatus, "gray" | "blue" | "green" | "amber" | "red"> = {
  generated: "gray", unassigned: "gray", reserved: "blue", assigned: "blue", active: "green", paused: "amber", archived: "gray", retired: "red", deactivated: "amber", lost: "red",
};

/** How a card's status reads in the UI: one dot colour, one plain-language label. */
export const CARD_STATUS: Record<CardStatus, { tone: "ok" | "info" | "warn" | "bad" | "idle"; label: string }> = {
  generated: { tone: "idle", label: "Generated" }, unassigned: { tone: "idle", label: "In stock" }, reserved: { tone: "info", label: "Reserved for you" },
  assigned: { tone: "info", label: "Assigned" }, active: { tone: "ok", label: "Live" }, paused: { tone: "warn", label: "Paused" },
  archived: { tone: "idle", label: "Archived" }, retired: { tone: "bad", label: "Retired" }, deactivated: { tone: "warn", label: "Deactivated" }, lost: { tone: "bad", label: "Reported lost" },
};

/** The order a card moves through, for filters and stock counts. */
export const CARD_LIFECYCLE: CardStatus[] = ["generated", "unassigned", "reserved", "assigned", "active", "paused", "archived", "retired"];

export const cardState = (s: CardStatus): CardState => (s === "active" || s === "assigned" ? "live" : s === "unassigned" || s === "generated" || s === "reserved" ? "unassigned" : "inactive");

/** A card resolves for customers only while assigned or active. */
export const isLive = (s: CardStatus) => s === "active" || s === "assigned";

/** Cards that belong to nobody (FlowHQ stock). */
export const isStock = (s: CardStatus) => s === "generated" || s === "unassigned" || s === "archived";

export async function copyText(t: string) {
  try { await navigator.clipboard.writeText(t); }
  catch { const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select(); document.execCommand("copy"); document.body.removeChild(a); }
}
