# Retention of autonomy records and business offboarding

Status: a proposal with the mechanisms it needs already built and tested (Phase 1.5). **Not legal advice.** The contractual and statutory questions in section 6 need a lawyer; the engineering here makes either answer implementable.

## 1. What is kept, and why it is a tension

FlowQR's autonomy engine keeps a record of every change it proposes or makes to a business's Google presence: the action (`agent_actions`), who authorised it (`agent_action_approvals`), every step it went through (`agent_intervention_events`, append-only and hash-chained so that an edit or a gap is detectable) and what was measured afterwards (`agent_rank_followups`, `rank_grid_scans`, `rank_grid_points`).

Two goods pull against each other:

* **Audit integrity.** An audit trail that can be quietly edited or shortened is worth very little. That is why the history table refuses UPDATE, DELETE and TRUNCATE for everyone, including the table owner, and why each event carries a hash of its content and of the event before it.
* **Privacy and the right to leave.** A business that ends its contract, or a person who asks to be forgotten, expects their data to go. "Append-only" must not turn into "kept forever".

The way out is to be precise about **what personal data the trail contains** and to give it **exactly two exits**, both whole-record, both audited.

## 2. What personal data is actually in the trail

| Held | Where | Is it personal data? |
|---|---|---|
| The acting person | `agent_intervention_events.user_id`, `agent_action_approvals.authorized_by`, `agent_actions.proposed_by_user` | An opaque UUID. The event column is a plain value (no foreign key), so erasing the person's account leaves an id that maps to nothing: **pseudonymous, then effectively anonymous**. The two foreign-keyed columns are set to NULL by the database when the person is deleted (those tables are not append-only). No name or email is ever written into an event. |
| Business content | `data` of events: description text, hours, post text, reply text, review ids | Business content. The reviewer's name is not stored in the trail; a reply's text is the business's own words. A person could have typed personal data into free text (a rejection reason, a post), which is why section 4 applies a time limit and why the export includes it. |
| Free-text reasons | rejection and approval `reason` | Authored by the business. Same treatment. |
| Measurements | rank scans and points | Business performance data; no individuals. |
| AI spend | `ai_call_ledger` (Phase 0) | Counts, tokens, cost and a tenant id; no content. See section 6, question 3. |

Consequence: erasing **one person** does not require editing the chain, and erasing **a whole record or a whole business** does not leave fragments.

## 3. Findings from the review (what was wrong, and what changed)

| # | Finding | Change made |
|---|---|---|
| 1 | The owner's **data export omitted every autonomy table** (actions, approvals, history, follow-ups, maps). A person exercising portability or access rights would have received an incomplete copy. | `account.TABLES` now includes `agent_actions`, `agent_action_approvals`, `agent_intervention_events`, `agent_rank_followups`, `rank_keywords`, `rank_grids`, `rank_grid_scans`, `rank_grid_points`. Secrets and the internal dedupe key are never exported. Tested. |
| 2 | There was **no time limit** on the history: it lived until the business was deleted. | `services/agent/retention.py` + the daily job `flowqr.autonomy_retention`: finished actions older than `AUTONOMY_HISTORY_RETENTION_DAYS` (default **730**) are erased **whole** (action, approvals, history, follow-ups together); map scans older than `RANK_GRID_RETENTION_DAYS` (default **400**) likewise. `0` = keep until the business is deleted. |
| 3 | Deleting a business already erased the history (the one deliberate exception to append-only), but this was untested for the new tables and not described anywhere. | Tested for every autonomy and map table, and that another business's rows are untouched. |
| 4 | A business that has **asked to be deleted** could keep sending changes to Google during its 14-day grace period. | Profile writes were already cancelled once deletion is scheduled (`target_unavailable`); governed publishing now holds too (section 5). |
| 5 | The meaning of "erased" for **backups** was undefined. | Section 5, step 6. |

## 4. The retention schedule

| Record | Kept | Then | Why this long |
|---|---|---|---|
| Actions waiting, approved or executing | until decided or expired (7 days for a proposal) | expire; become "finished" | live work is never erased by retention |
| Finished actions, their approvals and their tamper-evident history | **730 days** from creation | erased whole, counted in the audit log | long enough to answer "who changed my profile and why" for two years and to span a dispute; short enough that personal data typed into reasons or posts does not accumulate indefinitely |
| An action whose 7/14/28-day ranking follow-ups are still due | until they finish | then as above | the measurement needs its baseline |
| Geo-grid scans and points | **400 days** | erased | one year of trend plus a margin |
| Audit-log entries that an erasure happened | the audit log's own retention | n/a | holds a **count and a date only** (`records`, `older_than`, `retention_days`), never content |
| Everything of one business | until the business is deleted (14-day cancellable grace) | **all of it erased**, history included | the contractual deletion obligation always wins over the audit-retention default |

