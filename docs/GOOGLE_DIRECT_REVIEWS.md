# Direct Google reviews: feasibility, requirements, status

**Status (2026-11-03): direct submission to Google is NOT available to FlowQR and is NOT implemented.** The supported route (copy to clipboard,
open Google's direct Write-a-review page, the customer pastes and posts) is what ships. The code has a provider seam so a direct route can be added
if Google ever grants one. Nothing here claims otherwise, and nothing simulates a submission.

## What was researched

| Question | Finding | Source |
|---|---|---|
| How does Birdeye's "Direct Google Reviews" work? | A Birdeye-hosted pop-up ("Reviews powered by Google") opens on the page the customer is on; once submitted the review is "auto-posted on Google". Birdeye says it uses "a private Google API" through a Google partnership. The API is not named, no eligibility rules are published, and it is "enabled by default" for Birdeye customers. On Safari the customer gets a Google "Sign In" prompt even when already signed in, so the customer's own Google account is evidently involved. Reviews from Safari or Chrome incognito are not tracked. | Birdeye announcement (dated 2018), Birdeye support article (March 2026), Birdeye Safari troubleshooting article, Birdeye partnership page (vendor claims, "certified Google partner"; not independently verifiable) |
| Can the public Business Profile API create a review? | **No.** The v4 Reviews resource has exactly four methods: `list`, `get`, `updateReply`, `deleteReply`. Reviews are written by users on Google; merchants can only read and reply. The FAQ describes it as "get reviews and reply to reviews". | developers.google.com/my-business reference, FAQ |
| Can FlowHQ get Business Profile API access? | **Yes, for the documented read/reply API**, not for review creation. APIs are "not open to the public": request via the *Application for Basic API Access* form; granted per Google Cloud project; reviewed within 14 days; requires a verified, active Business Profile for 60+ days and a website for the business; approval shows as 300 QPM quota (0 = not approved). | developers.google.com/my-business prerequisites + FAQ |
| Is there a documented partner program for writing reviews? | **None found.** Neither the API docs, FAQ nor prerequisites mention partners, a partner programme or writing reviews. Birdeye's "private API" is, by its own description, private. | Same pages; absence verified on the pages read |
| What does Google's content policy say about asking for reviews? | Allowed: soliciting reviews of a genuine experience, without incentives and without trying to influence rating or content. Prohibited: incentives, discouraging negative reviews or selectively soliciting positive ones (gating), asking that "specific content be included", fake engagement, multiple accounts, unusual volumes or patterns. The page says nothing about AI text or pre-filled templates by name. | support.google.com/contributionpolicy (Maps UGC policy) |

## Feasibility verdict

* **Public, self-serve route to direct submission: none.** There is nothing to apply for through the documented Business Profile API.
* **Possible only through a Google-side arrangement that is not publicly documented** (what Birdeye describes). FlowHQ cannot assume it exists for a company of its size, has no way to start it other than asking Google, and must not guess at the API. Treat it as a business-development question for Google, not an engineering task.
* **We will not** use undocumented endpoints, scraping, reverse-engineered Maps calls, browser automation, or simulated submissions. A customer's review must be submitted by Google's own authenticated flow with that customer's consent.

## What FlowHQ can actually do next (in order)

1. **Apply for Basic API Access** (documented, 14-day review). Needs: a verified Business Profile active 60+ days with a website, a Google Cloud project, a finished OAuth consent screen. This unlocks read/reply features and location data (including the place id that lets us always use the direct Write-a-review link). It does **not** unlock review creation.
2. **Ask Google directly** (the same GBP API contact form / support channel, in writing): "Is there a supported way for an approved integration to let a signed-in customer submit a Google review from our page, as some review platforms do? What are the eligibility criteria, terms and API?" Record the answer. If the answer is no, this feature is closed.
3. **Only if Google offers a route:** implement it in `services/review_submit/google_direct.py` (below), against the documented API, then verify end to end.
4. **Until then keep the supported handoff** and keep improving it (direct link, clipboard, restore on return).

## Architecture already in place (inert until approval)

```
services/review_submit/
  base.py          SubmitRequest / SubmitResult / SubmitUnavailable / ReviewSubmitProvider protocol
  handoff.py       the supported route (mode "handoff"): FlowQR submits nothing
  google_direct.py placeholder (mode "direct"): implemented = False, available() is always False, submit() refuses
  __init__.py      provider_for(location): direct only if a real approved provider says it is available, else handoff
```

* `GET /public/reviews/{id}` returns `submission.mode` (`handoff` today). The page shows **Copy & Continue to Google** for `handoff`.
* `POST /public/reviews/{id}/submit` answers **409 `direct_unavailable`** while only the handoff provider exists, and stores nothing.
* **A configuration flag alone cannot enable it**: `GOOGLE_DIRECT_SUBMISSION=approved` is ignored until `GoogleDirectProvider.implemented` is `True`,
  which must be changed in the same commit as a real implementation. A test asserts this.
* When a provider is registered, the endpoint, not the provider, enforces: **explicit consent for the exact text** (`consent: true`, recorded
  through the confirmation event), **the customer's own final wording** (passed through unchanged), **equal access** (the rating is accepted as given;
  1-5 stars take the identical path), **no double posting** (a second tap returns the first result), and **honest outcomes** (`published` only when the
  provider returns Google's confirmation reference; `pending`/`rejected`/`failed`/a provider error all fall back to the handoff route with the review kept,
  and are counted as `review_submit_failed`, never as success). Analytics `direct_submitted` counts only Google-confirmed reviews and is 0 today.
* The page's direct branch (consent checkbox, Submit review button, success only on `published: true`, fallback to the handoff otherwise) is exercised in
  browser tests against a **mocked** server capability. Those tests prove the page's rules; they are not evidence that Google submission works.
* A guard test fails the build if browser-automation libraries or a Google "create review" call ever appear in the application code.

## Definition of done for the day an approved route exists

Do **not** announce or enable the feature until all of these are true:
1. Written confirmation from Google (or published documentation) of the route, its terms, quotas and per-customer sign-in requirements.
2. `GoogleDirectProvider` implemented against that documented API (`implemented = True`), with its own tests.
3. An **actual test review published on a real Google listing** through FlowQR by a real signed-in Google account, with the Google review id recorded, visible on Maps, and then deleted by its author.
4. Verified on Chrome (Android, desktop), Safari (iOS) and an in-app browser, including the sign-in step.
5. `GOOGLE_DIRECT_SUBMISSION=approved` set per environment, with the rollout limited to a pilot first.

## Policy risk to review (applies to the handoff route too)

Google's policy forbids asking that "specific content be included" and soliciting content that "does not represent a genuine experience". FlowQR's
AI suggestion is built to stay inside that line: the pre-filled starter says only who the review is about (no experience, no opinion), stars and topics
are the customer's own choices, the rewrite uses only what they picked or typed, the draft is clearly labelled as an AI suggestion, they can edit or delete
everything, and every rating (including 1 star) gets the same path with no gating. It is still an area where a business supplying ready-made text could be
read as steering content. Recommended before wide rollout: have counsel read the policy, and consider an owner setting to switch suggestions off per
business (the page works without them). This is not legal advice.

## Sources

* Birdeye: birdeye.com/updates/birdeye-partners-with-google-enables-direct-google-reviews; support.birdeye.com articles 12653049 (Direct Google Reviews), 12653686 (Safari), 13768301 (Google review access change); birdeye.com/blog/birdeye-google-partnership-integrations
* Google Business Profile API: developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews; /my-business/content/faq; /my-business/content/prereqs
* Google Maps content policy: support.google.com/contributionpolicy/answer/7400114
