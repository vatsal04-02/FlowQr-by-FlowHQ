import clsx from "clsx";
import { ChevronLeft, ChevronRight, Lock } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { LinkButton } from "@/components/ui/Button";
import type { GroupId, SettingsRow as RowT } from "./model";

export type ChipKind = "ok" | "warn" | "bad" | "info" | "neutral";
const CHIP: Record<ChipKind, string> = {
  ok: "bg-set-ok-bg text-set-ok", warn: "bg-set-warn-bg text-set-warn", bad: "bg-set-bad-bg text-set-bad", info: "bg-set-info-bg text-set-info", neutral: "bg-set-neutral-bg text-set-neutral",
};
const DOT: Record<ChipKind, string> = { ok: "bg-set-ok-dot", warn: "bg-set-warn-dot", bad: "bg-set-bad-dot", info: "bg-set-info-dot", neutral: "bg-set-neutral-dot" };

/** Status as a fact, in words, never colour alone. 24px high, 12px bold: the smallest type in the app. */
export function StatusChip({ kind, children, className }: { kind: ChipKind; children: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs font-bold", CHIP[kind], className)}>
      <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", DOT[kind])} />{children}
    </span>
  );
}

const TILE: Record<GroupId, string> = {
  account: "bg-set-t-security text-set-i-security", business: "bg-set-t-business text-set-i-business", connect: "bg-set-t-connect text-set-i-connect",
  prefs: "bg-set-t-prefs text-set-i-prefs", billing: "bg-set-t-billing text-set-i-billing", security: "bg-set-t-security text-set-i-security",
};

/** One row: 40px icon tile in the group's tint, title, then a status chip or a short subtitle, an optional value, a chevron. The whole row is the link. */
export function SettingsRow({ row, chip, value, current }: { row: RowT; chip?: { kind: ChipKind; label: string } | null; value?: ReactNode; current?: boolean }) {
  const Icon = row.icon;
  return (
    <Link href={row.href} aria-current={current ? "page" : undefined}
      className={clsx("set-focus set-motion flex min-h-[68px] items-center gap-3.5 border-t border-set-line px-4 py-3 first:border-t-0 hover:bg-set-paper", current && "bg-set-paper")}>
      <span aria-hidden className={clsx("grid h-10 w-10 shrink-0 place-items-center rounded-xl", TILE[row.group])}><Icon className="h-5 w-5" strokeWidth={1.75} /></span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-bold leading-tight text-set-ink">{row.title}</span>
        {chip ? <StatusChip kind={chip.kind} className="mt-1">{chip.label}</StatusChip> : <span className="mt-0.5 block truncate text-[13px] font-medium leading-snug text-set-muted">{row.sub}</span>}
      </span>
      {value && <span className="shrink-0 text-[13px] font-medium text-set-muted">{value}</span>}
      <ChevronRight aria-hidden className="h-[18px] w-[18px] shrink-0 text-set-switch-off" />
    </Link>
  );
}

/** A group: its label (sentence case, not capitals) above one white card whose rows are divided by hairlines. */
export function SettingsGroup({ label, action, children, id }: { label: string; action?: { label: string; href: string }; children: ReactNode; id?: string }) {
  return (
    <section aria-labelledby={id}>
      <div className="mb-2 flex items-center justify-between gap-3 px-1">
        <h2 id={id} className="text-sm font-extrabold text-set-soft">{label}</h2>
        {action && <Link href={action.href} className="set-focus inline-flex min-h-11 items-center text-[13px] font-bold text-set-action">{action.label}</Link>}
      </div>
      <div className="overflow-hidden rounded-[18px] border border-set-line bg-set-surface">{children}</div>
    </section>
  );
}

export type AttentionItem = { id: string; text: string; href: string; cta: string };

/** At the top of the hub, once: "N things need attention", each a link to the fix. Gone when nothing is left. */
export function AttentionCard({ items }: { items: AttentionItem[] }) {
  if (!items.length) return null;
  return (
    <section aria-labelledby="attn-title" className="rounded-[18px] border border-set-attn-line bg-set-attn-bg p-4">
      <h2 id="attn-title" className="text-[17px] font-extrabold leading-snug text-set-attn-title">{items.length === 1 ? "1 thing needs attention" : `${items.length} things need attention`}</h2>
      <ul className="mt-2 divide-y divide-set-attn-line/70">
        {items.map((i) => (
          <li key={i.id}>
            <Link href={i.href} className="set-focus flex min-h-11 items-center justify-between gap-3 py-2 text-[14px] font-medium text-set-attn-body">
              <span className="min-w-0">{i.text}</span>
              <span className="inline-flex shrink-0 items-center gap-0.5 font-bold text-set-attn-title">{i.cta}<ChevronRight aria-hidden className="h-4 w-4" /></span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Back link at the top-left of every detail page on a phone, naming its parent. 44px tall. */
export function BackLink({ href = "/settings", children = "Settings", className }: { href?: string; children?: ReactNode; className?: string }) {
  return <Link href={href} className={clsx("set-focus -ml-2 inline-flex min-h-11 items-center gap-1 rounded-lg px-2 text-[15px] font-bold text-set-ink", className)}><ChevronLeft aria-hidden className="h-5 w-5" />{children}</Link>;
}

/** The main action of a detail page on a phone: pinned above the tab bar with one line of reassurance. From md up it is just a row under the form. */
export function StickyActionBar({ children, note }: { children: ReactNode; note?: string }) {
  return (
    <div className="sticky bottom-[calc(env(safe-area-inset-bottom)+76px)] z-20 -mx-4 border-t border-set-line bg-set-surface px-4 pb-3 pt-3 md:static md:mx-0 md:border-0 md:bg-transparent md:p-0 lg:bottom-0">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-end">
        {note && <p className="text-[13px] font-medium text-set-muted md:mr-auto">{note}</p>}
        {children}
      </div>
    </div>
  );
}

/**
 * The one "Connect Google" in the app besides the Google page itself. Shown by every screen that needs Google: what the page needs in one sentence, one button, no setup steps.
 */
export function ConnectGoogleEmptyState({ what = "This page works on your real Google Business Profile.", className, compact }: { what?: string; className?: string; compact?: boolean }) {
  if (compact) {
    return (
      <div className={clsx("flex flex-wrap items-center justify-between gap-3", className)}>
        <p className="text-[14px] font-medium text-set-soft">{what}</p>
        <LinkButton href="/settings/connections/google" variant="secondary" size="sm">Connect Google</LinkButton>
      </div>
    );
  }
  return (
    <div className={clsx("flex flex-wrap items-center gap-4 rounded-[18px] border border-set-line bg-set-surface p-5", className)}>
      <span aria-hidden className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-set-t-connect text-set-i-connect"><Lock className="h-5 w-5" strokeWidth={1.75} /></span>
      <div className="min-w-0 flex-1 basis-60">
        <h3 className="text-[17px] font-extrabold text-set-ink">Connect Google to use this page</h3>
        <p className="mt-0.5 text-sm font-medium text-set-soft">{what} Nothing is posted until a person approves it.</p>
      </div>
      <LinkButton href="/settings/connections/google" variant="brand" className="w-full sm:w-auto">Connect Google</LinkButton>
    </div>
  );
}
