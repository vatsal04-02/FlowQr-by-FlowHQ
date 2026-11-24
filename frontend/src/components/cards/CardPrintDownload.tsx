"use client";
import { CreditCard, Download, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { apiFile, errorMessage, saveBlob } from "@/lib/api";

/** The physical card is a standard bank-card blank (CR80 / ID-1) printed lengthwise: 54 mm wide, 85.6 mm tall. */
export const CARD_SIZE_NOTE = "85.6 × 54 mm (CR80), portrait";

/**
 * The review card as a print file for the physical NFC/QR card: bank-card size, turned lengthwise, 600 dpi, with this card's own code
 * and serial. `path` is the endpoint without its extension, e.g. `/admin/cards/<id>/cr80`. The server checks that the finished file
 * decodes to exactly the right address before it will send it.
 */
export function CardPrintDownload({ path, filename, label = "Card file", variant = "ghost", size = "sm" }: {
  path: string; filename: string; label?: string; variant?: "primary" | "secondary" | "ghost"; size?: "sm" | "md";
}) {
  const [open, setOpen] = useState(false);
  const [fmt, setFmt] = useState<"pdf" | "png">("pdf");
  const [bleed, setBleed] = useState<"0" | "3">("0");
  const [preview, setPreview] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [notForPrint, setNotForPrint] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let url: string | null = null;
    let cancelled = false;
    setPreview(null); setProblem(null);
    apiFile(`${path}.png?bleed=0`)
      .then(({ blob, headers }) => { if (cancelled) return; url = URL.createObjectURL(blob); setPreview(url); setNotForPrint(!!headers.get("x-flowqr-not-for-print")); })
      .catch((e) => { if (!cancelled) setProblem(errorMessage(e)); });
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [open, path]);

  async function download() {
    setBusy(true); setProblem(null);
    try {
      const { blob, headers } = await apiFile(`${path}.${fmt}?bleed=${bleed}`);
      setNotForPrint(!!headers.get("x-flowqr-not-for-print"));
      saveBlob(blob, `${filename}-cr80${bleed === "3" ? "-bleed" : ""}.${fmt}`);
    } catch (e) { setProblem(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <Button size={size === "sm" ? "sm" : undefined} variant={variant} icon={<CreditCard className="h-4 w-4" />} onClick={() => setOpen(true)}>{label}</Button>
      {open && (
        <Modal open onClose={() => setOpen(false)} title="Print file for the physical card"
          footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Close</Button><Button loading={busy} icon={<Download className="h-4 w-4" />} onClick={() => void download()}>Download</Button></>}>
          <div className="grid gap-5 sm:grid-cols-[170px_1fr]">
            <div>
              {preview ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={preview} alt="Preview of the review card, turned lengthwise, with this code" className="w-full rounded-lg border border-ink-100 shadow-sm" data-testid="card-preview" />
                : problem ? null : <Skeleton className="aspect-[1275/2022] w-full" />}
            </div>
            <div className="min-w-0 space-y-3">
              <p className="text-sm text-ink-700">Bank-card size, {CARD_SIZE_NOTE}, with the design running lengthwise. The code is enlarged to 31 mm so a phone reads it quickly, and it always opens the same permanent link.</p>
              {problem && <Alert tone="error">{problem}</Alert>}
              {notForPrint && <p role="alert" className="flex gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />This file uses a test address (not the permanent web address), so it must not be printed.</p>}
              <div className="space-y-2">
                <p className="text-sm font-semibold">File</p>
                <Segmented label="File type" value={fmt} onChange={setFmt} options={[["pdf", "PDF (for the printer)"], ["png", "PNG (600 dpi)"]] as const} />
                <p className="pt-1 text-sm font-semibold">Bleed</p>
                <Segmented label="Bleed" value={bleed} onChange={setBleed} options={[["0", "None (exact size)"], ["3", "3 mm bleed"]] as const} />
                <p className="text-[13px] text-ink-500">{bleed === "3" ? "59.98 × 91.60 mm: the artwork runs 3 mm past the cut line, which printers who die-cut the card ask for." : "53.98 × 85.60 mm: the finished card, no extra margin."}</p>
              </div>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
