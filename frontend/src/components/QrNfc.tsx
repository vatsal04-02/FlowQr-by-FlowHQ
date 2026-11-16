import { Status } from "@/components/ui/kit";
import { isLive } from "@/lib/card-ui";
import type { Card as CardT } from "@/lib/types";

/** Plain-language QR / NFC state. FlowQR doesn't track whether an NFC tag has been written, so it never claims that. */
export function QrNfc({ c }: { c: Pick<CardT, "status"> }) {
  const live = isLive(c.status);
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-0.5">
      <Status tone={live ? "ok" : "idle"}>QR {live ? "live" : c.status === "unassigned" || c.status === "generated" || c.status === "reserved" ? "not issued" : c.status === "retired" ? "retired" : "paused"}</Status>
      <Status tone={live ? "gold" : "idle"}>NFC {live ? "link ready" : c.status === "retired" ? "retired" : "paused"}</Status>
    </span>
  );
}
