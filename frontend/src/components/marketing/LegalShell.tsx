"use client";
import type { ReactNode } from "react";
import { MarketingFooter, MarketingHeader } from "@/components/marketing/MarketingChrome";
import { useFetch } from "@/lib/use-api";

export interface LegalInfo { company: string; support_email: string | null; deletion_grace_days: number; review_session_retention_days: number; ai_provider: string | null }

/** Shared frame for the public legal pages. Contact details come from the server so a page never shows an address nobody reads. */
export function LegalShell({ title, updated, children }: { title: string; updated: string; children: (info: LegalInfo | null) => ReactNode }) {
  const { data } = useFetch<LegalInfo>("/legal/info");
  return (
    <div className="bg-white">
      <MarketingHeader />
      <main className="container-page max-w-3xl py-12 sm:py-16">
        <p className="eyebrow">Legal</p>
        <h1 className="mt-2 text-3xl font-bold sm:text-4xl">{title}</h1>
        <p className="mt-2 text-sm text-ink-500">Last updated {updated}</p>
        <div className="legal mt-8 space-y-6 text-[15px] leading-relaxed text-ink-700 [&_h2]:mt-8 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-ink [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-1.5 [&_a]:text-brand-700 [&_a]:underline">
          {children(data)}
        </div>
      </main>
      <MarketingFooter />
    </div>
  );
}

export function Contact({ info }: { info: LegalInfo | null }) {
  if (!info) return <>our support team</>;
  return info.support_email ? <a href={`mailto:${info.support_email}`}>{info.support_email}</a> : <>our support team (a contact address has not been configured on this server yet)</>;
}
