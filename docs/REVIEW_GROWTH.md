# Review Growth: QR campaigns + AI review drafts

Self-serve digital QR codes that open a branded page where a customer types a few words about their visit, gets an AI-organised
draft built only from those words (or writes it themselves), edits and confirms it, then continues to Google and posts it themselves.

Separate from the physical **cards** module (platform-issued NFC/QR inventory). Both share the short card domain, the QR
renderer, the AI provider, rate limiting and the Google review link stored on `locations`.

## Customer flow: one screen, one tap
`/r/{public_id}` is a single screen. The QR/campaign resolves tenant, business, location and category on its own.

1. **A starter review is already in the box when the page opens** (`GET /public/reviews/{id}/starter`). It is a *neutral opener built only from
   the business's own details* (name, kind, place, owner-listed services): "Sharing my feedback on Sunrise Physio, a physiotherapy clinic in
   Lucknow." It says nothing about a visit, a feeling or a result: a strict validator rejects any experience claim, praise, quality, outcome,
   number, rating, recommendation or unknown name. It is labelled **"AI suggestion · edit freely"** until the customer edits it or taps. A
   subtle skeleton shows while it is prepared. If AI is off or paused, the box is simply empty and they write their own review.
   *Cost control:* each business keeps a pool of 6 different openers per language (12 h, invalidated when the owner edits the context), so a busy
   QR code costs a handful of model calls, not one per scan; failures cool down for 60 s.
2. **Stars (1-5), above the topic chips.** They set the direction of the review (1-2 negative, 3 neutral/mixed, 4-5 positive) and never supply a reason.
3. **Stars + topics refine the draft automatically** (debounced; `POST /generate` the first time, then `POST /refine` in the same session, which
   neither opens another session nor uses up Regenerate). The customer's own words are the only "words" sent: AI-written text is never fed back as
   evidence. **Edits are never overwritten without permission**: if they edited the box, changing stars/topics asks "Update your review with your
   latest stars and topics?" (Update / Keep my text), a rewrite that arrives after they started typing is discarded, and *Undo* restores their text.
4. **Copy & Continue to Google**: one prominent button (a sticky bar on phones). It is a real link (`<a href target=_blank rel=noopener>`) to the
   business's **direct Write-a-review URL**; on the same tap the page copies the text (`navigator.clipboard` plus a synchronous `execCommand`
   fallback, started inside the gesture) while the browser opens Google natively, so popup blockers do not apply. No intermediate screen.
   Afterwards the page shows "Your review is copied. Paste it into Google's review box, then choose your own star rating and post it yourself."
   with *Copy again* and *Open Google again*. If copying is blocked it says so plainly and offers **Copy review** (which also selects the text so
   it can be copied by hand); it never claims it was copied. A visible **Copy review** button is always there.
5. **The review survives the trip**: the page keeps its state in memory and in `localStorage` (24 h, saved immediately at the tap and when the
   page is hidden), so coming back from Google, or a refresh, restores the text, stars, topics and the paste instruction.
6. **Tracking is one keepalive request** (`POST .../handoff`): confirms the customer's final wording, opens a session if they never used AI,
   counts the Google tap once, and records whether the browser reported a successful copy (`review_copied`, a yes/no, never the text).

**Direct submission** (no copy-paste, no Google page) is a separate question with a separate answer: see `docs/GOOGLE_DIRECT_REVIEWS.md`. In short: Google's public API cannot create reviews, no public partner route exists, so it is not available and not implemented; a provider seam (`services/review_submit`) keeps the route open and inert, and `POST .../submit` answers 409 today.

**What FlowQR cannot do, and does not pretend to:** Google offers no supported way to pre-fill or submit a customer's review. FlowQR never uses
browser automation, hidden submissions or unsupported APIs. The customer pastes and posts on Google themselves, and picks Google's own stars
there. "Continued to Google" is a tap, never a published review. Manual writing is always available (type in the box; AI off or ignored).

