"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function InboxAppointmentsPage() {
  return (
    <>
      <PageHeader eyebrow="Inbox & Leads" title="Appointments" subtitle="Bookings made through conversations." />
      <SetupRequired integration="whatsapp" what="Appointment booking" plans={["Offer slots you define and confirm bookings only after you or your team accept them.", "FlowQR never tells a customer an appointment is confirmed on its own."]} />
    </>
  );
}
