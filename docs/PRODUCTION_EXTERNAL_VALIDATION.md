# External validation: Google Business Profile and Places

Statuses: **PASS**, **FAIL**, **BLOCKED**, **NOT TESTED**. A test double is never a result here. Everything below was run **from the owner's development machine against the development stack**, not against production (which does not exist yet), on the owner's authorised test profile. The full procedure and evidence log are in `docs/LIVE_VALIDATION_RUNBOOK.md` section 9.

## Google Business Profile (test profile "FlowHQ", `flowhqofficial@gmail.com`, authorised by the owner for `locations/6589197820321114990`)

| Check | Status | Evidence |
|---|---|---|
| OAuth connection of the test account | **PASS** (development stack, consent screen in Testing mode, account added as a test user) | connection `approved`, one location found |
| Scopes and permissions | **PASS** for `business.manage`; the app refuses a connection that lacks it | `test_google_and_reviews` (doubles) and the live connection |
| Profile read | **PASS** | description, metadata, verification state read live |
| **Post: create, read back, delete, confirm gone** | **PASS** | live, read back from Google (2026-11-15) |
| **Photo: upload, read back, delete, confirm gone** | **PASS** on the second run | first run failed `400 invalid argument` because the **test image was under Google's 10 KB minimum** (a tool bug, fixed); second run read back with a live URL and removed |
| **Description: change, read back twice, restore, read back** | **PASS** | first attempt inconclusive (the profile had no description); after the owner wrote one, passed on two independent reads and restored |
| Review reply (stage 1), **including an automatic template reply** | **NOT TESTED** | needs a real review on the test profile from a different Google account |
| Governed path through FlowQr's approval policy (stage 2), hours/categories/phone/website (stage 3) | **NOT TESTED** | |
| Autonomous Level 1 and Level 2 changes, emergency stop against real Google, 28-day follow-ups (stage 4) | **NOT TESTED** | |
| Review synchronisation from real Google | **NOT TESTED on the test profile** (an earlier read-only check exists in `docs/LAUNCH_REPORT.md`) | |
| Production OAuth redirect URIs | **NOT TESTED** | register `https://api.flowqr.site/api/v1/google/callback` (and the sign-in callback) in Google Cloud |
| Google verification of the OAuth app for real customers | **BLOCKED** | the consent screen is in **Testing** mode: only listed test users (up to 100) can connect, and refresh tokens expire after 7 days |

**Rule that stands:** no real customer is connected to approved or automatic Google writes until stages 1 to 4 have passed on the test profile. Because autonomy and template replies are on by default, production must start with the emergency stop on (`AUTONOMY_EMERGENCY_STOP=true`) until then, or with the validation complete.

## Places API (New)

| Check | Status | Evidence |
|---|---|---|
| Real geo-grid scan, one business, 3x3 grid, keyword "physiotherapist near me" | **PASS (partly)** | 9 of 9 points returned, ranks 2 to 14, the business found at every point. **Run twice by mistake, so 18 searches were made** |
| Actual request count | **PASS** | the usage ledger recorded 18 `searchText` requests, one per grid point, all ok. **The real billed requests per point must still be read from Google Cloud Console**: do not assume one point equals one request |
| Actual cost | **BLOCKED** | no verified price: `API_PRICES` is empty, so cost is shown as "unpriced" (never as zero) |
| Plan allowance and map limit enforcement | **PASS** | the scan was checked against the plan's allowance first (Growth: 100 points a month, 91 left before the second scan) |
| Budget exhaustion, failure handling, retries | **NOT TESTED live** (tests with doubles only) | |
| Saved scan history and heatmap | **PASS (data)**; heatmap view **NOT TESTED in a browser on live data** | scans and points stored |
| Platform-wide monthly Places cap | **NOT SET**: `RANK_PLATFORM_MONTHLY_CAP=0` means no ceiling. Set it before enabling scans in production | |
| Production Places key | **BLOCKED** | the key used was pasted into a chat and must be rotated; production needs its own restricted key (Places API (New) only, quota cap, budget alert) |

## Production release rules applied

Unvalidated autonomous Google writes, unpriced Places scans and unapproved geo-grid limits are not enabled for real customers: on a new production database **maps are off for every plan** until an administrator sets the allowances (the owner chose a Conservative set on the development stack: Growth 1 map / 25 points / 100 a month, Pro 3 / 25 / 450, Starter off; it was applied there only); no Places price is configured; no payment provider is wired. The emergency stop and the approval controls are unchanged.
