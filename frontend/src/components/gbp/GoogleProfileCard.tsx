"use client";
import clsx from "clsx";
import { ExternalLink, Globe, ImageIcon, MapPin, Phone, Star } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { LinkButton } from "@/components/ui/Button";
import { Panel } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/Card";
import { useAuth } from "@/lib/auth";
import { fmtNum } from "@/lib/format";
import { useGbp } from "@/lib/use-gbp";
import type { Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { SafeImage } from "./Gallery";

interface Period { day: string; open: string; close: string }
interface Info { title: string | null; phone: string | null; website: string | null; primary_category: { id: string; name: string } | null; hours: Period[]; open_status: string | null }
interface Media { name: string; category: string | null; url: string | null; thumbnail: string | null }

const DAY = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"];
const WEEKDAY: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
const mins = (t: string) => { const [h, m] = t.split(":").map(Number); return h * 60 + (m || 0); };
const time12 = (t: string) => { const [h, m] = t.split(":").map(Number); return `${((h + 11) % 12) + 1}${m ? `:${String(m).padStart(2, "0")}` : ""} ${h < 12 ? "am" : "pm"}`; };

/** Open or closed right now, from Google's weekly hours, in the business's own time zone. Null when Google has no hours to go on (never guessed). */
export function openNow(hours: Period[], timezone: string, now = new Date()): { open: boolean; next: string } | null {
  if (!hours.length) return null;
  let day: number, at: number;
  try {
    const p = new Intl.DateTimeFormat("en-US", { timeZone: timezone, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(now);
    day = WEEKDAY[p.find((x) => x.type === "weekday")?.value ?? ""] ?? now.getDay();
    at = Number(p.find((x) => x.type === "hour")?.value) * 60 + Number(p.find((x) => x.type === "minute")?.value);
  } catch { day = now.getDay(); at = now.getHours() * 60 + now.getMinutes(); }
  const today = hours.filter((h) => h.day === DAY[day]).sort((a, b) => mins(a.open) - mins(b.open));
  const live = today.find((h) => mins(h.open) <= at && at < mins(h.close));
  if (live) return { open: true, next: `Closes ${time12(live.close)}` };
  const later = today.find((h) => mins(h.open) > at);
  if (later) return { open: false, next: `Opens ${time12(later.open)}` };
  for (let i = 1; i <= 7; i++) {
    const d = DAY[(day + i) % 7];
    const first = hours.filter((h) => h.day === d).sort((a, b) => mins(a.open) - mins(b.open))[0];
    if (first) return { open: false, next: `Opens ${i === 1 ? "tomorrow" : d.slice(0, 1) + d.slice(1, 3).toLowerCase()} ${time12(first.open)}` };
  }
  return { open: false, next: "" };
}

/** Photos in the order a visitor would want them: cover first, then the ones that show the place, then the rest. */
const ORDER = ["COVER", "EXTERIOR", "INTERIOR", "AT_WORK", "TEAMS", "PROFILE", "LOGO"];
const rank = (c: string | null) => { const i = ORDER.indexOf(c ?? ""); return i < 0 ? ORDER.length : i; };

/**
 * "How Google shows you": the connected Google Business Profile as people see it in Search and Maps (photos, name, rating, category,
 * open now, address, hours, phone, website). Everything comes from what Google returned for the selected location; a part Google
 * didn't give is left out, never invented.
 */
export function GoogleProfileCard() {
  const g = useGbp();
  const { tenant } = useAuth();
  const gl = g.selected.find((l) => l.id === g.gid);
  const gid = gl?.id ?? null;
  const info = useFetch<Info>(gid ? `/gbp/${gid}/info` : null);
  const media = useFetch<Media[]>(gid ? `/gbp/${gid}/media` : null);
  const range = useMemo(() => { const to = new Date(), from = new Date(); from.setDate(to.getDate() - 29); const d = (x: Date) => x.toISOString().slice(0, 10); return { from: d(from), to: d(to) }; }, []);
  const ov = useFetch<Overview>(gl ? "/analytics/overview" : null, { ...range, location_id: gl?.location_id ?? "" });

  if (g.loading || g.locsLoading) return <Skeleton className="h-64 !rounded-[28px]" />;
  if (!g.conn || !gl) {
    const none = !g.anyConn, why = none ? "Connect your Google Business Profile and your photos, rating, address and hours will show here, the way customers see them on Google."
      : g.anyConn?.status === "revoked" ? "Google access was lost. Reconnect to show your profile here." : "Choose a location to show its Google profile here.";
    return (
      <Panel dense title="How Google shows you" action={<LinkButton href="/settings/connections/google" variant="secondary" size="sm">{none ? "Connect Google" : "Open Google connection"}</LinkButton>}>
        <div className="flex items-center gap-4"><span aria-hidden className="grid h-14 w-14 shrink-0 place-items-center rounded-[14px] bg-surface-2"><ImageIcon className="h-6 w-6 text-muted" /></span><p className="max-w-xl text-[14px] text-muted">{why}</p></div>
      </Panel>
    );
  }

  const photos = [...(media.data ?? [])].sort((a, b) => rank(a.category) - rank(b.category));
  const lead = photos[0];
  const rest = photos.slice(1, 4);
  const profilePhoto = (media.data ?? []).find((m) => m.category === "PROFILE" || m.category === "LOGO");
  const d = info.data;
  const status = d ? openNow(d.hours, tenant?.timezone ?? "Asia/Kolkata") : null;
  const closed = d?.open_status === "CLOSED_PERMANENTLY" ? "Permanently closed" : d?.open_status === "CLOSED_TEMPORARILY" ? "Temporarily closed" : null;
  const r = ov.data?.reviews;
  const rating = r?.average_rating_all_time ?? null;
  const title = d?.title ?? gl.title ?? "Your business";
  const mapHref = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([title, gl.address].filter(Boolean).join(" "))}`;

  return (
    <Panel dense title="How Google shows you" meta={g.conn.google_email ?? undefined}
      action={<a href={mapHref} target="_blank" rel="noreferrer" className="inline-flex min-h-8 items-center gap-1.5 text-[13px] font-semibold text-accent-ink hover:underline">View on Google Maps<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:gap-6">
        {/* the photos, the way Google lays them out: one large, up to three small */}
        <div className="relative">
          {media.loading && !media.data ? <Skeleton className="h-56 !rounded-[16px]" /> : photos.length === 0 ? (
            <div className="grid h-56 place-items-center rounded-[16px] bg-surface-2 text-center"><div><ImageIcon className="mx-auto h-6 w-6 text-muted" aria-hidden /><p className="mt-2 text-[14px] font-medium">No photos on Google yet</p><Link href="/gbp/photos" className="text-[13px] font-semibold text-accent-ink hover:underline">Add photos</Link></div></div>
          ) : (
            <div className={clsx("grid h-56 gap-1.5 overflow-hidden rounded-[16px] sm:h-60", rest.length ? "grid-cols-[1.4fr_1fr]" : "grid-cols-1")}>
              <SafeImage m={lead} className="h-full w-full object-cover" />
              {rest.length > 0 && (
                <div className={clsx("grid min-h-0 gap-1.5", rest.length === 1 ? "grid-rows-1" : "grid-rows-2")}>
                  {rest.length === 1 ? <SafeImage m={rest[0]} className="h-full w-full object-cover" /> : (<>
                    <SafeImage m={rest[0]} className="h-full w-full object-cover" />
                    <div className={clsx("grid min-h-0 gap-1.5", rest.length > 2 ? "grid-cols-2" : "grid-cols-1")}>{rest.slice(1).map((m) => <SafeImage key={m.name} m={m} className="h-full w-full object-cover" />)}</div>
                  </>)}
                </div>
              )}
            </div>
          )}
          {photos.length > 0 && <Link href="/gbp/photos" className="absolute bottom-2 right-2 inline-flex min-h-8 items-center gap-1.5 rounded-full bg-black/65 px-3 text-[13px] font-semibold text-white backdrop-blur hover:bg-black/80"><ImageIcon className="h-3.5 w-3.5" aria-hidden />{photos.length} {photos.length === 1 ? "photo" : "photos"}</Link>}
        </div>

        <div className="min-w-0">
          <div className="flex items-start gap-3">
            {profilePhoto && <SafeImage m={profilePhoto} className="h-12 w-12 shrink-0 rounded-full object-cover ring-1 ring-line" />}
            <div className="min-w-0">
              <h3 className="text-[19px] font-semibold leading-6 [overflow-wrap:anywhere]">{title}</h3>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[14px]">
                {rating !== null && <span className="inline-flex items-center gap-1"><b className="num font-semibold">{rating.toFixed(1)}</b>
                  <span aria-hidden className="inline-flex">{[1, 2, 3, 4, 5].map((n) => <Star key={n} className={clsx("h-3.5 w-3.5", n <= Math.round(rating) ? "fill-star text-star" : "text-ink-300")} />)}</span>
                  <span className="sr-only">out of 5</span></span>}
                {r && r.total_synced > 0 && <span className="text-accent-ink">{fmtNum(r.total_synced)} Google {r.total_synced === 1 ? "review" : "reviews"}</span>}
              </p>
              {d?.primary_category && <p className="mt-0.5 text-[14px] text-muted">{d.primary_category.name}</p>}
            </div>
          </div>

          {(closed || status) && <p className="mt-3 text-[14px]"><span className={clsx("font-semibold", closed ? "text-neg" : status?.open ? "text-pos" : "text-neg")}>{closed ?? (status!.open ? "Open" : "Closed")}</span>{!closed && status?.next && <span className="text-muted"> · {status.next}</span>}</p>}

          <ul className="mt-3 space-y-2 text-[14px]">
            {gl.address && <li className="flex items-start gap-2.5"><MapPin className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden /><span className="[overflow-wrap:anywhere]">{gl.address}</span></li>}
            {d?.phone && <li className="flex items-center gap-2.5"><Phone className="h-4 w-4 shrink-0 text-muted" aria-hidden /><a href={`tel:${d.phone.replace(/\s/g, "")}`} className="hover:underline">{d.phone}</a></li>}
            {d?.website && <li className="flex items-center gap-2.5"><Globe className="h-4 w-4 shrink-0 text-muted" aria-hidden /><a href={d.website} target="_blank" rel="noreferrer" className="min-w-0 truncate hover:underline">{d.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</a></li>}
          </ul>
          {info.error && !d && <p className="mt-3 text-[13px] text-muted">Google didn&rsquo;t share the full profile just now. Name and address are from your connection.</p>}
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px] font-semibold"><Link href="/gbp/info" className="inline-flex min-h-8 items-center text-accent-ink hover:underline">Edit info &amp; hours</Link><Link href="/gbp/photos" className="inline-flex min-h-8 items-center text-accent-ink hover:underline">Manage photos</Link></div>
        </div>
      </div>
    </Panel>
  );
}
