# India DPDP Act 2023 and Rules 2025: FlowQR status

Written 2026-11-23. **Not legal advice.** The Act is the Digital Personal Data Protection Act, 2023. The Rules were notified in mid-November 2025 and start in stages: the Board provisions at once, consent managers about 13 Nov 2026, and the main duties for businesses (notice, consent, security, breach, rights, children) **18 months after notification, about 13 May 2027**.

**Source quality.** Read in full: the government explainer (PIB, 17 Nov 2025, https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf). The Rules' own text (meity.gov.in) could not be fetched from here, so rule-level details marked **(secondary)** come from law-firm and consultancy summaries and must be checked against the Gazette text by a lawyer before anyone relies on them.

FlowHQ is a **data fiduciary** for its own users (business owners, staff, demo leads) and a **processor** for what a business's customers type on the review page (the business decides why; FlowQR handles it).

| # | Duty (source) | FlowQR today | Gap / action |
|---|---|---|---|
| 1 | Itemised notice, plain language, English or an Eighth Schedule language (Act s5; Rules: separate, clear notice) | Privacy policy lists what is collected, why, who else handles it, retention. Updated 23 Nov: consent grounds, rights, grievance, breach, children, cookies. Offers the notice in Hindi or another scheduled language on request. | A Hindi draft is at `/privacy-hi` (see `DPDP_ARTIFACTS.md`); it **needs a native-speaker and lawyer review**. |
| 2 | Free, specific, informed, unambiguous consent; withdrawal as easy as giving it (s6) | One sign-up box now records age 18+, having read the notice, and consent to the listed core purposes, with a wording version. Google-profile automation and WhatsApp keep their own separate consents. | Lawyer: is one itemised box enough, or are per-purpose boxes needed? See `DPDP_ARTIFACTS.md` section 2. |
| 3 | Reasonable security safeguards; logs and relevant data kept 1 year for detection (Rule 6, **secondary**) | Argon2id, per-business row-level security, encrypted tokens, audit log (IP kept 365 days, entry kept), scrubbed Sentry. | Confirm the 1-year log rule. Application and proxy access logs have no stated retention here. Failing safeguards is the highest penalty tier (up to Rs 250 crore, PIB). |
| 4 | Breach: tell affected people without delay; tell the Board, detailed report within 72 hours (Rule 7, timings **secondary**) | Draft runbook `INCIDENT_AND_BREACH_RESPONSE.md` updated with these timings; privacy page promises notice without delay. | **The runbook is a draft, not adopted**; owner, lead and contacts are blanks. Not notifying a breach: up to Rs 200 crore (PIB). |
| 5 | Erase when purpose served or consent withdrawn; advance notice before erasure (Rule 8, **secondary**: 48 hours) | Business deletion with 14-day cancellable grace; retention jobs (sessions 30 d, reset tokens 30 d, leads 365 d, review-assistant text 90 d, Google content 30 d once its switch is on). | Backups keep deleted data until they expire: state the backup window in the policy once measured. Whether the 48-hour notice applies to FlowQR (it is tied to classes in the Third Schedule) is a lawyer question. |
| 6 | Publish the contact of the person who answers questions (Rule 9) | Privacy page shows the support email and `GRIEVANCE_OFFICER_NAME`; footer shows `LEGAL_COMPANY_ADDRESS`. | **Set `SUPPORT_EMAIL`, `GRIEVANCE_OFFICER_NAME`, `LEGAL_COMPANY_ADDRESS` in production** (empty = not shown, never invented), and name a real person. |
| 7 | Rights: access summary, correct/update, erase, grievance, nominate; answer within 90 days (ss11-14; PIB: 90 days) | Export (owner), in-app correction, deletion, grievance by email. The policy states the 90-day maximum and the nomination right. | Requests arrive by email and are handled by hand: no ticket queue or 90-day timer (the admin workflow covers deletion and export only). Nomination has no in-product form. |
| 8 | Children under 18: verifiable parental consent; no tracking, behavioural monitoring or targeted ads (s9) | Account holders tick an 18+ box (server-enforced, recorded). No ads. Review page stores no name, phone or email; unique scans are counted with a daily-rotating hash. | A minor can still open a review page. Lawyer: is the daily hash "tracking"? Customer words go to the AI provider. Up to Rs 200 crore for child-related failures (PIB). |
| 9 | Processor contracts; the fiduciary stays responsible (s8) | Providers listed (Google, AI provider, Cashfree, mail). | Written data-processing terms with each provider are not in the repo. Check where each one processes data. |
| 10 | Significant Data Fiduciary extras: audit, impact assessment (s10) | Not designated. | Only the Government designates; revisit if volume grows. |
| 11 | Consent managers (Rule 4) | None integrated. | Optional; no action. |
| 12 | Complaint to the Data Protection Board after the fiduciary's own grievance process | Policy says so. | none |

## The "20 things" list (screenshot), item by item

| # | Item | Status |
|---|---|---|
| 1 | Privacy policy | Live; expanded for DPDP on 23 Nov |
| 2 | Terms of service | Live; 18+ clause added |
| 3 | Refund policy | **Draft written 23 Nov** (`/refund-policy`, hidden from search engines until confirmed). Its numbers are assumptions listed in `DPDP_ARTIFACTS.md`. |
| 4 | Cookie policy | **Added** at `/cookie-policy`, linked from the footer and privacy page, in the sitemap |
| 5 | Cookie consent banner | Not applicable: only essential cookies, no analytics or ad scripts, so a banner would block nothing. If a tag (e.g. the `dataLayer` hook in `lib/track.ts`) is ever installed, a banner becomes mandatory first. |
| 6 | Form consents | Demo form unticked and linked; sign-up age box; automation consents |
| 7 | Collect only needed data | No date of birth (an 18+ declaration only); no name, phone or email from scans |
| 8 | Audit third-party SDKs | Fonts self-hosted; payment scripts load only on click; list in `PRIVACY_COMPLIANCE_AUDIT.md` |
| 9 | No dark patterns | Cancel is an in-app button; pricing shows renewal and GST text |
| 10 | No hidden fees | "+ GST as applicable" shown; confirm the exact GST treatment with the accountant |
| 11 | No fake reviews | Terms forbid them; FlowQR never posts a customer's review |
| 12 | No unsupported claims | Marketing copy scanned for guarantees and rankings: none found on this branch. Re-scan before each launch. |
| 13 | Alt text | Informative images have text; the `alt=""` ones are decorative (avatar, logo beside the name, industry photos with credit text) |
| 14 | Colour contrast | **Not measured** in this pass |
| 15 | Keyboard navigation | Focus styles exist; **not tested end to end** in this pass |
| 16 | Business details | Company name everywhere; address and named contact appear once the env vars are set |
| 17 | Age consent | 18+ box at sign-up, in the Terms and in the policy |
| 18 | Unsubscribe link | **Added** to notification emails, plus a one-click header when `API_PUBLIC_URL` is set |
| 19 | Licensed stock images | Industry photos credit Wikimedia on `/industries`; confirm each licence's attribution wording |
| 20 | Data deletion | Self-service with a grace period, plus the `/data-deletion` page |

## Questions for a lawyer
1. Rule 7 and Rule 8 exact wording, and whether the 48-hour erasure notice applies to FlowQR.
2. Is a single "by creating an account you agree" sentence valid consent, or are separate boxes needed?
3. Is the daily-rotating visitor hash "tracking" of a possible child on the public review page?
4. Hindi / Eighth Schedule notice: who translates and signs off.
5. Refund policy text and GST wording.
