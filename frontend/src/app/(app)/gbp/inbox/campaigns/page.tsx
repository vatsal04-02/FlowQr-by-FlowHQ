"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function InboxCampaignsPage() {
  return (
    <>
      <PageHeader eyebrow="Inbox & Leads" title="Message campaigns" subtitle="Approved template messages to opted-in customers." />
      <SetupRequired integration="whatsapp" what="WhatsApp campaigns" plans={["Send only Meta-approved templates, only to customers who opted in, with an easy opt-out.", "Show delivery results exactly as WhatsApp reports them."]} />
    </>
  );
}
