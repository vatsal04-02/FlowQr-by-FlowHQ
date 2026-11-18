"use client";
import { ChevronLeft } from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { TrialHeadline, TrialPitch } from "@/components/marketing/TrialHeadline";
import { Logo, LogoMark } from "./Brand";

/**
 * Sign-in and sign-up frame, adapted from the "Travel Connect" card: one rounded card on a soft gradient, a still dot map (no lines) on the left, the form on the right.
 * What changed for FlowQR: the FlowQR mark and wordmark instead of the arrow and "Travel Connect"; the brand's orange instead of blue and indigo; FlowQR's real pitch (and the "what happens
 * next" steps on sign-up) instead of travel copy; the card grows with the form (sign-up is longer than log-in); and the sign-in controls come from each page (its own validation, server errors
 * and the real Google button), not from this frame. Phones show the form only, with the logo above it. Reduced motion: the card simply appears.
 */
export function AuthPage({ title, subtitle, children, footer, pitch, points, mobileNote }: {
  title: string; subtitle?: string; children: ReactNode; footer?: ReactNode;
  pitch?: { title: ReactNode; body: string };
  /** A short numbered list under the pitch (what happens next). */ points?: ReactNode[];
  /** One line shown above the title on phones, where the map panel is hidden. */ mobileNote?: ReactNode;
}) {
  useEffect(() => { try { sessionStorage.removeItem("fq-splash"); } catch { /* private mode */ } }, []);   // the next sign-in replays the full start-up screen
  return (
    <MotionConfig reducedMotion="user">
      <div className="mkt relative flex min-h-dvh w-full flex-col items-center justify-center bg-gradient-to-br from-m-tint via-m-bg to-m-tint2 px-3 py-6 sm:p-6">
        <Link href="/" className="absolute left-3 top-3 z-10 inline-flex min-h-11 items-center gap-1 rounded-full px-3 text-[14px] font-medium text-m-muted transition-colors hover:bg-white/70 hover:text-m-ink sm:left-6 sm:top-5">
          <ChevronLeft className="h-4 w-4" aria-hidden />Home
        </Link>
        <motion.div initial={{ opacity: 0, scale: 0.97, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.2, 0.7, 0.2, 1] }}
          className="mt-10 flex w-full max-w-4xl overflow-hidden rounded-3xl bg-white shadow-[0_30px_70px_-30px_rgba(11,15,46,.35),0_2px_6px_rgba(11,15,46,.06)] sm:mt-6">
          {/* Left: dot map, logo and the real pitch */}
          <div className="relative hidden w-1/2 min-h-[600px] self-stretch overflow-hidden border-r border-m-line md:block">
            <div className="absolute inset-0 bg-gradient-to-br from-m-tint to-m-tint2">
              <DotMap />
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-end p-8 pb-10 text-center">
                <motion.div initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5, duration: 0.5 }} className="mb-5">
                  <span className="grid h-14 w-14 place-items-center rounded-2xl bg-[#FE6A05] shadow-lg shadow-orange-300/60"><LogoMark size={30} variant="onAccent" /></span>
                </motion.div>
                <motion.p initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.6, duration: 0.5 }} className="mb-3 font-bold lowercase tracking-[-.04em] text-[#11173F]" style={{ fontSize: 30 }}>
                  flow<span className="text-[#FE6A05]">qr</span>
                </motion.p>
                <motion.h2 initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.7, duration: 0.5 }} className="max-w-[17rem] text-[22px] font-semibold leading-[1.15] tracking-[-.02em] text-m-ink [text-wrap:balance]">
                  {pitch?.title ?? <TrialHeadline />}
                </motion.h2>
                <motion.p initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.8, duration: 0.5 }} className="mt-3 max-w-[18rem] text-[14px] leading-relaxed text-m-ink/80">
                  {pitch ? pitch.body : <TrialPitch />}
                </motion.p>
                {points && points.length > 0 && (
                  <motion.ol initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.9, duration: 0.5 }} className="mt-5 max-w-[18rem] space-y-2.5 text-left">
                    {points.map((p, i) => (
                      <li key={i} className="flex items-start gap-2.5 text-[13px] leading-snug text-m-ink">
                        <span aria-hidden className="mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[#FE6A05] text-[11px] font-semibold text-white">{i + 1}</span><span>{p}</span>
                      </li>
                    ))}
                  </motion.ol>
                )}
              </div>
            </div>
          </div>

          {/* Right: the page's own form */}
          <div className="flex w-full flex-col justify-center bg-white p-6 sm:p-8 md:w-1/2 md:p-10">
            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}>
              <div className="mb-6 md:hidden"><Logo tagline={false} /></div>
              {mobileNote && <p className="mb-4 inline-flex rounded-full bg-m-tint px-3.5 py-1.5 text-[13px] font-medium text-m-ink md:hidden">{mobileNote}</p>}
              <h1 className="text-[26px] font-bold leading-tight tracking-[-.02em] text-m-ink md:text-[30px]">{title}</h1>
              {subtitle && <p className="mb-7 mt-1.5 text-[15px] text-m-muted">{subtitle}</p>}
              <div className={subtitle ? "" : "mt-6"}>{children}</div>
              {footer && <div className="mt-7 text-center text-[15px] text-m-muted">{footer}</div>}
            </motion.div>
          </div>
        </motion.div>
        <p className="mt-5 max-w-md px-4 text-center text-[12.5px] text-m-muted">FlowQR is a product of FlowHQ and is not affiliated with or endorsed by Google.</p>
      </div>
    </MotionConfig>
  );
}

