"use client";
import { ImagePlus, Lock, Megaphone, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { ErrorSummary, Input, Select, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useForm } from "@/lib/form";
import type { GoogleConnection, GoogleLocation } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];
const TABS = [["info", "Business info"], ["posts", "Posts"], ["media", "Photos"], ["performance", "Performance"]] as const;
type Tab = (typeof TABS)[number][0];

/** Why a profile tool isn't available: plan limit, server not configured for Google yet, or a real failure. */
function Gate({ error }: { error: string }) {
  const upgrade = /plan|subscription/i.test(error);
  const pending = /awaiting configuration|not configured|configuration pending/i.test(error);
  if (/hasn.t approved FlowQR|awaiting .*approval/i.test(error)) return <Alert tone="warning" title="Awaiting Google approval">Google hasn&rsquo;t granted FlowQR Business Profile API access yet, so this tool is unavailable and nothing was changed. Your QR/NFC cards, review links and AI writing assistant keep working.</Alert>;
  if (/not enabled on FlowQR/i.test(error)) return <Alert tone="warning" title="A Google API is switched off for FlowQR">{error} Contact FlowQR support; this is fixed on FlowQR&rsquo;s side.</Alert>;
  if (/10 profile edits per minute/i.test(error)) return <Alert tone="warning" title="Slow down a little">{error}</Alert>;
  if (pending) return <Alert tone="warning" title="Configuration pending">Google Business Profile tools need Google API access, which isn&rsquo;t configured on this server yet. Your QR/NFC cards, review links and AI writing assistant work without it.</Alert>;
  return <Alert tone={upgrade ? "info" : "error"} title={upgrade ? "Not included in your plan" : "Couldn't load from Google"} action={upgrade ? <LinkButton href="/subscription" size="sm" variant="secondary">View plans</LinkButton> : undefined}>{error}</Alert>;
}

export default function ProfilePage() {
  const status = useFetch<{ connections: GoogleConnection[] }>("/google/status");
  const active = status.data?.connections.find((c) => c.status === "active");
  const locs = useFetch<GoogleLocation[]>(active ? `/google/connections/${active.id}/locations` : null);
  const selected = useMemo(() => locs.data?.filter((l) => l.selected) ?? [], [locs.data]);
  const [gid, setGid] = useState("");
  const [tab, setTab] = useState<Tab>("info");
  useEffect(() => { if (!gid && selected[0]) setGid(selected[0].id); }, [selected, gid]);

  return (
    <>
      <PageHeader eyebrow="Business" title="Google profile" subtitle="Update what customers see on Google. Changes go straight to your Google Business Profile." />
      {status.loading && !status.data ? <Skeleton className="h-40" /> : !active || (locs.data && selected.length === 0) ? (
        <EmptyState icon={<Lock className="h-6 w-6" />} title="Connect Google to manage your profile" action={<LinkButton href="/google">Go to Google connection</LinkButton>}>Profile tools need a connected Google Business Profile and at least one selected location.</EmptyState>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-end gap-3">
            <div className="min-w-[220px]"><Select label="Location" value={gid} onChange={(e) => setGid(e.target.value)}>{selected.map((l) => <option key={l.id} value={l.id}>{l.title}</option>)}</Select></div>
          </div>
          <div role="tablist" aria-label="Profile sections" className="mb-5 flex gap-1 overflow-x-auto border-b border-ink-100">
            {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`tap shrink-0 border-b-2 px-4 text-sm font-semibold ${tab === k ? "border-brand-600 text-brand-700" : "border-transparent text-ink-500"}`}>{l}</button>)}
          </div>
          {gid && tab === "info" && <InfoTab key={gid} gid={gid} />}
          {gid && tab === "posts" && <PostsTab key={gid} gid={gid} />}
          {gid && tab === "media" && <MediaTab key={gid} gid={gid} />}
          {gid && tab === "performance" && <PerfTab key={gid} gid={gid} />}
        </>
      )}
    </>
  );
}

interface Info { title: string | null; description: string | null; phone: string | null; website: string | null; primary_category: { id: string; name: string } | null; additional_categories: { id: string; name: string }[]; hours: { day: string; open: string; close: string }[] }

