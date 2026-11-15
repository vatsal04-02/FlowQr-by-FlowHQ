"use client";
import clsx from "clsx";
import { Clock, Globe, MapPin, Phone, Plus, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { Gate } from "./tools";

interface Period { day: string; open: string; close: string }
interface Info { title: string | null; description: string | null; phone: string | null; website: string | null; primary_category: { id: string; name: string } | null; additional_categories: { id: string; name: string }[]; hours: Period[] }

const DAYS: [string, string][] = [["MONDAY", "Mon"], ["TUESDAY", "Tue"], ["WEDNESDAY", "Wed"], ["THURSDAY", "Thu"], ["FRIDAY", "Fri"], ["SATURDAY", "Sat"], ["SUNDAY", "Sun"]];
const FULL = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"];
const time12 = (t: string) => { const [h, m] = t.split(":").map(Number); if (Number.isNaN(h)) return t; return `${((h + 11) % 12) + 1}${m ? `:${String(m).padStart(2, "0")}` : ""} ${h < 12 ? "am" : "pm"}`; };
const field = "min-h-11 rounded-lg border border-ink-300 bg-white px-2 text-sm sm:min-h-9";

/**
 * Profile editor: description, category and a Monday–Sunday hours grid, beside a preview of how it reads on Google. Same data and same
 * save call as before. `part` shows only Business info (description + category) or only Opening hours (PRD §5.2); only changed fields are sent.
 */
export function ProfileEditor({ gid, part = "all" }: { gid: string; part?: "all" | "info" | "hours" }) {
  const showInfo = part !== "hours", showHours = part !== "info";
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Info>(`/gbp/${gid}/info`);
  const [desc, setDesc] = useState("");
  const [hours, setHours] = useState<Period[]>([]);
  const [primary, setPrimary] = useState<{ id: string; name: string } | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  useEffect(() => { if (data) { setDesc(data.description ?? ""); setHours(data.hours); setPrimary(data.primary_category); } }, [data]);

  async function search() { try { setResults(await api(`/gbp/${gid}/categories`, { params: { q } })); } catch (e) { toast(errorMessage(e), "error"); } }
  async function save() {
    setBusy(true); setSaveErr(null);
    try {
      const body: Record<string, unknown> = {};
      if (desc !== (data?.description ?? "")) body.description = desc;
      if (JSON.stringify(hours) !== JSON.stringify(data?.hours)) body.hours = hours;
      if (primary && primary.id !== data?.primary_category?.id) body.primary_category = primary.id;
      if (!Object.keys(body).length) { toast("Nothing changed."); return; }
      await api(`/gbp/${gid}/info`, { method: "PATCH", body });
      toast("Saved on Google."); await reload();
    } catch (e) { setSaveErr(errorMessage(e)); } finally { setBusy(false); }
  }

  if (loading && !data) return <Skeleton className="h-96" />;
  if (error) return <Gate error={error} />;

  const dirty = !!data && (desc !== (data.description ?? "") || JSON.stringify(hours) !== JSON.stringify(data.hours) || (primary?.id ?? null) !== (data.primary_category?.id ?? null));
  const idx = (day: string) => hours.map((h, i) => [h, i] as const).filter(([h]) => h.day === day);
  const setAt = (i: number, patch: Partial<Period>) => setHours(hours.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const copyMonday = (days: string[]) => {
    const mon = hours.filter((h) => h.day === "MONDAY");
    setHours([...hours.filter((h) => !days.includes(h.day)), ...days.flatMap((d) => mon.map((p) => ({ ...p, day: d })))]);
  };
  const todayName = FULL[new Date().getDay()];
  const today = hours.filter((h) => h.day === todayName);
  const left = 750 - desc.length;

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="space-y-5">
        {showInfo && <>
        <section aria-labelledby="desc-h" className="panel p-5 sm:p-6">
          <div className="flex items-baseline justify-between gap-2"><h2 id="desc-h" className="text-lg font-semibold">About your business</h2><span className={clsx("num text-xs", left < 50 ? "font-semibold text-amber-800" : "text-ink-500")} aria-live="polite">{desc.length}/750</span></div>
          <textarea aria-labelledby="desc-h" rows={6} maxLength={750} value={desc} disabled={!isAdmin} onChange={(e) => setDesc(e.target.value)} placeholder="What you do, where, and who you help."
            className="mt-3 w-full rounded-inner border border-transparent bg-surface-2 p-4 text-sm leading-relaxed hover:border-ink-200 disabled:opacity-70" />
          <p className="mt-1.5 text-[13px] text-ink-500">No prices, phone numbers or links. Google may reject them.</p>
        </section>

        <section aria-labelledby="cat-h" className="panel p-5 sm:p-6">
          <h2 id="cat-h" className="text-lg font-semibold">Main category</h2>
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-sm"><span className="rounded-full bg-navy px-3 py-1 text-[13px] font-semibold text-white">{primary?.name ?? "Not set"}</span>
            {data?.additional_categories.map((c) => <span key={c.id} className="rounded-full bg-ink-100/70 px-2.5 py-1 text-[13px] text-ink-700">{c.name}</span>)}</p>
          {isAdmin && (
            <div className="mt-3">
              <div className="flex gap-2"><div className="relative flex-1"><Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
                <input aria-label="Search categories" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void search(); }} placeholder="Search, e.g. physiotherapist" className={clsx(field, "w-full pl-9")} /></div>
                <Button variant="secondary" onClick={() => void search()} disabled={!q.trim()}>Search</Button></div>
              {results.length > 0 && <ul className="mt-2 flex flex-wrap gap-1.5">{results.map((c) => <li key={c.id}><button type="button" onClick={() => { setPrimary(c); setResults([]); }} className="min-h-11 rounded-full bg-brand-50 px-3 text-sm font-medium text-navy ring-1 ring-brand-200 hover:bg-brand-100 sm:min-h-9">{c.name}</button></li>)}</ul>}
            </div>)}
        </section>
        </>}

        {showHours && <section aria-labelledby="hours-h" className="panel p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="hours-h" className="text-lg font-semibold">Opening hours</h2>
            {isAdmin && <div className="flex gap-1.5 text-[13px]"><button type="button" onClick={() => copyMonday(["TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"])} className="min-h-11 rounded-full px-3 font-semibold text-brand-700 hover:bg-brand-50 sm:min-h-8">Copy Monday to Tue–Fri</button>
              <button type="button" onClick={() => copyMonday(DAYS.slice(1).map(([d]) => d))} className="min-h-11 rounded-full px-3 font-semibold text-brand-700 hover:bg-brand-50 sm:min-h-8">to every day</button></div>}</div>
          <ul className="mt-2 divide-y divide-ink-100">
            {DAYS.map(([day, short]) => {
              const rows = idx(day);
              return (
                <li key={day} className="grid grid-cols-[3rem_minmax(0,1fr)] items-start gap-x-2 py-2.5">
                  <span className={clsx("pt-2 text-sm font-semibold", day === todayName ? "text-brand-700" : "text-navy")}>{short}</span>
                  <div className="flex flex-wrap items-center gap-2">
                    {rows.length === 0 && <span className="rounded-full bg-ink-100/70 px-3 py-1.5 text-[13px] font-medium text-ink-500">Closed</span>}
                    {rows.map(([h, i]) => (
                      <span key={i} className="inline-flex items-center gap-1 rounded-lg bg-brand-50 p-1 ring-1 ring-brand-100">
                        <input aria-label={`${short} opens`} type="time" disabled={!isAdmin} value={h.open} onChange={(e) => setAt(i, { open: e.target.value })} className={clsx(field, "w-[5.6rem] px-1.5 text-[13px]")} />
                        <span aria-hidden className="text-ink-400">–</span>
                        <input aria-label={`${short} closes`} type="time" disabled={!isAdmin} value={h.close} onChange={(e) => setAt(i, { close: e.target.value })} className={clsx(field, "w-[5.6rem] px-1.5 text-[13px]")} />
                        {isAdmin && <button type="button" aria-label={`Remove ${short} ${time12(h.open)} to ${time12(h.close)}`} onClick={() => setHours(hours.filter((_, j) => j !== i))} className="grid h-11 w-9 place-items-center rounded-md text-ink-500 hover:bg-white hover:text-red-700 sm:h-9"><X className="h-4 w-4" aria-hidden /></button>}
                      </span>))}
                    {isAdmin && <button type="button" onClick={() => setHours([...hours, { day, open: "09:00", close: "18:00" }])} title="Add a break or second period" className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-full px-3 text-[13px] font-semibold text-brand-700 hover:bg-brand-50 sm:min-h-9 sm:min-w-9"><Plus className="h-3.5 w-3.5" aria-hidden />{rows.length ? <span className="sr-only">Add break</span> : "Open this day"}</button>}
                  </div>
                </li>);
            })}
          </ul>
        </section>}
      </div>

      <aside aria-label="How your profile looks on Google" className="space-y-4 lg:sticky lg:top-4">
        <div className="keep-light overflow-hidden rounded-card bg-white shadow-card">
          <p className="border-b border-ink-100 bg-brand-50 px-4 py-2 text-[13px] font-semibold text-brand-800">Preview: how customers see you on Google</p>
          <div className="p-4">
            <h3 className="text-lg font-bold leading-tight text-navy">{data?.title ?? "Your business"}</h3>
            <p className="mt-0.5 text-sm text-ink-500">{primary?.name ?? "Add a category"}</p>
            <p className="mt-3 line-clamp-5 text-sm leading-relaxed text-ink-700">{desc || <span className="text-ink-400">Your description shows here.</span>}</p>
            <ul className="mt-4 space-y-2.5 border-t border-ink-100 pt-3 text-sm text-navy">
              <li className="flex gap-2.5"><Clock className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" aria-hidden /><span>{today.length ? <><b>Today</b> · {today.map((p) => `${time12(p.open)} – ${time12(p.close)}`).join(", ")}</> : <><b>Today</b> · Closed</>}</span></li>
              {data?.phone && <li className="flex gap-2.5"><Phone className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" aria-hidden />{data.phone}</li>}
              {data?.website && <li className="flex gap-2.5"><Globe className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" aria-hidden /><span className="min-w-0 break-all">{data.website.replace(/^https?:\/\//, "")}</span></li>}
              {!data?.phone && !data?.website && <li className="flex gap-2.5 text-ink-500"><MapPin className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" aria-hidden />Phone and website come from your Google profile.</li>}
            </ul>
          </div>
        </div>
        {saveErr && <Alert tone="error" title="Google didn't accept the change">{saveErr}. Nothing was changed.</Alert>}
        {isAdmin && <Button size="lg" className="w-full" loading={busy} disabled={!dirty} onClick={() => void save()}>{dirty ? "Save to Google" : "No changes to save"}</Button>}
      </aside>
    </div>
  );
}
