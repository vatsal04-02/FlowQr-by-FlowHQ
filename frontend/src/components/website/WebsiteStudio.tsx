"use client";
import clsx from "clsx";
import { Check, CircleDashed, ExternalLink, Loader2, Minus, Monitor, Smartphone, Sparkles, Tablet, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Skeleton } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { API_V1 } from "@/lib/config";
import { useAuth } from "@/lib/auth";
import type { Location } from "@/lib/types";
import { editableFields, emptyItem, phaseOf, previewKey, progress, STEP_WORD, type Device, type Field, type SiteSection, type WebsiteState } from "@/lib/website";
import { Preview } from "./Preview";

/** The whole owner journey on one screen: start (with or without Google), watch the real steps with the live preview, then review, edit and publish. Used in onboarding and in the app. */
export function WebsiteStudio({ onContinue, continueLabel }: { onContinue?: () => void; continueLabel?: string }) {
  const [state, setState] = useState<WebsiteState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setState(await api<WebsiteState>("/website")); setError(null); } catch (e) { setError(errorMessage(e)); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const phase = state?.enabled ? phaseOf(state) : null;
  useEffect(() => {  // follow the job while it runs; the server keeps going if this tab is closed or refreshed
    if (phase !== "building") return;
    const t = setInterval(() => void load(), 1500);
    return () => clearInterval(t);
  }, [phase, load]);

  async function generate(rebuild = false) {
    setBusy("generate"); setError(null);
    try { await api("/website/generate", { method: "POST", body: { rebuild } }); await load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(null); }
  }

  if (!state) return error ? <Alert tone="error">{error}</Alert> : <Skeleton className="h-96" />;
  if (!state.enabled) return <Alert tone="info" title="Website building is not switched on yet">Your set-up continues as normal. FlowQR will tell you when websites are available.</Alert>;

  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-accent-ink">FlowQR AI Website Builder</p>
          <h1 className="text-[24px] font-semibold leading-8 sm:text-[30px] sm:leading-9">{phase === "review" ? "Your website is ready for review." : phase === "building" ? "Building your digital presence." : "Let’s build your business website with AI."}</h1>
          <p className="mt-1 text-sm text-muted">{state.business?.name}{state.business?.category ? ` · ${state.business.category}` : ""} · Google {state.google?.connected ? `connected: ${state.google.title}` : "not connected"}</p>
        </div>
        {phase === "review" && <Badge tone="green">Website generated</Badge>}
        {phase === "building" && <Badge tone="amber">Generating</Badge>}
      </header>

      {phase === "start" && <Start state={state} busy={busy === "generate"} onGenerate={() => void generate()} onChanged={() => void load()} />}
      {phase === "failed" && (
        <Alert tone="error" title="The website was not finished">
          <p>{state.job?.error}</p>
          <div className="mt-2"><Button size="sm" loading={busy === "generate"} onClick={() => void generate()}>Try again</Button></div>
        </Alert>)}
      {(phase === "building" || phase === "failed") && state.job && <Building state={state} />}
      {phase === "review" && <Review state={state} setState={setState} onRebuild={() => void generate(true)} rebuilding={busy === "generate"} />}

      {onContinue && <div className="flex justify-end border-t border-line pt-4"><Button variant={phase === "review" ? "primary" : "secondary"} onClick={onContinue}>{continueLabel ?? (phase === "review" ? "Keep as draft and continue" : "Skip for now")}</Button></div>}
    </div>
  );
}

// ------------------------------------------------------------------ before it starts
function Start({ state, busy, onGenerate, onChanged }: { state: WebsiteState; busy: boolean; onGenerate: () => void; onChanged: () => void }) {
  const { isAdmin } = useAuth();
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="rounded-[22px] bg-surface p-5 shadow-card">
        <p className="text-sm text-ink-700">Your AI team will understand your business, create your website and prepare it for you. No coding or technical knowledge needed. Nothing is published until you approve it.</p>
        <div className="mt-4"><Button icon={<Sparkles className="h-4 w-4" />} loading={busy} disabled={!isAdmin} onClick={onGenerate}>Create my website with AI</Button></div>
        <p className="mt-2 text-[13px] text-muted">{state.google?.connected ? "It will use your Google Business Profile and your set-up details." : "It works with your set-up details alone. Connecting Google first gives it your hours, services and description."}</p>
      </section>
      {!state.google?.connected && <ConnectGoogle onChanged={onChanged} />}
    </div>
  );
}

