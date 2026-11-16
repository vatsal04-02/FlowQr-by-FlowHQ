"use client";
import clsx from "clsx";
import { Info, MapPinned, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Skeleton } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Meter, Panel, Segmented } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Pt { i: number; lat: number; lng: number; label?: string }
interface Change { comparable: boolean; reason?: string; significant?: boolean; direction?: "improved" | "declined" | "mixed" | "unchanged"; summary?: string; delta_solv?: number | null; delta_arp?: number | null; delta_coverage?: number | null; points?: Record<string, number> }
interface Scan { id: string; status: string; source: string; started_at: string; finished_at: string | null; points_total: number; points_ok: number; points_found: number; arp: number | null; atrp: number | null; solv: number | null; coverage: number | null; calls: number; change: Change | null; error: string | null }
interface Grid { id: string; name: string; mode: "square" | "custom"; size: number | null; spacing_m: number | null; points: Pt[]; point_count: number; active: boolean; latest: { keyword_id: string; scan: Scan | null }[] }
interface Allowance { enabled: boolean; reason?: "not_in_plan" | "not_configured" | "switched_off" | "caps_missing" | "unpriced" | null; limits: { max_grids: number; max_points: number; monthly_points: number } | null; used: number; cap: number; remaining: number; resets_on: string; platform_capped: boolean; cost_per_call_usd: number | null; estimated_spend_usd: number | null }
interface Overview { configured: boolean; allowance: Allowance; note: string; sizes: number[]; spacing: { min: number; max: number }; has_position: boolean; keywords: { id: string; keyword: string }[]; grids: Grid[] }
interface Cell { i: number; lat: number; lng: number; label?: string; rank: number | null; status: string; bucket: string; error?: string | null }
interface Heat { cells: Cell[]; scan: Scan | null; bounds: { south: number; north: number; west: number; east: number } | null; legend: { key: string; label: string }[]; note: string; stale_grid?: boolean }

const BUCKET: Record<string, string> = {
  top3: "bg-pos text-surface", top10: "bg-warn-tint text-warn ring-1 ring-inset ring-warn", top20: "bg-neg-tint text-neg ring-1 ring-inset ring-neg",
  none: "bg-surface-2 text-muted ring-1 ring-inset ring-line", error: "hatch text-muted ring-1 ring-inset ring-line", unmeasured: "bg-surface text-muted-soft ring-1 ring-inset ring-line border-dashed",
};
const SPACINGS = [500, 1000, 2000, 3000, 5000];

/** The map: one circle per measured point at its real position. Each shows the position (or "–" for not in the first 20); colour is never the only signal. */
export function Heatmap({ heat }: { heat: Heat }) {
  const n = Math.max(1, Math.ceil(Math.sqrt(heat.cells.length)));
  const b = heat.bounds;
  const pos = (c: Cell) => {
    if (!b || b.north === b.south || b.east === b.west) return { x: 50, y: 50 };
    return { x: 10 + (80 * (c.lng - b.west)) / (b.east - b.west), y: 10 + (80 * (b.north - c.lat)) / (b.north - b.south) };
  };
  const size = `${Math.min(15, 78 / n)}%`;
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[460px] rounded-tile bg-surface-2 ring-1 ring-inset ring-line" role="img"
      aria-label={`Map of ${heat.cells.length} measured points. ${heat.cells.filter((c) => c.bucket === "top3").length} are in the top 3.`}>
      {heat.cells.map((c) => {
        const p = pos(c);
        const text = c.status === "error" ? "!" : c.status === "unmeasured" ? "" : c.rank ? String(c.rank) : "–";
        return (
          <div key={c.i} title={`${c.label ?? `Point ${c.i + 1}`}: ${c.status === "error" ? "could not be measured" : c.status === "unmeasured" ? "not measured yet" : c.rank ? `position ${c.rank}` : "not in the first 20"}`}
            className={clsx("absolute grid aspect-square -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full text-[13px] font-semibold tabular-nums sm:text-sm", BUCKET[c.bucket] ?? BUCKET.unmeasured)}
            style={{ left: `${p.x}%`, top: `${p.y}%`, width: size }}>{text}</div>
        );
      })}
    </div>
  );
}

