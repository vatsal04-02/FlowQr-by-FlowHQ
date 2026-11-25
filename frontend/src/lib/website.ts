/** Shapes and pure helpers for the owner's AI website screens (backend/app/api/v1/website.py). Nothing here invents progress: every status is the server's. */
export type StepStatus = "waiting" | "running" | "done" | "skipped" | "failed";
export interface Step { key: string; label: string; detail: string; status: StepStatus; note: string | null }
export interface Job { id: string; status: "queued" | "running" | "completed" | "failed"; stage: string; steps: Step[]; notes: string[]; error: string | null; trigger: string }
export interface Field { key: string; label: string; kind: string; max?: number; max_items?: number; fields?: Field[] }
export interface SiteSection { id: string; type: string; label: string; enabled: boolean; data: Record<string, unknown> }
export interface SiteInfo { status: string; template: string; template_label: string; accent: string; version: number; address: string; sections: SiteSection[] }
export interface WebsiteState {
  enabled: boolean; business?: { name: string; category: string | null }; interest?: string | null; website_url?: string | null; google?: { connected: boolean; title: string | null };
  job?: Job | null; site?: SiteInfo | null; publish?: { available: boolean; reason: string | null; url: string | null }; templates?: { key: string; label: string }[]; accents?: Record<string, string>; section_types?: Record<string, Field[]>;
}

export type Phase = "start" | "building" | "failed" | "review";
export function phaseOf(s: WebsiteState): Phase {
  if (s.job && (s.job.status === "queued" || s.job.status === "running")) return "building";
  if (s.job?.status === "failed" && !s.site) return "failed";
  return s.site ? "review" : "start";
}

export function progress(steps: Step[]): { finished: number; total: number; current: Step | null } {
  const finished = steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  return { finished, total: steps.length, current: steps.find((s) => s.status === "running") ?? null };
}

export const STEP_WORD: Record<StepStatus, string> = { waiting: "Waiting", running: "In progress", done: "Completed", skipped: "Skipped", failed: "Failed" };

/** The key that tells the preview to fetch again: only when the server has finished more work or saved a new draft. */
export const previewKey = (s: WebsiteState): string => `${s.site?.version ?? 0}:${s.job ? progress(s.job.steps).finished : 0}`;

export const DEVICES = { desktop: 1280, tablet: 820, phone: 390 } as const;
export type Device = keyof typeof DEVICES;

export const editableFields = (fields: Field[]): Field[] => fields.filter((f) => ["text", "textarea", "strings", "list"].includes(f.kind));
export const emptyItem = (fields: Field[]): Record<string, unknown> => Object.fromEntries(fields.map((f) => [f.key, f.kind === "asset" ? null : f.kind === "list" ? [] : ""]));
