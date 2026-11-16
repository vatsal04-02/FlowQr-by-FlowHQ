"use client";
import { ArrowRight, Building2, CalendarClock, Check, MapPin, QrCode } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Spinner } from "@/components/ui/Card";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { rupees } from "@/lib/billing";
import { clearMemory, type WizardMemory } from "@/lib/places";
import type { Location, PlansResponse, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { StepActions, StepCard, StepHeading } from "./Shell";

interface Campaign { id: string }

function Row({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <li className="flex items-start gap-3.5 py-3.5">
      <span aria-hidden className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-m-tint text-m-accentStrong">{icon}</span>
      <div className="min-w-0 flex-1"><p className="text-[12.5px] font-medium uppercase tracking-[.06em] text-m-muted">{label}</p><div className="mt-0.5 text-[15px] text-m-ink">{children}</div></div>
    </li>
  );
}

/** The last step: a summary of what was set up, the first review page, and the one button that opens the app. The server refuses to finish until the payment authorisation is confirmed. */
export function LaunchStep({ method, businessName, onBack, onNeedAuthorization }: { method: WizardMemory["method"]; businessName: string; onBack: () => void; onNeedAuthorization: (reason: string) => void }) {
  const { refresh } = useAuth();
  const router = useRouter();
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const plans = useFetch<PlansResponse>("/billing/plans");
  const locs = useFetch<Location[]>("/locations");
  const camps = useFetch<Campaign[]>("/review-growth/campaigns");
  const [busy, setBusy] = useState<"campaign" | "finish" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const first = locs.data?.[0];
  const hasCampaign = (camps.data?.length ?? 0) > 0;
  const loading = sub.loading || locs.loading || camps.loading || plans.loading;
  const s = sub.data;
  const planName = plans.data?.plans.find((p) => p.code === s?.pending_plan);
  const ends = s?.trial_ends_at ? new Date(s.trial_ends_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : null;

  async function makeCampaign() {
    if (!first) return;
    setBusy("campaign"); setNotice(null);
    try {
      await api("/review-growth/campaigns", { method: "POST", body: { name: `${first.name} reviews`, location_id: first.id } });
      camps.reload();
    } catch (e) { setNotice(errorMessage(e)); } finally { setBusy(null); }
  }

  async function finish() {
    setBusy("finish"); setNotice(null);
    try {
      await api("/tenant/complete-onboarding", { method: "POST" });
      clearMemory();
      await refresh();
      if (method === "google") {
        try {
          const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST" });
          window.location.href = auth_url;
          return;
        } catch (e) {
          if (e instanceof ApiError && e.code === "google_config_pending") { router.replace("/gbp/locations"); return; }
          router.replace("/gbp/locations");  // the app is open; connecting Google can be retried from Locations
          return;
        }
      }
      router.replace("/overview");
    } catch (e) {
      if (e instanceof ApiError && e.code === "authorization_required") { onNeedAuthorization(e.message); }  // the plan step shows why
      else setNotice(errorMessage(e));
      setBusy(null);
    }
  }

  return (
    <StepCard>
      <StepHeading step={3} title="You are all set">One last look, then your dashboard opens.</StepHeading>
      {notice && <div className="mt-5"><Alert tone="error">{notice}</Alert></div>}
      {loading ? <div className="grid place-items-center py-14"><Spinner /></div> : (
        <>
          <ul className="mt-5 divide-y divide-m-line">
            <Row icon={<Building2 className="h-[18px] w-[18px]" strokeWidth={1.75} />} label="Business"><span className="font-medium">{businessName || "Your business"}</span></Row>
            <Row icon={<MapPin className="h-[18px] w-[18px]" strokeWidth={1.75} />} label="First location"><span className="font-medium">{first?.name ?? "Added"}</span>{first?.city && <span className="text-m-muted">, {first.city}</span>}</Row>
            <Row icon={<CalendarClock className="h-[18px] w-[18px]" strokeWidth={1.75} />} label="Free trial">
              <span className="font-medium">{plans.data ? `${plans.data.trial_days} days` : "Active"}</span>{ends && <span className="text-m-muted">, until {ends}</span>}
              <span className="mt-0.5 block text-[13.5px] text-m-muted">
                {s?.authorization_status === "authorized" && planName ? `Payment method authorised. ${planName.name} (${rupees(planName.price_paise)} + GST a month) is charged when the trial ends. Cancel any time from Billing.` : "Nothing is charged automatically."}
              </span>
            </Row>
            <Row icon={<QrCode className="h-[18px] w-[18px]" strokeWidth={1.75} />} label="First review page">
              {hasCampaign ? <span className="inline-flex items-center gap-1.5 font-medium text-[#157347]"><Check className="h-4 w-4" aria-hidden />Created</span> : (
                <>
                  <span className="block text-[14px] text-m-ink2">This is the page customers see when they scan your card.</span>
                  <Button variant="secondary" size="sm" className="mt-2.5" loading={busy === "campaign"} onClick={() => void makeCampaign()} icon={<QrCode className="h-4 w-4" aria-hidden />}>Create my review page</Button>
                </>
              )}
              {!first?.review_url && <span className="mt-2 block text-[13px] text-m-muted">Your Google review link is not set yet, so the page cannot send customers to Google. Add it under Locations after this step.</span>}
            </Row>
          </ul>
          <StepActions onBack={onBack} backDisabled={busy !== null}>
            <Button variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[240px]" loading={busy === "finish"} onClick={() => void finish()}>
              {method === "google" ? "Connect Google and open dashboard" : "Open my dashboard"} <ArrowRight className="h-4 w-4" aria-hidden />
            </Button>
          </StepActions>
          <p className="mt-3 text-center text-[13px] text-m-muted sm:text-right">Your dashboard keeps a getting-started checklist until the essentials are done.</p>
        </>
      )}
    </StepCard>
  );
}
