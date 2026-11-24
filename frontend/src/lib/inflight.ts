/**
 * One request for several identical readers. When two parts of a screen ask for the same GET at the same moment (the top bar and the page both want the locations), only one request goes to the
 * server and both get its answer. This is NOT a cache: nothing is kept once the request ends, so no one ever sees an old answer, and a write (POST/PUT/PATCH/DELETE) drops everything in flight on
 * the way in AND on the way out, so a refetch after a change is always a fresh request. Callers that pass an abort signal are never joined (aborting one must not cancel the others).
 * Pure (no imports) so it is unit-tested with `node --test` (frontend/tests).
 */
export type Shared = { status: number; text: string; failed: boolean };

const flying = new Map<string, Promise<Shared>>();

/** Run `send` once per `key` while it is in flight; later identical callers get the same promise. */
export function shareGet(key: string, send: () => Promise<Shared>): Promise<Shared> {
  const hit = flying.get(key);
  if (hit) return hit;
  const p = send().finally(() => { if (flying.get(key) === p) flying.delete(key); });
  flying.set(key, p);
  return p;
}

/** A write is starting or has finished: nothing in flight may answer a read that comes after it. */
export function forgetInFlight(): void { flying.clear(); }

export const inFlightCount = () => flying.size;
