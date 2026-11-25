# FlowQr AI Business Operator: architecture

Built on top of what exists (see `AI_OPERATOR_AUDIT.md`). **No new table, no migration, no new AI provider.** Code: `backend/app/services/operator/`, `backend/app/api/v1/operator.py`, `frontend/src/components/operator/`, `app/(app)/ai/changes`, `app/(app)/ai/operator`.

```
Owner ─ AI Operator screen ──► POST /operator/ask ──► orchestrator (loop, max 6 turns)
        Pending changes  ◄──── GET /operator/pending      │  one JSON object per turn, validated
        Fix your profile ──► POST /operator/prepare       ▼
                                                    tool registry (7 tools, typed, role-checked)
                                                          │ read tools            │ prepare tools
                                                          ▼                       ▼
                                         context, audit, pending list     seo_engine / v2 scan / reply + post drafts
                                                                                  │  creates a PROPOSAL (agent_action / draft)
                                                                                  ▼
Owner approves ─► existing endpoints ─► executor (policy, consent, gate, claim, write, read-back, history, notice)
```

## What is new and what is reused

| Piece | New | Reuses |
|---|---|---|
| Pending-work list (`pending.py`) | one read-only view | `agent_actions`, `reply_drafts`, `scheduled_posts` (incl. Marketing Studio), `agent_tasks`; each item keeps its own approve/reject endpoint |
| Prepare on demand (`prepare.py`) | the click that drafts a change | `seo_engine.scan_location`, `v2.scan.scan_location_v2` |
| Edit / regenerate (`changes.py`) | retire the old proposal, propose the new one | `executor.propose/cancel/decide`, `ai.description.draft_description` |
| Business context (`context.py`) | one bundle, facts vs unknowns | Business Brain, snapshots, reviews, posts, past decisions |
| Tool registry (`tools.py`) | schemas, validation, role check | the services above and the existing reply/post draft handlers |
| Orchestrator (`orchestrator.py`) | the loop and `Planner` interface | `get_provider()`, `metered()` (usage cap), `parse_json` |

## The guarantees, and where they are enforced

* **The AI cannot approve, publish or write to Google.** No such tool exists (`test_the_registry_has_no_tool_that_approves_publishes_or_writes`). Approval is the owner's click on the existing endpoint; the executor re-checks everything.
* **Unknown tool, extra arguments, bad enum, too-low role: refused before anything runs** (`run_tool`).
* **Tenant isolation**: a location id from the model is looked up inside the caller's own business and location scope; the database's row-level security applies as for any request.
* **The screen shows the stored proposal**, read from the database, never the model's description of it (`test_the_final_answer_never_becomes_the_change`).
* **Facts only**: `business_context` separates `verified_facts` and `google_profile` from `unknown`; the system prompt forbids inventing; the executor's own evidence validation still refuses an unverified service, category or claim.
* **Prompt injection**: review text is data, redacted (phones, e-mails, links) and withheld when the AI data policy says so; the registry has nothing to be tricked into (`test_instructions_hidden_in_a_review...`).
* **Cost**: every turn runs through `metered()`, so the platform hard limit and per-business budget apply. Production is capped at USD 0.05.
* **Bounded**: 6 turns, 600-character requests, 20 asks an hour, 12 prepares an hour.
* **Honest status**: `executed` plus `verified_at` is the only thing the screen calls "applied".

## Model independence and the tool-calling investigation

The loop talks to a `Planner` (`next_step(request, history) -> Turn`). `JsonPlanner` needs only `provider.generate(system, user)`, so **any provider in `get_provider()` works** (Gemini, OpenRouter, any OpenAI-compatible endpoint, a future OpenAI/Responses client). It asks for one JSON object per turn, validated by Pydantic, with one repair attempt. This is the protocol the WhatsApp assistant already uses.

**Does OpenRouter `openai/gpt-4o-mini` support native tool calling?** The question was investigated with a live request, but **could not be answered live**: the production OpenRouter key returned `401 API key expired` when tested on 2026-11-25. OpenRouter documents `tools`/`tool_choice` for OpenAI models, so native calling is very likely supported, but that is documentation, not a result. It was **not wired**: a native `chat()` would have to go through the metered wrapper (the cap), which today meters only `generate()`. Adding a native `Planner` later is one new class plus a metered `chat`; the registry, tools and screens do not change.

To switch model: change `AI_PROVIDER` / `OPENROUTER_MODEL` (or the OpenAI-compatible settings). Nothing in the operator names a model.

## Files changed outside the operator package

`app/main.py` (router), `app/api/v1/seo.py` (checklist rows now link to the prepared change), `frontend` `OptimizationCenter.tsx`, `ProfileOptimizer.tsx`, `PricingExperience.tsx`, `lib/nav.ts`, `tests/route_access_manifest.txt` (six reviewed routes).
