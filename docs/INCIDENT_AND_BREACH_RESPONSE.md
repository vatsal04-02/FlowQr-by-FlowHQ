# Personal-data incident and breach response (DRAFT for the owner and a lawyer)

Status: **draft, not adopted.** Everything in `[BRACKETS]` is for the owner to fill in. Every legal duty below is stated as the checklist assumed it ("India's DPDP Rules require telling the Data Protection Board and affected users; GDPR requires telling the authority within 72 hours") and **must be confirmed by a lawyer before this is relied on**: the exact triggers, deadlines, report contents and penalties are theirs to state, not engineering's.

> **OWNER AND LAWYER ACTION ITEMS.** Updated 2026-11-18. This runbook is a **draft**; it has not been adopted and contains **no legal advice**.
> *Owner:* name the incident lead, backup, technical responder, communications owner and legal adviser (section 2); fill the contact sheet (section 11); run the first tabletop exercise (section 10) and record it; confirm how to revoke sessions and rotate keys on the real server.
> *Lawyer:* every `[LAWYER]`: the exact duties, triggers and deadlines under the DPDP Act and Rules and (if EU/UK people are affected) GDPR, what the regulator and affected-people notices must contain, retention of the incident log, contract-based duties to business customers.
> Nothing in this file states a legal deadline as fact; the 72-hour and "without delay" wording is the checklist's assumption, to be confirmed.

## 1. What counts

A **personal-data incident** is any event where personal data may have been accessed, disclosed, altered, lost or made unavailable without authority. Examples specific to FlowQR:

* a leaked or stolen password-hash table, session token, Google refresh token, `SECRET_KEY`, database or backup file;
* one business seeing another business's data (a failure of tenant isolation or row-level security);
* a public QR/review page exposing more than it should;
* a mailbox, host, Cashfree, Google Cloud or Sentry account taken over;
* a wrong or malicious write to a business's Google profile caused by FlowQR (see section 6);
* a provider telling us they were breached.

When unsure, treat it as an incident and decide later. Declaring a false alarm is cheap.

## 2. Who decides

| Role | Person | Backup | Does |
|---|---|---|---|
| Incident lead | [NAME, phone, email] | [NAME] | declares the incident, owns the timeline, makes the notify/not-notify call with legal advice |
| Technical responder | [NAME] | [NAME] | containment, evidence, recovery |
| Legal adviser | [FIRM / NAME, 24h phone] | | confirms duties, wording, deadlines |
| Customer communications | [NAME] | [NAME] | messages to affected people |

Decision rule: the incident lead decides. If the lead is unreachable for [2] hours, the backup decides. Nobody waits for certainty to start containment.

## 3. The clock

Write down the **time the incident was first known** the moment it is declared (UTC and IST). Every deadline runs from there.

| Duty | Who | Deadline to confirm with the lawyer |
|---|---|---|
| Tell the Data Protection Board of India (DPDP Act 2023 and Rules) | FlowHQ as data fiduciary | Report to the Board **without delay**, then a detailed report within **72 hours** of becoming aware (the Board may extend it). From the DPDP Rules 2025, Rule 7, as summarised by law firms; the government explainer confirms only "without delay" for people. [LAWYER: confirm against the Gazette text] |
| Tell each affected person | FlowHQ | **Without delay**, in plain language: what happened, the likely effect, what was done, what they can do, and a contact for help (government explainer, 17 Nov 2025) |
| Tell the EU/UK supervisory authority (GDPR/UK GDPR) if EU/UK people are affected | FlowHQ | **72 hours** from becoming aware, as the checklist states; [LAWYER: confirm applicability] |
| Business customers whose own customers' data is involved (FlowQR processes reviews for them) | FlowHQ as processor | [LAWYER: contract-dependent; tell without undue delay] |
| Payment providers, Google, others per their agreements | FlowHQ | [CHECK each agreement] |

## 4. First hour: contain, preserve, assess

Do these in order. Record each action and its time in the incident log (section 8).

