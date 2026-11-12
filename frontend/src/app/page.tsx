import { ArrowRight, Check, Minus, Sparkles } from "lucide-react";
import Link from "next/link";
import { MarketingFooter, MarketingHeader } from "@/components/marketing/MarketingChrome";
import { HeroStage } from "@/components/marketing/HeroStage";
import { Poster } from "@/components/marketing/Poster";
import { PosterAnatomy } from "@/components/marketing/PosterAnatomy";
import { LandingPlans, TrialNote } from "@/components/marketing/LandingPlans";
import { Shot } from "@/components/marketing/Shot";
import { Reveal } from "@/components/motion";
import { LinkButton } from "@/components/ui/Button";

const FAQ: [string, string][] = [
  ["Do my customers need to install an app or make an account?", "No. Tapping the NFC card or scanning the QR code opens a web page in their phone's browser. They write their review there and continue to Google."],
  ["Does FlowQR work without Google API approval?", "Yes. In manual review-link mode, the cards, the customer writing assistant and scan analytics all work with the Google review link you paste in. Automatic review sync, reply publishing and profile tools need Google to approve Business Profile API access for your connection."],
  ["Who writes and posts the review?", "The customer, always. AI can tidy the grammar and clarity of what they typed, they can edit or ignore the suggestion, and they submit the review on Google themselves. FlowQR never posts a review for anyone."],
  ["Can I hide or avoid asking unhappy customers?", "No. FlowQR doesn't gate by rating or filter feedback, and doesn't offer incentives for reviews. Every customer gets the same flow. That is how Google expects review requests to work."],
  ["How do AI replies work?", "AI drafts a reply to a synced review. An owner or admin edits it and approves it, and only then is it sent to Google. A reply is shown as published only after Google confirms it. Reviews that mention medical details, threats or legal action are flagged for you to handle personally."],
  ["What happens if I change my Google link or move a card?", "Nothing breaks. Each card's link is permanent; the review link and the card's location are settings you can change. Scan history stays with the card."],
  ["What languages does it support?", "Customers can write in English, Hindi or Hinglish, and the suggestion comes back in the language they choose. Reply drafts follow your business language and brand tone."],
  ["How is my data kept private?", "Each business's data is isolated in the database with PostgreSQL row-level security. Passwords use Argon2id, Google tokens are encrypted at rest and never sent to your browser, and AI usage logs record sizes, not customer text."],
  ["Are the cards included in the subscription?", "No. Physical QR/NFC cards are sold separately and paid per order. The subscription covers the software."],
  ["Is FlowQR affiliated with Google?", "No. FlowQR is a FlowHQ product. It is not affiliated with, endorsed by or sponsored by Google."],
];

const PROCESS = [
  ["Tap or scan", "The customer taps the NFC card or scans the QR code at your counter."],
  ["Write in their own words", "They type what they actually felt, in English, Hindi or Hinglish."],
  ["Polish, don't invent", "AI tidies grammar and clarity. They edit it and keep full control."],
  ["Post on Google", "They copy it and submit on your Google review page themselves."],
  ["You manage the rest", "Reviews, drafted replies and scan analytics arrive in your dashboard."],
];

