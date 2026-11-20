import type { Metadata } from "next";
import { WhatsAppShowcase } from "@/components/marketing/WhatsAppShowcase";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.whatsapp;
export const metadata: Metadata = pageMeta("/whatsapp-marketing-ai-agent", c.meta.title, c.meta.description);

// The hero band only, by design: no other sections until the product is switched on for customers.
export default function WhatsAppMarketingAiAgent() {
  return <WhatsAppShowcase as="h1" />;
}