1. **Stop the bleeding without destroying evidence.** Do not delete logs, rows or servers. Snapshot first.
2. **Stop automation.** Confirm `AUTONOMY_EMERGENCY_STOP=true` in production (the runtime switch is in `platform_controls`); keep the worker and beat stopped if there is any doubt. This guarantees FlowQR is not writing to anyone's Google profile while investigating.
3. **Cut access.**
   * Suspected stolen sessions: revoke all (`UPDATE auth_sessions SET revoked_at = now() WHERE revoked_at IS NULL`, as the owner role, after taking a snapshot) and force re-login. For one person, `set-admin-password` in the ops CLI already signs that account out (`ops_cli.py`), and the reset-password confirmation revokes that person's sessions (`api/v1/auth.py`).
   * Suspected stolen `SECRET_KEY` or encryption key: rotate per `docs/PRODUCTION_SECRETS_RECOVERY.md` and `docs/PRODUCTION_ENVIRONMENT_VARIABLES.md`; note that rotating the Google token encryption key invalidates stored tokens, so businesses must reconnect.
   * Suspected stolen Google refresh tokens: revoke each at Google (the disconnect route and `GoogleProvider.revoke` do this) and mark connections disconnected. **Revoking real customers' OAuth access needs the owner's explicit decision.**
   * Suspected payment-provider credential exposure: rotate in the provider dashboard; do not touch billing code.
4. **Preserve evidence**: database snapshot, application and proxy logs (access logs already redact OAuth codes and tokens), the Sentry issue ids if enabled, the exact versions deployed (`docs/PRODUCTION_DEPLOYMENT_REPORT.md` tag), screenshots with timestamps.
5. **Scope it**: which tenants, which tables, which people, which time window, what fields. `audit_logs` (IP, action, entity), `auth_sessions` and the autonomy history (hash-chained, tamper-evident) are the first places to look. FlowQR keeps no card numbers; reviewer names/text, emails, phone numbers, Google tokens (encrypted), password hashes (Argon2id) are the data classes that can be involved.
6. **Decide the severity** with the lawyer on the call: is it likely to cause harm to the people involved? Is it a *breach* of personal data under the Act, or a security event with no personal data affected?

## 5. Fix, recover, and prove it

* Close the hole, then recover from the restore procedure in `docs/ROLLBACK_AND_RECOVERY.md` and `docs/PRODUCTION_BACKUP_RESTORE.md` if data was altered or lost. After any restore, **re-run deletions** that happened after the backup (the `account.deleted` audit lines list them) so erased data does not come back.
* Re-enable automation only when the cause is closed, the owner approves, and the emergency stop is lifted deliberately.
* Add a regression test for the cause.

## 6. Incidents unique to an autonomous system

If FlowQR changed a business's Google profile wrongly: stop automation (step 2); read the action's history (`agent_intervention_events`, hash-chained) to see what was proposed, who authorised it and what Google held before; restore the previous value through the normal approval path (an undo is itself an action with consent); tell the business owner the same day. Google's policy forbids automatically reverting changes Google itself made; never script that.

## 7. Telling people (templates for the lawyer to approve)

**To the regulator** [LAWYER: required fields]: what happened and when; what data and how many people (approximate is acceptable at first); the likely consequences; what has been done and will be done; contact of the responsible person [NAME, role, email, phone].

**To affected people**, plain words, no blame, no jargon:
> On [DATE] we found that [WHAT HAPPENED, ONE SENTENCE]. It involved your [DATA: for example name and email address]. It did not involve [WHAT WAS NOT AFFECTED: for example payment card details, which we never hold]. We have [CONTAINMENT DONE]. What you should do: [STEPS: for example change your password; watch for messages asking for codes]. Questions: [CONTACT]. We are sorry. [GRIEVANCE OFFICER / DPO CONTACT per lawyer]

**To a business customer** (processor to controller): the same facts, the list of their records involved, and the help FlowQR will give them with their own duties.

Never include tokens, passwords or full personal records in a message.

## 8. Incident log (copy per incident)

| Time (UTC / IST) | Who | What happened or was done | Evidence location |
|---|---|---|---|
| | | Incident first known | |

Keep it, with the final report, for [LAWYER: period].

## 9. After

Within [14] days: written post-incident review (what failed, what worked, what changes), updated risk list, tests added, policy and this runbook updated. Share the summary with affected business customers if they ask.

## 10. Rehearse

Run a tabletop exercise before launch and [every 6 months]: "a former contractor kept a copy of the database backup" and "a business reports seeing another business's reviews". Time each step in section 4. Record the result here: [DATE, PARTICIPANTS, GAPS FOUND].

## 11. Contact sheet (fill in)

| Need | Contact |
|---|---|
| Hosting / VPS provider | [ ] |
| Domain and DNS | [ ] |
| Cashfree support | [ ] |
| Google Cloud / API contact | [ ] |
| Email (SMTP) provider | [ ] |
| Sentry (if enabled) | [ ] |
| Legal adviser | [ ] |
| Cyber insurance (if any) | [ ] |
| Data Protection Board of India submission route | [LAWYER] |
