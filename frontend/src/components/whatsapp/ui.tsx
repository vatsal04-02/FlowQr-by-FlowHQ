"use client";
import clsx from "clsx";
import { BadgeCheck, ChevronRight, Clock, Lock, MessageSquareText, MoreHorizontal, Send, Smartphone, Users, Zap, Check, Info, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { pct, ringGeometry, STEP_LABEL, type Health, type StepKey } from "@/lib/whatsapp-ui";
import type { StepState } from "@/lib/whatsapp";

/**
 * Visual building blocks for the WhatsApp screens. The idea: show a state with a picture (a ring, a row of steps, a bar, a switch, a chat bubble) and a few words, and keep the
 * explanations for the places where someone asks. Everything uses the app's own tokens, so light and dark both work; colour is never the only signal (an icon or a word always comes with it).
 */

export const STEP_ICON: Record<StepKey, LucideIcon> = { plan: BadgeCheck, connect: Smartphone, messages: MessageSquareText, customers: Users, test: Send, helper: Zap };

const TONE = {
  neutral: "bg-surface-2 text-ink-700", pos: "bg-pos-tint text-pos", warn: "bg-warn-tint text-warn", neg: "bg-neg-tint text-neg", brand: "bg-brand-50 text-brand-700", accent: "bg-accent-tint text-accent-ink",
} as const;
export type Tone = keyof typeof TONE;

/** A rounded square holding one line icon: the app's way of giving a card a visual anchor. */
export function IconTile({ icon: Icon, tone = "neutral", size = 40, className }: { icon: LucideIcon; tone?: Tone; size?: number; className?: string }) {
  return <span aria-hidden className={clsx("grid shrink-0 place-items-center rounded-2xl", TONE[tone], className)} style={{ width: size, height: size }}><Icon style={{ width: size * 0.5, height: size * 0.5 }} strokeWidth={1.75} /></span>;
}

const DOT: Record<Health, string> = { ok: "bg-pos", warn: "bg-warn", bad: "bg-neg", off: "bg-ink-300" };
export function StateDot({ state, pulse }: { state: Health; pulse?: boolean }) {
  return <span aria-hidden className="relative inline-flex h-2.5 w-2.5 shrink-0"><span className={clsx("absolute inset-0 rounded-full", DOT[state], pulse && "motion-safe:animate-ping opacity-60")} /><span className={clsx("relative h-2.5 w-2.5 rounded-full", DOT[state])} /></span>;
}

/** A circular progress ring with room inside for a number or an icon. */
export function Ring({ done, total, size = 128, stroke = 10, label, complete, children }: { done: number; total: number; size?: number; stroke?: number; label: string; complete?: boolean; children?: ReactNode }) {
  const r = (size - stroke) / 2;
  const g = ringGeometry(done, total, r);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-surface-3" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} strokeLinecap="round" strokeDasharray={g.circumference} strokeDashoffset={g.offset}
          className={clsx("transition-[stroke-dashoffset] duration-700 ease-out motion-reduce:transition-none", complete ? "stroke-pos" : "stroke-brand-600")} />
      </svg>
      <div className="absolute inset-0 grid place-items-center">{children}</div>
    </div>
  );
}

/** One horizontal bar. The number next to it says the same thing in words. */
export function Meter({ value, tone = "pos", label }: { value: number; tone?: "pos" | "brand" | "accent" | "neg"; label: string }) {
  const fill = { pos: "bg-pos", brand: "bg-brand-600", accent: "bg-tone-sky", neg: "bg-neg" }[tone];
  return <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)} className="h-2 overflow-hidden rounded-full bg-surface-3"><div className={clsx("h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none", fill)} style={{ width: `${Math.min(100, Math.max(value > 0 ? 3 : 0, value))}%` }} /></div>;
}

/** The circle for one step: green tick when done, ringed icon when it is your turn, a clock while waiting, a lock when it cannot start yet. */
export function StepNode({ keyName, state, now, size = 40, className }: { keyName: StepKey; state: StepState; now?: boolean; size?: number; className?: string }) {
  const Icon = STEP_ICON[keyName];
  const node = state === "done" ? { cls: "bg-pos text-white", icon: <Check className="h-[18px] w-[18px]" strokeWidth={3} /> }
    : state === "waiting" ? { cls: "bg-warn-tint text-warn ring-2 ring-warn/40", icon: <Clock className="h-[18px] w-[18px]" strokeWidth={2} /> }
    : state === "blocked" ? { cls: "bg-surface-2 text-ink-400", icon: <Lock className="h-4 w-4" strokeWidth={2} /> }
    : { cls: "bg-white text-brand-700 ring-2 ring-brand-600", icon: <Icon className="h-[18px] w-[18px]" strokeWidth={2} /> };
  return <span aria-hidden className={clsx("relative z-10 grid shrink-0 place-items-center rounded-full", node.cls, now && state !== "done" && "shadow-card", className)} style={{ width: size, height: size }}>{node.icon}</span>;
}

