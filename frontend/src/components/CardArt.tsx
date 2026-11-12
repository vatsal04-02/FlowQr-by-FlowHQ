import clsx from "clsx";
import { Poster } from "./marketing/Poster";

export type CardState = "live" | "inactive" | "unassigned";

/**
 * The FlowQR card as it is sold: the real poster artwork, muted when the card is paused or not yet assigned.
 * The QR on the artwork is a sample, so this is a preview of the product, never a scannable code. The real,
 * scannable QR for a card is downloaded from its detail page.
 */
export function FlowCard({ code, state = "live", className }: { code?: string; state?: CardState; className?: string }) {
  const dim = state !== "live";
  return (
    <div className={clsx("relative w-full", className)}>
      <div style={{ filter: "drop-shadow(0 14px 18px rgba(23,23,25,.22))" }}>
        <Poster muted={dim} alt={`FlowQR card${code ? ` ${code}` : ""}${dim ? (state === "unassigned" ? ", not assigned" : ", inactive") : ""}`} />
      </div>
      {dim && <span className="absolute left-1/2 top-[44%] -translate-x-1/2 whitespace-nowrap rounded-md bg-ink px-2.5 py-1 text-xs font-medium text-white">{state === "unassigned" ? "Not assigned" : "Inactive"}</span>}
    </div>
  );
}
