"use client";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/kit";
import EntryWindow from "../whatsapp-entry-window/page";
import WhatsAppFestivals from "../whatsapp-festivals/page";
import WhatsAppAi from "../whatsapp-ai/page";
import WhatsAppPrices from "../whatsapp-prices/page";

type Tab = "prices" | "assistant" | "window" | "festivals";

/** The four WhatsApp platform pages as one page with tabs. Each tab is the same page it always was (their own addresses still work); this only removes three menu entries. */
export default function AdminWhatsApp() {
  const [tab, setTab] = useState<Tab>("prices");
  useEffect(() => { const t = new URLSearchParams(window.location.search).get("tab"); if (t === "assistant" || t === "window" || t === "festivals" || t === "prices") setTab(t); }, []);
  return (
    <>
      <PageHeader eyebrow="Platform" title="WhatsApp settings" subtitle="Message prices, the assistant's terms, the free-entry window and festival dates." />
      <div className="mb-5 overflow-x-auto"><Segmented label="WhatsApp settings" value={tab} onChange={setTab} options={[["prices", "Prices"], ["assistant", "Assistant"], ["window", "Free window"], ["festivals", "Festivals"]] as const} /></div>
      {tab === "prices" && <WhatsAppPrices />}
      {tab === "assistant" && <WhatsAppAi />}
      {tab === "window" && <EntryWindow />}
      {tab === "festivals" && <WhatsAppFestivals />}
    </>
  );
}
