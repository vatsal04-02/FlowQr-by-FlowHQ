# Google Business Profile: what third-party automation may and may not do through FlowQr's shared project

Status: **customer writes stay disabled.** This page records the restriction, what the code does about it today, and what is still unconfirmed. It is not legal advice and it does not claim Google has said yes.

## 1. The restriction as the project has read it

The policy gate (`backend/app/services/agent/v2/gate.py`) records Google's Business Profile API policy page, read on 2026-11-22. It was **not re-fetched while writing this page** (no web access in that session), so re-read the live page before relying on it. The points the gate was built around:

* Automatic or programmatic use of the API **by end-clients or agencies** needs **their own Business Profile API project**. FlowQr is one shared project serving many businesses.
* End users "need to manually sign in" to the application.
* Edits made through an application may not be automated "without the user's prior specific and express consent".
* FlowHQ's written question to Google about how this applies to a shared project is **still pending**.

## 2. Consequence for design

Customer approval is **not treated as sufficient**. A button an owner presses, a consent a customer ticks, or an owner's OAuth sign-in does not answer whether a shared developer project may make automated changes to many customers' profiles. So:

* `SEO_V2_CUSTOMER_WRITES_ENABLED` stays **false** for every customer profile. Opening it needs both the switch and `SEO_V2_POLICY_REFERENCE` (Google's written answer). Production refuses to start with one and not the other, and the check fails closed again at run time.
* The operator never gets a global write permission. Its tools cannot approve, publish or write to Google at all (`services/operator/tools.py`); a person approves through the existing endpoints.
* The only profile where a V2 write may run is a **dedicated test profile that FlowHQ owns**, named exactly in `SEO_V2_TEST_LOCATION_NAMES` (`locations/<id>`), and only those.

## 3. What each write path does today

| Path | Gate | Who authorises | Status |
|---|---|---|---|
| Services, categories, regular and special hours (V2), attributes, service area | **Gate applies**: closed for customers | A named person each time | Drafted and shown as "Drafted: not applied by FlowQr yet"; **no Approve button** is offered |
| Business description, missing phone or website (older engine) | Not held by the V2 gate | The owner approves each one; the owner's own Google sign-in | **Unchanged by this work.** It pre-dates the gate. It is subject to the same unanswered question and is **flagged here for the owner's decision**, not changed |
| Review replies and posts | Not held by the V2 gate | The owner approves each one | Unchanged. Same open question |
| Template auto-replies to new 4 and 5 star reviews | Own consent per location | The owner's standing consent | Unchanged. Same open question |
| The AI Business Operator | n/a | Cannot approve or write | Prepares drafts only |

## 4. Operating models that could make customer writes permissible (to be confirmed with Google in writing, none assumed)

1. **Each customer's business uses its own Business Profile API project and OAuth client** (Google's stated requirement for end-clients). Large operational burden; changes onboarding.
2. **FlowHQ manages only profiles it owns or is formally the agency for, under Google's agency terms and project approval** (the agency Manager path already built, internal-only).
3. **Written approval from Google** for FlowQr's shared-project model, recorded in `SEO_V2_POLICY_REFERENCE`.

Until one is confirmed in writing, nothing here opens customer writes.

## 5. How a customer is told

The Pending changes screen says, on every drafted change the gate holds: "Changes to this part of your profile are not made by FlowQR yet: Google's rules on automated changes to customers' profiles are still being confirmed with Google in writing. FlowQR shows you exactly what to change, and you can make it in Google Business Profile." No button is drawn that the server would refuse.
