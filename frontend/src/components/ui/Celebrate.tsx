import { Check } from "lucide-react";
import type { ReactNode } from "react";

/** The end of a journey (peak-end rule): a tick that pops with a soft ripple, a plain headline, and the one next step. Use when a person has finished something that mattered. */
export function Celebrate({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div role="status" className="panel flex flex-col items-center px-6 py-10 text-center">
      <span className="relative grid h-16 w-16 place-items-center" aria-hidden>
        <span className="fq-ripple absolute inset-0 rounded-full bg-pos/30" />
        <span className="fq-pop grid h-16 w-16 place-items-center rounded-full bg-pos text-pure-white"><Check className="h-8 w-8" strokeWidth={2.5} /></span>
      </span>
      <h2 className="mt-5 text-xl font-semibold">{title}</h2>
      {children && <p className="mt-1.5 max-w-md text-sm text-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
