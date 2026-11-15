# Controlled customer pilot: plan and checklists

**Status: prepared, not started.** The pilot may begin only after the gates in section 1 are true. Nothing in this file has been run with a real customer.

**Rule that governs everything below:** *no real customer is connected to autonomous or even approved Google writes until the live Google write validation (`docs/LIVE_VALIDATION_RUNBOOK.md`) has passed on an authorised test profile.* That validation is **BLOCKED** today (no test profile has been named). So the pilot has two stages, and stage B does not exist until the runbook's evidence log is filled in.

## 1. Entry gates (all must be true before the first pilot customer)

| Gate | Today |
|---|---|
| Production-like environment exists and has passed `docs/STAGING_DEPLOYMENT.md` on the current code | **Not met.** A local staging rehearsal passed (see `PHASE_2_FINAL_ACCEPTANCE.md`); a staging on a real host with a real domain does not exist |
| Real SMTP provider working (verification, invitations, password reset reach a real inbox, not spam) | Not met (`preflight --smtp-test` never run against a provider) |
| Backups: nightly, encrypted, **off-site**, restore proven in the last 7 days | Not met on a real host (proven on staging with a directory stand-in) |
| Error monitoring (`SENTRY_DSN`) set; Admin > Operations has no red item | Not met |
| Admin password set by the owner; admin address verified; MFA decision made (audit finding F7) | Not met |
| Platform-wide Places ceiling set (`RANK_PLATFORM_MONTHLY_CAP`), AI prices and budgets set | Not met (`docs/COMMERCIAL_LIMITS_AND_COSTS.md`) |
| Legal pages reviewed by a person who can approve them (privacy, terms, refund, deletion, retention) | Not met |
| Support address (`SUPPORT_EMAIL`) set and monitored; a named person on call | Not met |
| Payment: either not taken during the pilot (recommended: free pilot with a plan set by an admin), or a provider is wired and tested | Provider deferred (Cashfree, after the live website). **Run the pilot without taking payment.** |

## 2. Who

3 to 5 businesses, a mix of one location and, at most one, a multi-location. Chosen personally, each told in writing that this is a pilot, what data is held (`/privacy`), that they can export or delete everything (Settings > Account), and that FlowQR will **not** change their Google profile in the pilot's first stage. Prefer businesses that already have a verified Google Business Profile **or** who are happy to start without Google.

## 3. Stage A (cards and review pages only; no Google connection)

What works without connecting Google: the review landing page, QR and NFC cards, scan analytics, AI help for the *customer* writing their own review (the customer posts it themselves), leads, the getting-started checklist, local ranking if a Places key is configured.

### 3.1 Onboarding checklist (per business, done together on a call)

1. Create the account (the owner registers; verify the email together). Platform admins never register on the customer's behalf.
2. Wizard: business name and category; first location; choose **"Use my Google review link"**; the last step shows the plan or trial in force and creates the first review page. Confirm the plan line says what you promised.
3. **Google review link**: open the business's Google review link on a phone and confirm it opens the "write a review" box for the right place. Paste it under the location. (If they have no profile yet: create one at business.google.com first; do not connect FlowQR yet.)
4. Admin > Customers: set the plan you agreed (a pilot plan is set by an administrator; it is recorded in the subscription history with a note). Set the business's AI and Places ceilings (Admin > Customers > budgets).
5. Dashboard shows the getting-started checklist. Walk through each open item; mark optional ones as "later".
6. Notification preferences: who gets email for new and flagged reviews.

### 3.2 QR and NFC card assignment

1. Admin > Card inventory: reserve cards for the business, assign each to a location (a card is permanent: the printed QR is `https://<CARD_DOMAIN>/q/<token>` and **must not change**). Run `python -m app.cli card-url-audit --live --expect-domain <card domain>` first; it must pass before anything is printed.
2. Print or hand over; write the card codes on the handover sheet.
3. Scan each card yourself, from the business's own counter, on an Android and an iPhone; confirm the landing page shows the right business and sends to the right Google box. Tap an NFC card if one is used.
4. Confirm the scan appears in the business's analytics within a minute.

