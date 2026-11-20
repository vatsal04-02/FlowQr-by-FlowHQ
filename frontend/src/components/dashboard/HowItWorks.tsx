import clsx from "clsx";
import { ArrowRight, Check, PenLine } from "lucide-react";
import type { ReactNode } from "react";
import { Poster } from "@/components/marketing/Poster";
import { Stars } from "@/components/ui/Card";
import { LogoMark } from "@/components/ui/Brand";

/**
 * Two small pictures of how FlowQR works, for places where there is no real activity to show yet. They illustrate a workflow;
 * they are labelled "Example" and contain no business names, counts or results.
 */
function Step({ n, title, children, visual, last }: { n: number; title: string; children: string; visual: ReactNode; last?: boolean }) {
  return (
    <li className="relative flex min-w-0 flex-1 flex-col">
      <div className="flex h-[148px] items-center justify-center overflow-hidden rounded-xl bg-flow-50 p-3">{visual}</div>
      <p className="mt-3 text-sm font-semibold text-navy"><span className="mr-1.5 inline-grid h-5 w-5 place-items-center rounded-full bg-navy text-[12px] text-white" aria-hidden>{n}</span>{title}</p>
      <p className="mt-0.5 text-[13px] leading-snug text-ink-500">{children}</p>
      {!last && <ArrowRight aria-hidden className="absolute -right-3.5 top-[62px] hidden h-5 w-5 text-flow-700 lg:block" />}
    </li>
  );
}

const Mini = ({ children, className }: { children: ReactNode; className?: string }) => <div aria-hidden className={clsx("rounded-lg bg-white p-2.5 text-left text-navy shadow-panel", className)}>{children}</div>;

export function CardToReview() {
  return (
    <div>
      <h3 className="text-sm font-bold text-navy">How a customer review happens <span className="ml-1 rounded bg-ink-100 px-1.5 py-0.5 text-[12px] font-semibold text-ink-500">Example</span></h3>
      <ol className="mt-3 grid gap-5 lg:flex lg:gap-7">
        <Step n={1} title="They tap or scan your card" visual={<div className="w-[84px]"><Poster alt="The FlowQR review card with a QR code and Tap to Review" /></div>}>The card sits on your counter. No app to install.</Step>
        <Step n={2} title="They pick stars and topics" visual={
          <Mini className="w-[150px]"><p className="text-[12px] font-semibold">Share your experience</p><div className="mt-1"><Stars rating={5} size={13} /></div>
            <div className="mt-1.5 flex flex-wrap gap-1">{["Friendly staff", "On time"].map((t) => <span key={t} className="rounded bg-navy px-1.5 py-0.5 text-[9px] font-medium text-white">{t}</span>)}</div></Mini>}>The AI helps them say it clearly, in English or Hindi.</Step>
        <Step n={3} last title="They post it on Google" visual={
          <Mini className="w-[160px]"><Stars rating={5} size={12} /><p className="mt-1 text-[12px] leading-snug">The staff were friendly and I was seen on time.</p><p className="mt-1.5 text-[9px] font-semibold text-ink-500">Posted by the customer on Google</p></Mini>}>It&rsquo;s their own review. FlowQR never posts one for them.</Step>
      </ol>
    </div>
  );
}

export function AiReply() {
  return (
    <div>
      <h3 className="text-sm font-bold text-navy">How your AI assistant helps with replies <span className="ml-1 rounded bg-ink-100 px-1.5 py-0.5 text-[12px] font-semibold text-ink-500">Example</span></h3>
      <ol className="mt-3 grid gap-5 lg:flex lg:gap-7">
        <Step n={1} title="A review comes in" visual={<Mini className="w-[160px]"><Stars rating={5} size={12} /><p className="mt-1 text-[12px] leading-snug">Everything was explained clearly.</p></Mini>}>FlowQR picks it up from Google.</Step>
        <Step n={2} title="Your assistant writes a reply" visual={
          <Mini className="w-[170px]"><p className="flex items-center gap-1 text-[9px] font-semibold text-ink-500"><LogoMark size={11} />Draft in your voice</p><p className="mt-1 text-[12px] leading-snug">Thank you! We&rsquo;re glad it was clear. See you again soon.</p></Mini>}>It only uses what you&rsquo;ve told it about your business.</Step>
        <Step n={3} last title="You approve it" visual={
          <Mini className="w-[170px]"><p className="text-[12px] leading-snug text-ink-700">Ready to send to Google?</p>
            <div className="mt-2 flex gap-1.5"><span className="inline-flex items-center gap-1 rounded bg-fq px-2 py-1 text-[12px] font-bold text-pure-ink"><Check className="h-3 w-3" strokeWidth={3} />Approve</span><span className="inline-flex items-center gap-1 rounded bg-ink-100 px-2 py-1 text-[12px] font-semibold"><PenLine className="h-3 w-3" />Edit</span></div></Mini>}>Nothing goes live without your okay.</Step>
      </ol>
    </div>
  );
}
