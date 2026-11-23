"use client";
import { API_V1 } from "@/lib/config";
import { ArrowLeft, Ban, Copy, Download, Pause, Pencil, Play, Zap } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { FlowCard } from "@/components/CardArt";
import { CardEditModal } from "@/components/CardEditModal";
import { DateRange, presetRange } from "@/components/DateRange";
import { QrNfc } from "@/components/QrNfc";
import { Button } from "@/components/ui/Button";
import { PosterDownload } from "@/components/cards/PosterDownload";
import { Alert, Skeleton } from "@/components/ui/Card";
import { KV, Panel, Status } from "@/components/ui/kit";
import { useConfirm } from "@/components/ui/Confirm";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CARD_STATUS, cardState, copyText, isLive } from "@/lib/card-ui";
import { fmtDate, fmtNum, fmtPct, timeAgo } from "@/lib/format";
import type { Card as CardT, Location, Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

export default function CardDetail() {
  const confirm = useConfirm();
  const { id } = useParams<{ id: string }>();
  const { isAdmin } = useAuth();
  const toast = useToast();
  const cards = useFetch<CardT[]>("/cards");
  const locs = useFetch<Location[]>("/locations");
  const [range, setRange] = useState(presetRange("30"));
  const card = cards.data?.find((c) => c.id === id) ?? null;
  const ov = useFetch<Overview>(card ? "/analytics/overview" : null, { from: range.from, to: range.to, location_id: card?.location_id });
  const [edit, setEdit] = useState(false);
  const row = ov.data?.cards.find((c) => c.card_code === card?.card_code);

  const [acting, setActing] = useState<string | null>(null);
  async function act(path: string, msg: string, body?: unknown) {
    setActing(path);
    try { await api(`/cards/${id}/${path}`, { method: "POST", body }); toast(msg); }
    catch (e) {
      // 409: the card changed state since this page loaded (e.g. someone else paused it). Show the real state instead of a stale button.
      toast(e instanceof ApiError && e.status === 409 ? `${errorMessage(e)} The page has been refreshed.` : e instanceof ApiError && e.status === 404 ? "This card is no longer assigned to your business." : errorMessage(e), "error");
    } finally { setActing(null); void cards.reload(); }
  }

  if (cards.loading && !cards.data) return <div className="space-y-3"><Skeleton className="h-10 w-1/3" /><Skeleton className="h-72" /></div>;
  if (cards.error) return <Alert tone="error">{cards.error}</Alert>;
  if (!card) return <div className="space-y-3"><Link href="/gbp/cards" className="inline-flex min-h-11 items-center gap-1.5 text-[13px] font-medium text-brand-700 hover:underline"><ArrowLeft className="h-4 w-4" aria-hidden />All cards</Link><Alert tone="error" title="Card not found">It may belong to another business or have been unassigned.</Alert></div>;

  const live = isLive(card.status);
  const s = card.stats;
  const visits = row?.landing_views ?? s.landing_view ?? 0, scans = row?.scans ?? s.scan ?? 0, clicks = row?.google_clicks ?? s.google_click ?? 0;
  return (
    <>
      <Link href="/gbp/cards" className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-[13px] font-medium text-brand-700 hover:underline sm:min-h-8"><ArrowLeft className="h-4 w-4" aria-hidden />All cards</Link>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-ink-100 pb-4">
        <div>
          <p className="eyebrow mb-1">Card</p>
          <h1 className="card-code text-2xl font-semibold tracking-[.06em]">{card.card_code}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-ink-500"><span>{card.label ?? "No label"} · {card.location_name ?? "Not assigned to a location"}</span><Status tone={CARD_STATUS[card.status].tone}>{CARD_STATUS[card.status].label}</Status></p>
        </div>
        {isAdmin && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEdit(true)}>{card.location_id ? "Change" : "Assign"}</Button>
            {card.status === "paused" && <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} loading={acting === "activate"} onClick={() => void act("activate", "Card resumed. The same printed code works again.")}>Resume</Button>}
            {card.status === "deactivated" && <Button variant="secondary" size="sm" icon={<Zap className="h-3.5 w-3.5" />} loading={acting === "activate"} onClick={() => void act("activate", "Card reactivated. The same printed code works again.")}>Reactivate</Button>}
            {live && <Button variant="secondary" size="sm" icon={<Pause className="h-3.5 w-3.5" />} loading={acting === "pause"} onClick={() => void act("pause", "Card paused. Scans show an inactive notice until you resume it.")}>Pause</Button>}
            {(live || card.status === "paused") && <Button variant="danger" size="sm" icon={<Ban className="h-3.5 w-3.5" />} loading={acting === "deactivate"} onClick={async () => { if (await confirm({ title: `Deactivate ${card.card_code}?`, body: "Anyone scanning the printed card will see an inactive notice. You can reactivate it later; the printed code does not change.", confirmLabel: "Deactivate" })) void act("deactivate", "Card deactivated. Scans now show a notice."); }}>Deactivate</Button>}
            {card.location_id && card.status !== "retired" && <PosterDownload path={`/cards/${card.id}/poster`} filename={card.card_code} label="Download poster" />}
            {card.status !== "retired" && <Button variant="ghost" size="sm" loading={acting === "retire"} onClick={async () => { if (await confirm({ title: `Retire ${card.card_code} permanently?`, body: "Anyone who scans or taps it will see that it is no longer active, and it can never be used again. Its history is kept. To stop it temporarily, use Pause instead.", confirmLabel: "Retire for good", typeToConfirm: "retire" })) void act("retire", "Card retired. Its history is kept.", { confirm: true }); }}>Retire</Button>}
            {card.status !== "lost" && card.status !== "retired" && <Button variant="ghost" size="sm" onClick={async () => { if (await confirm({ title: `Report ${card.card_code} as lost?`, body: "Scans will show an inactive notice, and only FlowQR support can switch a lost card back on.", confirmLabel: "Report lost" })) void act("report-lost", "Marked as lost."); }}>Report lost</Button>}
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,300px)_1fr]">
        <div className="min-w-0 space-y-4">
          <FlowCard code={card.card_code} state={cardState(card.status)} className="mx-auto max-w-[300px]" />
          <Panel title="QR and link" action={isAdmin && live ? <span className="flex gap-1">
            <a className="inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-[13px] font-medium text-brand-700 hover:bg-brand-50 sm:min-h-7" href={`${API_V1}/cards/${card.id}/qr.png`} download><Download className="h-3.5 w-3.5" aria-hidden />PNG</a>
            <a className="inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-[13px] font-medium text-brand-700 hover:bg-brand-50 sm:min-h-7" href={`${API_V1}/cards/${card.id}/qr.svg`} download><Download className="h-3.5 w-3.5" aria-hidden />SVG</a>
            <a className="inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-[13px] font-medium text-brand-700 hover:bg-brand-50 sm:min-h-7" href={`${API_V1}/cards/${card.id}/qr.pdf`} download><Download className="h-3.5 w-3.5" aria-hidden />PDF</a></span> : undefined}>
            {isAdmin && live && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={`${API_V1}/cards/${card.id}/qr.svg`} alt={`Scannable QR code for card ${card.card_code}`} className="mx-auto mb-3 h-40 w-40 rounded-lg border border-ink-100 p-2" />
            )}
            <p className="break-all rounded-lg bg-ink-50 p-2.5 font-mono text-xs text-ink-700">{card.url}</p>
            <Button size="sm" variant="secondary" className="mt-2" icon={<Copy className="h-3.5 w-3.5" />} onClick={async () => { await copyText(card.url); toast("Link copied."); }}>Copy link</Button>
            {card.nfc_url && (
              <div className="mt-4 border-t border-ink-100 pt-3" data-testid="nfc-address">
                <p className="text-[13px] font-semibold">NFC tag address</p>
                <p className="mt-1 text-xs text-ink-500">Write this onto the tag as a URL (NDEF) record. It opens this same card and counts as an NFC tap.</p>
                <p className="mt-2 break-all rounded-lg bg-ink-50 p-2.5 font-mono text-xs text-ink-700">{card.nfc_url}</p>
                <Button size="sm" variant="secondary" className="mt-2" icon={<Copy className="h-3.5 w-3.5" />} onClick={async () => { await copyText(card.nfc_url ?? ""); toast("NFC address copied."); }}>Copy NFC address</Button>
              </div>
            )}
            {card.status === "paused" && <p className="mt-3 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900">Paused: people who scan this card see an inactive notice. Resume it to switch the same printed code back on.</p>}
            <p className="mt-3 text-xs text-ink-500">This link is permanent. Reassigning the card, changing the Google review link or changing your <Link href="/gbp/cards/designs" className="text-brand-700 hover:underline">QR design</Link> never changes it, so the printed card stays valid. QR and NFC share one link. To program an NFC tag (NTAG213/215/216), write this link as a URL/NDEF record with any free NFC writer app. The artwork above is a preview with a sample QR; download this card&rsquo;s real QR for printing.</p>
          </Panel>
        </div>

        <div className="min-w-0 space-y-4">
          <Panel title="Status" flush>
            <div className="px-4 py-1">
              <KV rows={[
                ["Activation", <Status key="a" tone={CARD_STATUS[card.status].tone}>{CARD_STATUS[card.status].label}</Status>],
                ["QR / NFC", <QrNfc key="q" c={card} />],
                ["Location", card.location_name ?? "Not assigned"],
                ["Review page", card.campaign_name ? `Campaign: ${card.campaign_name}` : "Plain review page"],
                ["Visits by", `${fmtNum(s.qr_scan ?? 0)} QR scans · ${fmtNum(s.nfc_scan ?? 0)} NFC taps${s.untracked_scan ? ` · ${fmtNum(s.untracked_scan)} before this was tracked` : ""}`],
                ["Assigned", card.assigned_at ? fmtDate(card.assigned_at) : "–"],
                ["Unique scans", `${fmtNum(s.unique_scan ?? 0)} all time (different devices per day)`],
                ["Last scanned", card.last_scan_at ? `${timeAgo(card.last_scan_at)} · ${fmtDate(card.last_scan_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "Never"],
              ]} />
            </div>
          </Panel>

          <Panel title="Performance" meta="this card" action={<DateRange value={range} onChange={setRange} />}>
            <ol className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-ink-100 bg-ink-100 sm:grid-cols-4" aria-label="Funnel for this card">
              {[["Scans", scans, "Card scanned or tapped"], ["Visits", visits, scans ? `${fmtPct(visits / scans)} of scans` : "Review page loaded"], ["AI assists", row?.ai_assists ?? s.ai_assist ?? 0, "Writing help used"], ["Clicks to Google", clicks, visits ? `${fmtPct(clicks / visits)} of visits` : "Continued to Google"]].map(([k, v, h]) => (
                <li key={k as string} className="bg-white p-3"><p className="text-xs font-medium text-ink-500">{k as string}</p><p className="num mt-1 text-2xl font-bold leading-none">{fmtNum(v as number)}</p><p className="mt-1.5 text-xs text-ink-500">{h as string}</p></li>))}
            </ol>
            <p className="mt-3 text-xs text-ink-500">A click to Google doesn&rsquo;t prove a review was posted, and posted reviews can&rsquo;t be traced to a single card. Reviews that landed are on the <Link href="/gbp/reviews" className="text-brand-700 hover:underline">Reviews</Link> page.</p>
          </Panel>
        </div>
      </div>
      {edit && <CardEditModal card={card} locations={(locs.data ?? []).filter((l) => l.is_active)} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); toast("Card updated."); void cards.reload(); }} />}
    </>
  );
}
