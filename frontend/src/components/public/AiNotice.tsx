import { Info } from "lucide-react";
import { aiNoticeFor } from "@/lib/ai-notice";

/** The AI-assistance notice for customers (wording in lib/ai-notice.ts). Always visible, never collapsed, 13.5px so it stays readable on a phone, and in the language the customer is using. */
export function AiNotice({ lang }: { lang: string }) {
  const n = aiNoticeFor(lang);
  return (
    <p lang={n.lang} data-testid="ai-notice" className="flex gap-2 rounded-xl bg-white/70 p-3 text-[13.5px] leading-relaxed text-ink-700 ring-1 ring-black/5">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-500" aria-hidden />
      <span>{n.text}</span>
    </p>
  );
}
