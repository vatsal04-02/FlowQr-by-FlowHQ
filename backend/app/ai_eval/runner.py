"""Run the benchmark: the PRODUCTION generation functions (or the legacy ones) on every case, with a given model, measuring latency, tokens, calls and
the deterministic quality metrics. Writes nothing to any database and sends only the invented benchmark text to the provider."""
from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.ai_eval import legacy
from app.ai_eval.dataset import Case, by_task, intel_for, kb_for
from app.ai_eval.metrics import WEIGHTS, score
from app.core.config import settings
from app.models import Review, Tenant
from app.services.ai.base import AIUnavailable

VARIANTS = ("legacy", "current")
TASKS = ("reply", "post", "description", "review_draft")


class Throttle:
    """One shared pace for every call in a run, so a benchmark does not trip the key's requests-per-minute limit (a failed call would count against the model, unfairly)."""

    def __init__(self, rpm: float):
        import threading
        self.gap, self.lock, self.next = 60.0 / rpm if rpm else 0.0, threading.Lock(), 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
        if at > now:
            time.sleep(at - now)


class PacedProvider:
    """Wraps a provider: paces calls and waits out a rate limit (up to 5 times) instead of failing. Daily-quota exhaustion is NOT retried."""

    def __init__(self, inner, throttle: Throttle):
        self._in, self._t = inner, throttle
        self.name, self.model = inner.name, inner.model

    @property
    def usage(self):
        return self._in.usage

    busy_ms = 0

    def generate(self, system, user, **kw):
        for attempt in range(6):
            self._t.wait()
            t0 = time.monotonic()
            try:
                out = self._in.generate(system, user, **kw)
                self.busy_ms += int((time.monotonic() - t0) * 1000)
                return out
            except AIUnavailable as exc:
                self.busy_ms += int((time.monotonic() - t0) * 1000)
                if exc.code != "rate_limited" or attempt == 5:
                    raise
                time.sleep(min(60, (exc.retry_after or 20) + 2 * attempt))


def make_provider(model: str, *, thinking: str | None = "minimal", timeout: int = 60):
    from app.services.ai.gemini import GeminiProvider
    if not settings.gemini_api_key:
        raise AIUnavailable("GEMINI_API_KEY is not set", code="not_configured")
    return GeminiProvider(api_key=settings.gemini_api_key, model=model, timeout=timeout, thinking_level=thinking or None)


def _tenant(case: Case) -> Tenant:
    b = case.business
    return Tenant(name=b["name"], category=b["category"], language=b["language"], brand_tone=b["voice"], ai_instructions=None)


def generate(variant: str, provider, case: Case) -> str:
    """One output from one variant. Raises AIUnavailable when the product would have refused or failed (that counts against the variant)."""
    tenant, kb, b = _tenant(case), kb_for(case.biz), case.business
    terms = "Search terms people used to find this profile (reported by Google): " + ", ".join(s.split(" and ")[0] for s in b["services"][:3])
    if case.task == "reply":
        d = case.data
        review = Review(rating=d["rating"], text=d["text"], reviewer_name=d.get("reviewer") or None)
        if variant == "legacy":
            return legacy.reply(provider, review, tenant, kb, case.lang)
        from app.services.ai.replies import draft_reply
        return draft_reply(provider, review, tenant, None, kb=kb, language=case.lang, intel=intel_for(case.biz))[0]
    if case.task == "post":
        recent = case.data.get("recent") or []
        if variant == "legacy":
            return legacy.post(provider, tenant, kb, case.lang, recent, terms)
        from app.services.agent import posts as posts_svc
        return posts_svc.draft_post(provider, tenant, kb, language=case.lang, avoid=recent, terms=terms, intel=intel_for(case.biz, recent), post_type=case.data.get("type"))[0]
    if case.task == "description":
        if variant == "legacy":
            return legacy.description(provider, tenant, kb, terms)
        from app.services.ai.description import draft_description
        intel = intel_for(case.biz)
        intel["profile"]["description"] = case.data.get("current", "")
        return draft_description(provider, tenant, kb, intel, terms_line=terms, language=case.lang)[0]
    from app.services.ai.review_generate import ReviewInput, generate_review
    d = case.data
    inp = ReviewInput(note=d["note"], topics=tuple(d.get("topics", ())), rating=d.get("rating"))
    return generate_review(provider, inp, language=case.lang, style="natural", business_name=b["name"], category=b["category"], verify=False)  # same for both variants: not changed by the upgrade