// ------------------------------------------------------------------------------------------------ the animated dot map (decorative)
/** The map lives in the top part of the panel (`mapH`), above the text, so it never sits behind the wordmark. Decorative: it shows no data. */
function DotMap() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const canvas = canvasRef.current, box = canvas?.parentElement;
    if (!canvas || !box) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect, dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
      canvas.getContext("2d")?.setTransform(dpr, 0, 0, dpr, 0, 0);
      setSize({ width, height });
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const { width, height } = size;
    const canvas = canvasRef.current, ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || !width || !height) return;

    // A grid of dots, kept where a rough world map would be (the continents are boxes, as in the original design), with a fixed seed so it does not shimmer on every resize.
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const mapH = Math.min(height * 0.48, 300);
    const dots: { x: number; y: number; o: number }[] = [];
    const gap = 12;
    for (let x = 0; x < width; x += gap) for (let y = 0; y < mapH; y += gap) {
      const fx = x / width, fy = y / mapH;
      const land =
        (fx < 0.25 && fx > 0.05 && fy < 0.4 && fy > 0.1) || (fx < 0.25 && fx > 0.15 && fy < 0.8 && fy > 0.4) || (fx < 0.45 && fx > 0.3 && fy < 0.35 && fy > 0.15) ||
        (fx < 0.5 && fx > 0.35 && fy < 0.65 && fy > 0.35) || (fx < 0.7 && fx > 0.45 && fy < 0.5 && fy > 0.1) || (fx < 0.8 && fx > 0.65 && fy < 0.8 && fy > 0.6);
      if (land && rnd() > 0.3) dots.push({ x, y, o: rnd() * 0.5 + 0.2 });
    }

    // A still picture of dots, drawn once (and again when the panel is resized).
    ctx.clearRect(0, 0, width, height);
    for (const d of dots) { ctx.beginPath(); ctx.arc(d.x, d.y, 1, 0, Math.PI * 2); ctx.fillStyle = `rgba(201,76,0,${d.o})`; ctx.fill(); }
  }, [size]);

  return <div className="absolute inset-0 overflow-hidden" aria-hidden><canvas ref={canvasRef} className="absolute inset-0 h-full w-full" /></div>;
}
