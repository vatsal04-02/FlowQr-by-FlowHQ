"use client";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { SettingsHub, SettingsMenu } from "@/components/settings/Hub";
import { BackLink } from "@/components/settings/parts";

/**
 * Settings has two levels: a group, then a page (docs/DESIGN_SETTINGS_MOBILE.md §5, §7).
 * Phone: /settings is the hub (account, what needs attention, search, six groups); every other page shows a back link to it.
 * Laptop (768px up): a 264px grouped menu on the left, the page on the right (760px at most); /settings itself goes to Business profile.
 */
export default function SettingsLayout({ children }: { children: ReactNode }) {
  const path = usePathname();
  const hub = path === "/settings";
  return (
    <div className="md:grid md:grid-cols-[264px_minmax(0,1fr)] md:items-start md:gap-8 lg:gap-10">
      <aside className="md:sticky md:top-4">
        <SettingsMenu className="hidden md:block" />
        {hub && <SettingsHub className="md:hidden" />}
      </aside>
      <div className={hub ? "hidden md:block" : "min-w-0 md:max-w-[760px]"}>
        {!hub && (path.startsWith("/settings/connections/") ? <BackLink href="/settings/connections" className="mb-1 md:hidden">Connected accounts</BackLink> : <BackLink className="mb-1 md:hidden" />)}
        {children}
      </div>
    </div>
  );
}
