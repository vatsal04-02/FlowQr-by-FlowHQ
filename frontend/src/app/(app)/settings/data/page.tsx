"use client";
import { YourDataPanel } from "@/components/YourDataPanel";
import { PageHeader } from "@/components/ui/Card";

/** Security & activity › Your data: export and deletion. Moved out of the business profile so that page is only the profile. */
export default function YourDataPage() {
  return (
    <>
      <PageHeader title="Your data" subtitle="Download what FlowQR holds about your business, or ask for it to be deleted." />
      <YourDataPanel />
    </>
  );
}