def run(models: list[str], variants: list[str], tasks: list[str], *, limit: int | None = None, workers: int = 3, thinking: str | None = "minimal", biz: str | None = None, rpm: float = 0) -> dict:
    results: dict = {"started": datetime.now(timezone.utc).isoformat(), "runs": []}
    cases = [c for t in tasks for c in by_task(t, biz)]
    if limit:
        cases = cases[:limit]
    for model in models:
        for variant in variants:
            if variant == "legacy" and "review_draft" in tasks and not any(c.task != "review_draft" for c in cases):
                continue
            throttle = Throttle(rpm)
            provider_factory = lambda: PacedProvider(make_provider(model, thinking=thinking), throttle)  # noqa: E731 - one provider per case keeps the token accounting per-case

            def one(case: Case, variant=variant, model=model):
                if case.task == "review_draft" and variant == "legacy":
                    return None  # the review assistant was not changed: only measured once, under "current"
                prov = provider_factory()
                t0 = time.monotonic()
                try:
                    text, err = generate(variant, prov, case), None
                except AIUnavailable as exc:
                    text, err = "", f"{exc.code}: {exc}"[:200]
                except Exception as exc:  # noqa: BLE001
                    text, err = "", f"{type(exc).__name__}: {str(exc)[:160]}"
                u = prov.usage
                return {"case": case.id, "task": case.task, "biz": case.biz, "lang": case.lang, "text": text, "error": err, "latency_ms": getattr(prov, "busy_ms", None) or int((time.monotonic() - t0) * 1000),
                        "calls": u["calls"], "tokens_in": u["prompt_tokens"], "tokens_out": u["completion_tokens"]}

            with ThreadPoolExecutor(max_workers=workers) as ex:
                rows = [r for r in ex.map(one, cases) if r is not None]
            by_case = {c.id: c for c in cases}
            for task in tasks:
                batch = [r["text"] for r in rows if r["task"] == task and r["text"]]
                for r in rows:
                    if r["task"] == task:
                        r["metrics"] = score(by_case[r["case"]], r["text"], batch=batch) if r["text"] else None
            results["runs"].append({"model": model, "variant": variant, "rows": rows})
    results["finished"] = datetime.now(timezone.utc).isoformat()
    return results


def summarise(run_: dict, prices: dict[str, tuple[float, float]] | None = None) -> dict:
    """Per (model, variant, task): means of every metric, failure rate (the product refused or errored), latency, tokens, calls and cost per output / per clean output."""
    out = []
    for r in run_["runs"]:
        for task in TASKS:
            rows = [x for x in r["rows"] if x["task"] == task]
            if not rows:
                continue
            ok = [x for x in rows if x["metrics"]]
            mean = lambda k: round(statistics.mean([x["metrics"][k] for x in ok if x["metrics"].get(k) is not None]), 3) if any(x["metrics"].get(k) is not None for x in ok) else None  # noqa: E731
            lat = sorted(x["latency_ms"] for x in rows)
            tin, tout = sum(x["tokens_in"] for x in rows), sum(x["tokens_out"] for x in rows)
            price = (prices or {}).get(r["model"])
            cost = (tin * price[0] + tout * price[1]) / 1e6 if price else None
            clean = sum(1 for x in ok if x["metrics"]["clean"])
            out.append({"model": r["model"], "variant": r["variant"], "task": task, "n": len(rows), "failed": len(rows) - len(ok), "clean": clean,
                        "clean_rate": round(clean / len(rows), 3), **{k: mean(k) for k in list(WEIGHTS) + ["local", "quality_score", "composite"]},
                        "unsupported_claims_per_output": round(sum(x["metrics"]["unsupported_claims"] for x in ok) / max(1, len(ok)), 2),
                        "latency_p50_ms": lat[len(lat) // 2], "latency_p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))],
                        "calls_per_output": round(sum(x["calls"] for x in rows) / len(rows), 2), "tokens_in_per_output": round(tin / len(rows)), "tokens_out_per_output": round(tout / len(rows)),
                        "cost_usd_total": round(cost, 5) if cost is not None else None,
                        "cost_per_output_usd": round(cost / len(rows), 6) if cost is not None else None,
                        "cost_per_clean_output_usd": round(cost / clean, 6) if cost is not None and clean else None})
    return {"rows": out}


def rescore(run_: dict) -> dict:
    """Recompute every metric from the stored outputs with the CURRENT metric code (no model call). Used to compare old and new outputs under one metric version."""
    from app.ai_eval.dataset import ALL_CASES
    cases = {c.id: c for c in ALL_CASES}
    for r in run_["runs"]:
        for task in TASKS:
            batch = [x["text"] for x in r["rows"] if x["task"] == task and x["text"]]
            for x in r["rows"]:
                if x["task"] == task:
                    x["metrics"] = score(cases[x["case"]], x["text"], batch=batch) if x["text"] else None
    return run_


def save(run_: dict, summary: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "run": run_}, f, ensure_ascii=False, indent=1)
