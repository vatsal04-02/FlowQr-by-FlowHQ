"use client";
import type { ReactNode } from "react";
import { useFetch } from "@/lib/use-api";

export interface LegalInfo { company: string; support_email: string | null; company_address?: string | null; grievance_officer?: string | null; deletion_grace_days: number; review_session_retention_days: number; ai_provider: string | null }

/** Shared frame for the public legal pages (inside the marketing layout, which adds the nav and footer). Contact details come from the server. */
export function LegalShell({ title, updated, children }: { title: string; updated: string; children: (info: LegalInfo | null) => ReactNode }) {
  const { data } = useFetch<LegalInfo>("/legal/info");
  return (
    <div className="mkt-wrap max-w-3xl py-16 sm:py-20">
      <h1 className="t-h2 text-m-ink">{title}</h1>
      <p className="mt-3 t-small text-m-muted">Last updated {updated}</p>
      <div className="legal mt-10 space-y-6 rounded-[20px] bg-m-surface p-6 text-[15px] leading-relaxed text-m-ink2 sm:p-10 [&_a]:text-m-accentStrong [&_a]:underline [&_h2]:mt-8 [&_h2]:text-xl [&_h2]:font-medium [&_h2]:text-m-ink [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-1.5">
        {children(data)}
      </div>
    </div>
  );
}

export function Contact({ info }: { info: LegalInfo | null }) {
  if (!info) return <>our support team</>;
  return info.support_email ? <a href={`mailto:${info.support_email}`}>{info.support_email}</a> : <>our support team (a contact address has not been configured on this server yet)</>;
}
