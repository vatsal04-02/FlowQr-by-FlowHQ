"use client";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Status } from "@/components/ui/kit";
import { POST_LABEL, type PostItem } from "@/lib/agent";
import { useFetch } from "@/lib/use-api";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Month view of Google posts that are scheduled, published or failed, in the business's time zone. */
export function PostCalendar() {
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const first = useMemo(() => { const d = new Date(month); d.setDate(1 - ((d.getDay() + 6) % 7)); return d; }, [month]);
  const last = useMemo(() => { const d = new Date(first); d.setDate(d.getDate() + 41); return d; }, [first]);
  const { data, error, loading } = useFetch<{ timezone: string; days: Record<string, { id: string; summary: string; status: PostItem["status"]; at: string }[]> }>("/posts/calendar", { from: iso(first), to: iso(last) });
  const cells = Array.from({ length: 42 }, (_, i) => { const d = new Date(first); d.setDate(d.getDate() + i); return d; });
  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <button type="button" aria-label="Previous month" className="tap grid place-items-center rounded-lg border border-ink-200 bg-white" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft className="h-4 w-4" /></button>
        <h2 className="text-sm font-semibold">{month.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</h2>
        <button type="button" aria-label="Next month" className="tap grid place-items-center rounded-lg border border-ink-200 bg-white" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight className="h-4 w-4" /></button>
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-64" /> : (
        <div className="overflow-x-auto"><div role="grid" aria-label="Post calendar" className="grid min-w-[640px] grid-cols-7 gap-px overflow-hidden rounded-xl border border-ink-100 bg-ink-100">
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} role="columnheader" className="bg-ink-50 px-2 py-1.5 text-xs font-medium text-ink-500">{d}</div>)}
          {cells.map((d) => {
            const items = data?.days[iso(d)] ?? [];
            const inMonth = d.getMonth() === month.getMonth();
            return (
              <div key={iso(d)} role="gridcell" className={`min-h-[84px] bg-white p-1.5 ${inMonth ? "" : "opacity-50"}`}>
                <p className="text-xs text-ink-500">{d.getDate()}</p>
                {items.map((p) => <p key={p.id} title={p.summary} className="mt-1 truncate rounded bg-ink-50 px-1 py-0.5 text-[11px]"><Status tone={POST_LABEL[p.status].tone} className="!text-[11px]">{p.status === "published" ? "Published" : POST_LABEL[p.status].label}</Status></p>)}
              </div>);
          })}
        </div></div>)}
      <p className="mt-2 text-xs text-ink-500">Times shown in {data?.timezone ?? "your time zone"}. Only posts that are approved, scheduled, published or failed appear here.</p>
    </div>
  );
}
