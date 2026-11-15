"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function InboxLeadsPage() {
  return (
    <>
      <PageHeader eyebrow="Inbox & Leads" title="Leads" subtitle="People who asked about your services." />
      <SetupRequired integration="whatsapp" what="Lead capture" plans={["Capture enquiries from WhatsApp with the customer's consent.", "No lead is shown until a real message arrived through a connected channel."]} />
    </>
  );
}
