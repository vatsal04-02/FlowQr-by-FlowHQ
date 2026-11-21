# Which Google API project model may FlowQR use? Options, evidence, and what the code supports

Written 2026-11-22. Sources read that day: `developers.google.com/my-business/content/policies` (Business Profile APIs policies), `.../prereqs`, `.../basic-setup`, `.../faq`, `support.google.com/business/answer/7353941` (third-party policies). The pages show no update date; quotes are short and exact, the rest is paraphrase. **This is an engineering reading, not Google's answer and not legal advice. No option below is stated by Google to be permitted for FlowQR's exact case, and none is treated as cleared.**

## The relevant text

* Programmatic use: "Any automatic or programmatic use of Business Profile by agencies or end-clients requires them to use their own Business Profile project. You cannot provide indirect access to your Business Profile project." Also: you "cannot allow agencies, end-clients, or other third parties to use your Business Profile project ... in a way that allows those third parties to avoid applying for their own". The page adds that the project owner's **own** programmatic use is not restricted, and that end users must sign in manually.
* Supplemental projects: "you cannot require them to apply for their own Business Profile project in order to use the Business Profile APIs", and an end-client's own application for such a project is not granted.
* Eligibility (prerequisites page): the Business Profile behind an application "can be the applicant's own office or headquarters or it could belong to one of the clients they manage". Nothing says who submits for a client, and nothing about a project serving several clients.
* Manager access is not API access: "GBP API access is granted on a Google Cloud project level"; a Manager can act in the product, the API needs an approved project.

## The options

| # | Model | What it is | What the text supports | Verdict |
|---|---|---|---|---|
| 1 | **Owner sign-in under FlowQR's one project** (live today) | Each business signs in to Google itself and approves access; FlowQR's approved project calls the API with that owner's token | End users sign in manually; the project owner's own programmatic use is not restricted | Matches the published expectations. Still open: storage (30 days) and AI use |
| 2 | **FlowHQ's own project, FlowHQ's own agency login** (built, off) | FlowHQ (the agency) is a Manager of client locations through one Location Group; the same approved project calls the API with FlowHQ's agency token | Agencies must use "their own" project: this one is FlowHQ's. The prerequisites allow an applicant to manage clients' profiles. Nothing is handed to another agency or client | **Plausible, not established.** The text does not say whether a SaaS dashboard that shows many clients' data through the agency login is "indirect access", nor whether FlowQR and FlowHQ count as one party. Needs Google's written answer (questions 1 to 3) |
| 3 | **Client-owned project per client** | Each client creates and applies for a Cloud project and authorizes FlowQR to use it | The policy says clients may not be required to apply, and that such applications are not granted. Multi-project routing would also be a way of presenting FlowQR's use as the client's | **Not supported.** Do not build. It is not a compliant substitute |
| 4 | **Manual sign-in only** (no background access) | A person signs in to Google for every action | Fully consistent with "must manually sign in" | Compliant but cannot do scheduled sync or reply automation |
| 5 | Borrowed, proxy, relabelled or shared credentials; hidden or concealed automated access | | Prohibited by the "no indirect access" text and by the third-party rules | **Never.** Not implemented, not to be implemented |

## What Google permits, exactly

The published text clearly describes **model 1** (owners sign in) and says an agency's programmatic use needs **its own project**, which is what **model 2** is **if** FlowHQ's project is the one it uses and nothing is handed on. Whether model 2 is allowed for this multi-client service is **not stated**, so it is the one decision that needs Google's written answer. Model 3 is excluded by the text. Nothing in the published pages tells a cloud project owner that a client-owned project makes agency automation compliant, so none is assumed.

## What is implemented (and what is not)

* **Only model 2 is supported by the agency code, and only behind an explicit setting.** `GOOGLE_AGENCY_PROJECT_MODEL` is empty (undecided) by default. The only value is `flowhq_own_project`. Anything else is refused at start-up ("no other project model is supported"). In production no agency token is used (`operations_enabled()` is false) until **both** the model is set **and** a policy reference is recorded; the start-up guard refuses `GOOGLE_AGENCY_OPERATIONS_ENABLED` without them.
* **No silent substitution.** There is no code path that routes an agency connection to a different project. Each use of the agency login is resolved to one explicit authorization (`resolve_agency_access`) and audited with the project model (`google.agency.used`, `meta.project`). A connection that is not on the agency login keeps using its owner's token under FlowQR's project (model 1), untouched.
* **Separation.** Agency credentials are a separate table, encrypted with a separate key, platform-only; owner tokens are untouched by the agency path. The agency path never uses an owner token and the owner path never uses the agency token.
* **Activation is a checked decision.** `python -m app.cli google-agency-activation-check` prints each precondition as PASS or BLOCK with who must act (EXTERNAL = Google's answer, CONFIG, DATA), and exits non-zero unless all are met. It reads only the local configuration and database and changes nothing. The two EXTERNAL lines (project model, policy reference) cannot be satisfied by code and must not be filled in to make it pass.
* **Not built:** client-owned projects (model 3); any form of borrowed or proxied project credential.

## When Google answers

1. If the answer permits model 2: record the written reference, set `GOOGLE_AGENCY_PROJECT_MODEL=flowhq_own_project` and `GOOGLE_AGENCY_POLICY_REFERENCE=<reference>`, run `google-agency-activation-check` until READY, register the agency login in production (`google-agency-register --listen`), run `google-agency-check` (read-only) there, then switch on the two agency flags and re-verify. Add the variables to the VPS overlay (they are not in it today).
2. If the answer does not permit it: keep model 1 as the only path. The agency code stays off and unused. No further engineering is needed to stay compliant.
