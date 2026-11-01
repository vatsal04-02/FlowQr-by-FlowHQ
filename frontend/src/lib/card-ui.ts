import type { CardStatus } from "./types";

export const STATUS_TONE: Record<CardStatus, "gray" | "blue" | "green" | "amber" | "red"> = {
  unassigned: "gray", assigned: "blue", active: "green", deactivated: "amber", lost: "red",
};

export async function copyText(t: string) {
  try { await navigator.clipboard.writeText(t); }
  catch { const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select(); document.execCommand("copy"); document.body.removeChild(a); }
}
