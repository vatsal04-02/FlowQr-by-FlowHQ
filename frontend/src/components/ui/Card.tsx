import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";

export function Card({ children, className, pad = true }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <section className={clsx("min-w-0 rounded-2xl border border-ink-100 bg-white shadow-card", pad && "p-5 sm:p-6", className)}>{children}</section>;
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-lg font-semibold">{title}</h2>{subtitle && <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>}</div>
      {action}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0"><h1 className="text-2xl font-semibold sm:text-[1.7rem]">{title}</h1>{subtitle && <p className="mt-1 max-w-2xl text-ink-500">{subtitle}</p>}</div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, icon, tone = "brand" }: { label: string; value: ReactNode; hint?: string; icon?: ReactNode; tone?: "brand" | "flow" | "green" | "yellow" | "red" }) {
  const tones = { brand: "bg-brand-50 text-brand-700", flow: "bg-flow-50 text-flow-700", green: "bg-green-50 text-green-700", yellow: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700" };
  return (
    <div className="min-w-0 rounded-2xl border border-ink-100 bg-white p-4 shadow-card sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-ink-500">{label}</p>
        {icon && <span className={clsx("grid h-9 w-9 place-items-center rounded-xl", tones[tone])} aria-hidden>{icon}</span>}
      </div>
      <p className="mt-2 font-display text-3xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

const badgeTones = {
  gray: "bg-ink-50 text-ink-700 ring-ink-200", blue: "bg-brand-50 text-brand-800 ring-brand-200", green: "bg-green-50 text-green-800 ring-green-200",
  amber: "bg-amber-50 text-amber-900 ring-amber-200", red: "bg-red-50 text-red-800 ring-red-200", orange: "bg-flow-50 text-flow-700 ring-flow-100",
};
export function Badge({ children, tone = "gray" }: { children: ReactNode; tone?: keyof typeof badgeTones }) {
  return <span className={clsx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset", badgeTones[tone])}>{children}</span>;
}

export function Alert({ tone = "info", title, children, action }: { tone?: "info" | "success" | "warning" | "error"; title?: string; children?: ReactNode; action?: ReactNode }) {
  const map = {
    info: ["bg-brand-50 border-brand-200 text-brand-900", Info], success: ["bg-green-50 border-green-200 text-green-900", CheckCircle2],
    warning: ["bg-amber-50 border-amber-200 text-amber-900", AlertTriangle], error: ["bg-red-50 border-red-200 text-red-900", XCircle],
  } as const;
  const [cls, Icon] = map[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={clsx("flex flex-wrap gap-x-3 gap-y-3 rounded-xl border p-4 text-sm", cls)}>
      <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
      <div className="min-w-[12rem] flex-1">{title && <p className="font-semibold">{title}</p>}{children && <div className={title ? "mt-0.5" : ""}>{children}</div>}</div>
      {action && <div className="ml-8 shrink-0 self-center sm:ml-0">{action}</div>}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-2xl border border-dashed border-ink-200 bg-ink-50/50 px-6 py-12 text-center">
      {icon && <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-white text-brand-600 shadow-card" aria-hidden>{icon}</div>}
      <h3 className="text-base font-semibold">{title}</h3>
      {children && <p className="mt-1 max-w-md text-sm text-ink-500">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("fq-skeleton rounded-xl", className)} />;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-ink-500">
      <span className="h-5 w-5 rounded-full border-2 border-ink-200 border-t-brand-600 fq-spin" aria-hidden /><span className="text-sm">{label}…</span>
    </div>
  );
}

export function GoogleDots({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1", className)} aria-hidden>
      <i className="h-1.5 w-1.5 rounded-full bg-g-blue" /><i className="h-1.5 w-1.5 rounded-full bg-g-red" />
      <i className="h-1.5 w-1.5 rounded-full bg-g-yellow" /><i className="h-1.5 w-1.5 rounded-full bg-g-green" />
    </span>
  );
}

export function Stars({ rating, size = 16 }: { rating: number; size?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" role="img" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <svg key={i} width={size} height={size} viewBox="0 0 20 20" aria-hidden className={i <= rating ? "fill-g-yellow" : "fill-ink-100"}>
          <path d="M10 1.5l2.6 5.6 6.1.7-4.5 4.2 1.2 6L10 14.9 4.6 18l1.2-6L1.3 7.8l6.1-.7L10 1.5z" />
        </svg>
      ))}
    </span>
  );
}
