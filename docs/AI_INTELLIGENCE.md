# AI intelligence: how FlowQR's AI works, how it is measured, and what it still cannot do

Written 2026-11-15. Everything below is in the repository; "measured" means executed here with the real model, "not measured" means exactly that.

## 1. What was audited (before)

| Area | Finding |
|---|---|
| Prompts | One generic system prompt per task (reply, post, description). No per-business-kind guidance, no language style guidance. |
| Business context | Only what the owner typed into the Business brain. Real reviews, past posts, the live Google profile, photos, performance and the place were never given to the model. |
| Output control | One retry, only on safety violations (invented prices, health claims, patient confirmation). Nothing checked whether text was generic, ignored the review, repeated a recent post or was in the wrong language. |
| Variety | Posts rotated one of five topics by day-of-year; replies had no memory of previous replies. |
| Descriptions | The prompt never stated the language: a Hindi or Hinglish business received an English description (4 of 7 benchmark cases). |
| Structured output | Plain text only; no way to get several distinct post concepts in one call. |
| Measurement | None. No benchmark, no acceptance metric, nothing that fails if quality drops. |

## 2. What was built

**Business Intelligence layer** (`services/ai/intelligence.py`, `GET /agent/intelligence`). One tenant-isolated picture per business, built through the caller's row-level-security session: the Business brain (services, offers, FAQs, voice, approved/prohibited claims, audience), the live Google profile as last read (categories, description, hours, services), photo counts by category, recent posts and their types, recent replies, performance (28 days vs the 28 before), Google's search terms, the city and the season. From the business's real reviews it counts recurring themes (praise vs concerns) with word lists that include Hinglish spellings. Review text itself is **never** placed in other prompts: only theme counts, so a hostile review cannot smuggle instructions into another task. If something is not known it is absent, and `missing_questions` lists what to ask the owner (audience, voice, FAQs, hours, city...). A new owner-facing field, "Who are your best customers?", feeds it.

**Task-specific craft** (`services/ai/craft.py`). Playbooks for seven kinds of business (physiotherapy, dental, salon, restaurant, gym, retail, coaching) plus a default: what customers care about, post angles that work, what to stay away from. Language style guides for English, Hindi (simple spoken Devanagari) and Hinglish (WhatsApp-style Roman script). Eight post types, each with its own structure; the next type avoids what was just posted and skips types the business has no facts for (no offer post without a verified offer, no FAQ post without an FAQ). A general festival/season calendar by month (windows only: lunar dates move, so no exact dates are claimed). Reply guidance by sentiment: complaint, mixed, praise-with-a-concern, praise.

**Generators** rebuilt on those pieces: replies (`services/ai/replies.py`), posts (`services/agent/posts.py`, including `POST /posts/ideas`: three genuinely different concepts in one call, each with a real photo to take and the business reason; unsafe, repeated or duplicate concepts are dropped), profile descriptions (`services/ai/description.py`). Each makes **one** model call; a second call happens only when the first draft has a clear problem, and quality problems after the retry only lower the draft's score: they never block a safe draft. Safety problems twice in a row still refuse the draft.

**Quality validators** (`services/ai/quality.py`): stock phrases (English and Hinglish), ignores-the-review, repeats a recent reply/post or its opening, wrong language or script, keyword stuffing, hashtags/emoji, promotional wording in a reply to a critical review, missing acknowledgement in a complaint, invented numbers in customer review drafts. Used at generation time, in the benchmark and in regression tests.

**Optimizer** (`services/agent/optimizer.py`): every check now carries the six parts an owner needs: current state, problem, recommendation, reason, supporting evidence (what was read from Google and when) and a preview of the proposed change. Deterministic, so identical every time. No reason claims a ranking effect.

**Agent opportunities** (`services/agent/plan.py`): posts that say the same thing (measured overlap and type repetition) and a fall in customer actions of 20% or more. The performance task is explicitly "a comparison, not a diagnosis": it lists only profile conditions that are actually visible (no recent post, no recent photo, no hours, marked closed), never claims a cause, and says FlowQR will not claim any change in ranking.

