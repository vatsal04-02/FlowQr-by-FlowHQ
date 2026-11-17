"use client";
import { useState } from "react";
import { TaskCard } from "@/components/agent/TaskCard";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/kit";
import type { TasksResponse } from "@/lib/agent";
import { useFetch } from "@/lib/use-api";

const KINDS = [["", "All"], ["reply_review", "Replies"], ["create_post", "Posts"], ["profile_fix", "Profile"], ["add_photo", "Photos"], ["connect_google", "Google"], ["complete_knowledge", "Knowledge"]] as const;

export default function Recommendations() {
  const [scope, setScope] = useState<"open" | "history">("open");
  const [kind, setKind] = useState("");
  const { data, error, loading, reload } = useFetch<TasksResponse>("/agent/tasks", { scope, kind });
  return (
    <>
      <PageHeader title="Tasks" subtitle="Things that would help your business, with the reason for each."
        actions={<Segmented label="Show" value={scope} onChange={setScope} options={[["open", "Open"], ["history", "History"]] as const} />} />
      <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Filter by kind">
        {KINDS.map(([k, l]) => <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)} className={`min-h-9 rounded-full px-3.5 text-[13px] font-medium transition-[background-color,color,transform] duration-200 ease-spring active:scale-95 ${kind === k ? "bg-ink-solid text-ink-on" : "bg-surface text-ink-700 ring-1 ring-line hover:bg-surface-2"}`}>{l}</button>)}
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-48" /> : (data?.tasks.length ?? 0) === 0 ? <EmptyState title={scope === "open" ? "Nothing open" : "No history yet"}>{scope === "open" ? "No open recommendations in this view." : "Finished tasks appear here."}</EmptyState>
        : <ul className="space-y-3">{data!.tasks.map((t) => <TaskCard key={t.id} t={t} onChange={() => void reload()} />)}</ul>}
    </>
  );
}
