# Admin-managed businesses

A platform administrator can set up a business, its locations and its Google review destination, and assign QR/NFC cards to it, entirely from the Admin Console. The shopkeeper needs no login for any of it.

## The model

- A **business** is a `tenants` row. A **user** is a `users` row. They are separate: owners are only `memberships` rows, so a business with no membership is valid.
- `tenants.origin` is `admin` for businesses created here and `self_service` for everything else (the default, so every existing row is unchanged).
- Creating a business never creates a user, a membership, a session or a password. The audit entry says `user_account_created: false`.
- Cards, scans, taps, the review page and analytics depend only on the business and location being active and the card being live. None of them looks for a user or a subscription.

## Access and limits (no billing)

An admin-created business gets a **manual Launch subscription**: plan `starter`, status `manual`, source `manual`, no payment provider, no trial dates. Limits come from the plan: **200 AI review writings and 200 AI replies a month**, enforced by the same counters as every other business. This month's use and AI cost are shown on the Business page.

- **Revoke** sets the status to `expired`: AI features stop; cards, scans and the plain review page keep working. **Restore** sets it back to `manual`. Both need a reason and are audited.
- **Suspend** (the existing action) turns the whole business off, including its cards' landing page.

## Creating a business

`POST /api/v1/admin/tenants` (platform administrator only). Required: name, phone, city. Optional: category, contact person, email, address, website, location name, Google review link (validated), offline agreement. Extra fields are refused.

Duplicates are detected by normalised name, last 10 digits of the phone, email and the Google place in the review link. If anything matches the response is `409 duplicates_found` with the matching businesses. The form shows them and offers **Create anyway**, which needs a reason of at least 10 characters. The reason and the ids of the matches are written to the audit log (`admin.business_create`).

`POST /api/v1/admin/tenants/duplicate-check` runs the same check without creating anything.

Additional locations: `POST /admin/tenants/{id}/locations`. An administrator is not held to the plan's location cap; each bypass is audited. Turning off a location that has live cards needs `confirm`.

## Offline agreement record

`tenant_agreements` is append-only for the application role (SELECT and INSERT only). Each row stores the administrator, the time, the terms version (`2026-11-18.admin-offline.1`), the method (phone, in person, WhatsApp, paper, other), an optional note and a fixed statement. The statement says it was recorded by a FlowQR administrator on behalf of the business, is **not** the shopkeeper personally accepting the terms and does **not** confirm anyone is 18 or older. Nothing writes to the user consent fields for it.

## Optional claiming

Off by default (`CLAIM_INVITATIONS_ENABLED=false`). When on, an administrator can invite the shopkeeper by **email** or by a **copyable link** (with a `wa.me` WhatsApp URL). The link is shown once; only a hash of the token is stored. Invitations expire (`CLAIM_INVITATION_TTL_HOURS`, default 168), can be revoked, and only one is open at a time. Creating one adds the email to the registration allowlist, which is audited. Accepting is refused if the business already has an owner. The shopkeeper accepts the terms and confirms their age themselves when they sign up.

### Revoking a claim, and the sign-up allowlist

Revoking an invitation stops its link at once and keeps the invitation row and every audit entry. The sign-up allowlist entry is **kept by default**. The administrator can tick *Also remove this email from the sign-up list*, and the entry is then removed only when **all** of these hold (`allowlist_removal_check`, shown on the page before the box is ticked, with the reason when it is not allowed):

- the entry was **created by this claim** (`invitations.allowlist_entry_id`). An address that was already listed, or that an administrator added by hand, is never removed;
- no **other invitation** to the address (any business, any role) is still valid: not accepted, not revoked, not expired;
- **no account** exists for the address (the entry may be what lets that person create a business);
- the address is not permitted by the server's own configuration (`REGISTRATION_ALLOWLIST`, administrator addresses).

The outcome is audited either way (`admin.allowlist_removed_after_claim_revoke` or `admin.allowlist_kept_after_claim_revoke` with the reason). Revoking again is harmless, so an administrator who forgot the box can remove the entry afterwards from the revoked invitation. An accepted invitation cannot be revoked.

## Assigning cards

The Assign card and Assign selected windows, and the **Scan to assign** tab, use one picker with two paths: **Existing business** (search by name, city or phone; location; campaign or plain page) and **New business** (a compact form that saves the business and its first location, returns to the assignment with both preselected, without leaving the inventory screen). Assignment, history, destination clearing on reassignment, attribution and audit are the existing QR/NFC code, unchanged. Printed URLs are untouched.