function InfoTab({ gid }: { gid: string }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Info>(`/gbp/${gid}/info`);
  const [desc, setDesc] = useState("");
  const [hours, setHours] = useState<Info["hours"]>([]);
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

  if (loading && !data) return <Skeleton className="h-64" />;
  if (error) return <Gate error={error} />;
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card><CardHeader title="Description" subtitle="Shown on your Google profile (max 750 characters)" />
        <Textarea label="Business description" rows={7} maxLength={750} value={desc} disabled={!isAdmin} onChange={(e) => setDesc(e.target.value)} hint={`${desc.length}/750 · Don't use promotional prices, phone numbers or links; Google may reject them.`} />
      </Card>
      <Card><CardHeader title="Category" subtitle="Your primary category affects where you appear in search" />
        <p className="mb-3 text-sm">Primary: <b>{primary?.name ?? "not set"}</b>{data?.additional_categories.length ? <span className="text-ink-500"> · also {data.additional_categories.map((c) => c.name).join(", ")}</span> : null}</p>
        {isAdmin && <><div className="flex gap-2"><input aria-label="Search categories" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search e.g. physiotherapist" className="min-h-11 flex-1 rounded-xl border border-ink-200 px-3 text-sm" /><Button variant="secondary" onClick={() => void search()} disabled={q.trim().length < 2}>Search</Button></div>
          <ul className="mt-2 space-y-1">{results.map((c) => <li key={c.id}><button onClick={() => { setPrimary(c); setResults([]); }} className="tap w-full rounded-lg px-3 text-left text-sm hover:bg-ink-50">{c.name}</button></li>)}</ul></>}
      </Card>
      <Card className="lg:col-span-2"><CardHeader title="Opening hours" subtitle="24-hour times. Add one row per opening period." />
        <ul className="space-y-2">{hours.map((h, i) => (
          <li key={i} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-2 sm:grid-cols-[180px_130px_130px_auto]">
            <select aria-label="Day" disabled={!isAdmin} value={h.day} onChange={(e) => setHours(hours.map((x, j) => j === i ? { ...x, day: e.target.value } : x))} className="min-h-11 rounded-xl border border-ink-200 bg-white px-2 text-sm">{DAYS.map((d) => <option key={d}>{d}</option>)}</select>
            <input aria-label="Opens" type="time" disabled={!isAdmin} value={h.open} onChange={(e) => setHours(hours.map((x, j) => j === i ? { ...x, open: e.target.value } : x))} className="min-h-11 rounded-xl border border-ink-200 px-2 text-sm" />
            <input aria-label="Closes" type="time" disabled={!isAdmin} value={h.close} onChange={(e) => setHours(hours.map((x, j) => j === i ? { ...x, close: e.target.value } : x))} className="min-h-11 rounded-xl border border-ink-200 px-2 text-sm" />
            {isAdmin && <Button variant="ghost" size="sm" aria-label="Remove period" icon={<Trash2 className="h-4 w-4" />} onClick={() => setHours(hours.filter((_, j) => j !== i))} />}
          </li>))}</ul>
        {isAdmin && <Button className="mt-3" variant="secondary" size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setHours([...hours, { day: "MONDAY", open: "09:00", close: "18:00" }])}>Add hours</Button>}
        {hours.length === 0 && <p className="mt-2 text-sm text-ink-500">No regular hours set on Google.</p>}
      </Card>
      {saveErr && <div className="lg:col-span-2"><Alert tone="error" title="Google didn't accept the change">{saveErr}. Nothing was changed.</Alert></div>}
      {isAdmin && <div className="flex justify-end lg:col-span-2"><Button size="lg" loading={busy} onClick={() => void save()}>Save to Google</Button></div>}
    </div>
  );
}

interface Post { name: string; summary: string; state: string | null; created_at: string | null; cta_type: string | null; search_url?: string | null }

