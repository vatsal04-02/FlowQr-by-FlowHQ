"use client";
import clsx from "clsx";
import { ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { googleLine } from "@/lib/shell-status";
import type { GoogleConnection, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { GROUPS, rowAt, rowsFor, searchRows, type SettingsRow as RowT, type StatusKey } from "./model";
import { AttentionCard, SettingsGroup, SettingsRow, type AttentionItem, type ChipKind } from "./parts";

type Chip = { kind: ChipKind; label: string } | null;

/** What each live chip says, and what needs attention, all from what the API returned. Nothing is shown until it has answered (no guessing). */
export function useSettingsStatus() {
  const { me, role } = useAuth();
  const google = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const sub = useFetch<SubscriptionInfo>(role === "owner" || role === "admin" ? "/billing/subscription" : null);
  const g = googleLine(google.data?.connections);
  const s = sub.data;

  const chips: Partial<Record<StatusKey, Chip>> = {};
  if (g) chips.google = g.tone === "ok" ? { kind: "ok", label: "Connected" } : g.tone === "warn" ? { kind: "warn", label: g.label } : { kind: "warn", label: "Not connected" };
  if (s) chips.plan = !s.active ? { kind: "bad", label: "Plan inactive" } : s.status === "past_due" ? { kind: "bad", label: "Payment failed" } : s.status === "trialing" ? { kind: "info", label: "Free trial" } : { kind: "ok", label: s.plan_name ?? "Active" };

  const attention: AttentionItem[] = [];
  if (g && g.tone !== "ok") attention.push({ id: "google", text: g.label === "Google not connected" ? "Google isn't connected" : g.label, href: "/settings/connections/google", cta: g.tone === "idle" ? "Connect" : "Fix" });
  if (s && !s.active) attention.push({ id: "plan", text: "Your plan is inactive", href: "/settings/billing", cta: "Choose a plan" });
  else if (s?.status === "past_due") attention.push({ id: "pay", text: "Your last payment failed", href: "/settings/billing", cta: "Review" });
  if (me && !me.user.email_verified_at) attention.push({ id: "email", text: "Your email isn't verified", href: "/settings/account", cta: "Verify" });
  return { chips, attention };
}

const initials = (name: string | undefined, email: string) => {
  const p = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return (p.length ? p.slice(0, 2).map((x) => x[0]) : [email[0]]).join("").toUpperCase();
};

/** The phone's Settings home: who you are, what needs attention, a search box, then the six groups. Every page is two taps away. */
export function SettingsHub({ className }: { className?: string }) {
  const { me, role } = useAuth();
  const { chips, attention } = useSettingsStatus();
  const rows = useMemo(() => rowsFor(role), [role]);
  const [q, setQ] = useState("");
  const found = searchRows(rows, q);
  const name = me?.user.full_name?.trim() || me?.user.email || "";

  return (
    <div className={clsx("space-y-5", className)}>
      <h1 className="text-[28px] font-extrabold leading-tight tracking-[-0.02em] text-set-ink">Settings</h1>
      <label className="relative block">
        <span className="sr-only">Search settings</span>
        <Search aria-hidden className="pointer-events-none absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-set-muted" />
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search settings" enterKeyHint="search"
          className="set-focus h-12 w-full rounded-[14px] border border-set-line-strong bg-set-surface pl-11 pr-4 text-[15px] font-medium text-set-ink placeholder:text-set-muted" />
      </label>

      {q.trim() ? (
        <SettingsGroup label={found.length ? `${found.length} ${found.length === 1 ? "result" : "results"}` : "No match"}>
          {found.length ? found.map((r) => <SettingsRow key={r.id} row={r} chip={r.status ? chips[r.status] : null} />)
            : <p className="px-4 py-5 text-sm font-medium text-set-soft">Nothing in Settings matches &ldquo;{q.trim()}&rdquo;. Try a shorter word.</p>}
        </SettingsGroup>
      ) : (
        <>
          {me && (
            <Link href="/settings/account" className="set-focus flex min-h-[72px] items-center gap-3.5 rounded-[18px] border border-set-line bg-set-surface p-3.5">
              <span aria-hidden className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-set-navy text-[15px] font-extrabold text-white">{initials(me.user.full_name, me.user.email)}</span>
              <span className="min-w-0 flex-1"><span className="block truncate text-[15px] font-bold text-set-ink">{name}</span><span className="block truncate text-[13px] font-medium text-set-muted">{me.user.email}{role ? ` · ${role}` : ""}</span></span>
              <ChevronRight aria-hidden className="h-[18px] w-[18px] shrink-0 text-set-switch-off" />
            </Link>
          )}
          <AttentionCard items={attention} />
          {GROUPS.filter((g) => g.id !== "account").map((g) => {
            const list = rows.filter((r) => r.group === g.id);
            if (!list.length) return null;
            return (
              <SettingsGroup key={g.id} id={`g-${g.id}`} label={g.label} action={g.action}>
                {list.map((r) => <SettingsRow key={r.id} row={r} chip={r.status ? chips[r.status] : null} />)}
              </SettingsGroup>
            );
          })}
        </>
      )}
    </div>
  );
}

/** The laptop's left pane: the same groups as a quiet menu (264px). The current page is marked with a tint and `aria-current`. */
export function SettingsMenu({ className }: { className?: string }) {
  const { role } = useAuth();
  const path = usePathname();
  const { chips } = useSettingsStatus();
  const rows = useMemo(() => rowsFor(role), [role]);
  const here = rowAt(path, rows);
  return (
    <nav aria-label="Settings" className={clsx("space-y-5", className)}>
      {GROUPS.map((g) => {
        const list = rows.filter((r) => r.group === g.id);
        if (!list.length) return null;
        return (
          <div key={g.id}>
            <h2 className="mb-1.5 px-3 text-sm font-extrabold text-set-soft">{g.label}</h2>
            <ul className="space-y-0.5">
              {list.map((r: RowT) => {
                const on = here?.id === r.id;
                const chip = r.status ? chips[r.status] : null;
                return (
                  <li key={r.id}>
                    <Link href={r.href} aria-current={on ? "page" : undefined}
                      className={clsx("set-focus set-motion flex min-h-11 items-center justify-between gap-2 rounded-xl px-3 text-[14px]", on ? "bg-set-surface font-bold text-set-ink shadow-[0_0_0_1px_rgb(var(--s-line))]" : "font-medium text-set-soft hover:bg-set-surface/70")}>
                      <span className="truncate">{r.title}</span>
                      {chip && chip.kind !== "ok" && <><span aria-hidden title={chip.label} className={clsx("h-2 w-2 shrink-0 rounded-full", chip.kind === "bad" ? "bg-set-bad-dot" : chip.kind === "warn" ? "bg-set-warn-dot" : "bg-set-info-dot")} /><span className="sr-only">{chip.label}</span></>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
