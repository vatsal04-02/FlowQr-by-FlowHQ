"""AI regression guards. Two kinds of silent quality loss are caught here:

1. PROMPTS. The text sent to the model for a fixed set of cases is hashed and compared with tests/ai_baselines/prompt_hashes.json. Any edit to a prompt, the playbooks,
   the language guidance or the business-context block changes a hash and fails this test. That is deliberate: the change must be justified by re-running the benchmark
   (python -m app.cli ai-eval ...), comparing it with the committed baseline, and only then accepting the new hashes with UPDATE_AI_SNAPSHOTS=1.
2. SCORING. tests/ai_baselines/<model>.current.json holds real outputs of the production prompts, recorded from a live benchmark run. They are rescored with the current
   validators and metric code, and each task's averages must stay at or above the recorded floor. A change that weakens a validator or the metric fails here.

Neither guard calls a model. Neither replaces the live benchmark and a human's review: they make sure nobody can change the machinery without noticing."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.ai_eval import dataset, metrics
from app.ai_eval.dataset import intel_for, kb_for
from app.models import Review, Tenant
from app.services.agent import posts as posts_svc
from app.services.ai import description, replies

BASE = Path(__file__).parent / "ai_baselines"
HASHES = BASE / "prompt_hashes.json"


def _tenant(biz):
    b = dataset.BUSINESSES[biz]
    return Tenant(name=b["name"], category=b["category"], language=b["language"], brand_tone=b["voice"], ai_instructions=None)


def canonical_prompts() -> dict[str, str]:
    out = {}
    for cid in ("reply-physio-2", "reply-dental-1", "reply-coaching-1", "reply-salon-3"):
        c = next(x for x in dataset.ALL_CASES if x.id == cid)
        rv = Review(rating=c.data["rating"], text=c.data["text"], reviewer_name=c.data.get("reviewer"))
        out[cid] = replies.SYSTEM + "\n=====\n" + replies.build_prompt(rv, _tenant(c.biz), None, kb_for(c.biz), tone=None, lang=c.lang, recent=["Aapka shukriya."], intel=intel_for(c.biz))
    for cid, ptype in (("post-physio-1", "educational"), ("post-dental-2", "offer"), ("post-coaching-1", "educational"), ("post-restaurant-2", "update"), ("post-gym-2", "faq")):
        c = next(x for x in dataset.ALL_CASES if x.id == cid)
        p, _ = posts_svc.build_prompt(_tenant(c.biz), kb_for(c.biz), lang=c.lang, post_type=ptype, topic=None, avoid=c.data.get("recent"), terms="Search terms: a, b",
                                      intel=intel_for(c.biz, c.data.get("recent")))
        out[cid] = posts_svc.SYSTEM + "\n=====\n" + p
    for cid in ("desc-physio", "desc-coaching"):
        c = next(x for x in dataset.ALL_CASES if x.id == cid)
        intel = intel_for(c.biz)
        intel["profile"]["description"] = c.data["current"]
        out[cid] = description.SYSTEM + "\n=====\n" + description.build_prompt(_tenant(c.biz), kb_for(c.biz), intel, None, c.lang)
    return out


def _hashes() -> dict[str, str]:
    return {k: hashlib.sha256(v.encode("utf-8")).hexdigest()[:16] for k, v in canonical_prompts().items()}


def test_prompts_have_not_changed_without_a_benchmark():
    now = _hashes()
    if os.environ.get("UPDATE_AI_SNAPSHOTS") == "1":
        HASHES.write_text(json.dumps(now, indent=1, sort_keys=True), encoding="utf-8")
        pytest.skip("prompt hashes rewritten")
    old = json.loads(HASHES.read_text(encoding="utf-8"))
    changed = sorted(k for k in now if now[k] != old.get(k))
    assert not changed, (f"The prompts for {changed} changed. Re-run the benchmark (python -m app.cli ai-eval --variants current ...), compare it with "
                         f"docs/ai-eval/RESULTS.md, and only if quality held or improved accept the change with UPDATE_AI_SNAPSHOTS=1 pytest tests/test_ai_regression.py")


def test_canonical_prompts_cover_every_language_and_task():
    p = canonical_prompts()
    assert len(p) == 11 and any("Devanagari" in v for v in p.values()) and any("Roman letters" in v or "WhatsApp" in v for v in p.values())


def _baselines():
    return sorted(BASE.glob("*.current.json"))


@pytest.mark.parametrize("path", _baselines() or [pytest.param(None, marks=pytest.mark.skip(reason="no recorded baseline"))])
def test_recorded_real_outputs_still_score_at_or_above_their_floor(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = {c.id: c for c in dataset.ALL_CASES}
    by_task: dict[str, list[dict]] = {}
    for row in data["outputs"]:
        by_task.setdefault(row["task"], []).append(row)
    for task, rows in by_task.items():
        batch = [r["text"] for r in rows]
        scored = [metrics.score(cases[r["case"]], r["text"], batch=batch) for r in rows]
        comp = sum(m["composite"] for m in scored) / len(scored)
        clean = sum(1 for m in scored if m["clean"]) / len(scored)
        floor = data["floors"][task]
        assert comp >= floor["composite"], f"{task}: composite {comp:.3f} fell below the recorded floor {floor['composite']}"
        assert clean >= floor["clean_rate"], f"{task}: clean rate {clean:.2f} fell below the recorded floor {floor['clean_rate']}"
        assert sum(m["unsupported_claims"] for m in scored) <= floor["max_unsupported_claims"], f"{task}: more unsupported claims than recorded"


def test_the_metric_still_ranks_the_old_prompts_below_the_new_ones_on_recorded_outputs():
    """A sanity check on the scoring itself: on real outputs from the same model, the upgraded prompts must not score below the old ones."""
    f = BASE / "gemini-3.5-flash-lite.legacy.json"
    if not f.exists():
        pytest.skip("no legacy baseline recorded")
    cases = {c.id: c for c in dataset.ALL_CASES}
    def mean(path):
        data = json.loads(path.read_text(encoding="utf-8"))
        out = {}
        for task in ("reply", "post", "description"):
            rows = [r for r in data["outputs"] if r["task"] == task]
            batch = [r["text"] for r in rows]
            out[task] = sum(metrics.score(cases[r["case"]], r["text"], batch=batch)["composite"] for r in rows) / len(rows)
        return out
    old, new = mean(f), mean(BASE / "gemini-3.5-flash-lite.current.json")
    for task in old:
        assert new[task] >= old[task] - 0.005, (task, old[task], new[task])
