import { useFetch } from "./use-api";

export type AdminCount = { n: number; tone: "bad" | "warn" } | null;
interface Ops { counts: Record<string, number> }
interface Queue { failed: { counts: Record<string, number>; posts_total: number }; account_requests: { deletions_scheduled: { overdue: boolean }[] } }

/** The two badges on the operator navigation, from the same live checks the pages themselves show: critical or attention items on System health, and things waiting for a person in the Work queue. */
export function useAdminCounts(enabled: boolean): { ops: AdminCount; queue: AdminCount } {
  const ops = useFetch<Ops>(enabled ? "/admin/ops" : null);
  const q = useFetch<Queue>(enabled ? "/admin/work-queue" : null);
  const crit = ops.data?.counts.critical ?? 0, warn = ops.data?.counts.warn ?? 0;
  const failed = q.data ? Object.values(q.data.failed.counts).reduce((a, b) => a + b, 0) + q.data.failed.posts_total + q.data.account_requests.deletions_scheduled.filter((d) => d.overdue).length : 0;
  return { ops: crit ? { n: crit, tone: "bad" } : warn ? { n: warn, tone: "warn" } : null, queue: failed ? { n: failed, tone: "bad" } : null };
}
