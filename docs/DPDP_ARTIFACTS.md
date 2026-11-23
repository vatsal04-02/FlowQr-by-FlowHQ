# DPDP artifacts drafted without a lawyer (2026-11-23)

Everything here was written from the product's real behaviour and from what is publicly known about the DPDP Act 2023 and the DPDP Rules 2025 (see `DPDP_COMPLIANCE.md` for the sources and which details are only from secondary summaries). **None of it has been reviewed by a lawyer.** Give this file and the pages below to the lawyer; every item marked ASSUMPTION is a choice I made, not a legal or commercial fact.

## 1. What was produced

| Artifact | Where | State |
|---|---|---|
| Privacy policy with DPDP rights, consent, grievance, breach, children, cookies | `/privacy` (`frontend/src/app/(marketing)/privacy/page.tsx`) | Written; indexed |
| Hindi privacy notice (Eighth Schedule language) | `/privacy-hi` | **Draft translation**; needs a native-speaker and lawyer check |
| Cookie policy | `/cookie-policy` | Written; indexed |
| Refund and cancellation policy | `/refund-policy` | **Draft; deliberately kept out of search engines** (`refund-policy/layout.tsx`, remove `robots` after sign-off) |
| One-time consent at sign-up | single box on `/register` (and Google sign-up) | Live in code; see section 2 |
| Unsubscribe link and one-click header in notification emails | backend `notifications` | Done and tested |
| Breach plan | `INCIDENT_AND_BREACH_RESPONSE.md` | Draft with blanks for names and phone numbers |
| Grievance procedure (internal) | section 4 below | Draft |
| Questions for the lawyer | section 5 | |

## 2. The "one-time consent for everything"

**What was built.** The sign-up page now has one box that records, in one act: age 18+, that the person has read the Privacy Policy and Terms, and consent to the purposes listed there (running the account and business tools, connecting Google and syncing reviews, AI drafts the user asks for, security, billing and service emails). It works for password and Google sign-up, is server-enforced, never pre-ticked, is in English and Hindi, and the wording version (`2026-11-23.1`) and `privacy_consent: true` are written to the append-only audit log and the user row. Withdrawal is by disconnecting, switching emails off, or deleting the business, as the policy says.

**What it deliberately does not do, and why.**
1. **Google profile automation** (FlowQR changing a Google profile or replying without asking each time) still needs its own consent, per location and per action type, as Google's Business Profile API policy requires it to be "specific and express". A sign-up checkbox cannot satisfy that, and the existing consent records (`services/consent.py`) are untouched. Collapsing them would risk losing Google API access.
2. **Optional extras** such as WhatsApp messaging stay separate and unticked. The Act asks for consent that is specific to a purpose and not bundled with things the service does not need.
3. **Consent already given by existing users** is not rewritten: they accepted the earlier wording, and the audit log shows which version each person saw.

ASSUMPTION for the lawyer: that one itemised notice and one checkbox covering all the core purposes is valid consent under s6, because the purposes are listed in plain words and the person can withdraw. If the lawyer wants separate boxes per purpose, only `register/page.tsx` and its Google twin need to change.

## 3. Assumptions inside the refund policy (the owner must confirm each)
- First payment for a plan is refundable in full if asked within **7 days**.
- Duplicate or wrong charges and "paid but not activated" are refunded in full.
- Unused part of a period is **not** refunded after the 7 days.
- Custom printed cards are not refundable once printing starts; damaged or wrong cards are replaced or refunded if reported within **7 days** of delivery.
- Reply to a refund request within **3 working days**; money back within **7 working days** of approval.
- A failed renewal pauses the plan instead of retrying indefinitely. **Check this against how Cashfree retries mandates before publishing it.**

## 4. Grievance procedure (internal; the policy promises 90 days at most)
1. Requests arrive at the support email. Reply within **2 working days** to acknowledge, and log the date received.
2. Verify the person by having the request come from the account's email address (or an equivalent check for people without an account).
3. Access: give a summary of what is held and who it is shared with (the owner's export covers a business's data). Correction: fix it or explain why not. Erasure: use the account deletion workflow in the admin console. Demo leads are deleted automatically after 365 days.
4. Answer within **30 days** as a target and never later than **90 days**.
5. Tell the person they may complain to the Data Protection Board of India if they are not satisfied.
6. Keep a simple record: date received, request type, date answered, outcome. A spreadsheet is enough for now.

ASSUMPTION: the 2-day and 30-day figures are internal targets, not legal requirements.

## 5. Questions for the lawyer
1. Is the single sign-up box a valid s6 consent for all core purposes, or are per-purpose boxes needed?
2. Exact text of Rules 3, 6, 7, 8 and 9 and the Third Schedule: confirm the 72-hour Board report, the 48-hour erasure notice (and whether it applies to FlowQR), and the log-retention period.
3. Is the daily-rotating visitor hash on the public review page "tracking" if a child scans?
4. The Hindi notice: translation accuracy and whether this layout satisfies the notice requirements.
5. Refund and cancellation text, consumer-protection (e-commerce) disclosures, and GST wording.
6. Processor terms with Google, the AI provider, Cashfree and the mail provider; cross-border transfer position.
7. Whether FlowHQ should appoint a Data Protection Officer or a named grievance officer, and who.