## Export and deletion for a business with no owner

A business with an owner uses Settings > Account. A business staff set up has no owner, so an administrator handles these requests (`services/data_requests.py`, `admin_data_requests.py`, the *Data export and deletion* card on the business page). **Nothing is exported, sent or deleted automatically.**

1. **Log the request** (export or deletion): who is asking (owner, someone speaking for the owner, someone else), how they asked, and optionally how they reached you. Only for a business with no owner; one open request of each kind at a time. This changes no data.
2. **Verify who is asking.** The administrator records how: a callback to the shop's phone, a WhatsApp message from that number, an email from the address on file, in person at the shop, or another described way. For the first three the number or address used **must match the one already on the business record**. Details that merely arrived with the request do not count, and a business with nothing on record cannot be verified that way. The administrator also ticks that they checked.
3. **Export:** an administrator downloads the same ZIP an owner would get (never any secret, token or password hash), hands it to the verified person, and records how it was delivered. The system emails nothing.
   **Deletion:** after verification there is a **cooling-off period** (`ACCOUNT_DELETION_GRACE_DAYS`, 14 days, the same as an owner's). Then an administrator executes it by typing the business name exactly and acknowledging that it is permanent. A paid subscription must be cancelled first. Execution is the existing `delete_tenant`: cards go back to stock as unassigned (a deleted business's printed code never shows another business's page), Google access is revoked best-effort.
4. **Reject or cancel** at any time before it is resolved, with a reason.

Safeguards: the request does **not** set the business's own deletion schedule, so the daily deletion job never touches it. If someone claims the business meanwhile, every step stops (the owner has the real tools). The requester's contact detail is erased when the request ends. The request and its append-only history (who, when, what) **outlive the deleted business** (`tenant_id` becomes NULL, a name snapshot stays), and an audit entry that survives the deletion names the administrator and the verification. Both tables are platform-only (row-level security admits the bypass context and nothing else); no business can read them.

Handling guidance: verify before anything else; prefer in-person or a callback to the number on file; hand an export over only to the person you verified; if the person cannot be verified, reject with the reason. Keep the cooling-off period unless there is a legal reason to shorten it (there is no override in the product).

## Usage and cost view

*Businesses > Usage and cost* (`GET /admin/managed-usage`) shows, for the businesses staff manage: how many there are (active, suspended, access revoked), this month's AI review writings and replies used against what is allowed (200 + 200 each while access is on), model calls, and **estimated AI cost**, with a per-business table and a flag for businesses at 80% of an allowance. It is read-only.

Consumption is counted from the successful-generation log the limits are enforced against. Cost comes from the per-call ledger the platform's AI budgets read: each call carries the cost the provider reported, or the cost estimated from the configured prices when it was made. **Nothing is invented.** A call with no recorded cost is priced from its recorded tokens only when `AI_PRICE_IN_PER_MTOK` and `AI_PRICE_OUT_PER_MTOK` are set (shown separately as "priced from tokens"); with no prices configured, or no tokens recorded, it is counted as "without a cost" and adds nothing. The page says which case applies. These are the platform's existing price settings, so this view and the AI spending limits always agree.

## Directory

`/admin/customers` (URL kept so every link works) is labelled **Businesses**. It shows name, category, contact, phone, email, locations, cards, live cards, onboarding stage, access and created date, with search (name, contact, email, city, location, phone digits) and filters for who set it up, onboarding stage and subscription.

## Migration 0046

Adds `tenants.contact_name`, `origin` (check: `self_service` | `admin`), `created_by`, `updated_by`; `invitations.allowlist_entry_id`; the `tenant_agreements` table (forced RLS, tenant policy, SELECT and INSERT only); and `data_requests` / `data_request_events` (forced RLS, platform-only policy; the app role can SELECT, INSERT and UPDATE requests, and only SELECT and INSERT events). Existing rows keep `origin = 'self_service'` and no existing row is changed. Downgrade drops everything above, including any recorded requests and agreements. It is a single migration on top of 0045; the chain has one head and one parent per revision (`test_migration_0046`).

## Not covered

- Claiming keeps the managed Launch access; moving the business to a paid plan is a separate manual step.
- Verification is an administrator's judgement recorded with a method; the system checks that the contact used matches the record but cannot prove the person is who they say.
- Deletion and export are single-administrator actions (typed name, acknowledgement, cooling-off). There is no second-person approval, because production currently has one platform administrator.
- A bulk export of many requests, and automatic reminders about requests waiting too long, are not built.