**The direct link.** `resolve_review_url` prefers the location's own link; if that is only a general Maps/Search *listing* (not `g.page/r/.../review`
or `search.google.com/local/writereview?placeid=...`) and the connected Business Profile gives a place id, the direct link is used instead.
Settings shows which kind each location has and warns when it is a general listing. The landing response includes `review_url` and
`review_url_kind` (public information; never gated by rating).

### Competitor patterns studied (Birdeye, Podium, Reviewflowz)
Public documentation is thin. What it supports: review requests are delivered by text, email or QR to a **direct review link** with few taps
("a couple of clicks", ~30 seconds); AI in these products drafts *owner replies* to existing reviews, not customer reviews; Reviewflowz exposes a
direct review link per profile; some "funnel" tools gate by star rating (send happy customers to Google, others to private feedback). Adopted: a
direct review link, the fewest steps, mobile-first layout, nothing to install or sign in to. **Not adopted, deliberately:** rating-gated routing
(every customer gets the same road to Google) and any claim of automatic posting. None of the three documents a clipboard hand-off, so that
part is designed here from first principles and tested in the browser.
## Business context (owner-configured; `services/review_suggestions.py`)
Categories: physio, dental, healthcare, restaurant, hotel, salon, auto service, retail, gym, coaching, plus a **generic** fallback.
`resolve_category` matches the tenant's free-text category; an owner override wins. Dashboard -> Review Growth -> Settings -> **Business
context**: business type (auto-detected, previewable), plain description (<=300), services/products (<=12), enable/disable each topic,
supported languages. Claims such as "best", guarantees, cures, "free", prices and links are rejected on save. The context tells the AI
what the business **offers**; it is never evidence of what a customer **experienced**. Other customers' reviews are never a source.
`GET/PUT /review-growth/context` (PUT is admin-only, audited as `review_context.update`; `?preview_category=` previews a category).

### When AI is unavailable (never a dead end)
| Situation | What the customer sees |
|---|---|
| Transient provider trouble (timeout, 5xx, short rate limit) | "We couldn't write that just now" + **Try again** (reuses the same session) + *I'll write it myself* |
| Draft failed the faithfulness checks (after up to `REVIEW_MAX_ATTEMPTS`) | "...without adding things you didn't say" + Try again / write it yourself |
| Provider known to be down (daily cap, no credits, bad key, model refused) or HTTP 403/429 | Their own words in the editor with a calm one-line note; the next visitors open straight on the plain editor |
| AI not configured / plan quota used | Page opens directly on the plain "Write your review" editor |

Customers never see provider names, status codes or keys. Owners see the real reason (dashboard banner, generator page,
`GET /review-growth/settings` -> `ai.degraded`, logs). The pause clears by itself after <=10 min, or immediately after a successful
*Test the AI model* run.

## Generation pipeline (`services/ai/review_generate.py`)
write (temp 0.5, worked examples in the prompt) -> deterministic checks -> AI fact-check (`REVIEW_VERIFY_WITH_AI`) -> on failure, retry
with an instruction ("only the customer's facts, no feelings/praise/results"), up to `REVIEW_MAX_ATTEMPTS` (default 3). The business
*type* is withheld from the prompt so the model can't guess the service.

Rejected: invented numbers/names/ratings/cures/guarantees/incentives; a **service** taken from the business type; **results**
("helped", "improved") and **feelings** ("frustrated", "uncomfortable") the customer didn't state; praise or a thank-you added to a
complaint or neutral remark; sentiment more positive than their words; untranslated Hindi in an English review; wrong script; padding
beyond what the words support; rewrites too similar to the last draft. The model may answer `NEEDS_MORE` instead of guessing.
(Rules cannot prove every sentence is semantically faithful; the customer always reviews and confirms.)

**Richer drafts without invention (v3).** Why drafts used to be one flat line: the prompt said "stop after the topics / no extra sentences",
topics carried only a label, every descriptive word was rejected as an invented quality, and a length cap of `max(160, 3 x the labels)`
chars (about 25 words) made anything fuller impossible. Now:
* **Structured prompt:** BUSINESS CONTEXT (name, location, owner description, offered services, category *wording*; labelled "never evidence of
  what this customer received"), GENERATION CONTROLS (language, style, **detail level** with soft word targets, rating tone, opening/structure
  variation), CUSTOMER CONTEXT (topics, what each topic is about, rating, typed words, Hindi topic names).