/** The six set-up steps as one row of icons joined by a line. Finished steps are green with a tick; the step to do now is ringed; waiting shows a clock; not-yet shows a lock. */
export function StepRail({ steps, current, onPick }: { steps: { key: StepKey; state: StepState }[]; current: number; onPick?: (i: number) => void }) {
  const doneRun = (() => { let n = 0; for (const s of steps) { if (s.state === "done") n += 1; else break; } return n; })();
  const fill = steps.length > 1 ? (Math.min(doneRun, steps.length - 1) / (steps.length - 1)) * 100 : 0;
  return (
    <ol className="relative grid" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
      <span aria-hidden className="absolute top-[19px] h-[3px] rounded-full bg-surface-3" style={{ left: `${50 / steps.length}%`, right: `${50 / steps.length}%` }}>
        <span className="block h-full rounded-full bg-pos transition-[width] duration-700 motion-reduce:transition-none" style={{ width: `${fill}%` }} />
      </span>
      {steps.map((s, i) => {
        const Icon = STEP_ICON[s.key];
        const now = i === current;
        const word = `${STEP_LABEL[s.key]}: ${s.state === "done" ? "done" : s.state === "waiting" ? "waiting" : s.state === "blocked" ? "not yet" : "your turn"}`;
        const inner = (
          <>
            <StepNode keyName={s.key} state={s.state} now={now} />
            <span className={clsx("mt-1.5 block text-[13px] leading-4", now ? "font-semibold text-ink" : "text-muted")}>{STEP_LABEL[s.key]}</span>
          </>
        );
        return (
          <li key={s.key} className="flex justify-center">
            {onPick ? <button type="button" onClick={() => onPick(i)} aria-label={word} aria-current={now ? "step" : undefined} className="flex min-h-11 w-full flex-col items-center rounded-xl px-0.5 text-center">{inner}</button>
              : <span aria-label={word} aria-current={now ? "step" : undefined} className="flex w-full flex-col items-center px-0.5 text-center">{inner}</span>}
          </li>
        );
      })}
    </ol>
  );
}

/** A card that is also a link: an icon, one big value, one small label. */
export function TileLink({ href, icon, tone, label, children, className }: { href: string; icon: LucideIcon; tone?: Tone; label: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Link href={href} className={clsx("panel group flex min-h-[136px] flex-col justify-between p-4 transition-transform duration-200 active:scale-[.985] motion-reduce:transition-none", className)}>
      <div className="flex items-start justify-between"><IconTile icon={icon} tone={tone} /><ChevronRight aria-hidden className="mt-1 h-4 w-4 text-ink-300 transition-colors group-hover:text-ink-500" /></div>
      <div className="mt-4 min-w-0">{children}<div className="mt-1 flex items-center gap-1.5 text-[13px] leading-4 text-muted">{label}</div></div>
    </Link>
  );
}

/** An on/off switch, sized like the system one (51 x 31) inside a 44-point touch target. */
export function Switch({ checked, onChange, label, disabled, busy }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; busy?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} aria-busy={busy || undefined} disabled={disabled || busy} onClick={() => onChange(!checked)}
      className="inline-flex h-11 w-[62px] shrink-0 items-center justify-center rounded-full outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50">
      <span className={clsx("relative block h-[31px] w-[51px] rounded-full ring-1 ring-inset transition-colors duration-200 motion-reduce:transition-none", checked ? "bg-pos ring-pos" : "bg-ink-200 ring-ink-300")}>
        <span className={clsx("absolute top-[2px] block h-[27px] w-[27px] rounded-full bg-white shadow-md transition-transform duration-200 motion-reduce:transition-none", checked ? "translate-x-[22px]" : "translate-x-[2px]", busy && "animate-pulse")} />
      </span>
    </button>
  );
}

