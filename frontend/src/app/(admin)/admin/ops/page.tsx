"use client";
import { CheckCircle2, HelpCircle, OctagonAlert, TriangleAlert } from "lucide-react";
import { Alert, Badge, Card, PageHeader, Skeleton } from "@/components/ui/Card";
import { PlatformStop } from "@/components/admin/PlatformControls";
import { Button } from "@/components/ui/Button";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

type Status = "ok" | "warn" | "critical" | "unknown";
interface Check { id: string; label: string; status: Status; detail: string; action: string }
interface Ops { status: Status; checked_at: string; counts: Record<Status, number>; checks: Check[] }

const TONE = { ok: "green", warn: "amber", critical: "red", unknown: "gray" } as const;
const WORD = { ok: "Healthy", warn: "Needs attention", critical: "Critical", unknown: "Not measured" } as const;
const ICON = { ok: CheckCircle2, warn: TriangleAlert, critical: OctagonAlert, unknown: HelpCircle } as const;
const ORDER: Status[] = ["critical", "warn", "unknown", "ok"];

/** FlowHQ operations: every check the platform runs on itself, worst first, with what to do. Nothing here is customer content. */
export default function AdminOps() {
  const ops = useFetch<Ops>("/admin/ops");
  const d = ops.data;
  const sorted = d ? [...d.checks].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status)) : [];
  return (
    <>
      <PageHeader eyebrow="Platform" title="Operations" subtitle="Is FlowQR healthy right now, and what needs a person? Checked live each time you open this page; the scheduler also checks every 15 minutes and emails admins about new critical items."
        actions={<Button variant="secondary" size="sm" onClick={() => void ops.reload()}>Check again</Button>} />
      {ops.error && <Alert tone="error" title="Couldn't run the checks">{ops.error}</Alert>}
      {!d && !ops.error && <Skeleton className="h-64" />}
      {d && (
        <>
          <Alert tone={d.status === "ok" ? "success" : d.status === "critical" ? "error" : "warning"} title={d.status === "ok" ? "Everything measured is healthy" : d.status === "critical" ? `${d.counts.critical} critical item${d.counts.critical === 1 ? "" : "s"} need action` : `${d.counts.warn} item${d.counts.warn === 1 ? "" : "s"} need attention`}>
            {d.counts.ok} healthy · {d.counts.warn} attention · {d.counts.critical} critical · {d.counts.unknown} not measured. Checked {fmtDate(d.checked_at)}.
          </Alert>
          <Card className="mt-5" pad={false}>
            <ul className="divide-y divide-line" aria-label="Platform checks">
              {sorted.map((c) => { const I = ICON[c.status]; return (
                <li key={c.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 p-4 sm:px-6">
                  <I className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">{c.label}</p>
                    <p className="text-sm text-muted">{c.detail}</p>
                    {c.action && <p className="mt-1 text-sm"><span className="font-semibold">Do this:</span> {c.action}</p>}
                  </div>
                  <Badge tone={TONE[c.status]}>{WORD[c.status]}</Badge>
                </li>); })}
            </ul>
          </Card>
        </>
      )}
      <PlatformStop />
    </>
  );
}