function Legend({ items }: { items: { key: string; label: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted" aria-label="Legend">
      {items.map((l) => <li key={l.key} className="flex items-center gap-1.5"><span aria-hidden className={clsx("h-3.5 w-3.5 rounded-full", BUCKET[l.key])} />{l.label}</li>)}
    </ul>
  );
}

function ChangeNote({ c }: { c: Change | null }) {
  if (!c) return null;
  if (!c.comparable) return <p className="text-sm text-muted">{c.reason}</p>;
  const tone = c.direction === "improved" ? "green" : c.direction === "declined" ? "red" : "gray";
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone}>{c.significant ? `Significant change: ${c.direction}` : "No significant change"}</Badge>
        {c.delta_solv != null && <span className="text-xs text-muted">Top-3 coverage {c.delta_solv > 0 ? "+" : ""}{c.delta_solv} pts</span>}
        {c.delta_arp != null && <span className="text-xs text-muted">Average position {c.delta_arp > 0 ? "+" : ""}{c.delta_arp}</span>}
      </div>
      <p className="text-sm text-muted">{c.summary}</p>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return <div className="rounded-tile bg-surface-2 p-3"><p className="text-xs text-muted">{label}</p><p className="num mt-0.5 text-xl font-semibold">{value}</p><p className="text-[11px] text-muted">{hint}</p></div>;
}

function NewGrid({ gid, ov, onDone }: { gid: string; ov: Overview; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"square" | "custom">("square");
  const [size, setSize] = useState(5);
  const [spacing, setSpacing] = useState(2000);
  const [pts, setPts] = useState("");
  const [busy, setBusy] = useState(false);
  const max = ov.allowance.limits?.max_points ?? 0;
  const sizes = ov.sizes.filter((s) => s * s <= max);
  async function save() {
    setBusy(true);
    try {
      const points = mode === "custom" ? pts.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [la, lo, ...rest] = l.split(","); return { lat: Number(la), lng: Number(lo), label: rest.join(",").trim() }; }) : undefined;
      await api(`/gbp/${gid}/rank/grids`, { method: "POST", body: { name, mode, ...(mode === "square" ? { size, spacing_m: spacing } : { points }) } });
      toast("Grid created. Run a scan to measure it."); setName(""); setPts(""); onDone();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <form className="space-y-4 rounded-tile border border-line p-4" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <h3 className="text-sm font-semibold">New map</h3>
      <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} placeholder="e.g. Around the clinic" />
      <Segmented value={mode} onChange={setMode} label="How to choose the points" options={[["square", "Square grid"], ["custom", "My own points"]] as const} />
      {mode === "square" ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="Points per side" value={size} onChange={(e) => setSize(Number(e.target.value))}>{sizes.map((s) => <option key={s} value={s}>{s} × {s} ({s * s} searches per scan)</option>)}</Select>
          <Select label="Distance between points" value={spacing} onChange={(e) => setSpacing(Number(e.target.value))}>{SPACINGS.filter((s) => s >= ov.spacing.min && s <= ov.spacing.max).map((s) => <option key={s} value={s}>{s >= 1000 ? `${s / 1000} km` : `${s} m`}</option>)}</Select>
        </div>
      ) : (
        <Textarea label="One point per line: latitude, longitude, name" rows={4} value={pts} onChange={(e) => setPts(e.target.value)} placeholder={"26.8467, 80.9462, Main road\n26.8601, 80.9120, North side"} hint={`Up to ${max} points, each within 50 km of the business.`} />
      )}
      <Button type="submit" loading={busy} disabled={name.trim().length < 2} icon={<Plus className="h-4 w-4" aria-hidden />}>Create map</Button>
    </form>
  );
}

