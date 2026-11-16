import { Skeleton } from "@/components/ui/Card";

/** Shown instantly while a page's code loads, so a click never feels dead. Same grid rhythm as the real pages (no layout jump). */
export default function Loading() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <Skeleton className="mb-3 h-10 w-72 max-w-full" />
      <Skeleton className="mb-8 h-5 w-96 max-w-full" />
      <div className="grid gap-5 sm:gap-6 lg:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-64 !rounded-card" />)}</div>
    </div>
  );
}
