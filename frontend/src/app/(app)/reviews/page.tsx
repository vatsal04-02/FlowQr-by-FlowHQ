import { Check } from "lucide-react";

const STEPS = [
  ["Draft", "Write a reply yourself, or let AI draft one from the review and your brand tone."],
  ["Approve", "An owner or admin reads it, edits it and approves. Sensitive reviews need an explicit acknowledgement."],
  ["Publish", "FlowQR sends it to Google and shows “Replied” only after Google confirms."],
];

/** Detail-pane content when nothing is selected (no reviews yet, or mobile list view). Explains the workflow instead of showing a blank box. */
export default function ReviewsIndex() {
  return (
    <div className="mx-auto max-w-lg p-6 sm:p-10">
      <p className="eyebrow mb-2">How replies work</p>
      <h2 className="text-lg font-semibold">Nothing is posted until a person approves it.</h2>
      <ol className="mt-5 space-y-4">
        {STEPS.map(([t, b], i) => (
          <li key={t} className="flex gap-3">
            <span aria-hidden className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-ink text-[11px] font-bold text-white">{i + 1}</span>
            <div><p className="text-sm font-semibold">{t}</p><p className="mt-0.5 text-[13px] text-ink-500">{b}</p></div>
          </li>
        ))}
      </ol>
      <p className="mt-6 flex items-start gap-2 text-[13px] text-ink-500"><Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />Select a review on the left to start.</p>
    </div>
  );
}
