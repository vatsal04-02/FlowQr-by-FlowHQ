"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function InboxPage() {
  return (
    <>
      <PageHeader eyebrow="Inbox & Leads" title="WhatsApp inbox" subtitle="Conversations with customers." />
      <SetupRequired integration="whatsapp" what="WhatsApp Business Platform" plans={["Receive and answer customer messages through the official WhatsApp Business Platform only.", "Replies grounded in your Knowledge Base with a clear hand-off to a person.", "Opt-in and consent tracked per customer, in line with WhatsApp's rules and India's DPDP Act."]} />
    </>
  );
}
