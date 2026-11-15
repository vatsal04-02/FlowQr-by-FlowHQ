"use client";
import clsx from "clsx";
import { Check } from "lucide-react";
import { PageHeader } from "@/components/ui/Card";
import { useTheme, type ThemeMode } from "@/lib/theme";

/** A miniature of the app in one theme: canvas, a white (or dark) card, an orange tile and a black pill. Decorative. */
function Preview({ dark }: { dark: boolean }) {
  const c = dark ? { canvas: "#100D13", card: "#17141A", well: "#1F1B24", ink: "#F2EFF5", line: "#3A3540" } : { canvas: "#F2EFF3", card: "#FFFFFF", well: "#F3F0F4", ink: "#131014", line: "#E3DFE5" };
  return (
    <div aria-hidden className="grid h-full grid-cols-[14px_1fr] gap-2 p-3" style={{ background: c.canvas }}>
      <div className="flex flex-col gap-1.5 rounded-full p-0.5" style={{ background: c.card }}>{[0, 1, 2].map((i) => <span key={i} className="h-2.5 w-2.5 rounded-full" style={{ background: i === 0 ? c.ink : c.line }} />)}</div>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl p-2" style={{ background: c.card }}><span className="block h-1.5 w-8 rounded-full" style={{ background: c.line }} /><span className="mt-2 block h-3 w-10 rounded-full" style={{ background: c.ink }} /></div>
        <div className="rounded-xl" style={{ background: "linear-gradient(135deg,#F4754C,#EA542E 55%,#DA451A)" }} />
        <div className="col-span-2 rounded-xl p-2" style={{ background: c.card }}><span className="block h-6 rounded-lg" style={{ background: c.well }} /></div>
      </div>
    </div>
  );
}

const OPTIONS: [ThemeMode, string, string][] = [
  ["light", "Light", "Soft grey canvas, white cards."],
  ["dark", "Dark", "Easier on the eyes at night."],
  ["system", "System", "Follows your phone or computer setting."],
];

export default function AppearancePage() {
  const { mode, setTheme } = useTheme();
  return (
    <>
      <PageHeader title="Appearance" subtitle="Choose how FlowQR looks on this device. The sun and moon in the left rail switch it too." />
      <div role="radiogroup" aria-label="Theme" className="grid gap-4 sm:grid-cols-3 sm:gap-6">
        {OPTIONS.map(([m, label, desc]) => {
          const on = mode === m;
          return (
            <button key={m} type="button" role="radio" aria-checked={on}
              onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setTheme(m, { x: r.left + r.width / 2, y: r.top + r.height / 2 }); }}
              className={clsx("panel lift overflow-hidden p-2 text-left", on && "ring-2 ring-accent")}>
              <div className="h-36 overflow-hidden rounded-[22px]">
                {m === "system" ? <div className="grid h-full grid-cols-2"><Preview dark={false} /><Preview dark /></div> : <Preview dark={m === "dark"} />}
              </div>
              <div className="flex items-start justify-between gap-3 px-3 pb-3 pt-4">
                <span><span className="block text-base font-semibold">{label}</span><span className="block text-sm text-muted">{desc}</span></span>
                <span aria-hidden className={clsx("grid h-6 w-6 shrink-0 place-items-center rounded-full", on ? "bg-ink-solid text-ink-on" : "bg-surface-2")}>{on && <Check className="h-3.5 w-3.5" strokeWidth={3} />}</span>
              </div>
            </button>
          );
        })}
      </div>
      <p className="mt-6 text-sm text-muted">Saved on this device only. Your customers&rsquo; QR card page always uses its own design.</p>
    </>
  );
}