* **Topic meaning** (`review_suggestions.MEANING`): for every topic, what it is about and the plain *describing words* that merely restate
  "good / not good <topic>" ("clear", "easy to follow" for Explanations; "polite", "attentive" for Staff). Positive ratings may use them;
  negative ones only negated ("not explained clearly"); a 3-star review uses none. Nothing else is allowed: no events, results (recovery, pain
  relief, reduced symptoms), punctuality, specific dishes/products, reasons, feelings, recommendations, closing summaries.
* **Detail level (soft, never padded):** 1 topic ~15-30 words; 2-3 topics ~30-60; several topics plus the customer's own details ~50-90.
  The validator enforces only an upper bound (1.35 x the target). A draft that is honest but thin for 2+ topics gets one extra request to
  connect and expand; if it is still short it is kept as is.
* **Variation:** direction-aware opening and structure hints, a ban on generic openers ("I had a good experience", "I recently visited"), an
  over-used-adjective check, and "everything" repaired to "things" instead of paying for a retry.
* **Optional follow-up** (`follow_up` in the draft response): ONE short question, only for a single topic with no typed words, matched to the
  rating (a neutral "anything specific to add?" for 1-3 stars). Shown under the draft; never blocks Continue.
* **Hindi:** the prompt asks for idiomatic Hindi (not word-for-word) and passes Hindi topic names. Hindi guards remain thinner than English.
* **Rating-aware guards:** a draft cannot contradict the stars (praise on 1-2, a complaint on 4-5), and no reason ("because...") or event the
  customer did not state is accepted.

Picked topics are still topics, not claims. A draft that mentions none of the picked topics is rejected rather than shown.

Measured on the live provider (openai/gpt-4o-mini via OpenRouter, fact-check on; 45 chip-based requests over 6 business types):
93% accepted (the rest show "try again / write it yourself"), 2.47 model calls/request, ~2,370 input and ~26 output tokens/request,
**~$0.00027 per accepted draft**, rule-check rejection 36.7% of write attempts (retried or trimmed), fact-check rejection 2.3%, median
latency ~4 s. Hindi: roughly 80% accepted; grammatical but plainer, occasionally adds a mild "I am satisfied" line. Drafts built from
topics alone are deliberately plain ("I was happy with the staff and how things were explained."): the system will not invent detail.

Measured on the live provider *before* the depth work (same 45-request matrix): avg 14.6 words for 2-3 topics, 23.7 with details, 91% accepted.
After the main depth changes: **28.3 words for 2-3 topics, 39.8 with details, 98% accepted (44/45)**, 0 banned/invented terms, ~$0.00053 per
accepted draft (2.9 model calls/request, up from ~$0.00028 and 2.4), median 4.4 s. Several later rule/prompt refinements (rating-aware
guards, recommendation and reason blocks, direction-aware openings) were **not re-measured live**: the OpenRouter account ran out of credits
(HTTP 402) during the final run. Re-run `node e2e/review-depth-eval.js 3 <label>` (needs `playwright-core`, the local stack and throwaway `zz-ev-*` businesses to delete afterwards) after topping up. Most 2-3 topic drafts are still below the 30-word target: the
guards trade length for honesty.

## Data (migrations `0007`-`0010`; reversible; RLS on the four review tables)
`review_campaigns`, `review_sessions` (customer words under `customer_input.text`), `review_drafts`, `review_events`;
`ai_generation_logs` gained token, `model_calls`, `attempts`, `rejects_rules`, `rejects_factcheck` and `cost_usd` columns;
`tenants.review_context` (JSONB) holds the owner context; `review_events.suggestion_id` records chip selections; `review_events.rating` (0010,
1-5, CHECK-constrained) records the stars on `feedback_submitted`. No name/phone/email is stored. Answers and drafts are deleted after
`REVIEW_SESSION_RETENTION_DAYS` (Celery `flowqr.purge_review_sessions`); events hold no text and are kept.