export default function Landing() {
  return (
    <div className="overflow-x-clip bg-white">
      <MarketingHeader />
      <main>
        {/* 1. Hero: headline on the left, the physical product and the software it feeds on the right. */}
        <section className="border-b border-ink-100 bg-ink-50">
          <div className="container-page grid items-center gap-10 py-12 sm:py-16 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.1fr)] lg:gap-8 lg:py-20">
            <div>
              <p className="eyebrow">FlowQR by FlowHQ</p>
              <h1 className="mt-3 text-[2.15rem] font-bold leading-[1.06] tracking-[-.035em] sm:text-[2.9rem] lg:text-[3.2rem]">Collect reviews at the counter. <span className="text-flow-700">Manage your reputation</span> in one place.</h1>
              <p className="mt-4 max-w-xl text-[17px] leading-relaxed text-ink-700">FlowQR connects physical tap-and-scan cards with AI-assisted review workflows, Google review management and business analytics.</p>
              <div className="mt-7 flex flex-wrap gap-3">
                <LinkButton href="/register" size="lg">Start free trial<ArrowRight className="h-4 w-4" aria-hidden /></LinkButton>
                <LinkButton href="#how" size="lg" variant="secondary">See how it works</LinkButton>
              </div>
              <ul className="mt-8 divide-y divide-ink-200 border-y border-ink-200 text-sm">
                {["Works in manual review-link mode, with no Google API approval needed", "Customers write and submit their own reviews", "You approve every reply before it is published"].map((t) => (
                  <li key={t} className="flex items-center gap-2.5 py-2.5"><Check className="h-4 w-4 shrink-0 text-ok" strokeWidth={2.6} aria-hidden />{t}</li>))}
              </ul>
            </div>
            <HeroStage />
          </div>
        </section>

        {/* 2. The product itself, annotated. */}
        <PosterAnatomy />

        {/* 3. How it works: one ruled strip, five steps. */}
        <section id="how" className="py-14 sm:py-20">
          <div className="container-page">
            <Reveal><p className="eyebrow">How it works</p><h2 className="mt-2 max-w-2xl text-2xl font-bold sm:text-3xl">From the counter to Google in under a minute.</h2></Reveal>
            <ol className="mt-8 grid border-t-2 border-ink sm:grid-cols-2 lg:grid-cols-5">
              {PROCESS.map(([t, b], i) => (
                <Reveal as="li" key={t} delay={i * 50} className="border-b border-ink-200 py-5 sm:pr-6 lg:border-b-0 lg:border-r lg:px-5 lg:first:pl-0 lg:last:border-r-0">
                  <span className="card-code text-xs text-ink-500">STEP {i + 1}</span>
                  <h3 className="mt-2 text-[15px] font-semibold">{t}</h3><p className="mt-1 text-[13px] leading-relaxed text-ink-500">{b}</p>
                </Reveal>))}
            </ol>
          </div>
        </section>

        {/* 3. AI review assistance: the customer's side, shown as UI. */}
        <section id="ai" className="border-y border-ink-100 bg-ink-50 py-14 sm:py-20">
          <div className="container-page grid items-center gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-16">
            <Reveal>
              <p className="eyebrow">AI review assistance</p>
              <h2 className="mt-2 text-2xl font-bold sm:text-3xl">Help people say it clearly. Never say it for them.</h2>
              <p className="mt-3 max-w-lg text-ink-700">Customers describe their visit in their own words. The assistant fixes grammar and clarity and shows its suggestion next to what they wrote. They choose which to keep, edit it, then post it themselves.</p>
              <dl className="mt-6 divide-y divide-ink-200 border-y border-ink-200 text-sm">
                {[["Their words first", "The suggestion only appears after they have written something."], ["Fully editable", "They can edit the suggestion or go back to their original text."], ["Clearly labelled", "The page says the suggestion is AI-assisted, every time."], ["No invented praise", "The assistant rewrites what was said. It doesn't add claims."]].map(([k, v]) => (
                  <div key={k} className="grid gap-1 py-2.5 sm:grid-cols-[9.5rem_1fr] sm:gap-4"><dt className="font-semibold">{k}</dt><dd className="text-ink-500">{v}</dd></div>))}
              </dl>
            </Reveal>
            <Reveal delay={80}>
              <div className="grid gap-3 sm:grid-cols-2" role="img" aria-label="Side by side: a customer's own words, and the AI-assisted suggestion they can edit. Illustrative example.">
                <div className="panel p-4"><p className="eyebrow !text-[11px]">What they wrote</p><p className="mt-2 text-[15px] leading-relaxed">booked online, seen on time. staff explained the exercises clearly. bit of a wait but ok</p></div>
                <div className="panel border-brand-200 p-4"><p className="eyebrow !text-[11px] text-brand-700"><Sparkles className="mr-1 inline h-3 w-3 align-[-1px]" aria-hidden />AI-assisted suggestion</p><p className="mt-2 text-[15px] leading-relaxed">I booked online and was seen on time. The staff explained the exercises clearly. There was a short wait, but it was fine.</p><p className="mt-3 text-xs text-ink-500">Edit freely, or use your original words instead.</p></div>
                <div className="panel sm:col-span-2">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-4 py-2.5"><p className="text-sm font-semibold">Reply to a synced review</p>
                    <ol aria-label="Reply progress" className="flex items-center gap-2 text-xs font-medium"><li className="flex items-center gap-1.5"><span className="grid h-4 w-4 place-items-center rounded-full bg-ok text-white"><Check className="h-2.5 w-2.5" strokeWidth={3.5} aria-hidden /></span>Draft</li><li aria-hidden className="h-px w-4 bg-ink-300" /><li className="flex items-center gap-1.5" aria-current="step"><span className="grid h-4 w-4 place-items-center rounded-full bg-brand-600 text-[10px] font-bold text-white">2</span>Approve</li><li aria-hidden className="h-px w-4 bg-ink-300" /><li className="flex items-center gap-1.5 text-ink-500"><span className="grid h-4 w-4 place-items-center rounded-full bg-ink-100 text-[10px] font-bold">3</span>Publish</li></ol></div>
                  <div className="p-4"><p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-700"><span className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-1.5 py-0.5 text-brand-800"><Sparkles className="h-3 w-3" aria-hidden />AI draft</span>Edit before approving</p>
                    <p className="rounded-lg border border-ink-300 p-3 text-[14px] leading-relaxed">Thank you for taking the time to share this. We&rsquo;re glad your visit went smoothly and we look forward to seeing you again.</p></div>
                </div>
                <p className="text-xs text-ink-500 sm:col-span-2">Illustrative example</p>
              </div>
            </Reveal>
          </div>
        </section>

        {/* 4. Google review management: the real workspace, with its five stages listed under it. */}
        <section id="reviews" className="py-14 sm:py-20">
          <div className="container-page">
            <Reveal className="grid items-end gap-3 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
              <div><p className="eyebrow">Google review management</p><h2 className="mt-2 text-2xl font-bold sm:text-3xl">One inbox. Every reply approved by a person.</h2></div>
              <p className="text-ink-700">Reviews from your Google Business Profile arrive in one workspace, filtered by location, rating and reply status. Drafting is fast; publishing is deliberate.</p>
            </Reveal>
            <Reveal delay={60} className="mt-8"><Shot src="/product/reviews.jpg" path="/reviews" alt="The FlowQR reviews workspace: a list of reviews with reply status on the left, and the selected review with its reply editor and approval steps on the right." /></Reveal>
            <ol className="mt-6 grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-5">
              {[["Sync", "Reviews arrive from connected Google locations."], ["Triage", "Needs reply, drafts and failures are separated. Sensitive reviews are flagged."], ["Draft", "Write a reply or let AI draft one from your brand tone."], ["Approve", "An owner or admin edits and approves it."], ["Publish", "Marked “Replied” only after Google confirms."]].map(([t, b], i) => (
                <li key={t} className="border-t border-ink-200 pt-3"><p className="text-sm font-semibold"><span className="num mr-1.5 text-ink-400">{i + 1}</span>{t}</p><p className="mt-1 text-[13px] text-ink-500">{b}</p></li>))}
            </ol>
            <p className="mt-6 max-w-3xl border-l-2 border-gold-400 pl-3 text-[13px] text-ink-700"><b className="font-semibold">Honest about sync.</b> Automatic review sync and reply publishing need Google to approve Business Profile API access for your connection. Until then, FlowQR runs in manual review-link mode: cards, the writing assistant and scan analytics all work.</p>
          </div>
        </section>

        {/* 5. Card management: the one graphite band, where the physical product leads. */}
        <section id="cards" className="bg-ink py-14 text-white sm:py-20">
          <div className="container-page grid items-center gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-14">
            <Reveal>
              <p className="eyebrow !text-gold-400">Card management</p>
              <h2 className="mt-2 text-2xl font-bold sm:text-3xl">Every card has an ID, a link and a place.</h2>
              <p className="mt-3 max-w-lg text-ink-200">Cards are managed like the physical products they are. Each one has a printed FQR ID and its own permanent QR and NFC link, assigned to a location and tracked from the first scan.</p>
              <ul className="mt-6 grid gap-x-6 gap-y-2.5 text-sm text-ink-200 sm:grid-cols-2">
                {["Unique, unguessable link per card", "Assign, reassign or deactivate", "Download QR as PNG or SVG", "Scans, visits, clicks, last scan", "Change the Google link, keep the card", "History is kept when a card moves"].map((t) => <li key={t} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-gold-400" strokeWidth={2.6} aria-hidden />{t}</li>)}
              </ul>
            </Reveal>
            <Reveal delay={80}>
              <div className="mx-auto grid max-w-[560px] grid-cols-3 items-end gap-3 sm:gap-5" role="img" aria-label="Three FlowQR cards in the inventory: two live, one deactivated. Illustrative example.">
                {[["FQR-0001", "Live", "text-green-400", false, "-rotate-[3deg]"], ["FQR-0002", "Live", "text-green-400", false, "rotate-0 -translate-y-3"], ["FQR-0003", "Deactivated", "text-amber-400", true, "rotate-[3deg]"]].map(([code, state, tone, off, rot]) => (
                  <div key={code as string} className={rot as string}>
                    <div style={{ filter: "drop-shadow(0 18px 20px rgba(0,0,0,.5))" }}><Poster muted={off as boolean} /></div>
                    <p className="mt-3 flex items-center justify-between gap-1 text-[11px] sm:text-xs"><span className="card-code text-gold-400">{code as string}</span><span className={`font-medium ${tone}`}>{state as string}</span></p>
                  </div>))}
              </div>
              <p className="mt-4 text-xs text-ink-200">Illustrative example. The QR on the artwork is a sample; real cards each get their own generated code.</p>
            </Reveal>
          </div>
        </section>

        {/* 6. Multi-location: screenshot first, facts second. */}
        <section id="locations" className="py-14 sm:py-20">
          <div className="container-page grid items-center gap-10 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:gap-14">
            <Reveal className="order-2 lg:order-1"><Shot src="/product/locations.jpg" path="/locations" crop="aspect-[16/9]" alt="The FlowQR locations ledger: each branch with its Google sync status, review link and assigned cards, and a warning on the branch that has no review link." /></Reveal>
            <Reveal delay={80} className="order-1 lg:order-2">
              <p className="eyebrow">Multi-location support</p>
              <h2 className="mt-2 text-2xl font-bold sm:text-3xl">See which branch needs attention at a glance.</h2>
              <p className="mt-3 text-ink-700">Each branch has its own review link, cards, stats and team. The ledger shows what&rsquo;s connected, what&rsquo;s syncing, and what&rsquo;s missing, and flags the branches that need you.</p>
              <ul className="mt-5 space-y-2 text-sm">
                {["Google connection and sync status per branch", "The configured review link, one click to test", "Which cards are assigned, and whether they are live", "Clear “configuration pending” states, never a fake connection"].map((t) => <li key={t} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" strokeWidth={2.6} aria-hidden />{t}</li>)}
              </ul>
            </Reveal>
          </div>
        </section>

        {/* 7. Analytics: definitions beside the chart, because the numbers mean different things. */}
        <section id="analytics" className="border-y border-ink-100 bg-ink-50 py-14 sm:py-20">
          <div className="container-page grid items-start gap-10 lg:grid-cols-[minmax(0,.85fr)_minmax(0,1.3fr)] lg:gap-14">
            <Reveal>
              <p className="eyebrow">Analytics</p>
              <h2 className="mt-2 text-2xl font-bold sm:text-3xl">Four numbers. Four different meanings.</h2>
              <p className="mt-3 text-ink-700">A scan is not a visit, a click is not a review. FlowQR keeps them apart so you can trust each one.</p>
              <dl className="mt-6 divide-y divide-ink-200 border-y border-ink-200 text-sm">
                {[["Scans", "A card was tapped or scanned and its link resolved."], ["Visits", "The review page actually loaded in a browser."], ["Clicks to Google", "Someone pressed “Continue to Google”. It doesn't prove a review was posted."], ["Published reviews", "Counted from your synced Google reviews, not from clicks."]].map(([k, v]) => (
                  <div key={k} className="grid gap-1 py-2.5 sm:grid-cols-[9rem_1fr] sm:gap-4"><dt className="font-semibold">{k}</dt><dd className="text-ink-500">{v}</dd></div>))}
              </dl>
            </Reveal>
            <Reveal delay={80}><Shot src="/product/analytics.jpg" path="/analytics" alt="The FlowQR analytics workspace: card scans, visits and clicks shown separately from published Google reviews, with review volume and rating trends." /></Reveal>
          </div>
        </section>

        {/* 8. Pricing */}
        <section id="pricing" className="py-14 sm:py-20">
          <div className="container-page">
            <Reveal className="max-w-2xl"><p className="eyebrow">Pricing</p><h2 className="mt-2 text-2xl font-bold sm:text-3xl">Simple pricing in rupees.</h2><p className="mt-2 text-ink-700"><TrialNote /></p></Reveal>
            <Reveal delay={60} className="mt-8"><LandingPlans /></Reveal>
            <p className="mt-4 max-w-3xl text-xs text-ink-500">Physical QR/NFC cards are sold separately from the subscription and paid per order. Payments are processed by Razorpay (UPI, cards, netbanking). Google review sync, replies and profile tools need your own Google Business Profile and Google&rsquo;s API access.</p>
          </div>
        </section>

        {/* 9. Compliance and trust */}
        <section id="trust" className="border-t border-ink-100 bg-ink-50 py-14 sm:py-20">
          <div className="container-page">
            <Reveal className="max-w-2xl"><p className="eyebrow">Compliance and trust</p><h2 className="mt-2 text-2xl font-bold sm:text-3xl">Built to Google&rsquo;s review rules, and to keep your data yours.</h2></Reveal>
            <div className="mt-8 grid gap-4 lg:grid-cols-2">
              <Reveal className="panel overflow-hidden">
                <h3 className="border-b border-ink-100 px-4 py-2.5 text-sm font-semibold">What FlowQR does</h3>
                <ul className="divide-y divide-ink-100 text-sm">{["Gives every customer the same review flow, whatever their rating", "Lets customers write, edit and submit their own review", "Labels AI-assisted text as AI-assisted", "Requires a person to approve every reply", "Marks a reply published only after Google confirms it", "Runs without Google API access, in manual review-link mode"].map((t) => <li key={t} className="flex gap-2.5 px-4 py-2.5"><Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" strokeWidth={2.6} aria-hidden />{t}</li>)}</ul>
              </Reveal>
              <Reveal delay={60} className="panel overflow-hidden">
                <h3 className="border-b border-ink-100 px-4 py-2.5 text-sm font-semibold">What FlowQR never does</h3>
                <ul className="divide-y divide-ink-100 text-sm">{["Post a review on a customer's behalf", "Filter or hide feedback by rating (review gating)", "Offer incentives in exchange for reviews", "Invent praise or write reviews customers didn't say", "Publish a reply without approval", "Claim to be affiliated with or endorsed by Google"].map((t) => <li key={t} className="flex gap-2.5 px-4 py-2.5"><Minus className="mt-0.5 h-4 w-4 shrink-0 text-red-700" strokeWidth={2.6} aria-hidden />{t}</li>)}</ul>
              </Reveal>
            </div>
            <dl className="mt-4 grid divide-ink-200 rounded-panel border border-ink-200 bg-white text-sm sm:grid-cols-3 sm:divide-x">
              {[["Tenant isolation", "Each business's data is separated with PostgreSQL row-level security, in addition to application checks."], ["Credentials", "Passwords are hashed with Argon2id. Google tokens are encrypted at rest and never sent to your browser."], ["AI logging", "Usage logs store sizes, never customer text. Sensitive reviews are flagged for personal handling."]].map(([k, v]) => (
                <div key={k} className="p-4"><dt className="font-semibold">{k}</dt><dd className="mt-1 text-[13px] text-ink-500">{v}</dd></div>))}
            </dl>
          </div>
        </section>

        {/* 10. FAQ */}
        <section id="faq" className="py-14 sm:py-20">
          <div className="container-page grid gap-8 lg:grid-cols-[minmax(0,.7fr)_minmax(0,1.5fr)] lg:gap-14">
            <div><p className="eyebrow">FAQ</p><h2 className="mt-2 text-2xl font-bold sm:text-3xl">Questions owners ask first.</h2><p className="mt-3 text-sm text-ink-500">Something missing? <Link href="/login" className="font-medium text-brand-700 hover:underline">Log in</Link> and use the in-app help, or start the trial and try the card yourself.</p></div>
            <div className="divide-y divide-ink-200 border-y border-ink-200">
              {FAQ.map(([q, a]) => (
                <details key={q} className="group py-3.5">
                  <summary className="flex cursor-pointer list-none items-start justify-between gap-4 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">{q}<span aria-hidden className="mt-1 text-ink-400 transition-transform group-open:rotate-45">+</span></summary>
                  <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-700">{a}</p>
                </details>))}
            </div>
          </div>
        </section>

        <section className="bg-flow-500 py-14 text-ink sm:py-20">
          <div className="container-page flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div><h2 className="max-w-2xl text-3xl font-bold leading-[1.08] tracking-[-.03em] sm:text-[2.6rem]">Put a card on your counter this week.</h2><p className="mt-3 max-w-xl text-[17px] text-ink/90">Set up your business and first location in about two minutes. The 14-day trial needs no card.</p></div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3"><LinkButton href="/register" size="lg" variant="ink">Start free trial<ArrowRight className="h-4 w-4" aria-hidden /></LinkButton><Link href="/pricing" className="inline-flex min-h-11 items-center font-semibold underline decoration-ink/40 underline-offset-4 hover:decoration-ink">See pricing</Link></div>
          </div>
        </section>
      </main>
      <MarketingFooter />
    </div>
  );
}