/**
 * GBP Manager › Local ranking › Map. Where the business appears for a search term from several points around it (Google Places API), drawn as a heat map.
 * Every circle is one billed Google search: the page always says how many a scan will use and how many are left, and a scan that does not fit is refused before anything is spent.
 */
export function GeoGrid({ gid }: { gid: string }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const ov = useFetch<Overview>(`/gbp/${gid}/rank/grids`);
  const [gridId, setGridId] = useState<string | null>(null);
  const [kwId, setKwId] = useState<string | null>(null);
  const [heat, setHeat] = useState<Heat | null>(null);
  const [hist, setHist] = useState<Scan[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const d = ov.data;
  const grid = useMemo(() => d?.grids.find((g) => g.id === (gridId ?? d.grids[0]?.id)) ?? null, [d, gridId]);
  const kw = kwId ?? d?.keywords[0]?.id ?? null;

  useEffect(() => {
    let live = true;
    setHeat(null); setHist([]);
    if (!grid || !kw) return;
    void (async () => {
      try {
        const [h, hs] = await Promise.all([api<Heat>(`/gbp/${gid}/rank/grids/${grid.id}/heatmap`, { params: { keyword_id: kw } }), api<{ scans: Scan[] }>(`/gbp/${gid}/rank/grids/${grid.id}/history`, { params: { keyword_id: kw, limit: 8 } })]);
        if (live) { setHeat(h); setHist(hs.scans); }
      } catch (e) { if (live) toast(errorMessage(e), "error"); }
    })();
    return () => { live = false; };
  }, [gid, grid?.id, kw, d?.allowance.used]); // eslint-disable-line react-hooks/exhaustive-deps

  if (ov.error) return <Alert tone="error" title="Couldn't load the map view">{ov.error}</Alert>;
  if (!d) return <Skeleton className="h-48" />;
  if (!d.allowance.enabled) return <Panel title="Visibility across nearby areas"><p className="text-sm text-muted">{d.allowance.reason === "not_in_plan" ? "Measuring your ranking from several points around your business isn't included in your current plan. The single-point ranking above still works." : "Map ranking is switched off for now while FlowQR finishes setting its Google search limits and allowances. The single-point ranking above still works."}</p></Panel>;

  const a = d.allowance;
  const need = grid?.point_count ?? 0;
  const fits = need <= a.remaining;
  const canRun = isAdmin && d.configured && d.has_position !== false && !!grid && !!kw && fits;
  async function scan() {
    if (!grid || !kw) return;
    setBusy("scan");
    try {
      const r = await api<{ scan: Scan }>(`/gbp/${gid}/rank/grids/${grid.id}/scan`, { method: "POST", body: { keyword_id: kw } });
      toast(r.scan.status === "done" ? `Measured ${r.scan.points_ok} points.` : r.scan.error ?? "Scan finished with some points not measured.", r.scan.status === "done" ? undefined : "error");
      await ov.reload();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  async function remove() {
    if (!grid) return;
    setBusy("del");
    try { await api(`/gbp/${gid}/rank/grids/${grid.id}`, { method: "DELETE" }); setGridId(null); toast("Map removed."); await ov.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  const s = heat?.scan ?? null;

  return (
    <Panel title="Map view" meta="Where you appear, street by street" action={isAdmin && d.grids.length < (a.limits?.max_grids ?? 0) ? <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" aria-hidden />} onClick={() => setAdding(!adding)}>New map</Button> : undefined}>
      <div className="space-y-5">
        <div className="rounded-tile bg-surface-2 p-3.5">
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm"><span className="font-semibold">{a.remaining} of {a.cap} map searches left this month</span><span className="text-xs text-muted">Resets {fmtDate(a.resets_on, { day: "numeric", month: "short" })}</span></div>
          <div className="mt-2"><Meter value={a.used} max={a.cap} tone={a.remaining < need ? "warn" : "info"} label="Map searches used this month" /></div>
          <p className="mt-2 text-xs text-muted">Each point on a map is one Google search. {a.cost_per_call_usd ? `Estimated spend so far this month: $${a.estimated_spend_usd?.toFixed(2)}.` : "Prices are not configured, so only counts are shown."}</p>
        </div>

        {!d.configured && <Alert tone="warning" title="Local ranking isn't switched on for this server">Maps need the Google Places key on the server.</Alert>}
        {adding && isAdmin && <NewGrid gid={gid} ov={d} onDone={() => { setAdding(false); void ov.reload(); }} />}

        {d.grids.length === 0 ? (
          <p className="rounded-tile bg-surface-2 p-5 text-sm text-muted">{d.keywords.length === 0 ? "Add a search term above first, then create a map." : isAdmin ? "No map yet. Create one to see how your ranking changes from place to place." : "An owner or admin creates the map."}</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Select label="Map" value={grid?.id ?? ""} onChange={(e) => setGridId(e.target.value)}>{d.grids.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.point_count} points)</option>)}</Select>
              <Select label="Search term" value={kw ?? ""} onChange={(e) => setKwId(e.target.value)}>{d.keywords.map((k) => <option key={k.id} value={k.id}>{k.keyword}</option>)}</Select>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {isAdmin && <Button onClick={() => void scan()} loading={busy === "scan"} disabled={!canRun} icon={<RefreshCw className="h-4 w-4" aria-hidden />}>Scan now ({need} searches)</Button>}
              {isAdmin && grid && <Button variant="ghost" size="sm" onClick={() => void remove()} loading={busy === "del"} icon={<Trash2 className="h-4 w-4" aria-hidden />}>Remove map</Button>}
              {!fits && <span className="text-sm text-warn">Not enough searches left this month for a full scan. Nothing is spent until it fits.</span>}
              {s && <span className="text-xs text-muted">Last scan {timeAgo(s.started_at)}{s.source === "auto" ? " (automatic)" : ""}</span>}
            </div>

            {!heat ? <Skeleton className="mx-auto aspect-square w-full max-w-[460px]" /> : (
              <div className="grid gap-5 lg:grid-cols-[minmax(0,460px)_1fr] lg:items-start">
                <div className="space-y-3"><Heatmap heat={heat} /><Legend items={heat.legend} /></div>
                <div className="space-y-4">
                  {s ? (
                    <>
                      <div className="grid grid-cols-3 gap-2">
                        <Stat label="Top 3" value={s.solv != null ? `${Math.round(s.solv)}%` : "–"} hint="of points" />
                        <Stat label="Average position" value={s.arp != null ? s.arp.toFixed(1) : "–"} hint="21 = not found" />
                        <Stat label="In first 20" value={s.coverage != null ? `${Math.round(s.coverage)}%` : "–"} hint="of points" />
                      </div>
                      {s.status !== "done" && <Alert tone="warning" title={s.status === "failed" ? "This scan could not be measured" : "Some points could not be measured"}>{s.error}</Alert>}
                      <ChangeNote c={s.change} />
                    </>
                  ) : <p className="text-sm text-muted">Not scanned yet. Run a scan to fill in the map.</p>}
                  {hist.length > 1 && (
                    <div>
                      <h3 className="text-sm font-semibold">Earlier scans</h3>
                      <ul className="mt-2 divide-y divide-line rounded-tile border border-line text-sm">
                        {hist.map((h) => <li key={h.id} className="flex items-center justify-between gap-3 px-3 py-2"><span className="text-muted">{fmtDate(h.started_at)}</span><span className="tabular-nums">Top 3: {h.solv != null ? `${Math.round(h.solv)}%` : "–"}</span><span className="tabular-nums text-muted">Avg {h.arp?.toFixed(1) ?? "–"}</span>{h.change?.significant && <Badge tone={h.change.direction === "improved" ? "green" : "red"}>{h.change.direction}</Badge>}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}
        <p className="flex items-start gap-2 text-xs text-muted"><MapPinned className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /><Info className="sr-only" aria-hidden />{d.note} Active maps are re-scanned about once a week when your allowance covers the whole scan.</p>
      </div>
    </Panel>
  );
}