**AI Output Acceptance Rate** (`services/ai/outcomes.py`, `GET /agent/ai-quality`, `GET /admin/ai-quality`, AI › Usage & limits). Per kind of output (review replies, Google Posts, profile descriptions, customer review drafts): generated, decided, kept as is, acceptance rate, median edit ratio, rejected, regenerated and why. *Accepted* = approved with at most 25% of the words changed. A rate is shown only after something has been decided (never "0%" for nothing). Original text is stored only for owner-facing content (`ai_outputs`, row-level security); customer review drafts are measured from the existing `review_drafts` rows and the customer's text is never copied. Recording can never block the owner's action (tested).

## 3. How quality is evaluated

`python -m app.cli ai-eval` runs the **production** generation functions (and, for comparison, the pre-upgrade ones kept in `app/ai_eval/legacy.py`) on a benchmark of invented businesses: 7 kinds x (4 review replies, 2 posts, 1 description, 1 customer review draft), English, Hindi and Hinglish, each business with a complaint and praise. Scoring is deterministic (no second model judging): factual accuracy (safety violations plus numbers and names the context never contained), compliance, relevance (replies pick up review details; posts and descriptions name real services), naturalness (stock phrases), repetition within the batch, language/script, brand voice (emoji rules), local relevance, helpfulness (the right move for the sentiment). It also records latency, tokens, calls per output and cost per output and per "clean" output. A CSV rating sheet is written for a human reviewer, and `ai-eval-human` correlates their scores with the automatic ones.

Regression guards (`backend/tests/test_ai_regression.py`): prompt hashes for 11 canonical cases (any prompt, playbook or context change fails until the benchmark is re-run and the change accepted deliberately), and recorded real model outputs that must keep scoring at or above their recorded floor with the current validators.

## 4. Measured results (summary; full tables in [ai-eval/RESULTS.md](ai-eval/RESULTS.md))

On the configured model (`gemini-3.5-flash-lite`), same cases, old prompts vs new: profile descriptions went from 14% to 100% "clean" because the old prompt ignored the business's language (4 of 7 Hindi/Hinglish businesses got English); replies went from 82% to 96-100% clean with less repetition; posts became clearly more varied (repetition score 0.80 to 0.94, helpfulness 0.71 to 0.93). Reply *relevance* did not improve on the metric. The cost per output rose 37-82% (about $0.0004-0.0006 each) because prompts carry more real context; latency is 1.1-1.4 s p50. `gemini-3.1-flash-lite` is cheaper but slower and wrote 2 of 7 descriptions in the wrong language; no model change is recommended. `gemini-3.5-flash` and `gemini-3.8-flash` could not be benchmarked: this key's daily quota ran out. Differences of 10-15 points at these sample sizes are within run-to-run noise, the metric was corrected once after reading real outputs (documented), and **no human has rated the outputs yet**.

## 5. Limitations (what is still not true)

- The benchmark's metrics are proxies. They catch invented facts, boilerplate, wrong language and templating; they cannot tell good writing from adequate writing. **No human has rated these outputs yet.** The rating sheet exists for that; until it is filled in, "better" means "fewer measurable failures", not "owners prefer it".
- The AI Output Acceptance Rate starts at zero decisions. It needs real owners approving real drafts before it means anything; there is no number to report yet.
- The customer review assistant supports English and Hindi only; Hinglish customer drafts are not supported there (replies, posts and descriptions do support Hinglish).
- Keyword research uses Google's own search-term report for the profile. There is no third-party keyword database.
- Photo recommendations are based on photo categories and ages, not on what is in the images.
- Review themes come from word lists, not understanding; a theme count is a prompt to look, not a finding.
- Local-festival coverage is general (month windows). Regional festivals and local events are not known.
- Gemini model comparison covers four models on 49 benchmark cases per variant: enough to see large differences, too small to rank models that are close.
