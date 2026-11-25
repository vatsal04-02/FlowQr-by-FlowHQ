# AI Business Operator: audit of what already exists (2026-11-25)

Base audited: `6e9371b` (what runs in production: backend `prod-6e9371b`, alembic 0068). Read-only audit; nothing was changed or deployed. The brief asks for one central AI brain. Most of its plumbing already exists and is tested; this document says what, so the new work extends it instead of duplicating it.

## 1. The brief against what is built

| Brief part | Already built | Where | Gap |
|---|---|---|---|
| Business context (P3) | Business Brain (verified facts vs assumptions), Google profile snapshots, reviews, posts, media, rank, analytics | `agent/knowledge.py`, `agent/snapshots.py`, `ai/intelligence.py`, `growth_score.py` | No single `get_business_context()` that hands one bundle to a caller |
| Autonomous audit (P4) | 6-hourly `autonomy_scan`: description, categories, services, hours, special hours, attributes, service area, phone, website, with evidence and `google_changed` detection | `agent/seo_engine.py`, `agent/v2/*` | Reviews, posts and media gaps are not part of the same scan result |
| Change generation (P5) | Drafted BEFORE/AFTER with reason, risk, expected outcome for every V2 field | `agent/v2/present.py`, `overview.py` | Description is drafted on a separate older path (`/agent/profile/{gid}/suggest-description`) |
| Universal change preview (P6) | `agent_actions` + `agent_action_approvals` + hash-chained history: id, tenant, location, field, before, after, reason, risk, status, timestamps, verification. This IS the proposal table | `models/autonomy.py`, `agent/executor.py` | Posts, replies and campaigns use their own tables (`ReplyDraft`, posts, studio) and are not in the same list |
| Statuses (P6) | DETECTED..VERIFIED all mapped (see LOCAL_SEO_ENGINE_V2_IMPLEMENTATION.md section 2) | `executor.py` | None needed |
| Autonomy levels (P7) | Policy levels 1 to 3 per action type, owner consent per location, daily limits, failure suspension, platform emergency stop | `agent/autonomy_policy.py`, `consent.py`, `controls.py` | Matches the brief; keep |
| Approved execution (P7, P12) | propose, validate, dry run, claim, write, independent read-back, notice, audit; idempotent, advisory locks, retry with backoff, `recover_stuck` | `executor.py` | None for fields; see Google gate below |
| Tool layer (P11) | Per-field `field_ops`; the WhatsApp assistant has a strict one-JSON-object tool protocol | `agent/v2/field_ops.py`, `whatsapp/agent.py` | **No central tool registry or orchestrator for the owner side.** `LLMProvider` only has `generate(system, user)`; there is no native function calling |
| Control panel (P10) | `AI > Today / Tasks / Approvals / Activity / Automations / Studio`, `SEO > Fix your profile` | `app/(app)/ai/*`, `OptimizationCenter.tsx` | **No "ask the AI" surface**, and the pending work is spread over four screens |
| Reviews, posts, Marketing Studio (P8) | Reply drafts with risk checks and template auto-replies, daily posts, Google Marketing Studio | `ai/replies.py`, `auto_reply.py`, `agent/posts.py`, `marketing_studio.py` | Not in the unified list |
| Model config (P14) | One provider factory: gemini, openrouter, openai_compat; metering, hard cap, privacy gate, kill switch | `ai/base.py`, `ai_usage.py`, `ai/privacy.py` | Production runs OpenRouter `openai/gpt-4o-mini`, capped at USD 0.05. No Responses API client |

## 2. Why "Apply" does nothing for most fixes (Part 1)

The most important finding. It is policy, not a broken handler:

1. `SEO_V2_CUSTOMER_WRITES_ENABLED` is **false** in production. For every V2 field (categories, services, regular and special hours, attributes, service area) the action is stored as `recommended`, an approval click answers 409, and the screen shows only **Dismiss**. The panel says so at the top: "FlowQR shows you these fixes; it does not make them yet." The gate exists because Google's rules on automated profile changes are not confirmed in writing.
2. The gate opens for a profile an operator names in `SEO_V2_TEST_LOCATION_NAMES`. FlowHQ's own profile (`locations/6589197820321114990`) is the safe place to prove live writes. Nothing has been written live yet.
3. In `OptimizationCenter.tsx` the per-area chip (`x.fix.label`, e.g. "Edit it in Google Business Profile") is a plain `<span>`. It looks like a button and does nothing when clicked.
4. The description and contact path (`/gbp/info`, "Approve & publish to Google") is separate, works, and is not behind the V2 gate.

## 3. Broken or dead navigation found

Method: every `href`, `push`, `replace`, `link`, `cta_href` target in the frontend and in backend responses was compared with the 128 real pages and the 59 configured redirects.

| Finding | Where | Effect |
|---|---|---|
| `/help` has no page and no redirect | `components/billing/PricingExperience.tsx:163`, `lib/nav.ts:118` | A visible help entry leads to a 404 |
| Area chips look clickable but are not | `OptimizationCenter.tsx` `AreaList` | Click does nothing |
| `Recommended` cards offer only Dismiss while the gate is closed | `OptimizationCenter.tsx` | The owner cannot act on a drafted fix and is told to do it in Google, with no link there |
| `/gbp/locations?connected=` and `?error=` redirect to `/settings/connections/google` | `gbp/locations/page.tsx:28` | Intentional OAuth return handling; it looks like "redirected back" after a connect |

Not found: dead `/subscription`, `/google`, `/gbp/rank`, `/settings/ai` links. They are covered by the legacy redirect table. The two `/_enquiry` and `/{css_name}` hits belong to generated customer websites, not the app.

**Not reproduced:** the "Change Information" button that sends the user back. No control with that label exists in the code. The closest are "Edit info & hours" (`/gbp/info`, working) and the area chips above. I need the screen where it appears to pin it down.

## 4. What the build should be (extend, never duplicate)

1. **Operator service** `services/operator/`: a registry of typed tools that wrap the existing services (get context, audit, propose via `executor.propose`, list pending, approve and execute via `executor`, draft reply, draft post, performance). No tool touches the database or Google directly. Every tool re-checks tenant, role, location access, plan and the existing gate.
2. **Model access** through the existing `get_provider()` with a structured one-JSON-object plan per turn (the WhatsApp assistant's proven protocol), not a second provider layer. Model, key and cap stay environment configuration.
3. **One list of pending work** `GET /operator/pending` that unions `agent_actions`, reply drafts and post drafts, with category filters. No new proposal table.
4. **`FlowQR AI Business Operator`** screen: ask, see real states from the backend (running, prepared, waiting, executed, verified, failed), approve or reject through the existing endpoints.
5. **Fix the dead ends**: `/help`; make area chips and recommended cards open the exact prepared change or say plainly why it cannot be applied.
6. **Live proof** on FlowHQ's own profile only, with the gate opened for that one location, before any wider claim.

## 5. Decisions needed from the owner

1. Open the V2 write gate for the FlowHQ test profile only (`SEO_V2_TEST_LOCATION_NAMES`)? Customers stay read-only.
2. Keep the current provider (OpenRouter `gpt-4o-mini`, USD 0.05 cap) for the build, with the model name staying a setting? The brief's model and Responses API are not available through the current provider layer.
3. Which screen shows "Change Information"?
