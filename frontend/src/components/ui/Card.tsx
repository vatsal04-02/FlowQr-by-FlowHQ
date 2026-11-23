import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, Loader2, Lock, RotateCw, XCircle } from "lucide-react";
import type { ReactNode } from "react";

/** DESIGN.md "Card": white, 28px radius, soft shadow, no border. */
export function Card({ children, className, pad = true }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <section className={clsx("panel min-w-0", pad && "p-5 sm:p-6", className)}>{children}</section>;
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-[18px] font-semibold leading-6">{title}</h2>{subtitle && <p className="mt-0.5 text-[15px] leading-[22px] text-muted">{subtitle}</p>}</div>
      {action}
    </div>
  );
}

/** Page title row: big H1, one muted line, at most one primary action on the right (DESIGN.md §4). */
export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 sm:mb-5 lg:mb-6">
      <div className="min-w-0">
        {/* `eyebrow` is accepted for older callers but not shown: the section pill and the rail already say where you are. */}
        <h1 className="text-[30px] font-bold leading-[36px] tracking-[-.015em] text-ink sm:text-[32px] sm:leading-10 lg:text-[34px]">{title}</h1>
        {subtitle && <div className="mt-1.5 max-w-2xl text-[15px] leading-[22px] text-muted sm:text-base sm:leading-6">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A number and what it counts: label 14/500 muted, value 32/600. Neutral by design: colour is reserved for meaning. */
export function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: string; icon?: ReactNode }) {
  return (
    <div className="panel min-w-0 p-5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[15px] font-medium text-muted">{label}</p>
        {icon && <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-surface-2 text-ink" aria-hidden>{icon}</span>}
      </div>
      <p className="num mt-3 text-[32px] font-semibold leading-9 tracking-[-.02em]">{value}</p>
      {hint && <p className="mt-2 text-xs text-muted">{hint}</p>}
    </div>
  );
}

// Pill labels. Colour carries status; the text always says the same thing.
const badgeTones = {
  gray: "bg-surface-2 text-ink-700", blue: "bg-accent-tint text-accent-ink", green: "bg-pos-tint text-pos",
  amber: "bg-warn-tint text-warn", red: "bg-neg-tint text-neg",
};
export function Badge({ children, tone = "gray" }: { children: ReactNode; tone?: keyof typeof badgeTones }) {
  return <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[13px] font-semibold leading-4", badgeTones[tone])}>{children}</span>;
}

/** Soft alert card (DESIGN.md §5): tinted, 22px radius, icon in a circle. Only warning, error and success carry colour. */
export function Alert({ tone = "info", title, children, action }: { tone?: "info" | "success" | "warning" | "error"; title?: string; children?: ReactNode; action?: ReactNode }) {
  const map = {
    info: ["bg-surface-2 ring-1 ring-inset ring-line", Info, "text-ink"], success: ["bg-pos-tint", CheckCircle2, "text-pos"],
    warning: ["bg-warn-tint", AlertTriangle, "text-warn"], error: ["bg-neg-tint", XCircle, "text-neg"],
  } as const;
  const [cls, Icon, iconCls] = map[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={clsx("flex flex-wrap items-start gap-x-3 gap-y-3 rounded-tile p-3.5 text-sm text-ink sm:p-4", cls)}>
      <span aria-hidden className={clsx("grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white", iconCls)}><Icon className="h-[18px] w-[18px]" /></span>
      <div className="min-w-[12rem] flex-1 self-center">{title && <p className="font-semibold">{title}</p>}{children && <div className={clsx(title && "mt-0.5", "text-ink-700")}>{children}</div>}</div>
      {action && <div className="ml-12 shrink-0 self-center sm:ml-0">{action}</div>}
    </div>
  );
}

/** Says what is missing, why, and the next step. Never fake data (product rule). */
export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="panel flex flex-wrap items-start gap-4 p-5 sm:p-6">
      {icon && <div className="grid h-14 w-14 shrink-0 place-items-center rounded-full bg-accent-tint text-accent-ink [&_svg]:h-6 [&_svg]:w-6" aria-hidden>{icon}</div>}
      <div className="min-w-0 flex-1 basis-60">
        <h3 className="text-lg font-semibold">{title}</h3>
        {children && <p className="mt-1 max-w-xl text-sm text-muted">{children}</p>}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("fq-skeleton", className)} />;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-muted">
      <span className="h-5 w-5 rounded-full border-2 border-ink-200 border-t-accent fq-spin" aria-hidden /><span className="text-sm">{label}…</span>
    </div>
  );
}

