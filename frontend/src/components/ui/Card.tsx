import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";

export function Card({ children, className, pad = true }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <section className={clsx("panel min-w-0", pad && "p-4 sm:p-5", className)}>{children}</section>;
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-[15px] font-semibold">{title}</h2>{subtitle && <p className="mt-0.5 text-[13px] text-ink-500">{subtitle}</p>}</div>
      {action}
    </div>
  );
}

/** Page title row. Compact and left-aligned; the hairline under it separates chrome from work. */
export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: string; actions?: ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-x-4 gap-y-3 border-b border-ink-100 pb-4">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
        <h1 className="text-xl font-bold sm:text-[22px]">{title}</h1>
        {subtitle && <p className="mt-0.5 max-w-2xl text-sm text-ink-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A number and what it counts. Neutral by design: colour is reserved for meaning. */
export function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: string; icon?: ReactNode }) {
  return (
    <div className="panel min-w-0 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-medium text-ink-500">{label}</p>
        {icon && <span className="text-ink-400" aria-hidden>{icon}</span>}
      </div>
      <p className="num mt-1.5 text-[26px] font-bold leading-none tracking-tight">{value}</p>
      {hint && <p className="mt-2 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

// Small rectangular labels. Colour carries status; the text always says the same thing.
const badgeTones = {
  gray: "bg-ink-100/70 text-ink-700", blue: "bg-brand-50 text-brand-800", green: "bg-green-50 text-green-800",
  amber: "bg-amber-50 text-amber-900", red: "bg-red-50 text-red-800",
};
export function Badge({ children, tone = "gray" }: { children: ReactNode; tone?: keyof typeof badgeTones }) {
  return <span className={clsx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium", badgeTones[tone])}>{children}</span>;
}

/** Inline message. Only warning, error and success carry colour; information stays neutral. */
export function Alert({ tone = "info", title, children, action }: { tone?: "info" | "success" | "warning" | "error"; title?: string; children?: ReactNode; action?: ReactNode }) {
  const map = {
    info: ["bg-white border-ink-200 text-ink", Info, "text-ink-500"], success: ["bg-green-50 border-green-200 text-green-900", CheckCircle2, ""],
    warning: ["bg-amber-50 border-amber-200 text-amber-900", AlertTriangle, ""], error: ["bg-red-50 border-red-200 text-red-900", XCircle, ""],
  } as const;
  const [cls, Icon, iconCls] = map[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={clsx("flex flex-wrap gap-x-3 gap-y-3 rounded-lg border p-3.5 text-sm", cls)}>
      <Icon className={clsx("mt-0.5 h-[18px] w-[18px] shrink-0", iconCls)} aria-hidden />
      <div className="min-w-[12rem] flex-1">{title && <p className="font-semibold">{title}</p>}{children && <div className={title ? "mt-0.5" : ""}>{children}</div>}</div>
      {action && <div className="ml-8 shrink-0 self-center sm:ml-0">{action}</div>}
    </div>
  );
}

/** Concise, informative empty state. Says what is missing, why, and the next step. No dashed boxes. */
export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-panel border border-ink-100 bg-white p-4 sm:p-5">
      {icon && <div className="mt-0.5 text-ink-400" aria-hidden>{icon}</div>}
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold">{title}</h3>
        {children && <p className="mt-0.5 max-w-xl text-sm text-ink-500">{children}</p>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("fq-skeleton", className)} />;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-ink-500">
      <span className="h-5 w-5 rounded-full border-2 border-ink-200 border-t-brand-600 fq-spin" aria-hidden /><span className="text-sm">{label}…</span>
    </div>
  );
}

/** Star rating. Filled and empty stars differ in lightness as well as hue; the rating is also exposed as text. */
export function Stars({ rating, size = 16 }: { rating: number; size?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" role="img" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <svg key={i} width={size} height={size} viewBox="0 0 20 20" aria-hidden className={i <= rating ? "fill-star" : "fill-ink-100"}>
          <path d="M10 1.5l2.6 5.6 6.1.7-4.5 4.2 1.2 6L10 14.9 4.6 18l1.2-6L1.3 7.8l6.1-.7L10 1.5z" />
        </svg>
      ))}
    </span>
  );
}
