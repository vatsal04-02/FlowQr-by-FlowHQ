"use client";
import { Download, QrCode } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { FlowCard } from "@/components/CardArt";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel, Segmented, Status } from "@/components/ui/kit";
import { CardEditModal } from "@/components/CardEditModal";
import { QrNfc } from "@/components/QrNfc";
import { useAuth } from "@/lib/auth";
import { CARD_STATUS, cardState, isLive } from "@/lib/card-ui";
import { fmtNum, timeAgo } from "@/lib/format";
import type { Card as CardT, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { useToast } from "@/components/ui/Toast";

export default function CardsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<CardT[]>("/cards");
  const locs = useFetch<Location[]>("/locations");
  const [view, setView] = useState<"gallery" | "table">("gallery");
  const [filter, setFilter] = useState<"all" | "live" | "off">("all");
  const [edit, setEdit] = useState<CardT | null>(null);

  const shown = useMemo(() => (data ?? []).filter((c) => filter === "all" || (filter === "live" ? isLive(c.status) : !isLive(c.status))), [data, filter]);
  const live = (data ?? []).filter((c) => isLive(c.status)).length;
  const total = (data ?? []).reduce((a, c) => a + (c.stats.scan ?? 0), 0);

  return (
    <>
      <PageHeader eyebrow="Cards" title="QR/NFC cards"
        subtitle={data ? `${data.length} ${data.length === 1 ? "card" : "cards"} · ${live} live · ${fmtNum(total)} scans all time` : "Each card has its own permanent link. Change the Google review link any time without replacing a card."}
        actions={<>
          {isAdmin && <LinkButton href="/qr" size="sm" variant="secondary" icon={<Download className="h-4 w-4" />}>Design &amp; bulk export</LinkButton>}
          <Segmented label="Show" value={filter} onChange={setFilter} options={[["all", "All"], ["live", "Live"], ["off", "Inactive"]] as const} />
          <Segmented label="View" value={view} onChange={setView} options={[["gallery", "Cards"], ["table", "Table"]] as const} />
        </>} />
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-64" />)}</div> : data && data.length === 0 ? (
        <div className="grid items-center gap-6 lg:grid-cols-[1fr_220px]">
          <EmptyState icon={<QrCode className="h-5 w-5" />} title="No cards assigned yet"
            action={<LinkButton href="/payments" size="sm">Order cards</LinkButton>}>
            FlowQR cards are issued centrally and assigned to your locations once they ship. When one is assigned it appears here with its printed ID, link and scan activity.</EmptyState>
          <FlowCard code="FQR-0000" state="unassigned" className="mx-auto max-w-[220px]" />
        </div>
      ) : view === "gallery" ? (
        <ul className="grid grid-cols-2 gap-x-4 gap-y-8 md:grid-cols-3 xl:grid-cols-4">
          {shown.map((c) => (
            <li key={c.id}>
              <Link href={`/cards/${c.id}`} className="group block" aria-label={`${c.card_code}, ${CARD_STATUS[c.status].label}`}>
                <FlowCard code={c.card_code} state={cardState(c.status)} className="transition-transform duration-200 group-hover:-translate-y-0.5" />
              </Link>
              <div className="mt-3 flex items-start justify-between gap-3">
                <div className="min-w-0"><p className="card-code text-sm font-medium">{c.card_code}</p><p className="truncate text-[13px] text-ink-500">{c.label ?? "No label"} · {c.location_name ?? "No location"}</p></div>
                <Status tone={CARD_STATUS[c.status].tone}>{CARD_STATUS[c.status].label}</Status>
              </div>
              <dl className="mt-2 grid grid-cols-4 divide-x divide-ink-100 rounded-lg border border-ink-100 bg-white text-center">
                {[["Scans", c.stats.scan], ["Visits", c.stats.landing_view], ["Clicks", c.stats.google_click], ["AI", c.stats.ai_assist]].map(([k, v]) => (
                  <div key={k as string} className="px-1 py-1.5"><dd className="num text-sm font-semibold">{fmtNum((v as number) ?? 0)}</dd><dt className="text-[11px] text-ink-500">{k as string}</dt></div>))}
              </dl>
              <div className="mt-2 flex items-center justify-between gap-2 text-xs text-ink-500">
                <span>Last scan {c.last_scan_at ? timeAgo(c.last_scan_at) : "never"}</span>
                <span className="flex gap-1">
                  {isAdmin && isLive(c.status) && <a className="inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-[13px] font-medium text-brand-700 hover:bg-brand-50 sm:min-h-7" href={`/api/v1/cards/${c.id}/qr.png`} download><Download className="h-3.5 w-3.5" aria-hidden />QR</a>}
                  {isAdmin && <Button size="sm" variant="ghost" onClick={() => setEdit(c)}>{c.location_id ? "Reassign" : "Assign"}</Button>}
                </span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <Panel flush>
          <div className="overflow-x-auto"><table className="dt min-w-[820px]">
            <thead><tr><th>Card</th><th>Location</th><th>Status</th><th>QR / NFC</th><th className="!text-right">Scans</th><th className="!text-right">Visits</th><th className="!text-right">Clicks</th><th>Last scan</th><th /></tr></thead>
            <tbody>{shown.map((c) => (
              <tr key={c.id}>
                <td><Link href={`/cards/${c.id}`} className="card-code text-[13px] font-medium text-brand-700 hover:underline">{c.card_code}</Link><p className="text-xs text-ink-500">{c.label ?? "No label"}</p></td>
                <td>{c.location_name ?? <span className="text-ink-400">Not assigned</span>}</td>
                <td><Status tone={CARD_STATUS[c.status].tone}>{CARD_STATUS[c.status].label}</Status></td>
                <td><QrNfc c={c} /></td>
                <td className="n font-medium">{fmtNum(c.stats.scan ?? 0)}</td><td className="n">{fmtNum(c.stats.landing_view ?? 0)}</td><td className="n">{fmtNum(c.stats.google_click ?? 0)}</td>
                <td className="whitespace-nowrap text-ink-500">{c.last_scan_at ? timeAgo(c.last_scan_at) : "never"}</td>
                <td className="text-right"><Link href={`/cards/${c.id}`} className="text-[13px] font-medium text-brand-700 hover:underline">Open</Link></td>
              </tr>))}</tbody>
          </table></div>
        </Panel>
      )}
      {data && data.length > 0 && shown.length === 0 && <p className="mt-4 text-sm text-ink-500">No cards in this view.</p>}
      <p className="mt-6 max-w-2xl text-xs text-ink-500">QR and NFC use the same permanent link. FlowQR can&rsquo;t tell whether an NFC tag has been programmed, so NFC shows &ldquo;link ready&rdquo; whenever the card is live. Cards are issued by the FlowQR team; you can label them and move them between your own locations.</p>
      {edit && <CardEditModal card={edit} locations={(locs.data ?? []).filter((l) => l.is_active)} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); toast("Card updated."); void reload(); }} />}
    </>
  );
}