/** Star rating. Filled and empty stars differ in lightness as well as hue; the rating is also exposed as text. */
export function Stars({ rating, size = 16 }: { rating: number; size?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" role="img" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <svg key={i} width={size} height={size} viewBox="0 0 20 20" aria-hidden className={i <= rating ? "fill-star" : "fill-ink-200"}>
          <path d="M10 1.5l2.6 5.6 6.1.7-4.5 4.2 1.2 6L10 14.9 4.6 18l1.2-6L1.3 7.8l6.1-.7L10 1.5z" />
        </svg>
      ))}
    </span>
  );
}

/** Graceful error recovery: say what happened in plain words, that nothing was lost, and give one button that tries again. */
export function ErrorState({ title = "This didn't load", error, onRetry, retrying, compact }: { title?: string; error?: string | null; onRetry?: () => void; retrying?: boolean; compact?: boolean }) {
  return (
    <div role="alert" className={clsx("panel flex flex-wrap items-center gap-4", compact ? "p-4" : "p-5 sm:p-6")}>
      <span aria-hidden className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-neg-tint text-neg"><XCircle className="h-6 w-6" /></span>
      <div className="min-w-0 flex-1 basis-56">
        <h3 className="text-base font-semibold">{title}</h3>
        <p className="mt-0.5 text-sm text-muted">{error ? `${error} ` : ""}Nothing was lost or changed.</p>
      </div>
      {onRetry && (
        <button type="button" onClick={onRetry} disabled={retrying} className="btn-glass tap inline-flex items-center gap-2 rounded-[12px] px-5 text-sm font-semibold text-ink disabled:opacity-60">
          {retrying ? <Loader2 className="h-4 w-4 fq-spin" aria-hidden /> : <RotateCw className="h-4 w-4" aria-hidden />}Try again
        </button>
      )}
    </div>
  );
}

/** Autosave status line: "Saving…", "All changes saved", or what failed with a retry. Quiet when nothing changed. */
export function SaveStatus({ state, error, onRetry, className }: { state: "idle" | "dirty" | "saving" | "saved" | "error"; error?: string | null; onRetry?: () => void; className?: string }) {
  if (state === "idle") return <span className={clsx("text-xs text-muted-soft", className)} aria-live="polite">Saves automatically</span>;
  return (
    <span aria-live="polite" className={clsx("inline-flex items-center gap-1.5 text-xs font-medium", state === "error" ? "text-neg" : state === "saved" ? "text-pos" : "text-muted", className)}>
      {state === "saving" && <Loader2 className="h-3.5 w-3.5 fq-spin" aria-hidden />}
      {state === "saved" && <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />}
      {state === "error" && <XCircle className="h-3.5 w-3.5" aria-hidden />}
      {state === "dirty" ? "Unsaved changes…" : state === "saving" ? "Saving…" : state === "saved" ? "All changes saved" : (error ?? "Could not save")}
      {state === "error" && onRetry && <button type="button" onClick={onRetry} className="underline underline-offset-2">Retry</button>}
    </span>
  );
}

/** A plan marker beside a feature the current plan doesn't include (tier-based indicators). Text and an icon, never colour alone. */
export function TierBadge({ plan = "Growth", className }: { plan?: string; className?: string }) {
  return <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-gold-50 px-2 py-0.5 text-[11px] font-semibold text-gold-700 ring-1 ring-inset ring-gold-400/40 dark:bg-gold-500/15 dark:text-gold-400", className)}><Lock className="h-3 w-3" aria-hidden />{plan}</span>;
}

/** Placeholder rows for a list or table that is loading, the same height as the real rows so nothing jumps when data arrives. */
export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div aria-busy="true" aria-label="Loading" className={clsx("space-y-2.5", className)}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 rounded-tile bg-surface p-3">
          <Skeleton className="h-10 w-10 shrink-0 !rounded-full" />
          <div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-3.5 w-2/5 !rounded-md" /><Skeleton className="h-3 w-4/5 !rounded-md" /></div>
          <Skeleton className="hidden h-7 w-20 !rounded-full sm:block" />
        </div>
      ))}
    </div>
  );
}
