import { BarChart3, Check, MessageSquareReply, Nfc, QrCode, ShieldCheck, Sparkles, Store } from "lucide-react";
import { MarketingFooter, MarketingHeader } from "@/components/MarketingChrome";
import { LinkButton } from "@/components/ui/Button";
import { GoogleDots } from "@/components/ui/Card";

const features = [
  { icon: QrCode, title: "Unique QR + NFC cards", body: "Every card has its own permanent, unguessable link. Tap or scan, and the customer lands on your branch's review page.", tint: "bg-flow-50 text-flow-700" },
  { icon: Sparkles, title: "Writing help in their words", body: "Customers describe their visit; AI fixes grammar and clarity in English, Hindi or Hinglish. Never invented praise, always editable.", tint: "bg-brand-50 text-brand-700" },
  { icon: MessageSquareReply, title: "Reply drafts you approve", body: "Connect Google, see every review in one inbox, and approve AI-drafted replies before anything is published.", tint: "bg-green-50 text-green-700" },
  { icon: BarChart3, title: "Honest analytics", body: "Scans, page visits and clicks to Google, shown separately from reviews that actually landed.", tint: "bg-amber-50 text-amber-700" },
  { icon: Store, title: "Multi-branch ready", body: "One account, many locations, many cards. Each branch has its own link, stats and team.", tint: "bg-brand-50 text-brand-700" },
  { icon: ShieldCheck, title: "Built to Google's rules", body: "No review gating, no incentives, no auto-posting. Every customer gets the same chance to be heard.", tint: "bg-red-50 text-red-700" },
];

export default function Landing() {
  return (
    <div className="bg-white">
      <MarketingHeader />

      <main>
        <section className="relative overflow-hidden">
          <div className="container-page grid items-center gap-10 py-14 sm:py-20 lg:grid-cols-[1.1fr_.9fr]">
            <div>
              <p className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-sm font-semibold text-brand-800"><GoogleDots />Made for clinics, salons &amp; restaurants in India</p>
              <h1 className="mt-5 text-4xl font-semibold leading-[1.1] sm:text-5xl">AI-powered reputation &amp; review management for <span className="text-flow-600">local businesses</span>.</h1>
              <p className="mt-5 max-w-xl text-lg text-ink-500">Hand customers a FlowQR card. They tap, share their real experience, and post it on Google. You see every review and reply in minutes, with a human always in charge.</p>
              <div className="mt-8 flex flex-wrap gap-3">
                <LinkButton href="/register" size="lg" variant="accent">Start free trial</LinkButton>
                <LinkButton href="#how" size="lg" variant="secondary">See how it works</LinkButton>
              </div>
              <ul className="mt-8 grid gap-2 text-sm text-ink-700 sm:grid-cols-2">
                {["Works without waiting for Google API approval", "Hindi, Hinglish and English", "Prices in INR, no lock-in", "No fake reviews. No review gating."].map((t) => (
                  <li key={t} className="flex items-center gap-2"><Check className="h-4 w-4 shrink-0 text-g-green" aria-hidden />{t}</li>
                ))}
              </ul>
            </div>

            <div className="relative mx-auto w-full max-w-[320px]" aria-hidden>
              <div className="absolute -inset-6 -z-10 rounded-[3rem] bg-gradient-to-br from-brand-50 via-white to-flow-50" />
              <div className="rounded-[2.2rem] border-[10px] border-ink bg-white p-4 shadow-pop">
                <div className="mx-auto mb-3 h-1.5 w-16 rounded-full bg-ink-100" />
                <div className="flex items-center gap-2.5"><span className="grid h-10 w-10 place-items-center rounded-xl bg-flow-500 font-display font-bold">G</span><div><p className="text-sm font-semibold">Geeta Krishna Physio</p><p className="text-xs text-ink-500">Gomti Nagar, Lucknow</p></div></div>
                <p className="mt-4 font-display text-lg font-semibold">Share your experience</p>
                <div className="mt-2 rounded-xl border border-ink-200 p-3 text-xs text-ink-700">doctor was very kind, my back pain is much better after 3 sessions</div>
                <div className="mt-2 rounded-lg bg-brand-600 py-2 text-center text-xs font-semibold text-white">Improve my wording</div>
                <div className="mt-3 rounded-xl bg-brand-50 p-3 text-xs text-ink-700"><p className="mb-1 flex items-center gap-1 font-semibold text-brand-800"><Sparkles className="h-3 w-3" />AI-assisted, edit freely</p>The doctor was very kind, and my back pain has improved a lot after three sessions.</div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-center text-xs font-semibold"><span className="rounded-lg border border-ink-200 py-2">Copy</span><span className="rounded-lg bg-ink py-2 text-white">Continue to Google</span></div>
              </div>
              <div className="absolute -bottom-5 -left-5 grid h-20 w-20 place-items-center rounded-2xl bg-white shadow-pop"><Nfc className="h-8 w-8 text-flow-600" /></div>
            </div>
          </div>
        </section>

        <section id="how" className="bg-ink-50/70 py-16">
          <div className="container-page">
            <h2 className="text-center text-3xl font-semibold">From counter to Google in four steps</h2>
            <ol className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {[["Tap or scan", "Customer taps the NFC card or scans the QR code at your desk."], ["Say it in your own words", "They type what they really felt, in any of three languages."], ["Polish, don't invent", "AI tidies grammar and clarity. They edit and keep full control."], ["Post on Google", "They copy and continue to your Google review page and submit it themselves."]].map(([t, b], i) => (
                <li key={t} className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
                  <span className="grid h-9 w-9 place-items-center rounded-full bg-brand-600 font-display font-semibold text-white">{i + 1}</span>
                  <h3 className="mt-3 text-base font-semibold">{t}</h3><p className="mt-1 text-sm text-ink-500">{b}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="features" className="py-16">
          <div className="container-page">
            <h2 className="text-center text-3xl font-semibold">Everything for a trusted reputation</h2>
            <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {features.map((f) => (
                <article key={f.title} className="rounded-2xl border border-ink-100 p-6 shadow-card transition-shadow hover:shadow-pop">
                  <span className={`grid h-11 w-11 place-items-center rounded-xl ${f.tint}`}><f.icon className="h-5 w-5" aria-hidden /></span>
                  <h3 className="mt-4 text-lg font-semibold">{f.title}</h3><p className="mt-1.5 text-ink-500">{f.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="container-page pb-16">
          <div className="grid items-center gap-6 rounded-3xl border border-ink-100 p-8 shadow-card sm:grid-cols-[1fr_auto]">
            <div><h2 className="text-2xl font-semibold">Plans from ₹399 / month</h2><p className="mt-1 text-ink-500">14-day free trial with Growth features. Cards are ordered separately. Pay by UPI, card or netbanking.</p></div>
            <LinkButton href="/pricing" variant="secondary" size="lg">See pricing</LinkButton>
          </div>
        </section>

        <section className="container-page pb-20">
          <div className="rounded-3xl bg-brand-900 px-6 py-12 text-center text-white sm:px-12">
            <h2 className="!text-white text-3xl font-semibold">Ready to hear from more happy customers?</h2>
            <p className="mx-auto mt-3 max-w-xl text-brand-100">Set up your business and first location in two minutes. Order cards when you're ready.</p>
            <div className="mt-7"><LinkButton href="/register" size="lg" variant="accent">Create your account</LinkButton></div>
          </div>
        </section>
      </main>

      <MarketingFooter />
    </div>
  );
}
