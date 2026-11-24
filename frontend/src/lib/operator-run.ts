import { api } from "./api";
import type { Op } from "./operator";

/** Run an operation and the one that follows it (a reply is approved, then published). A step that fails stops the chain; the error text is the server's. */
export async function runOperation(op: Op, body?: Record<string, unknown>): Promise<unknown> {
  if (!op.available || !op.method || !op.path) throw new Error(op.reason ?? "This is not available.");
  const r = await api<unknown>(op.path, { method: op.method, body: { ...op.body, ...(body ?? {}) } });
  return op.then ? runOperation(op.then) : r;
}
