# Local SEO engine V2: runbook

For an operator. Nothing here has been run against production. Read `LOCAL_SEO_ENGINE_V2_IMPLEMENTATION.md` section 5 first: customer writes are gated closed.

## 1. Switches

| Setting | Default | Meaning |
|---|---|---|
| `SEO_V2_CUSTOMER_WRITES_ENABLED` | `false` | Opens the gate for **customer** profiles. Leave false. |
| `SEO_V2_POLICY_REFERENCE` | empty | Case id / document holding Google's **written** answer. Never fill it in unless Google actually answered. Production refuses to start if the switch is on and this is empty, or if this is set and the switch is off. |
| `SEO_V2_TEST_LOCATION_NAMES` | empty | Comma-separated `locations/<id>` of **dedicated test profiles that FlowHQ owns**. The only profiles V2 may dry-run or write today. |
| `AUTONOMY_EMERGENCY_STOP` / admin endpoint | off | Existing platform stop: holds V2 execution too. |

**These must also be listed in `deploy/vps/docker-compose.vps.yml` to reach the container** (env vars reach the app only through the overlay). Not edited here. The defaults are safe if they are absent.

## 2. Deploy (when approved; not done)

1. Review the branch; merge onto the then-current release branch (it moves fast: fetch first, re-check the alembic head; 0066 assumes head 0065).
2. Migration 0066 is additive and reversible (`downgrade` cancels any `recommended`/`superseded` rows). Back up the database first (existing runbook).
3. Deploy backend then frontend. With defaults, customers see "Fix your profile": detections, drafts shown as **Recommended** (not made by FlowQR), no new write to any customer profile. The legacy description/contact engine behaves as before.
4. Rollback caveat (real, not tested): once V2 has created any action of a new type (`category_set_update`, `special_hours_update`, or a V2 `attribute_change`/`service_area_change`), the **previous** image does not know those types and its action listing/presentation can raise on them. So roll back **before** the first V2 scan has run, or after the new-type rows are dealt with by a person who understands the history (the history table is append-only and cannot be deleted from). `alembic downgrade 0065` cancels `recommended`/`superseded` rows but does not remove those rows. Prefer turning V2 off by not deploying it over rolling it back.

## 3. Proving it against Google, safely (the only way to move an operation from "mock-tested" to "validated")

Use a **dedicated test profile that FlowHQ owns**, never a customer's.

1. Connect it in a dev stack and note the connection id.
2. Read-only and dry-run probes (writes nothing; guards compare the profile before and after):
   `python -m app.cli google-readiness --connection <id> --location locations/<n> --expect-title "<exact live title>" --evidence <path>.json`
   The new "V2" section reports, per operation, whether Google accepted FlowQR's services / special-hours / service-area / category-set bodies in a `validateOnly` dry run, whether `canModifyServiceList` is present, whether the attribute and service-type reads normalise, and whether current attributes and structured services pass FlowQR's own checks. Keep the evidence file; it holds counts and outcomes only.
3. Only after step 2 is clean, and only for that profile, add its name to `SEO_V2_TEST_LOCATION_NAMES` in the **dev** stack, run a scan, approve a drafted change in the app, and confirm the history shows `validated` -> `executing` -> `google_write` -> `read_back` -> `verified`. Record what Google actually showed, including anything that differed from the documentation (especially: whole-list vs merge for `serviceItems`, and BOOL attribute values).
4. Record results in `LOCAL_SEO_ENGINE_V2_TEST_MATRIX.md` ("Proven against a real profile") with the date. Until then that table stays empty.

## 4. Operating it

* **See what it did:** `/ai/activity` (hash-chained history per action), `GET /seo/v2/overview`, `audit_logs` (`seo.v2_scan`, `seo.v2.*`, `email.sent` with `kind = seo_v2_change_notice`).
* **Stop everything now:** emergency stop (admin endpoint). Queued V2 actions are held, not failed. Per business: the owner switches autonomy off; V2 changes never needed consent because they are never autonomous.
* **A change failed with "read-back mismatch":** Google accepted but the profile does not show it. The action is `failed`, nothing is claimed. Three consecutive failures suspend that business's autonomy. Investigate the exact value in the action's `verification`.
* **A change is `blocked` with a validation error:** Google refused it in the dry run; the message is Google's. Nothing was written. Fix the data (for example a custom service needs a category) and re-scan.
* **An owner says "it did something I did not approve":** every V2 write needs a named person's approval bound to the exact value (`agent_action_approvals`, `scope_hash`). Check `approvals` and `history_integrity` on the action.
* **Owner wants out:** disconnecting Google (existing control) revokes the token; V2 then has nothing to act with. FlowQR does not revert prior changes; the owner edits them in Google.
* **A Google-made change appears:** shown as "Google changed some details itself"; FlowQR proposes nothing over those fields and never reverts them.

## 5. Open items for a person

1. Send the Google questions (`docs/audits/GOOGLE_QUESTIONS_TO_SUBMIT.md`); record the answer as `SEO_V2_POLICY_REFERENCE` only if one arrives.
2. Provide/confirm a dedicated test profile and run step 3 above.
3. Add the three env vars to the VPS overlay when the gate decision is made.
4. Decide whether to store competitor categories (billed Place Details) so category evidence can include them.
5. Decide on the owner-facing wording for the notice email before enabling any customer write.

## 6. The live test command (used on 2026-11-22/23)

`python -m app.cli seo-v2-live-test --connection <id> --location locations/<n> [--steps refresh scan special-hours services failure] [--execute --confirm-location <same> --confirm-title "<exact title>" --report file.json]`

* Dry run by default. `--execute` also needs `FLOWQR_LIVE_WRITE_AUTHORIZED=<location>` and the location listed in `SEO_V2_TEST_LOCATION_NAMES` **in that one process**. Run it in a one-off container: `docker compose -p flowqr-production ... run --rm --no-deps -T -e SEO_V2_TEST_LOCATION_NAMES=<loc> -e FLOWQR_LIVE_WRITE_AUTHORIZED=<loc> ... api python -m app.cli seo-v2-live-test ...`. The running api, worker and beat never see those variables, so the gate for every customer stays closed.
* The acting person is the business owner recorded for the test tenant; the report says `live` or `mocked`.
* Preconditions the command cannot satisfy for you: the test tenant needs an **active plan** (otherwise every change is held with reason `plan` and nothing is written); the platform emergency stop (`AUTONOMY_EMERGENCY_STOP=true` in production) holds every write too, so a live run needs it overridden **for that one process only** (`-e AUTONOMY_EMERGENCY_STOP=false`), which is a deliberate, recorded decision, never a change to the running services.
* `deploy` note: on 2026-11-23 the test tenant's trial was extended for the run and restored afterwards (audit actions `ops.test_tenant_trial_extended` / `ops.test_tenant_trial_restored`; the original was status `expired`, `trial_ends_at` 2026-11-22 20:51:37+00).
* Token expiry: while Google's OAuth consent screen is in *Testing*, a refresh token dies seven days after the connection was made (the Geeta customer connection was revoked on 2026-11-22 at 21:16, exactly seven days after 2026-11-15 20:47). The FlowHQ test connection (made 2026-11-21 15:04) will expire about 2026-11-28 15:04; reconnect it before the next live run.
