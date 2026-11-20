"use client";
import { useState } from "react";
import { Alert, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { useFetch } from "@/lib/use-api";
import { type WaAttribution } from "@/lib/whatsapp";

const clock = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "");

/** Which ads and page buttons your WhatsApp chats come from. Counts only: no customer is named here. */
export default function AdSources() {
  const [days, setDays] = useState(90);
  const q = useFetch<WaAttribution>(`/whatsapp/attribution?days=${days}`);
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Ad sources" subtitle="Which ads and page buttons your WhatsApp chats come from, and how many of those customers booked. Part of the WhatsApp Pro add-on." />
      {!d ? (q.error ? <Alert tone="info" title="Not available">Ad tracking is part of the Pro add-on and is not switched on for everyone yet.</Alert> : <Skeleton className="h-40" />) : (
        <Card>
          <CardHeader title={`Last ${days} days`} subtitle={`${d.from_ads_or_posts} of ${d.conversations_in_period} chats started from an ad or your page.`} />
          <div className="mb-3 flex gap-1.5" role="group" aria-label="Period">{[30, 90, 180].map((n) => <button key={n} type="button" aria-pressed={days === n} onClick={() => setDays(n)} className={`rounded-full border px-3 py-1 text-[13px] ${days === n ? "border-brand-500 bg-brand-50" : "border-ink-200"}`}>{n} days</button>)}</div>
          {d.window_note && <div className="mb-3"><Alert tone="info" title="Free window not checked yet">{d.window_note}</Alert></div>}
          {d.sources.length === 0 ? <EmptyState title="No ad chats yet">When a customer starts a chat from an ad or your page button, it shows up here.</EmptyState> : (
            <ul className="divide-y divide-ink-100">{d.sources.map((s) => (
              <li key={`${s.type}${s.id}`} className="py-2.5 text-sm" data-testid="source"><b className="text-ink">{s.headline ?? (s.type === "ad" ? "An ad" : "Your page")}</b><span className="ml-2 text-[12px] text-ink-500">{s.type === "ad" ? "Ad" : "Page"}{s.id ? ` ${s.id}` : ""}</span>
                <p className="text-ink-700">{s.conversations} chat{s.conversations === 1 ? "" : "s"} · {s.customers_who_booked} booked · last {clock(s.last_at)}</p></li>))}</ul>)}
        </Card>)}
    </div>
  );
}
