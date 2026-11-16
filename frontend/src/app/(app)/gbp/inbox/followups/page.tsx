"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function InboxFollowupsPage() {
  return (
    <>
      <PageHeader eyebrow="Inbox & Leads" title="Follow-ups" subtitle="Reminders to get back to people." />
      <SetupRequired integration="whatsapp" what="Follow-ups" plans={["Remind your team to follow up, and send approved template messages only to people who opted in."]} />
    </>
  );
}
