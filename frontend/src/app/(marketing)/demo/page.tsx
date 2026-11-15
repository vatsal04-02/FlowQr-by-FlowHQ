import type { Metadata } from "next";
import { DemoForm } from "@/components/marketing/DemoForm";
import { BlurWords } from "@/components/marketing/motion";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.demo;
export const metadata: Metadata = pageMeta("/demo", c.meta.title, c.meta.description);

export default function Demo() {
  return (
    <section className="pb-24 pt-16 md:pb-36 md:pt-24">
      <div className="mkt-wrap">
        <h1 className="t-display text-m-ink"><BlurWords text={c.title} /></h1>
        <p className="mt-5 max-w-[520px] text-[15px] text-m-muted">{c.sub}</p>
        <div className="mt-12"><DemoForm /></div>
      </div>
    </section>
  );
}
