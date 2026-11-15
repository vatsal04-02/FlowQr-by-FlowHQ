"use client";
import { Copy, MessageCircle, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/use-api";

interface T { id: string; name: string; channel: string; language: string; body: string }
interface Preset { name: string; channel: string; language: string; body: string }

/**
 * Review request templates for one campaign: a neutral message, the same for every customer, with this campaign's link. FlowQR doesn't send
 * anything: copy the text or open WhatsApp with it. Messages that offer something, ask for a rating, or only ask happy customers are refused.
 */
export function RequestTemplates({ campaignId, canEdit }: { campaignId: string; canEdit: boolean }) {
  const toast = useToast();
  const { data, loading, reload } = useFetch<{ templates: T[]; presets: Preset[] }>("/review-growth/templates");
  const [customer, setCustomer] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [draft, setDraft] = useState<Preset | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function render(id: string) {
    setPicked(id);
    try { setText((await api<{ text: string }>(`/review-growth/templates/${id}/render`, { method: "POST", body: { campaign_id: campaignId, customer: customer || null } })).text); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  async function save() {
    if (!draft) return;
    setErr(null);
    try { await api("/review-growth/templates", { method: "POST", body: draft }); setDraft(null); toast("Template saved."); reload(); }
    catch (e) { setErr(e instanceof ApiError ? errorMessage(e) : "Couldn't save."); }
  }
  async function remove(id: string) {
    try { await api(`/review-growth/templates/${id}`, { method: "DELETE" }); if (picked === id) { setPicked(null); setText(null); } reload(); } catch (e) { toast(errorMessage(e), "error"); }
  }

  return (
    <Panel title="Ask customers for a review" meta="the same neutral message for everyone">
      {loading && !data ? <Skeleton className="h-32" /> : (
        <div className="space-y-4">
          {(data?.templates.length ?? 0) === 0 ? <p className="text-sm text-muted">No templates yet{canEdit ? ". Start from one of these neutral examples." : "."}</p> : (
            <ul className="flex flex-wrap gap-2">{data!.templates.map((t) => (
              <li key={t.id} className="flex items-center rounded-full bg-surface-2">
                <button type="button" onClick={() => void render(t.id)} aria-pressed={picked === t.id}
                  className={`min-h-9 rounded-full px-4 text-[13px] font-medium ${picked === t.id ? "bg-ink-solid text-ink-on" : ""}`}>{t.name}</button>
                {canEdit && <button type="button" aria-label={`Delete ${t.name}`} onClick={() => void remove(t.id)} className="grid h-9 w-9 place-items-center rounded-full text-muted hover:text-neg"><Trash2 className="h-3.5 w-3.5" /></button>}
              </li>))}</ul>
          )}
          {canEdit && !draft && (
            <div className="flex flex-wrap gap-1.5">{data?.presets.map((p) => (
              <button key={p.name} type="button" onClick={() => setDraft({ ...p })} className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-dashed border-ink-300 px-3.5 text-[13px] font-medium hover:bg-surface-2">
                <Plus className="h-3.5 w-3.5" aria-hidden />{p.name}</button>))}</div>
          )}
          {draft && (
            <div className="space-y-2 rounded-tile bg-surface-2 p-4">
              <input aria-label="Template name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="min-h-10 w-full rounded-inner bg-surface px-3 text-sm font-semibold" />
              <textarea aria-label="Message" rows={3} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} className="w-full rounded-inner bg-surface p-3 text-sm" />
              <p className="text-xs text-muted">Use {"{customer}"}, {"{business}"} and {"{link}"}. No offers, no star ratings, and the same words for every customer.</p>
              {err && <Alert tone="error">{err}</Alert>}
              <div className="flex gap-2"><Button size="sm" onClick={() => void save()}>Save template</Button><Button size="sm" variant="ghost" onClick={() => { setDraft(null); setErr(null); }}>Cancel</Button></div>
            </div>
          )}
          {picked && (
            <div className="space-y-2 rounded-tile bg-surface-2 p-4">
              <label className="block"><span className="mb-1 block text-xs font-medium text-muted">Customer name (optional)</span>
                <input value={customer} onChange={(e) => setCustomer(e.target.value)} onBlur={() => void render(picked)} className="min-h-10 w-full max-w-xs rounded-inner bg-surface px-3 text-sm" /></label>
              {text && <p className="whitespace-pre-wrap rounded-inner bg-surface p-3 text-sm">{text}</p>}
              {text && <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" icon={<Copy className="h-4 w-4" />} onClick={() => { void navigator.clipboard.writeText(text).then(() => toast("Copied.")); }}>Copy</Button>
                <a href={`https://wa.me/?text=${encodeURIComponent(text)}`} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-2 rounded-full bg-surface px-4 text-[13px] font-semibold sm:min-h-9"><MessageCircle className="h-4 w-4" aria-hidden />Open in WhatsApp</a>
              </div>}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
