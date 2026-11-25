"use client";
import { Sparkles } from "lucide-react";
import { LinkButton } from "@/components/ui/Button";
import { useFetch } from "@/lib/use-api";
import { phaseOf, type WebsiteState } from "@/lib/website";

/** One line on Home for a business that said it has no website: where the AI website stands. Nothing is shown when website building is off or the business has its own site. */
export function WebsiteBanner() {
  const { data } = useFetch<WebsiteState>("/website");
  if (!data?.enabled || (data.interest !== "wants_site" && !data.site) || data.site?.status === "published") return null;
  const phase = phaseOf(data);
  const text = { start: "Your AI team can build your business website.", building: "Your website is being built.", failed: "Your website was not finished.", review: "Your website draft is ready for review." }[phase];
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-tile bg-surface p-4 shadow-card">
      <p className="flex min-w-0 items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 shrink-0 text-accent-ink" aria-hidden />{text}</p>
      <LinkButton href="/website" size="sm" variant="secondary">{phase === "review" ? "Review website" : "Open website"}</LinkButton>
    </div>
  );
}