interface GoogleStatus { configured: boolean; connections: { id: string; status: string; google_email: string | null }[] }
interface GLoc { id: string; title: string | null; address: string | null; selected: boolean }

/** The existing Google sign-in, then choosing the profile. Choosing it starts the website by itself (the server does that once). */
function ConnectGoogle({ onChanged }: { onChanged: () => void }) {
  const [st, setSt] = useState<GoogleStatus | null>(null);
  const [locs, setLocs] = useState<GLoc[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const conn = st?.connections.find((c) => c.status === "active" || c.status === "pending_selection");

  useEffect(() => { api<GoogleStatus>("/google/status").then(setSt).catch((e) => setMsg(errorMessage(e))); }, []);
  useEffect(() => { if (conn) api<GLoc[]>(`/google/connections/${conn.id}/locations`).then(setLocs).catch((e) => setMsg(errorMessage(e))); }, [conn?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function connect() {
    setBusy(true); setMsg(null);
    try { const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST", params: { return_to: "website" } }); window.location.href = auth_url; }
    catch (e) { setMsg(errorMessage(e)); setBusy(false); }
  }
  async function choose(id: string) {
    setBusy(true); setMsg(null);
    try {
      const mine = await api<Location[]>("/locations");
      await api(`/google/connections/${conn!.id}/selection`, { method: "PUT", body: { selections: [{ google_location_id: id, selected: true, location_id: mine[0]?.id ?? null }] } });
      onChanged();
    } catch (e) { setMsg(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <section className="rounded-[22px] bg-surface p-5 shadow-card">
      <p className="font-semibold">Connect Google Business Profile <span className="text-[13px] font-normal text-muted">(optional)</span></p>
      {!conn ? <><p className="mt-1 text-sm text-muted">You sign in on Google&rsquo;s own screen. FlowQR never sees your password.</p><Button className="mt-3" variant="secondary" loading={busy} onClick={() => void connect()}>Connect Google</Button></> : (
        <><p className="mt-1 text-sm text-muted">Choose your business. The website starts by itself.</p>
          <ul className="mt-2 divide-y divide-line">{(locs ?? []).map((l) => <li key={l.id} className="flex items-center justify-between gap-3 py-2"><span className="min-w-0"><span className="block truncate text-sm font-medium">{l.title}</span><span className="block truncate text-[12px] text-muted">{l.address}</span></span><Button size="sm" variant="secondary" loading={busy} onClick={() => void choose(l.id)}>Use this</Button></li>)}</ul>
          {locs && locs.length === 0 && <p className="mt-2 text-sm text-muted">Google lists no business for this account.</p>}</>)}
      {msg && <p role="alert" className="mt-2 text-[13px] text-neg">{msg}</p>}
    </section>
  );
}

// ------------------------------------------------------------------ while it builds
function Building({ state }: { state: WebsiteState }) {
  const [tab, setTab] = useState<"progress" | "preview">("progress");
  const job = state.job!;
  const p = progress(job.steps);
  return (
    <div className="space-y-3">
      <div role="tablist" aria-label="Generation view" className="flex gap-2 lg:hidden">
        {(["progress", "preview"] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={clsx("min-h-11 flex-1 rounded-full text-sm font-semibold ring-1 ring-inset", tab === t ? "bg-navy text-white ring-navy" : "bg-surface ring-line")}>{t === "progress" ? "Progress" : "Preview"}</button>)}
      </div>
      <div className="grid gap-3 lg:grid-cols-[minmax(320px,400px)_minmax(0,1fr)] lg:gap-4">
        <section className={clsx("rounded-[22px] bg-gradient-to-b from-surface to-surface-2 p-4 shadow-card sm:p-5", tab !== "progress" && "hidden lg:block")} aria-label="Progress">
          <p className="text-[13px] font-semibold text-muted" role="status" aria-live="polite">{p.finished} of {p.total} steps finished{p.current ? ` · ${p.current.label}` : job.status === "queued" ? " · Starting" : ""}</p>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line"><div className="h-full rounded-full bg-accent transition-[width] duration-700 motion-reduce:transition-none" style={{ width: `${(p.finished / p.total) * 100}%` }} /></div>
          <ol className="mt-3 space-y-1">
            {job.steps.map((s) => (
              <li key={s.key} aria-current={s.status === "running" ? "step" : undefined} className={clsx("flex gap-3 rounded-xl px-2 py-1.5 transition-colors", s.status === "running" && "bg-accent-tint")}>
                <span aria-hidden className={clsx("mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full", s.status === "done" ? "bg-pos text-white" : s.status === "failed" ? "bg-neg text-white" : s.status === "running" ? "text-accent-ink" : "text-muted")}>
                  {s.status === "done" ? <Check className="h-3.5 w-3.5" /> : s.status === "skipped" ? <Minus className="h-4 w-4" /> : s.status === "failed" ? <X className="h-3.5 w-3.5" /> : s.status === "running" ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <CircleDashed className="h-4 w-4" />}
                </span>
                <span className="min-w-0">
                  <span className={clsx("block text-[14px] leading-5", s.status === "waiting" ? "text-muted" : "font-semibold")}>{s.label}<span className="sr-only">: {STEP_WORD[s.status]}</span></span>
                  {s.status === "running" && <span className="block text-[12.5px] text-ink-700">{s.detail}</span>}
                  {s.note && <span className="block text-[12.5px] text-muted">{s.status === "skipped" ? "Skipped. " : ""}{s.note}</span>}
                </span>
              </li>))}
          </ol>
          <p className="mt-3 text-[12.5px] text-muted">You can leave this page. The work carries on and you will find it here.</p>
        </section>
        <div className={clsx("h-[70vh] min-h-[460px]", tab !== "preview" && "hidden lg:block")}><Preview version={previewKey(state)} device="desktop" ready={!!state.site} /></div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ after it is built
function Review({ state, setState, onRebuild, rebuilding }: { state: WebsiteState; setState: (s: WebsiteState) => void; onRebuild: () => void; rebuilding: boolean }) {
  const { isAdmin, role } = useAuth();
  const [device, setDevice] = useState<Device>("desktop");
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "success" | "info" | "error"; text: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const site = state.site!;
  const router = useRouter();
  const [googleLink, setGoogleLink] = useState<string | null>(null);
  const removePhoto = (id: string) => run(`photo-${id}`, () => api<WebsiteState>(`/website/photo/${id}`, { method: "DELETE" }), setState);
  const linkGoogle = () => run("google", () => api<{ action_id: string | null; message: string }>("/website/google-link", { method: "POST" }), (r) => {
    setMsg({ tone: r.action_id ? "success" : "info", text: r.message });
    if (r.action_id) router.push(`/ai/changes?focus=action:${r.action_id}`);
  });

  async function run<T>(key: string, fn: () => Promise<T>, then: (r: T) => void) {
    setBusy(key); setMsg(null);
    try { then(await fn()); } catch (e) { setMsg({ tone: "error", text: errorMessage(e) }); } finally { setBusy(null); }
  }
  const improve = (instruction: string, section_id?: string) => run(section_id ?? "ask", () => api<{ done: string[]; refused: string[]; cannot: string; state: WebsiteState }>("/website/ask", { method: "POST", body: { instruction, section_id: section_id ?? null } }), (r) => {
    setState(r.state); setAsk("");
    setMsg({ tone: r.done.length ? "success" : "info", text: [...r.done, ...r.refused, r.cannot].filter(Boolean).join(" ") || "Nothing needed changing." });
  });
  const design = (body: { template?: string; accent?: string }) => run("design", () => api<WebsiteState>("/website/design", { method: "POST", body }), setState);
  const publish = () => run("publish", () => api<{ published: boolean; message: string; google_action_id?: string | null; state: WebsiteState }>("/website/publish", { method: "POST" }), (r) => { setState(r.state); setGoogleLink(r.google_action_id ?? null); setMsg({ tone: r.published ? "success" : "info", text: r.message }); });
  async function photo(file: File) {
    await run("photo", () => api<WebsiteState>("/website/photo", { method: "POST", raw: file, params: { alt: `Photo of ${state.business?.name ?? "the business"}` } }), setState);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div role="tablist" aria-label="Preview size" className="flex gap-1 rounded-full bg-surface p-1 shadow-card">
            {([["desktop", Monitor, "Desktop"], ["tablet", Tablet, "Tablet"], ["phone", Smartphone, "Mobile"]] as const).map(([k, Icon, label]) => (
              <button key={k} role="tab" aria-selected={device === k} onClick={() => setDevice(k)} className={clsx("inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold sm:min-h-9", device === k ? "bg-navy text-white" : "text-ink-700")}><Icon className="h-4 w-4" aria-hidden />{label}</button>))}
          </div>
          <span className="text-[13px] text-muted">{site.status === "published" ? "Published" : "Draft: not public"}</span>
        </div>
        <div className="h-[72vh] min-h-[460px]"><Preview version={previewKey(state)} device={device} ready /></div>
      </div>

      <div className="space-y-3">
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        {state.job?.notes.length ? (
          <section className="rounded-[18px] bg-surface p-4 shadow-card">
            <p className="flex items-center gap-2 text-sm font-semibold"><TriangleAlert className="h-4 w-4 text-warn" aria-hidden />Please check these</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-ink-700">{state.job.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          </section>) : null}

        <section className="rounded-[18px] bg-surface p-4 shadow-card">
          <p className="text-sm font-semibold">Improve with AI</p>
          <form onSubmit={(e) => { e.preventDefault(); if (ask.trim().length > 2) void improve(ask.trim()); }} className="mt-2 space-y-2">
            <Textarea label="What should change?" rows={2} maxLength={400} value={ask} disabled={!isAdmin} onChange={(e) => setAsk(e.target.value)} placeholder="Improve the headline" />
            <Button size="sm" type="submit" loading={busy === "ask"} disabled={!isAdmin || ask.trim().length < 3} icon={<Sparkles className="h-4 w-4" />}>Apply</Button>
          </form>
          <div className="mt-2 flex flex-wrap gap-1.5">{["Make it feel more premium", "Improve the headline", "Make it suit my business better"].map((s) => <button key={s} type="button" disabled={!isAdmin || !!busy} onClick={() => void improve(s)} className="min-h-9 rounded-full bg-surface-2 px-3 text-[12.5px] font-semibold ring-1 ring-inset ring-line disabled:opacity-50">{s}</button>)}</div>
        </section>

        <section className="rounded-[18px] bg-surface p-4 shadow-card">
          <p className="text-sm font-semibold">Design</p>
          <label className="mt-2 block text-[13px]"><span className="text-muted">Layout</span>
            <select value={site.template} disabled={!isAdmin || !!busy} onChange={(e) => void design({ template: e.target.value })} className="mt-1 block min-h-11 w-full rounded-lg border border-line bg-surface px-2 text-sm">{state.templates?.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</select></label>
          <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label="Colour">{Object.entries(state.accents ?? {}).map(([k, hex]) => <button key={k} role="radio" aria-checked={site.accent === k} aria-label={k} disabled={!isAdmin || !!busy} onClick={() => void design({ accent: k })} className={clsx("h-9 w-9 rounded-full ring-2 ring-offset-2", site.accent === k ? "ring-ink" : "ring-transparent")} style={{ background: hex }} />)}</div>
          <label className="mt-3 block text-[13px]"><span className="text-muted">Add a photo of your business (JPEG, PNG or WebP)</span>
            <input type="file" accept="image/jpeg,image/png,image/webp" disabled={!isAdmin || !!busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) void photo(f); e.target.value = ""; }} className="mt-1 block w-full min-h-11 text-[13px]" /></label>
          {(site.photos?.length ?? 0) > 0 && <ul className="mt-2 grid grid-cols-3 gap-2" aria-label="Photos on your website">{site.photos!.map((p) => (
            <li key={p.id} className="space-y-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${API_V1}/website/photo/${p.id}`} alt={p.alt} className="aspect-square w-full rounded-lg object-cover" />
              <button type="button" disabled={!isAdmin || !!busy} onClick={() => void removePhoto(p.id)} className="min-h-9 w-full text-[12.5px] font-semibold text-neg">Remove</button>
            </li>))}</ul>}
        </section>

        <section className="rounded-[18px] bg-surface p-4 shadow-card">
          <p className="text-sm font-semibold">Sections</p>
          <ul className="mt-1 divide-y divide-line">{site.sections.map((s) => (
            <li key={s.id} className="py-1.5">
              <button type="button" aria-expanded={open === s.id} onClick={() => setOpen(open === s.id ? null : s.id)} className="flex min-h-11 w-full items-center justify-between gap-2 text-left text-sm"><span className="font-medium">{s.label}</span><span className="text-[12.5px] text-muted">{s.enabled ? "On the page" : "Hidden"}</span></button>
              {open === s.id && isAdmin && <SectionEditor section={s} fields={state.section_types?.[s.type] ?? []} busy={busy} onRegenerate={() => void improve("Rewrite this section so it reads better.", s.id)}
                onSave={(enabled, data) => run(`save-${s.id}`, () => api<WebsiteState>(`/website/sections/${s.id}`, { method: "PUT", body: { enabled, data } }), (r) => { setState(r); setMsg({ tone: "success", text: `${s.label} saved.` }); })} />}
            </li>))}</ul>
        </section>

        <section className="rounded-[18px] bg-surface p-4 shadow-card">
          <p className="text-sm font-semibold">Publish</p>
          <p className="mt-1 text-[13px] text-muted">Address: <span className="font-medium text-ink">{site.address}</span>. Custom domains are not supported yet.</p>
          {state.publish?.reason && <p className="mt-1 text-[13px] text-ink-700">{state.publish.reason}</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            {site.status === "published" && state.publish?.url ? <a href={state.publish.url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent-ink">Open my website<ExternalLink className="h-4 w-4" aria-hidden /></a>
              : <Button size="sm" loading={busy === "publish"} disabled={role !== "owner"} onClick={() => void publish()}>{state.publish?.available ? "Publish website" : "Approve for publishing"}</Button>}
            {site.status === "draft" && <Button size="sm" variant="secondary" loading={rebuilding} disabled={!isAdmin} onClick={onRebuild}>Build again from my latest details</Button>}
          </div>
          {site.status === "published" && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" variant="secondary" loading={busy === "google"} disabled={role !== "owner"} onClick={() => void linkGoogle()}>Add website to my Google profile</Button>
              {googleLink && <Link href={`/ai/changes?focus=action:${googleLink}`} className="inline-flex min-h-9 items-center text-[13px] font-semibold text-accent-ink hover:underline">Approve the Google change</Link>}
            </div>)}
          {role !== "owner" && <p className="mt-1 text-[12.5px] text-muted">Only the owner can approve publishing.</p>}
        </section>
      </div>
    </div>
  );
}

function SectionEditor({ section, fields, busy, onSave, onRegenerate }: { section: SiteSection; fields: Field[]; busy: string | null; onSave: (enabled: boolean, data: Record<string, unknown>) => void; onRegenerate: () => void }) {
  const [data, setData] = useState<Record<string, unknown>>(section.data);
  const [enabled, setEnabled] = useState(section.enabled);
  useEffect(() => { setData(section.data); setEnabled(section.enabled); }, [section]);
  const set = (k: string, v: unknown) => setData((d) => ({ ...d, [k]: v }));
  return (
    <div className="space-y-2 pb-2">
      <label className="flex min-h-11 items-center gap-2 text-[13px]"><input type="checkbox" className="h-[18px] w-[18px]" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Show this section</label>
      {editableFields(fields).map((f) => {
        const v = data[f.key];
        if (f.kind === "text") return <Input key={f.key} label={f.label} maxLength={f.max} value={String(v ?? "")} onChange={(e) => set(f.key, e.target.value)} />;
        if (f.kind === "textarea") return <Textarea key={f.key} label={f.label} rows={3} maxLength={f.max} value={String(v ?? "")} onChange={(e) => set(f.key, e.target.value)} />;
        if (f.kind === "strings") return <Textarea key={f.key} label={`${f.label} (one per line)`} rows={3} value={((v as string[]) ?? []).join("\n")} onChange={(e) => set(f.key, e.target.value.split("\n"))} />;
        const items = (v as Record<string, unknown>[]) ?? [];
        return (
          <fieldset key={f.key} className="space-y-2 rounded-xl border border-line p-2">
            <legend className="px-1 text-[13px] font-semibold">{f.label}</legend>
            {items.map((it, i) => (
              <div key={i} className="space-y-1 border-b border-line pb-2 last:border-0">
                {(f.fields ?? []).filter((x) => x.kind === "text" || x.kind === "textarea").map((x) => <Input key={x.key} label={x.label} maxLength={x.max} value={String(it[x.key] ?? "")} onChange={(e) => set(f.key, items.map((o, j) => (j === i ? { ...o, [x.key]: e.target.value } : o)))} />)}
                <button type="button" className="min-h-9 text-[12.5px] font-semibold text-neg" onClick={() => set(f.key, items.filter((_, j) => j !== i))}>Remove</button>
              </div>))}
            {items.length < (f.max_items ?? 12) && (f.fields ?? []).some((x) => x.kind === "text") && <button type="button" className="min-h-9 text-[13px] font-semibold text-accent-ink" onClick={() => set(f.key, [...items, emptyItem(f.fields ?? [])])}>Add one</button>}
          </fieldset>);
      })}
      <div className="flex flex-wrap gap-2"><Button size="sm" loading={busy === `save-${section.id}`} onClick={() => onSave(enabled, data)}>Save section</Button><Button size="sm" variant="secondary" loading={busy === section.id} onClick={onRegenerate}>Rewrite with AI</Button></div>
    </div>
  );
}
