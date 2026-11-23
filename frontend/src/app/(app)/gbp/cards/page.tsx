"use client";
import { Download, QrCode, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { FlowCard } from "@/components/CardArt";
import { CardEditModal } from "@/components/CardEditModal";
import { AssignCards } from "@/components/cards/AssignCards";
import { PosterDownload } from "@/components/cards/PosterDownload";
import { QrNfc } from "@/components/QrNfc";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton, ErrorState } from "@/components/ui/Card";
import { Panel, Segmented, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/lib/auth";
import { CARD_STATUS, cardState, isLive } from "@/lib/card-ui";
import { fmtNum, timeAgo } from "@/lib/format";
import type { Card as CardT, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

type Filter = "all" | "live" | "reserved" | "paused" | "retired";
const FILTERS: [Filter, string][] = [["all", "All"], ["live", "Live"], ["reserved", "Waiting"], ["paused", "Paused"], ["retired", "Retired"]];
const matches = (c: CardT, f: Filter) => f === "all" || (f === "live" ? isLive(c.status) : f === "reserved" ? c.status === "reserved" : f === "paused" ? c.status === "paused" || c.status === "deactivated" || c.status === "lost" : c.status === "retired");

export default function CardsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<CardT[]>("/cards");
  const locs = useFetch<Location[]>("/locations");
  const [tab, setTab] = useState<"inventory" | "assign">("inventory");
  const [view, setView] = useState<"gallery" | "table">("gallery");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<CardT | null>(null);

  const term = q.trim().toLowerCase();
  const shown = useMemo(() => (data ?? []).filter((c) => matches(c, filter) && (!term || c.card_code.toLowerCase().includes(term) || (c.label ?? "").toLowerCase().includes(term))), [data, filter, term]);
  const counts = useMemo(() => {
    const n: Record<string, number> = { live: 0, reserved: 0, paused: 0, retired: 0 };
    for (const c of data ?? []) { if (matches(c, "live")) n.live++; else if (c.status === "reserved") n.reserved++; else if (matches(c, "paused")) n.paused++; else if (c.status === "retired") n.retired++; }
    return n;
  }, [data]);
  const total = (data ?? []).reduce((a, c) => a + (c.stats.scan ?? 0), 0);
  const waiting = counts.reserved;

  return (
    <>
      <PageHeader title="Cards"
        subtitle={data && data.length ? `${data.length} · ${counts.live} live · ${fmtNum(total)} scans` : undefined}
        actions={<>
          <Segmented label="Section" value={tab} onChange={setTab} options={isAdmin ? ([["inventory", "Inventory"], ["assign", "Assign cards"]] as const) : ([["inventory", "Inventory"]] as const)} />
        </>} />
      {error && <ErrorState error={error} onRetry={() => void reload()} />}

      {tab === "assign" && isAdmin ? <AssignCards mode="tenant" onDone={() => void reload()} /> : (
        <>
          {waiting > 0 && isAdmin && (
            <div className="mb-4"><Alert tone="info" title={`${waiting} ${waiting === 1 ? "card is" : "cards are"} waiting for you`}
              action={<Button size="sm" onClick={() => setTab("assign")}>Assign cards</Button>}>FlowHQ has set these aside for your business. Scan each one to give it a location and review page, and it goes live.</Alert></div>
          )}
          {data && data.length > 0 && <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative min-w-[200px] flex-1 sm:max-w-xs"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden />
              <input aria-label="Search by serial number or label" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search serial, e.g. FQR-0012" className="min-h-11 w-full rounded-xl border border-ink-200 bg-white pl-9 pr-3 text-[16px] sm:min-h-10 sm:text-sm" /></div>
            <Segmented label="Show" value={filter} onChange={setFilter} options={FILTERS.map(([k, l]) => [k, k === "all" ? l : `${l} ${counts[k] ?? 0}`] as const)} />
            <Segmented label="View" value={view} onChange={setView} options={[["gallery", "Cards"], ["table", "Table"]] as const} />
          </div>}
          {loading && !data ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-64" />)}</div> : data && data.length === 0 ? (
            <section aria-labelledby="first-card-h" className="overflow-hidden rounded-[16px] bg-surface shadow-card max-md:overflow-visible max-md:!bg-transparent max-md:!shadow-none max-md:!border-0">
              <div className="grid items-center gap-6 p-5 sm:p-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] max-md:flex max-md:flex-col max-md:gap-4 max-md:p-0">
                <div className="max-md:order-2 max-md:w-full max-md:rounded-[18px] max-md:border max-md:border-set-line max-md:bg-set-surface max-md:p-4">
                  <h2 id="first-card-h" className="text-[17px] font-semibold">Your first card</h2>
                  <ol className="mt-5 space-y-3">
                    {[["Order cards", ""], ["Scan one to place it", ""], ["Put it at the counter", ""]].map(([t, d], i) => (
                      <li key={t} className="flex items-start gap-3"><span aria-hidden className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-ink-solid text-xs font-bold text-ink-on">{i + 1}</span><div><p className="text-[14px] font-semibold">{t}</p><p className="text-[13px] text-ink-700">{d}</p></div></li>))}
                  </ol>
                  <div className="mt-6 max-md:mt-4"><LinkButton href="/settings/billing/payments" variant="brand" size="lg" className="max-md:w-full">Order cards</LinkButton></div>
                </div>
                <div className="flex items-start justify-center gap-4 max-md:order-1 max-md:w-full max-md:items-center max-md:rounded-[18px] max-md:bg-[#EEE8E0] max-md:py-6 dark:max-md:bg-set-neutral-bg" aria-hidden>
                  <FlowCard code="FQR-0000" state="unassigned" className="w-[150px] sm:w-[170px] max-md:w-[136px] max-md:-rotate-[4deg]" />
                  <FlowCard code="FQR-0000" state="unassigned" className="mt-10 w-[150px] sm:w-[170px] max-md:mt-0 max-md:w-[136px] max-md:rotate-[4deg]" />
                </div>
              </div>
            </section>
          ) : view === "gallery" ? (
            <ul className="grid grid-cols-2 gap-x-4 gap-y-8 md:grid-cols-3 xl:grid-cols-4">
              {shown.map((c) => (
                <li key={c.id} data-testid="card-tile">
                  <Link href={`/gbp/cards/${c.id}`} className="group block" aria-label={`${c.card_code}, ${CARD_STATUS[c.status].label}`}>
                    <FlowCard code={c.card_code} state={cardState(c.status)} className="transition-transform duration-200 group-hover:-translate-y-0.5" />
                  </Link>
                  <div className="mt-3 flex items-start justify-between gap-3">
                    <div className="min-w-0"><p className="card-code text-sm font-medium">{c.card_code}</p><p className="truncate text-[13px] text-ink-500">{c.label ?? "No label"} · {c.location_name ?? "No location"}</p>
                      {c.campaign_name && <p className="truncate text-[13px] text-ink-500">Campaign: {c.campaign_name}</p>}</div>
                    <Status tone={CARD_STATUS[c.status].tone}>{CARD_STATUS[c.status].label}</Status>
                  </div>
                  <dl className="mt-2 grid grid-cols-4 divide-x divide-ink-100 rounded-lg border border-ink-100 bg-white text-center">
                    {[["QR", c.stats.qr_scan], ["NFC", c.stats.nfc_scan], ["Visits", c.stats.landing_view], ["Clicks", c.stats.google_click]].map(([k, v]) => (
                      <div key={k as string} className="px-1 py-1.5"><dd className="num text-sm font-semibold">{fmtNum((v as number) ?? 0)}</dd><dt className="text-[12px] text-ink-500">{k as string}</dt></div>))}
                  </dl>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-x-2 text-xs text-ink-500">
                    <span>Last scan {c.last_scan_at ? timeAgo(c.last_scan_at) : "never"}</span>
                    <span className="flex gap-1">
                      {isAdmin && c.location_id && c.status !== "retired" && <PosterDownload path={`/cards/${c.id}/poster`} filename={c.card_code} label="Poster" variant="ghost" />}
                      {isAdmin && c.status !== "retired" && <Button size="sm" variant="ghost" onClick={() => setEdit(c)}>{c.location_id ? "Change" : "Assign"}</Button>}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Panel flush>
              <div className="overflow-x-auto"><table className="dt min-w-[900px]">
                <thead><tr><th>Card</th><th>Location · campaign</th><th>Status</th><th>QR / NFC</th><th className="!text-right">QR scans</th><th className="!text-right">NFC taps</th><th className="!text-right">Visits</th><th className="!text-right">Clicks</th><th>Last activity</th><th /></tr></thead>
                <tbody>{shown.map((c) => (
                  <tr key={c.id}>
                    <td><Link href={`/gbp/cards/${c.id}`} className="card-code text-[13px] font-medium text-brand-700 hover:underline">{c.card_code}</Link><p className="text-xs text-ink-500">{c.label ?? "No label"}</p></td>
                    <td>{c.location_name ?? <span className="text-ink-400">Not placed yet</span>}{c.campaign_name && <span className="block text-xs text-ink-500">{c.campaign_name}</span>}</td>
                    <td><Status tone={CARD_STATUS[c.status].tone}>{CARD_STATUS[c.status].label}</Status></td>
                    <td><QrNfc c={c} /></td>
                    <td className="n">{fmtNum(c.stats.qr_scan ?? 0)}</td><td className="n">{fmtNum(c.stats.nfc_scan ?? 0)}</td><td className="n">{fmtNum(c.stats.landing_view ?? 0)}</td><td className="n">{fmtNum(c.stats.google_click ?? 0)}</td>
                    <td className="whitespace-nowrap text-ink-500">{c.last_scan_at ? timeAgo(c.last_scan_at) : "never"}</td>
                    <td className="text-right"><Link href={`/gbp/cards/${c.id}`} className="text-[13px] font-medium text-brand-700 hover:underline">Open</Link></td>
                  </tr>))}</tbody>
              </table></div>
            </Panel>
          )}
          {data && data.length > 0 && shown.length === 0 && <p className="mt-4 text-sm text-ink-500">No cards match.</p>}
          
        </>
      )}
      {edit && <CardEditModal card={edit} locations={(locs.data ?? []).filter((l) => l.is_active)} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); toast("Card updated."); void reload(); }} />}
    </>
  );
}