function PostsTab({ gid }: { gid: string }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Post[]>(`/gbp/${gid}/posts`);
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<{ name: string; text: string } | null>(null);
  async function saveEdit() {
    if (!edit || edit.text.trim().length < 10) { toast("Write at least 10 characters", "error"); return; }
    try { await api(`/gbp/${gid}/posts`, { method: "PATCH", params: { name: edit.name }, body: { summary: edit.text.trim() } }); toast("Post updated on Google."); setEdit(null); await reload(); }
    catch (er) { toast(errorMessage(er), "error"); }
  }
  const f = useForm({ summary: "", cta_type: "", cta_url: "", photo_url: "" }, {
    summary: (v) => (String(v).trim().length >= 10 ? undefined : "Write at least 10 characters"),
    cta_url: (v, all) => (all.cta_type && all.cta_type !== "CALL" && !String(v).startsWith("https://") ? "Buttons need an https:// link" : undefined),
    photo_url: (v) => (!v || String(v).startsWith("https://") ? undefined : "Use an https:// photo link"),
  });
  async function create(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try { const v = f.values; await api(`/gbp/${gid}/posts`, { method: "POST", body: { summary: v.summary.trim(), cta_type: v.cta_type || null, cta_url: v.cta_url || null, photo_url: v.photo_url || null } }); toast("Post published on Google."); f.setValues({ summary: "", cta_type: "", cta_url: "", photo_url: "" }); await reload(); }
    catch (er) { f.fail(errorMessage(er)); } finally { setBusy(false); }
  }
  if (error) return <Gate error={error} />;
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
      {isAdmin && <Card><CardHeader title="New post" subtitle="Appears on your Google profile and Maps listing" />
        <form onSubmit={create} noValidate className="space-y-4">
          <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
          <Textarea label="What's new?" rows={5} maxLength={1500} {...f.bind("summary")} />
          <Select label="Button (optional)" {...f.bind("cta_type")}><option value="">No button</option><option value="LEARN_MORE">Learn more</option><option value="BOOK">Book</option><option value="ORDER">Order online</option><option value="SHOP">Shop</option><option value="SIGN_UP">Sign up</option><option value="CALL">Call now</option></Select>
          {f.values.cta_type && f.values.cta_type !== "CALL" && <Input label="Button link" inputMode="url" placeholder="https://…" {...f.bind("cta_url")} />}
          <Input label="Photo link (optional)" inputMode="url" placeholder="https://…/photo.jpg" {...f.bind("photo_url")} />
          <Button type="submit" loading={busy} icon={<Megaphone className="h-4 w-4" />}>Publish post</Button>
        </form></Card>}
      <Card className={isAdmin ? "" : "lg:col-span-2"}><CardHeader title="Your posts on Google" />
        {loading && !data ? <Skeleton className="h-32" /> : data && data.length === 0 ? <p className="text-sm text-ink-500">No posts yet.</p> : (
          <ul className="divide-y divide-ink-100">{data?.map((p) => (
            <li key={p.name} className="flex gap-3 py-3"><div className="min-w-0 flex-1">{edit?.name === p.name
                ? <div className="space-y-2"><Textarea label="Edit post" rows={4} maxLength={1500} value={edit.text} onChange={(e) => setEdit({ name: p.name, text: e.target.value })} /><div className="flex gap-2"><Button size="sm" onClick={() => void saveEdit()}>Save to Google</Button><Button size="sm" variant="secondary" onClick={() => setEdit(null)}>Cancel</Button></div></div>
                : <p className="whitespace-pre-wrap text-sm">{p.summary}</p>}<p className="mt-1 flex gap-2 text-xs text-ink-500">{p.state && <Badge tone={p.state === "LIVE" ? "green" : "gray"}>{p.state.toLowerCase()}</Badge>}{p.cta_type && <span>button: {p.cta_type.toLowerCase().replace("_", " ")}</span>}</p></div>
              {isAdmin && <Button variant="ghost" size="sm" aria-label="Edit post" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit({ name: p.name, text: p.summary })} />}
              {isAdmin && <Button variant="ghost" size="sm" aria-label="Delete post" icon={<Trash2 className="h-4 w-4 text-red-600" />} onClick={async () => { if (confirm("Delete this post from Google?")) { try { await api(`/gbp/${gid}/posts`, { method: "DELETE", params: { name: p.name } }); toast("Post deleted."); void reload(); } catch (e) { toast(errorMessage(e), "error"); } } }} />}</li>))}</ul>)}
      </Card>
    </div>
  );
}

interface Media { name: string; category: string | null; url: string | null; thumbnail: string | null }

