"use client";
import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";

const TABS = [
  { href: "/settings/ai/voice", label: "Voice" },
  { href: "/settings/ai/brain", label: "Brain" },
  { href: "/settings/ai/autonomy", label: "Autonomy", admin: true },
  { href: "/settings/ai/usage", label: "Usage", admin: true },
];

/** AI and brand voice has four pages. The settings menu has no third level, so they are tabs inside the page (scrolling on a phone). */
export default function AiSettingsLayout({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { isAdmin } = useAuth();
  return (
    <>
      <div role="tablist" aria-label="AI and brand voice" className="-mx-4 mb-4 flex gap-1 overflow-x-auto px-4 md:mx-0 md:px-0">
        {TABS.filter((t) => !t.admin || isAdmin).map((t) => {
          const on = path === t.href || path.startsWith(t.href + "/");
          return (
            <Link key={t.href} href={t.href} role="tab" aria-selected={on}
              className={clsx("set-focus inline-flex min-h-11 shrink-0 items-center rounded-full px-4 text-[14px]", on ? "bg-set-navy font-bold text-white" : "font-medium text-set-soft hover:bg-set-surface")}>{t.label}</Link>
          );
        })}
      </div>
      {children}
    </>
  );
}
