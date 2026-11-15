"use client";
import { LinkButton } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { SetupRequired } from "@/components/SetupRequired";

export default function StudioPage() {
  return (
    <>
      <PageHeader eyebrow="Content Studio" title="AI Creator" subtitle="Write captions and festival or seasonal posts from your Knowledge Base." />
      <div className="mb-4"><Panel title="What works today" meta="Google posts"><p className="text-sm text-ink-700">You can already write an AI draft for your Google profile from your Knowledge Base, check it against your rules, approve it, and schedule it.</p><p className="mt-2"><LinkButton href="/gbp/posts" size="sm">Write a Google post with AI</LinkButton></p></Panel></div>
      <SetupRequired integration="meta" what="Social content creation" plans={["Draft captions and festival/seasonal posts grounded in your Knowledge Base, with the same safety checks as Google posts.", "Optionally generate images through a provider you configure; generated is never the same as published.", "Publish to Facebook and Instagram through an authorized Meta connection, or download the files and post them yourself."]} />
    </>
  );
}