/** A row of filter chips (one of them is chosen). */
export function Chips<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string; count?: number }[]; label: string }) {
  return (
    <div role="group" aria-label={label} className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
          className={clsx("inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full px-4 text-[14px] font-medium transition-colors motion-reduce:transition-none sm:min-h-10", value === o.value ? "bg-ink-solid text-ink-on" : "bg-surface-2 text-ink-700 hover:bg-surface-3")}>
          {o.label}{o.count !== undefined && <span className={clsx("text-[13px] tabular-nums", value === o.value ? "opacity-70" : "text-muted")}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** A "more" menu for a row: one three-dot button that opens a short list. Closes on Escape and on a tap outside, and opens upward near the bottom of the screen. */
export function ActionMenu({ label, items }: { label: string; items: { label: string; onClick: () => void; danger?: boolean }[] }) {
  const [open, setOpen] = useState(false);
  const [up, setUp] = useState(false);
  const box = useRef<HTMLDivElement>(null), btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("pointerdown", away); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", key); };
  }, [open]);
  if (items.length === 0) return null;
  return (
    <div ref={box} className="relative">
      <button ref={btn} type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open}
        onClick={() => { if (!open) setUp(window.innerHeight - (btn.current?.getBoundingClientRect().bottom ?? 0) < items.length * 48 + 24); setOpen(!open); }}
        className="grid h-11 w-11 place-items-center rounded-full text-ink-500 transition-colors hover:bg-surface-2 hover:text-ink"><MoreHorizontal className="h-5 w-5" aria-hidden /></button>
      {open && (
        <div role="menu" aria-label={label} className={clsx("absolute right-0 z-30 min-w-[200px] overflow-hidden rounded-2xl bg-white py-1 shadow-lift ring-1 ring-line", up ? "bottom-full mb-1" : "top-full mt-1")}>
          {items.map((it) => <button key={it.label} role="menuitem" type="button" onClick={() => { setOpen(false); it.onClick(); }} className={clsx("flex min-h-11 w-full items-center px-4 text-left text-[15px] hover:bg-surface-2", it.danger ? "text-neg" : "text-ink")}>{it.label}</button>)}
        </div>
      )}
    </div>
  );
}

/** A chat bubble: `in` is the customer (grey, left), `out` is you (WhatsApp green, right). */
export function Bubble({ side = "out", children, className }: { side?: "in" | "out"; children: ReactNode; className?: string }) {
  return <div className={clsx("max-w-[86%] rounded-2xl px-3 py-2 text-[14px] leading-[1.4] text-ink", side === "in" ? "self-start rounded-bl-md bg-surface-2" : "self-end rounded-br-md bg-pos-tint", className)}>{children}</div>;
}

/** A small phone outline that holds a preview of what a customer sees. */
export function PhonePreview({ children, label, className }: { children: ReactNode; label: string; className?: string }) {
  return (
    <figure aria-label={label} className={clsx("mx-auto w-full max-w-[200px] rounded-[30px] bg-ink-solid p-[6px] shadow-lift sm:max-w-[250px]", className)}>
      <div className="flex min-h-[150px] sm:min-h-[170px] flex-col gap-2 rounded-[24px] bg-white p-3">{children}</div>
    </figure>
  );
}

/** A round icon-only button with a label for screen readers (44-point target). */
export function IconButton({ label, icon: Icon, onClick, className }: { label: string; icon: LucideIcon; onClick: () => void; className?: string }) {
  return <button type="button" aria-label={label} title={label} onClick={onClick} className={clsx("grid h-11 w-11 place-items-center rounded-full bg-white text-ink-700 shadow-pill ring-1 ring-line transition-colors hover:bg-surface-2 motion-reduce:transition-none", className)}><Icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden /></button>;
}

/** A person's initials in a circle. */
export function Avatar({ text, tone = "neutral", size = 44 }: { text: string; tone?: Tone; size?: number }) {
  return <span aria-hidden className={clsx("grid shrink-0 place-items-center rounded-full text-[15px] font-semibold", TONE[tone])} style={{ width: size, height: size }}>{text}</span>;
}

/** One quiet line of context with an icon, for what used to be a paragraph. */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={clsx("flex items-start gap-2 text-[13px] leading-5 text-muted", className)}><Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /><span className="min-w-0">{children}</span></p>;
}

/** A big number with its small label, for a row of metrics. */
export function Figure({ value, label = "", tone }: { value: ReactNode; label?: string; tone?: "pos" | "neg" | "warn" }) {
  return <div className="min-w-0"><p className={clsx("num text-[28px] font-semibold leading-8 tracking-[-.02em]", tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : tone === "warn" ? "text-warn" : "text-ink")}>{value}</p>{label && <p className="text-[13px] leading-4 text-muted">{label}</p>}</div>;
}

export { pct };
