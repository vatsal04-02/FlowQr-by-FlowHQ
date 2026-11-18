"use client";
import { motion, useScroll, useTransform, type MotionValue } from "motion/react";
import { useRef, type CSSProperties, type ReactNode } from "react";

/**
 * "Get started in 3 simple steps" as a pinned scene. The section is three screens tall; while you scroll through it the stage stays on the screen and the scroll itself drives the story:
 * step 1 (Connect Google) gives way to step 2 (the QR card) and then step 3 (reviews and replies), the active step lit in the list and a three-part progress bar filling. It is scrubbed,
 * so it plays backwards when you scroll back up, and nothing waits on a timer.
 *
 * Same words and the same three pictures as the plain steps section (content/marketing/en.ts, HomeVisuals.tsx). Everything is CSS and motion values, so the server and the browser draw the
 * same markup. Under reduced motion CSS (`motion-reduce:`) switches the pinning off: the section is its normal height and the three steps and pictures sit one under the other, fully visible.
 */

/** Straight-line lookup between breakpoints, held flat outside them. */
function lerp(v: number, xs: number[], ys: number[]) {
  if (v <= xs[0]) return ys[0];
  for (let k = 1; k < xs.length; k++) if (v <= xs[k]) return ys[k - 1] + ((v - xs[k - 1]) / (xs[k] - xs[k - 1])) * (ys[k] - ys[k - 1]);
  return ys[ys.length - 1];
}

/** Active-ness of step i (0..1) as the section scrolls: 1 while it is the step on show, crossing over with its neighbours in the gaps. Written as a function (not a range list) so the browser's own
 *  scroll-timeline shortcut is not used for it: that shortcut drew the wrong values for a multi-point curve like this one. */
const CURVES: [number[], number[]][] = [[[0, 0.3, 0.42], [1, 1, 0]], [[0.3, 0.42, 0.58, 0.7], [0, 1, 1, 0]], [[0.58, 0.7, 1], [0, 1, 1]]];
function useActive(p: MotionValue<number>, i: number) {
  return useTransform(p, (v) => lerp(v, CURVES[i][0], CURVES[i][1]));
}

function Layer({ a, children }: { a: MotionValue<number>; children: ReactNode }) {
  const scale = useTransform(a, (v) => 0.94 + 0.06 * v);
  const y = useTransform(a, (v) => 28 * (1 - v));
  return (
    <motion.div aria-hidden className="pointer-events-none absolute inset-0 grid place-items-center motion-reduce:pointer-events-auto motion-reduce:static motion-reduce:!transform-none motion-reduce:!opacity-100" style={{ opacity: a, scale, y }}>
      {children}
    </motion.div>
  );
}

function Segment({ p, i }: { p: MotionValue<number>; i: number }) {
  const fill = useTransform(p, (v) => Math.min(1, Math.max(0, v * 3 - i)));
  return <span className="relative h-1 flex-1 overflow-hidden rounded-full bg-m-ink/10"><motion.span className="absolute inset-0 origin-left rounded-full bg-m-accent" style={{ scaleX: fill }} /></span>;
}

export function PinnedSteps({ title, sub, steps, art }: { title: string; sub?: string; steps: [string, string][]; art: ReactNode[] }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const act = [useActive(p, 0), useActive(p, 1), useActive(p, 2)];
  return (
    <section ref={ref} id="how-it-works" aria-labelledby="how-h" className="relative h-[300svh] scroll-mt-0 motion-reduce:h-auto">
      <div className="sticky top-0 flex h-[100svh] items-center overflow-hidden motion-reduce:static motion-reduce:h-auto motion-reduce:overflow-visible motion-reduce:py-16">
        <div className="mkt-wrap grid w-full gap-5 pt-[88px] max-lg:grid-rows-none lg:grid-cols-[1fr_1.08fr] lg:items-center lg:gap-x-14 lg:gap-y-6 lg:pt-14 motion-reduce:pt-0 lg:motion-reduce:pt-0">
          <div className="lg:col-start-1 lg:row-start-1 lg:self-end">
            <h2 id="how-h" className="t-h2 max-w-[520px] text-m-ink max-sm:!text-[length:min(8.4vw,32px)]">{title}</h2>
            {sub && <p className="mt-3 hidden max-w-[460px] text-[16px] leading-relaxed text-m-muted lg:block">{sub}</p>}
          </div>

          <div className="relative mx-auto h-[min(38svh,290px)] w-full max-w-[560px] overflow-hidden rounded-[28px] bg-gradient-to-br from-m-tint to-m-tint2/70 shadow-[inset_0_0_0_1px_rgba(11,15,46,.05)] motion-reduce:h-auto motion-reduce:space-y-4 motion-reduce:overflow-visible motion-reduce:bg-none motion-reduce:shadow-none lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:h-[min(58svh,470px)] lg:max-w-none lg:motion-reduce:h-auto">
            {art.map((node, i) => (
              <Layer key={i} a={act[i]}>
                <div className="h-[184px] w-[300px] shrink-0 scale-[1.08] overflow-hidden rounded-[14px] bg-m-tint shadow-[var(--shadow-float)] sm:scale-[1.28] lg:scale-[1.62] motion-reduce:!scale-100">{node}</div>
              </Layer>
            ))}
          </div>

          <div className="lg:col-start-1 lg:row-start-2 lg:self-start">
            <div aria-hidden className="flex gap-2 motion-reduce:hidden">{[0, 1, 2].map((i) => <Segment key={i} p={p} i={i} />)}</div>
            <ol className="mt-4 grid lg:mt-6 lg:block lg:space-y-5 motion-reduce:mt-6 motion-reduce:block motion-reduce:space-y-5">
              {steps.map(([t, b], i) => (
                <motion.li key={t} style={{ "--a": act[i] } as unknown as CSSProperties}
                  className="flex gap-4 max-lg:[grid-area:1/1] max-lg:opacity-[var(--a)] lg:opacity-[calc(.3+.7*var(--a))] motion-reduce:!opacity-100">
                  <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-m-accent text-[14px] font-medium text-m-ink">{i + 1}</span>
                  <div>
                    <h3 className="text-[20px] font-medium leading-tight tracking-[-.025em] text-m-ink lg:text-[24px]">{t}</h3>
                    <p className="mt-1.5 max-w-[440px] text-[15px] leading-relaxed text-m-muted lg:text-[16px]">{b}</p>
                  </div>
                </motion.li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </section>
  );
}
