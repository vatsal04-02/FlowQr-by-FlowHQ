"use client";
import { PenLine } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { Library } from "@/components/gbp/StudioParts";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { api, errorMessage } from "@/lib/api";
import { DURATIONS, OBJECTIVES, type Campaign, type Objective } from "@/lib/marketing";

function Form({ gid }: { gid: string }) {
  const router = useRouter();
  const [brief, setBrief] = useState("");
  const [objective, setObjective] = useState<Objective>("keep_active");
  const [days, setDays] = useState<7 | 15 | 30>(7);
  const [start, setStart] = useState("");
  const [lang, setLang] = useState("");
  const [assets, setAssets] = useState<string[]>([]);
  const [evTitle, setEvTitle] = useState("");
  const [evStart, setEvStart] = useState("");
  const [evEnd, setEvEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const hint = OBJECTIVES.find((o) => o.value === objective)?.hint;
  const posts = DURATIONS.find((d) => d.value === days)?.posts;
  async function go() {
    setBusy(true); setErr(null);
    try {
      const c = await api<Campaign>("/marketing/campaigns", { method: "POST", body: {
        google_location_id: gid, brief, objective, duration_days: days, start_date: start || null, language: lang || null, asset_ids: assets,
        ...(objective === "events" ? { event_title: evTitle || null, event_start: evStart || null, event_end: evEnd || null } : {}) } });
      router.push(`/gbp/studio/${c.id}`);
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  const eventOk = objective !== "events" || (evTitle && evStart && evEnd);
  return (
    <div className="space-y-5">
      {err && <Alert tone="error">{err}</Alert>}
      <Panel title="1. What do you want to promote?">
        <Textarea label="Describe it in your own words" rows={4} maxLength={1500} value={brief} onChange={(e) => setBrief(e.target.value)} hint={`${brief.length}/1500`}
          placeholder="e.g. We have launched a new summer collection. Create posts to attract customers from Lucknow." />
      </Panel>
      <Panel title="2. Goal and length">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="Campaign goal" value={objective} onChange={(e) => setObjective(e.target.value as Objective)} hint={hint}>{OBJECTIVES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select>
          <Select label="How long should it run?" value={String(days)} onChange={(e) => setDays(Number(e.target.value) as 7 | 15 | 30)} hint={`About ${posts} posts, spread across the period.`}>{DURATIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}</Select>
          <Input label="Start date (optional)" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          <Select label="Language" value={lang} onChange={(e) => setLang(e.target.value)}><option value="">Use my business language</option><option value="en">English</option><option value="hi">Hindi</option><option value="hinglish">Hinglish</option></Select>
        </div>
        {objective === "events" && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Input label="Event name" maxLength={58} value={evTitle} onChange={(e) => setEvTitle(e.target.value)} wrapperClassName="sm:col-span-2" />
            <Input label="Starts" type="datetime-local" value={evStart} onChange={(e) => setEvStart(e.target.value)} />
            <Input label="Ends" type="datetime-local" value={evEnd} onChange={(e) => setEvEnd(e.target.value)} />
            <p className="text-[13px] text-muted sm:col-span-2">FlowQR never invents an event. Posts are scheduled before it begins.</p>
          </div>)}
      </Panel>
      <Panel title="3. Photos and documents (optional)" meta="Used as context; photos are matched to posts">
        <Library picked={assets} onPick={(id) => setAssets((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id].slice(0, 12)))} compact />
        <p className="mt-2 text-[12px] text-muted">Tick the photos and documents this campaign may use. Prices in a catalogue are only used if they are also in your verified offers.</p>
      </Panel>
      <div className="flex flex-wrap items-center gap-3">
        <Button icon={<PenLine className="h-4 w-4" />} loading={busy} disabled={brief.trim().length < 10 || !eventOk} onClick={() => void go()}>Write my campaign</Button>
        <span className="text-[13px] text-muted">{busy ? "Writing and checking your posts. This can take up to a minute." : "You review, edit and approve every post before anything is published."}</span>
      </div>
    </div>
  );
}

export default function NewCampaignPage() {
  return (
    <>
      <PageHeader title="New campaign" subtitle="Tell FlowQR what to promote." />
      <GbpFrame>{(gid) => <Form key={gid} gid={gid} />}</GbpFrame>
    </>
  );
}
