"use client";
import { Download, Image as ImageIcon, Printer, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { apiFile, errorMessage, saveBlob } from "@/lib/api";

type Choice = "pdf-ref" | "pdf-a6" | "pdf-a5" | "pdf-a4" | "png-1" | "png-2" | "png-3" | "svg";

const CHOICES: { id: Choice; label: string; hint: string }[] = [
  { id: "pdf-ref", label: "Print-ready PDF", hint: "Approved poster size, 89 × 126 mm. The code is vector and stays sharp." },
  { id: "pdf-a6", label: "PDF · A6", hint: "105 × 148 mm" },
  { id: "pdf-a5", label: "PDF · A5", hint: "148 × 210 mm" },
  { id: "pdf-a4", label: "PDF · A4", hint: "210 × 297 mm, for a wall poster" },
  { id: "png-1", label: "PNG", hint: "1055 × 1491 px, for screens and WhatsApp" },
  { id: "png-2", label: "PNG · high resolution", hint: "2110 × 2982 px" },
  { id: "png-3", label: "PNG · print resolution", hint: "3165 × 4473 px" },
  { id: "svg", label: "SVG", hint: "Editable vector file" },
];

/** What most people need: print at the approved size, print on a normal A4 sheet, or send a picture on WhatsApp. The rest sit under "More formats". */
const MAIN: Choice[] = ["pdf-ref", "pdf-a4", "png-1"];

/**
 * The approved FlowQR review poster with this code in it, in every print format. The design is the same for every business and campaign;
 * only the QR code differs. The server checks that the finished file decodes to exactly the right address before it will send it.
 * `path` is the endpoint without its extension, e.g. `/cards/<id>/poster`.
 */
export function PosterDownload({ path, filename, label = "Download poster", variant = "secondary", size = "sm" }: {
  path: string; filename: string; label?: string; variant?: "primary" | "secondary" | "ghost"; size?: "sm" | "md";
}) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<Choice>("pdf-ref");
  const [preview, setPreview] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [notForPrint, setNotForPrint] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState<{ file: File; url: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    let url: string | null = null;
    let cancelled = false;
    setPreview(null); setProblem(null);
    apiFile(`${path}.png`)
      .then(({ blob, headers }) => { if (cancelled) return; url = URL.createObjectURL(blob); setPreview(url); setNotForPrint(!!headers.get("x-flowqr-not-for-print")); })
      .catch((e) => { if (!cancelled) setProblem(errorMessage(e)); });
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [open, path]);

  useEffect(() => { setReady((r) => { if (r) URL.revokeObjectURL(r.url); return null; }); }, [choice, open]);

  async function download() {
    setBusy(true); setProblem(null);
    const [kind, opt] = choice.split("-");
    const q = kind === "png" ? `?scale=${opt}` : kind === "pdf" ? `?size=${opt}` : "";
    try {
      const { blob, headers } = await apiFile(`${path}.${kind}${q}`);
      setNotForPrint(!!headers.get("x-flowqr-not-for-print"));
      saveBlob(blob, `${filename}-poster${kind === "pdf" ? `-${opt}` : kind === "png" && opt !== "1" ? `-${opt}x` : ""}.${kind}`);
    } catch (e) { setProblem(errorMessage(e)); } finally { setBusy(false); }
  }

  /**
   * Phones cannot print a downloaded file directly, and they only allow a share sheet or a new tab straight from a tap (not after waiting for a file). So it takes two taps: the first
   * prepares the file, the second hands it to the phone's own share sheet (Print, AirPrint, a nearby printer, WhatsApp) or, where that is not supported, opens it in a new tab where Print is one tap away.
   */
  async function printOrShare() {
    setProblem(null);
    if (ready) {
      if (typeof navigator !== "undefined" && navigator.canShare?.({ files: [ready.file] })) { try { await navigator.share({ files: [ready.file], title: "FlowQR poster" }); return; } catch (e) { if ((e as Error).name === "AbortError") return; } }
      if (!window.open(ready.url, "_blank")) saveBlob(ready.file, ready.file.name);  // pop-up blocked: fall back to a normal download
      return;
    }
    setBusy(true);
    const [kind, opt] = choice.split("-");
    const q = kind === "png" ? `?scale=${opt}` : kind === "pdf" ? `?size=${opt}` : "";
    try {
      const { blob, headers } = await apiFile(`${path}.${kind}${q}`);
      setNotForPrint(!!headers.get("x-flowqr-not-for-print"));
      const name = `${filename}-poster${kind === "pdf" ? `-${opt}` : ""}.${kind}`;
      const file = new File([blob], name, { type: blob.type || (kind === "pdf" ? "application/pdf" : "image/png") });
      setReady({ file, url: URL.createObjectURL(file) });
    } catch (e) { setProblem(errorMessage(e)); } finally { setBusy(false); }
  }
  const row = (c: (typeof CHOICES)[number]) => (
    <label key={c.id} className={`flex min-h-11 cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-sm ${choice === c.id ? "border-brand-600 bg-brand-50" : "border-ink-200 hover:bg-ink-50"}`}>
      <input type="radio" name="poster-format" value={c.id} checked={choice === c.id} onChange={() => setChoice(c.id)} className="mt-1" />
      <span className="min-w-0"><span className="font-medium">{c.label}</span><span className="block text-[13px] text-ink-500">{c.hint}</span></span>
    </label>
  );
  const main = CHOICES.filter((c) => MAIN.includes(c.id)), more = CHOICES.filter((c) => !MAIN.includes(c.id));

  return (
    <>
      <Button size={size === "sm" ? "sm" : undefined} variant={variant} icon={<ImageIcon className="h-4 w-4" />} onClick={() => setOpen(true)}>{label}</Button>
      {open && (
        <Modal open onClose={() => setOpen(false)} title="Download the FlowQR poster"
          footer={<><Button variant="secondary" onClick={() => setOpen(false)} className="max-sm:order-3 max-sm:flex-1">Close</Button><Button variant="secondary" loading={busy} icon={<Download className="h-4 w-4" />} onClick={() => void download()} className="max-sm:order-2 max-sm:flex-1">Download</Button><Button loading={busy} icon={<Printer className="h-4 w-4" />} onClick={() => void printOrShare()} className="max-sm:order-1 max-sm:w-full">{ready ? (typeof navigator !== "undefined" && navigator.canShare?.({ files: [ready.file] }) ? "Share or print file" : "Open file to print") : "Print or share"}</Button></>}>
          <div className="grid gap-4 sm:grid-cols-[200px_1fr] sm:gap-5">
            <div className="mx-auto w-full max-w-[104px] sm:max-w-none">
              {preview ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={preview} alt="Preview of the FlowQR review poster with this code" className="w-full rounded-lg border border-ink-100 shadow-sm" data-testid="poster-preview" />
                : problem ? null : <Skeleton className="aspect-[1055/1491] w-full" />}
            </div>
            <div className="min-w-0 space-y-3">
              <p className="text-sm text-ink-700">Only the QR code is yours; it always opens the same permanent link. To print from a phone, tap <b>Print or share</b>.</p>
              {problem && <Alert tone="error">{problem}</Alert>}
              {notForPrint && <p role="alert" className="flex gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />This file uses a test address (not your permanent web address), so it must not be printed. Set the public card address first.</p>}
              <fieldset>
                <legend className="mb-1 text-sm font-semibold">Format</legend>
                <div className="grid gap-1.5" role="radiogroup" aria-label="Poster format">
                  {main.map(row)}
                  <details className="group" open={more.some((c) => c.id === choice)}><summary className="flex min-h-11 cursor-pointer items-center rounded-lg px-3 text-sm font-medium text-accent-ink hover:bg-ink-50">More formats</summary><div className="mt-1.5 grid gap-1.5">{more.map(row)}</div></details>
                </div>
              </fieldset>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