Retention is **by whole record, never by editing**. An erased action leaves no half-record to explain, and the hash chain of every surviving action is untouched. The erase permission is a transaction-local flag that only the retention job and account deletion set; outside them the database still refuses to delete a single history row (tested).

## 5. Offboarding, step by step

1. **Owner requests deletion** (`POST` in Settings > Business). The business keeps working for the cancellable grace period (`ACCOUNT_DELETION_GRACE_DAYS`, 14).
2. **Immediately**, nothing new is sent to Google for that business: profile changes are cancelled, and governed publishing of posts, photos and replies is held (`content_exec.govern`).
3. **During the grace period** the owner can export everything (now including the autonomy records and maps) and can cancel the request.
4. **After the grace period** the daily job (`purge_deleted_accounts`) revokes the Google grant (best effort), returns printed cards to inventory as unassigned, and deletes the business. Every tenant-owned table cascades, **including the append-only history** (the single deliberate exception, via the transaction-local flag). People whose only business it was lose their account too.
5. **What remains**: one audit-log line with no tenant, listing the slug and counts (`account.deleted`), and spend counters in `ai_call_ledger` (section 6, question 3).
6. **Backups.** Encrypted database backups taken before the deletion still contain the business until they age out (`BACKUP_KEEP_DAYS`, default 14 locally; the remote's lifecycle rule for off-site copies). State this in the privacy notice: deleted data disappears from live systems at once and from backups within the backup retention period; a backup restore must **re-run deletions that happened after the backup** (record deleted tenant ids in the audit log, which this process does, and replay them after any restore).

**Note for operators.** The app never hard-deletes a Google location or connection (it deselects or marks them), so autonomy history is never orphaned. A hand-written `DELETE FROM google_locations` for a location that has autonomy history is refused by the database, because the cascade would erase append-only rows. That is intended. To remove such a location on purpose, set the erase flag in the same transaction (`SELECT set_config('app.history_purge','on',true)`), knowing it erases that location's history.

## 6. Decisions that need a lawyer (not engineering)

1. **Is 730 days right?** Indian DPDP Act obligations (erase when the purpose is served unless law requires retention), any sector rule that applies to your customers (for example health businesses), and what your own customer contracts promise. The number is a single setting; the mechanism does not change.
2. **A customer who wants the trail after they leave.** The export is the answer (they take their copy at exit, then everything is erased). If a contract needs FlowQR to keep a copy for a defined period after termination, that is an exception to build explicitly, with its own end date, not a silent default.
3. **The AI spend ledger survives deletion** by design (Phase 0: costs must reconcile). It holds a tenant id, model, token counts and cost, no content. Decide whether a tenant id there is personal data in your context; if so the options are to keep it as a pseudonymous accounting record for the legally required financial period, or to null the tenant id at deletion with a privileged maintenance step. The ledger is deliberately outside this change.
4. **Right to erasure of one person who remains in an active business.** The design already makes the trail identify them only by an opaque id. Confirm that this satisfies your reading of "erased"; if it does not, the alternative is a per-person lookup table that is deleted (so the id can never be resolved), which would be a small, reversible addition.
5. **Tamper evidence at rest.** The hash chain proves internal consistency, not that the database owner did not rewrite the whole chain. If an external guarantee is ever contractually needed, the next step is to anchor each tenant's latest chain hash daily in separate write-once storage. That is not built.

## 7. How this is enforced and tested

* `tests/test_phase15_retention_and_live_prep.py`: whole-record erasure with counts-only audit entries; live work and actions still being measured are never erased; retention can be switched off; the job exists and is scheduled daily; the erase permission does not leak out of the job; old map scans and their points; the export contains the autonomy and map files without secrets; deleting a business erases everything of it and nothing of another; removing a person leaves the history intact and identifying nobody.
* `tests/test_phase1_executor.py`: UPDATE, DELETE and TRUNCATE on the history are refused, even to the table owner; tampering that bypasses the trigger is detected by the chain.

## 8. Settings

| Variable | Default | Meaning |
|---|---|---|
| `AUTONOMY_HISTORY_RETENTION_DAYS` | 730 | finished actions and their history; `0` = keep until the business is deleted |
| `RANK_GRID_RETENTION_DAYS` | 400 | geo-grid scans and points; `0` = keep |
| `ACCOUNT_DELETION_GRACE_DAYS` | 14 | cancellable delay before a requested deletion is carried out |
| `BACKUP_KEEP_DAYS` | 14 | local backup retention (remote copies follow the remote's own rule) |