## API
Tenant (member to read, admin to write; owner to permanently delete):
`GET/POST /review-growth/campaigns`, `GET/PATCH/DELETE /review-growth/campaigns/{id}` (DELETE archives; `?permanent=true` erases an
archived one), `POST .../regenerate-qr`, `GET .../qr.png|svg`, `POST /review-growth/locations/{id}/review-url`,
`GET /review-growth/analytics`, `GET/PUT /review-growth/context`, `GET /review-growth/settings`, `POST /review-growth/ai/test` (admin: one real generation + checks).

Public (no auth; rate limited; automated clients get 403 on anything that creates a session or calls the model): GET /public/reviews/{public_id}/starter, POST .../refine, POST .../handoff (the one tap), plus:
`GET /public/reviews/{public_id}`, `POST .../generate` (`{text, suggestions: [topic ids], rating: 1-5 (required when mode is "ai"), language, mode: "ai"|"manual"}`; the older three-field body is still
accepted), `.../regenerate`, `.../approve`, `.../redirect`. Responses carry `ai_status` (ok | manual | needs_more | rejected |
unavailable) and `retryable`.

## Analytics
Funnel (distinct customers): **Page opened -> Started a review -> Confirmed their review -> Continued to Google**. Separately, "How
customers write": AI help asked, drafts generated, rewrites, asked for more detail, failed checks, wrote it themselves.
"Continued to Google" is a **tap**, never reported as a published review. Each chip pick records `suggestion_selected` ("Topics
customers choose"); an **AI cost and quality** panel shows accepted drafts, cost per accepted draft, model calls/request, retries,
rule-check and fact-check rejection rates, tokens and latency. **Ratings given on your review page**: the 1-5 distribution, average and
count (`ratings` in the analytics response), labelled as chosen on the FlowQr page and **not** the Google rating (that is under Reviews).

## Config (all optional)
`AI_PROVIDER` (`gemini` | `openrouter`), `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `AI_TIMEOUT_SECONDS`,
`REVIEW_MAX_ATTEMPTS=3`, `REVIEW_VERIFY_WITH_AI=true`, `REVIEW_SESSION_RETENTION_DAYS=90`, `REVIEW_MAX_DRAFTS_PER_SESSION=5`,
`RL_REVIEW_GENERATE_PER_10MIN=20` (generous: a waiting-room Wi-Fi puts many customers behind one IP).
OpenRouter **free** accounts are capped at 50 free-model requests per day and each draft costs two calls; use a paid model for real
traffic. `AI_PROVIDER=openai_compat` talks to any OpenAI-compatible chat-completions server (Groq, Mistral, Cerebras, Gemini's OpenAI endpoint...) with
`OPENAI_COMPAT_BASE_URL` (up to `/v1`; `/chat/completions` is appended), `OPENAI_COMPAT_API_KEY`, `OPENAI_COMPAT_MODEL` and an optional
`OPENAI_COMPAT_NAME` label. Server-side key only. Free tiers suit development and tests; for real customers use a paid plan (limits, model
availability and data terms change), and re-run `e2e/review-depth-eval.js` for any new model because the guards are tuned on gpt-4o-mini.
**Gemini** (`AI_PROVIDER=gemini`, `GEMINI_API_KEY`): default model is now `gemini-3.5-flash` (`gemini-2.5-flash` is closed to new keys) with
`GEMINI_THINKING_LEVEL=minimal` (Gemini 3 models otherwise spend `maxOutputTokens` on hidden thinking and return empty drafts; set it empty
for a model that rejects the field). 429s are split into per-minute (one short retry, then `rate_limited`) and per-day (`quota_exhausted`,
which pauses AI and tells the owner). Observed free-tier reality: **20 requests/day per full-size flash model**, and the lite models run out
within a few dozen calls. A draft costs 2-3 calls, so the free tier is for manual smoke tests, not for evaluation or customers.
New providers: implement `LLMProvider` in `services/ai/base.py`.

## Production routing
`deploy/Caddyfile`: `/r/*` is routed on the card domain next to `/c/*`.
