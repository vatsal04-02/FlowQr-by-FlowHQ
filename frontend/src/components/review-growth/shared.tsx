"use client";
import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtNum, fmtPct } from "@/lib/format";
import type { Campaign, FunnelStep } from "@/lib/review-growth";
import { useFetch } from "@/lib/use-api";

export const STATUS: Record<Campaign["status"], { label: string; tone: "ok" | "warn" | "idle" }> = {
  active: { label: "Active", tone: "ok" }, paused: { label: "Paused", tone: "warn" }, archived: { label: "Archived", tone: "idle" },
};
export const StatusBadge = ({ status }: { status: Campaign["status"] }) => <Status tone={STATUS[status].tone}>{STATUS[status].label}</Status>;

export const useCampaigns = (includeArchived = false) =>
  useFetch<Campaign[]>("/review-growth/campaigns", includeArchived ? { include_archived: "true" } : undefined);

/** Reads ?c=<campaign id> once, so sub-pages can deep-link to a campaign. */
export function useCampaignParam(): string {
  const [id, setId] = useState("");
  useEffect(() => { setId(new URLSearchParams(window.location.search).get("c") ?? ""); }, []);
  return id;
}

/** Campaign list plus the currently chosen one (deep-link ?c=, else the first non-archived). */
export function useSelectedCampaign() {
  const list = useCampaigns();
  const wanted = useCampaignParam();
  const [chosen, setChosen] = useState("");
  const campaigns = (list.data ?? []).filter((c) => c.status !== "archived");
  const selected = campaigns.find((c) => c.id === (chosen || wanted)) ?? campaigns[0] ?? null;
  return { ...list, campaigns, selected, choose: setChosen };
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button variant="secondary" size="sm" icon={done ? <Check className="h-4 w-4 text-ok" /> : <Copy className="h-4 w-4" />}
      onClick={async () => { try { await navigator.clipboard.writeText(value); setDone(true); setTimeout(() => setDone(false), 2000); } catch { /* clipboard blocked */ } }}>
      {done ? "Copied" : label}
    </Button>
  );
}

/** Ordered funnel bars. Rates are shown against the previous step and against QR scans. */
export function Funnel({ steps }: { steps: FunnelStep[] }) {
  const top = Math.max(1, steps[0]?.count ?? 1);
  return (
    <ol className="space-y-3.5">
      {steps.map((s, i) => (
        <li key={s.key}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
            <span className="font-medium">{s.label}</span>
            <span className="num shrink-0"><b className="font-semibold">{fmtNum(s.count)}</b>
              {i > 0 && <span className="ml-2 text-xs text-ink-500">{s.rate_of_previous === null ? "–" : fmtPct(s.rate_of_previous)} of previous</span>}</span>
          </div>
          <div className="h-5 overflow-hidden rounded bg-ink-100"><div className="h-full rounded bg-brand-600" style={{ width: `${Math.max((s.count / top) * 100, s.count ? 1.5 : 0)}%`, opacity: 1 - i * 0.14 }} /></div>
        </li>
      ))}
    </ol>
  );
}

/** Attach the Google review link used by all campaigns at a location: paste a link, or take the connected Business Profile's. */
export function ReviewLinkEditor({ locationId, current, source, googleAvailable, onSaved }: {
  locationId: string; current: string | null; source: string | null; googleAvailable: boolean; onSaved: () => void;
}) {
  const toast = useToast();
  const [url, setUrl] = useState(current ?? "");
  const [busy, setBusy] = useState<"manual" | "google" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setUrl(current ?? ""), [current]);

  async function save(body: { url?: string; use_google?: boolean }, kind: "manual" | "google") {
    setBusy(kind); setErr(null);
    try { await api(`/review-growth/locations/${locationId}/review-url`, { method: "POST", body }); toast("Google review link saved."); onSaved(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  return (
    <div className="space-y-3">
      <Input label="Google review link" inputMode="url" placeholder="https://g.page/r/…/review" value={url} onChange={(e) => setUrl(e.target.value)}
        hint={source ? `Currently ${source === "google" ? "taken from your connected Google Business Profile" : "entered manually"}.` : "Where customers land after they approve their review. Must be a Google link."} />
      {err && <Alert tone="error">{err}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" loading={busy === "manual"} disabled={!url.trim() || url.trim() === current} onClick={() => void save({ url: url.trim() }, "manual")}>Save link</Button>
        {googleAvailable && <Button size="sm" variant="secondary" loading={busy === "google"} onClick={() => void save({ use_google: true }, "google")}>Use my connected Google link</Button>}
      </div>
    </div>
  );
}