### 3.3 First campaign

The wizard creates one campaign page named after the location. Together: open it, check the wording, the languages offered, the staff-name or topic options, then attach the card to it. A campaign can be changed later without reprinting.

### 3.4 Local ranking baseline (only if a Places key and a plan allowance exist)

1. Pick 3 to 5 search terms the owner would be happy to rank for (the keyword limit is `RANK_MAX_KEYWORDS_PER_LOCATION`).
2. Run the first check and write the position down on the pilot sheet. **A position is where Google Places placed the business among the first 20 results around the location, measured once; it is not "your Google Maps rank".**
3. Maps (geo-grid) only if allowances are configured for the plan; otherwise the page says maps are off, which is correct.
4. Re-check weekly; never promise a ranking improvement.

### 3.5 Review monitoring in Stage A

Without Google connected the app cannot see the business's Google reviews. Monitoring means: scan counts, review-page completions and hand-offs, leads, and the owner telling you what they see. Say so; do not present a count of Google reviews that the app cannot know.

## 4. Stage B (Google connected): **only after the runbook's evidence log is filled in**

Entry: `docs/LIVE_VALIDATION_RUNBOOK.md` section 9 completed on a test profile, `release_gates.json` updated by a person with dated evidence, and each customer's written consent to connecting Google. Then, per customer: Settings > Connections > connect; confirm permissions screen matches the in-app explanation; choose locations; **autonomy stays off**; the owner approves each proposed change or reply themselves for the first two weeks; review the Admin > Work queue daily. Turn on any standing permission only after the owner has watched at least five approved changes behave correctly.

## 5. Customer feedback collection

* Day 3, day 14, day 30: a 5-question call or message (did the card get used, did customers complain, what confused you, would you pay ₹499 / ₹799, what is missing). Record answers verbatim in the pilot sheet, not summaries.
* A feedback link inside the app is not built; use the support email thread.
* Never ask a pilot business to ask its customers for positive reviews; the product does not do that and neither may the pilot (Google's review policies).

## 6. Support process

* One support address and one named person; first reply the same working day.
* Triage: **S1** the business's cards or review page are down, or data is wrong or exposed; **S2** a feature is broken but cards work; **S3** a question or a wish.
* Every ticket records: business, time, what was done, outcome. Admin > Audit shows what the platform did.
* Tools: Admin > Customers (state, plan, suspend), Admin > Work queue (failed Google changes, waiting approvals, deletion and export requests), Admin > Operations (worker, scheduler, backup, sync health).

## 7. Incident reporting

1. Stop the harm first: per business, the owner (or you with them) switches autonomy off in AI > Autonomy; platform-wide, an administrator uses the emergency stop (Admin > Operations > Autonomy). A suspended business sends nothing to Google.
2. Write the incident down within the hour: what, which business(es), when noticed, what was done, data involved.
3. If personal data may have been exposed: tell the owner of this product immediately; tell affected businesses without delay; keep the audit trail (do not delete rows). A legal basis and notification duty are for the owner and counsel to decide, not for this document.
4. Afterwards: a short written review (cause, fix, regression test) added to the security audit.

## 8. Usage and cost tracking during the pilot

Weekly, from Admin > Finance and usage: AI calls and dollars per business, Google/Places requests per business (counted; dollars only once prices are configured), failed and refused calls, cards issued. Compare against the plan allowances and the ceilings set in step 3.1.4. **Do not report margin** until every input in `COMMERCIAL_LIMITS_AND_COSTS.md` section 3 exists; the page will say "missing" and that is the correct answer.

## 9. Exit criteria (end of pilot, about 6 weeks)

* No S1 incident; every S2 has a regression test.
* Every pilot card still resolves; no business deleted data by accident.
* At least 3 of 5 businesses used their cards in the last two weeks.
* Real per-business cost per month known (AI, Places, hosting share) and compared with ₹499 / ₹799 / ₹1,499.
* Owner decisions made: map allowances, per-plan keyword and location numbers, free-month length.
* Written go / no-go for opening sign-ups, by a named person.