function MediaTab({ gid }: { gid: string }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Media[]>(`/gbp/${gid}/media`);
  const [url, setUrl] = useState(""); const [cat, setCat] = useState("ADDITIONAL"); const [busy, setBusy] = useState(false);
  if (error) return <Gate error={error} />;
  return (
    <>
      {isAdmin && <Card className="mb-5"><CardHeader title="Add a photo" subtitle="Google fetches the image from a public https link. Use photos you own." />
        <div className="grid gap-3 sm:grid-cols-[1fr_200px_auto] sm:items-end">
          <Input label="Photo link" inputMode="url" placeholder="https://…/front-desk.jpg" value={url} onChange={(e) => setUrl(e.target.value)} error={url && !url.startsWith("https://") ? "Must start with https://" : undefined} />
          <Select label="Category" value={cat} onChange={(e) => setCat(e.target.value)}>{["ADDITIONAL", "COVER", "PROFILE", "LOGO", "EXTERIOR", "INTERIOR", "AT_WORK", "TEAMS", "PRODUCT", "FOOD_AND_DRINK"].map((c) => <option key={c} value={c}>{c.replace(/_/g, " ").toLowerCase()}</option>)}</Select>
          <Button loading={busy} disabled={!url.startsWith("https://")} icon={<ImagePlus className="h-4 w-4" />} onClick={async () => { setBusy(true); try { await api(`/gbp/${gid}/media`, { method: "POST", body: { source_url: url, category: cat } }); toast("Photo sent to Google."); setUrl(""); await reload(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); } }}>Add photo</Button>
        </div></Card>}
      {loading && !data ? <Skeleton className="h-40" /> : data && data.length === 0 ? <EmptyState icon={<ImagePlus className="h-6 w-6" />} title="No photos yet">Profiles with photos get more calls and direction requests.</EmptyState> : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{data?.map((m) => (
          <li key={m.name} className="overflow-hidden rounded-2xl border border-ink-100 bg-white shadow-card">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {m.thumbnail || m.url ? <img src={m.thumbnail ?? m.url ?? ""} alt={`Google photo (${m.category ?? "photo"})`} className="aspect-square w-full object-cover" /> : <div className="aspect-square bg-ink-50" />}
            <div className="flex items-center justify-between gap-2 p-2.5"><Badge>{(m.category ?? "photo").replace(/_/g, " ").toLowerCase()}</Badge>
              {isAdmin && <Button variant="ghost" size="sm" aria-label="Delete photo" icon={<Trash2 className="h-4 w-4 text-red-600" />} onClick={async () => { if (confirm("Delete this photo from Google?")) { try { await api(`/gbp/${gid}/media`, { method: "DELETE", params: { name: m.name } }); toast("Photo deleted."); void reload(); } catch (e) { toast(errorMessage(e), "error"); } } }} />}</div>
          </li>))}</ul>)}
    </>
  );
}

const METRIC_LABELS: Record<string, string> = { CALL_CLICKS: "Calls", WEBSITE_CLICKS: "Website clicks", BUSINESS_DIRECTION_REQUESTS: "Direction requests", BUSINESS_CONVERSATIONS: "Messages", BUSINESS_BOOKINGS: "Bookings" };

function PerfTab({ gid }: { gid: string }) {
  const [range, setRange] = useState(presetRange("30"));
  const { data, error, loading } = useFetch<{ totals: Record<string, number>; series: Record<string, { date: string; value: number }[]>; note: string }>(`/gbp/${gid}/performance`, { from: range.from, to: range.to });
  if (error) return <Gate error={error} />;
  const impressions = data ? Object.entries(data.totals).filter(([k]) => k.startsWith("BUSINESS_IMPRESSIONS")).reduce((a, [, v]) => a + v, 0) : 0;
  const days = data ? [...new Set(Object.values(data.series).flatMap((s) => s.map((p) => p.date)))].sort() : [];
  const chart = days.map((d) => ({ date: d, calls: data!.series.CALL_CLICKS?.find((p) => p.date === d)?.value ?? 0, website: data!.series.WEBSITE_CLICKS?.find((p) => p.date === d)?.value ?? 0, directions: data!.series.BUSINESS_DIRECTION_REQUESTS?.find((p) => p.date === d)?.value ?? 0 }));
  return (
    <>
      <div className="mb-4"><DateRange value={range} onChange={setRange} /></div>
      {loading && !data ? <Skeleton className="h-60" /> : data && (<>
        <dl className="panel grid grid-cols-2 divide-ink-100 overflow-hidden sm:grid-cols-4 sm:divide-x">
          {[["Profile views", impressions, "Search + Maps impressions"], ...Object.entries(METRIC_LABELS).filter(([k]) => k in data.totals).slice(0, 3).map(([k, l]) => [l, data.totals[k] ?? 0, ""] as [string, number, string])].map(([k, v, h]) => (
            <div key={k as string} className="border-b border-ink-100 px-4 py-3 sm:border-b-0"><dt className="text-xs font-medium text-ink-500">{k as string}</dt><dd className="num mt-1 text-2xl font-bold leading-none tracking-tight">{(v as number).toLocaleString("en-IN")}</dd>{h && <p className="mt-1.5 text-xs text-ink-500">{h as string}</p>}</div>))}
        </dl>
        <Panel className="mt-4" title="Actions on your Google profile">
          <LineChart ariaLabel="Calls, website clicks and direction requests per day" data={chart} series={[{ key: "calls", label: "Calls", color: "#0A7D6B" }, { key: "website", label: "Website clicks", color: "#1B46B8", dash: "6 4" }, { key: "directions", label: "Directions", color: "#57554F", dash: "2 4" }]} /></Panel>
        <p className="mt-3 text-xs text-ink-500">{data.note}</p></>)}
    </>
  );
}
