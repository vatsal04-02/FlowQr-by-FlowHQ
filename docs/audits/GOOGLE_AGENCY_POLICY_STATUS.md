# Google agency operations: policy and data-retention status

Re-read on 2026-11-21 from the pages below. This is an engineering reading of Google's published text, **not Google's answer and not legal advice**. A successful API call is not policy clearance and is not treated as one.

Sources read: `developers.google.com/my-business/content/policies` (Business Profile APIs policies), `developers.google.com/my-business/content/basic-setup`, `developers.google.com/my-business/content/faq`, `support.google.com/business/answer/7353941` (third-party policies). The pages show no "last updated" date. Quotes are short and exact; everything else is paraphrase.

## What Google's pages say

| Topic | What the page says | Effect on FlowQR |
|---|---|---|
| Programmatic third-party use | "Any automatic or programmatic use of Business Profile by agencies or end-clients requires them to use their own Business Profile project. You cannot provide indirect access to your Business Profile project." (the first sentence as returned by a search summary of the page, the second quoted from the page) | The agency model has FlowHQ's login act, through FlowQR's one project, on behalf of many clients. Whether that is "indirect access to your project" or "your own programmatic use" (which the page says is not restricted) is **not answered by the page**. |
| Avoiding own projects | "You cannot allow agencies, end-clients, or other third parties to use your Business Profile project ... in a way that allows those third parties to avoid applying for their own Business Profile project." (search summary of the page) | Same question. |
| Supplemental projects | "you cannot require them to apply for their own Business Profile project in order to use the Business Profile APIs" (partial quote) | Pulls the other way for a provider that serves end-clients: the page contains both rules and does not reconcile them for this case. |
| Manual sign-in | End users "must manually sign in" and cannot make automatic or programmatic changes to their accounts through your project. | The existing owner-OAuth route (each owner signs in themselves) is the shape the page describes. |
| Manager access | A merchant adding a partner as manager lets the partner edit and read data without the merchant's credentials (FAQ). Manager access is not API-project access: "GBP API access is granted on a Google Cloud project level." | An accepted invitation or a Manager role does not settle project eligibility. |
| Reviews and automation | Authorization from the end-client is required before responding to reviews or posting; automating review replies, Q&A, listing creation or edits needs "the user's prior specific and express consent". | Already enforced (consent record, separate notice). |
| Notice | A tool that changes an end-client's account (for example adding a manager) must notify the end-client within 48 hours, separately from Google's notices. Seven business days to let a client disassociate and remove permissions. | Already built (separate notice, stop button, removal deadline). |
| Storage | Content may not be "pre-fetch[ed], cache[d], index[ed], or store[d]"; stored content "must be stored temporarily for no more than 30 calendar days" and "cannot be manipulated or aggregated". Reviews are not named; no exception for operational data is stated. | **FlowQR stores reviews indefinitely and aggregates them.** This affects the live owner-OAuth route too, not only the agency route. See below. |
| AI / ML | The page says nothing about AI or machine-learning use of the data. | Unresolved. The review-reply AI stays off until the provider's terms are verified (`GEMINI_DATA_TERMS_VERIFIED`). |

## Decision

- **Agency operations: BLOCKED on Google's written answer.** `GOOGLE_AGENCY_OPERATIONS_ENABLED` stays **false**. In production the application also refuses to run agency operations without `GOOGLE_AGENCY_POLICY_REFERENCE` (a configuration error at start-up, and `operations_enabled()` returns false at run time). Nothing here records an approval, and nothing may be entered as a reference unless Google actually answered.
- **Not done, on purpose:** no proxy account, no credential sharing, no project relabelling, no per-client hidden API calls to get around the question.
- **If Google says the shared project is not permitted:** the permitted shapes are (1) the existing owner-OAuth route (each owner signs in; no agency token acts for them), which stays the supported default and is untouched, or (2) a client-owned Cloud project and OAuth client per client for any programmatic agency use, which needs each client to apply for API access themselves. That is a different build and is not started here.
- **Draft question to Google:** `GOOGLE_CLIENT_ACCOUNT_OPTIONS.md` section 9 and the questions at the end of section 11.

## Storage: a separate, existing issue

The 30-day limit above is a stated condition for any content "provided through the Business Profile APIs". FlowQR's review sync keeps reviews until the business is deleted and shows trends over them. That is how the product works today on the live owner-OAuth route. This change does **not** alter it (doing so would silently remove customers' history). It is recorded as open item **R-1**: ask Google (the same message as the project question) whether review text may be kept for the service the owner asked for, and if not, add a retention job. Until then the exposure exists exactly as before; the agency work neither widens nor narrows it.

## What is verified versus not

| | Status |
|---|---|
| Google's published rules, as quoted above | Read on 2026-11-21 |
| Whether the shared-project agency model is allowed | **Not established** (no written answer) |
| Whether FlowQR's review storage meets the 30-day text | **Not established**; the text, read literally, does not allow it |
| Whether AI use of review data is allowed | **Not established** (page silent) |
| Agency API reads of one client location, read-only | Worked on 2026-11-21 (see the migration runbook). That is evidence the API answers, **not** approval |

## Update, same day (second pass)

* **Retention mechanism now exists** (migration 0064, off by default): `GOOGLE_RETENTION_ARCHITECTURE.md`. It is the mechanism, not a compliance claim; the 30-day text is still unanswered for FlowQR's service (R-1).
* **The exact questions and the channel are written down** in `GOOGLE_QUESTIONS_TO_SUBMIT.md`. Nothing has been sent, so there is no reference to record and agency operations stay off.
* **Statuses:** agency operations BLOCKED (no written answer); retention mechanism IMPLEMENTED and TESTED, not ENABLED; Google policy compliance NOT established.
