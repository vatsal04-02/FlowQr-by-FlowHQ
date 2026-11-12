# Google OAuth & Business Profile API: setup and approval requirements

> **Verification status (updated 2026-11-10).** The Google-side process below was checked against Google's own pages on 2026-11-10 (prerequisites, basic setup, limits, FAQ, OAuth and the API reference). Items still marked 🔎 could not be confirmed from those pages and must be checked before you rely on them. The FlowQR-side items (env vars, redirect URI, scopes, endpoints, behaviour without credentials) are taken from this repository.
>
> **Where things stand:** real OAuth credentials are in place and the token exchange works against live Google. **Every Business Profile API is currently disabled on the Cloud project**, so no Business Profile call has ever succeeded. See "What was actually verified against Google" at the end, and [GOOGLE_API_AUDIT.md](GOOGLE_API_AUDIT.md) for the call-by-call audit.

## "Continue with Google" sign-in (separate from everything below)

Logging in with Google uses its **own OAuth client**, so the sensitive Business Profile scope and its review process can never block or break login.

| | Sign-in client | Business Profile client (rest of this doc) |
|---|---|---|
| Env vars | `GOOGLE_LOGIN_CLIENT_ID` / `GOOGLE_LOGIN_CLIENT_SECRET` / `GOOGLE_LOGIN_REDIRECT_URI` | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` |
| Scopes | `openid email profile` (non-sensitive: no Google verification review) | `business.manage` (+ `openid email`) |
| Redirect URI | `https://<APP_DOMAIN>/api/v1/auth/google/callback` | `https://<APP_DOMAIN>/api/v1/google/callback` |
| Stores Google tokens? | No (ID token is verified once, then discarded) | Yes, encrypted |

Cloud Console: Credentials → Create OAuth client ID → Web application → add the redirect URI exactly as above (one entry per environment). Consent screen: External, scopes `openid`, `email`, `profile`, publishing status *In production*. In staging/production the config guard refuses to boot if the redirect URI is not a public https URL or if the sign-in client ID equals the Business Profile one.

Behaviour: state + nonce + PKCE (S256) in a signed, HttpOnly, 10-minute, path-scoped cookie; ID token checked for RS256 signature (Google JWKS), issuer, audience, expiry and nonce; email trusted only when `email_verified=true`. A new Google identity links to an existing account **only if that account's email is already verified**; otherwise it is refused (`account_unverified`) and the owner must log in with their password and use *Settings -> Sign-in methods -> Connect Google* (`POST /auth/google/link`, CSRF-protected). Google-only users have no password until they choose one (*Settings -> Set a password*, or "Forgot password").

## What FlowQR needs from Google (Business Profile)

| Need | Detail |
|---|---|
| One Google Cloud project | owned by FlowHQ (not per customer). Each customer signs in with **their own** Google account through FlowQR's OAuth flow; no per-customer setup. |
| OAuth 2.0 Web client | gives `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| Authorised redirect URI | exactly `https://<APP_DOMAIN>/api/v1/google/callback` (= `GOOGLE_REDIRECT_URI`; staging and production need separate entries or separate clients) |
| Scope | `https://www.googleapis.com/auth/business.manage` (+ `openid email` to display the connected account). Nothing else is requested. |
| API access approval | Google must approve **this Cloud project** for the Business Profile APIs (access is granted per project) |

## APIs FlowQR calls (enable all four on the Cloud project)

| API name in the Cloud Console API Library | Service name (appears in error messages) | Used for |
|---|---|---|
| My Business Account Management API | `mybusinessaccountmanagement.googleapis.com` | list accounts |
| My Business Business Information API | `mybusinessbusinessinformation.googleapis.com` | locations; description, hours, categories, phone, website |
| Google My Business API (v4) | `mybusiness.googleapis.com` | **reviews and replies**, local posts, media |
| Business Profile Performance API | `businessprofileperformance.googleapis.com` | impressions, calls, website clicks, directions, bookings |

All four were confirmed **disabled** on FlowQR's project on 2026-11-10 (live HTTP 403 `SERVICE_DISABLED` for each). Google's setup page says the *Google My Business API* is only visible in the API Library to projects whose access request has been approved, so it may not be possible to enable that one until approval. The other three can be enabled from the API Library today.

Google's setup page also lists Lodging, Place Actions, Notifications and Verifications APIs. FlowQR does not call them; enabling them is harmless but unnecessary.

Reviews, posts and media still live on the v4 surface and are not on Google's deprecation schedule as of 2026-11-10. If Google moves or retires any surface, the matching method in `HttpGoogleProvider` is the only place to change.

## Step-by-step

1. **Create the Cloud project** (e.g. "FlowQR Production") under a FlowHQ-owned Google account or organisation. Note the **project number** (Cloud Console, Project info card).
2. **Meet the prerequisites.** Google requires that you "manage a Google Business Profile that is verified and active for 60+ days" and have a website representing that business.
3. **Request access.** Submit the GBP API contact form (https://support.google.com/business/contact/api_default), choosing **"Application for Basic API Access"**, with the project number. Use an email address that is listed as an owner or manager of the Business Profile; Google asks that the email domain match the website domain. Google's FAQ says requests are reviewed within 14 days and a follow-up email is sent. Access is granted per Cloud project.
4. **Enable the four APIs** in Cloud Console. For each one: select the FlowQR project (top bar) → **APIs & Services → Library** → search the API name from the table above → open it → **Enable**. Direct links (add your project in the selector): `https://console.cloud.google.com/apis/library/<service name>`, e.g. `.../apis/library/mybusinessaccountmanagement.googleapis.com`. Afterwards **APIs & Services → Enabled APIs & services** must list all four. If *Google My Business API* does not appear in the Library, the access request (step 3) has not been approved yet. Allow a few minutes after enabling before re-testing.
5. **Check whether you are approved** in Cloud Console → APIs & Services → the API → Quotas. Google's rule: a quota of **0 QPM means not approved; 300 QPM means approved.** Do not file a quota-increase request to get from 0 to 300; submit the access application instead.
6. **Run the read-only check** and read the result:
   ```
   docker compose exec api python -m app.cli google-smoke --connection <google_connections.id>
   ```
   | Result | Meaning |
   |---|---|
   | `NOT APPROVED … API not enabled on the project (<service>)` | Step 4 is not done for that API. *(This is the current state.)* |
   | `RATE LIMITED` on every call | The APIs are enabled but the quota is 0: the access request is not approved yet. |
   | `PASS` on accounts, locations, reviews, posts, media, performance | Reads work. Writes are still untested; see "Testing sequence". |
7. **Configure the OAuth consent screen**
   - User type **External**; app name "FlowQR by FlowHQ"; support email; developer contact email.
   - App home page, **privacy policy URL** and terms URL (these pages **do not exist yet**: build them first).
   - **Authorised domains**: your marketing and app root domain, verified in Google Search Console 🔎.
   - Add the scope `https://www.googleapis.com/auth/business.manage`.
   - **Publishing status: "In production".** Google documents that an External app in *Testing* is issued refresh tokens that **expire after 7 days** (unless only name/email/profile scopes are requested, which is not the case here). That would disconnect every customer weekly. FlowQR marks such a connection *revoked* and asks to reconnect, but it is not an acceptable steady state.
   - Other documented ways a refresh token stops working: unused for six months; the user revokes access; more than 100 live refresh tokens for one Google account on one client (the oldest is invalidated silently).
8. **OAuth app verification** 🔎. Because the scope is sensitive, expect Google to require verification before more than a small number of users can connect: verified domain ownership, a privacy policy that discloses the data you access and why, a justification for the scope, and a demo video of the OAuth flow. Allow days to weeks. (Not re-checked on 2026-11-10.)
9. **OAuth client** (Credentials → OAuth client ID → Web application) with the redirect URI above, values in the server `.env`:
   ```
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=https://app.flowqr.co.in/api/v1/google/callback
   ```
   then `docker compose ... up -d api worker beat`. *(Done for local development.)*

### What customers see while Google is not ready

| State | Shown on the Google connection page | Stored as `google_connections.api_access` |
|---|---|---|
| No OAuth credentials on the server | "Configuration pending" | n/a |
| Sign-in works, an API is disabled on the project | "A Google API is switched off for FlowQR", naming the API | `api_disabled` |
| Sign-in works, quota 0 | "Awaiting Google approval" | `awaiting_approval` |
| Reads have succeeded at least once | normal location list | `approved` |

In every one of these states manual review-link mode (cards, QR campaigns, AI writing assistant) keeps working, and nothing is simulated.

### Limits to know about (from Google's limits page)

* 300 requests per minute per API by default once approved. Exceeding it returns HTTP 429.
* **10 edits per minute per Business Profile**, which cannot be raised. FlowQR refuses the 11th edit locally.
* There is no sandbox: every call acts on real listings.

## Use-case text for the access request (edit before sending)

> FlowQR (https://flowqr.co.in) is a SaaS for small local businesses in India. Business owners connect **their own** Google Business Profile account to FlowQR to (1) read their reviews, (2) draft replies that **the owner reviews and approves before anything is posted**, and (3) update their own profile information, posts and photos. We do not post on behalf of anyone without explicit per-action owner approval, we do not request or incentivise reviews in exchange for rewards, we do not filter or gate reviews by rating, and we store OAuth refresh tokens encrypted and never expose them to browsers. We access only the locations the owner selects.

## Testing sequence once credentials exist (staging)

0. Run `python -m app.cli google-smoke --connection <id>` first. It is read-only and tells you whether the APIs are enabled and approved before you touch the UI.
1. Put real values in `.env.staging` (`GOOGLE_*`, redirect URI on the staging host, which must be a **public** domain Google can redirect to; use a real staging subdomain with a public certificate, not the `.dev` local-CA example).
2. Sign in as a business owner → *Google connection* → **Connect Google**. Expected: consent screen → redirect back to `/google?connected=1` → locations listed.
3. Map a location, *Save & sync*; reviews appear in *Reviews* and `google_locations.last_sync_status = ok`.
4. Draft → approve → publish a reply on a **test location you control**; confirm it appears on Google and `reply_logs.success = true`. Retry/failed paths: temporarily revoke access in your Google account security settings and confirm FlowQR marks the connection *revoked*.
5. Try each Profile tool (info/hours/category, post, photo, performance). The request and response shapes were audited against Google's reference on 2026-11-10 ([GOOGLE_API_AUDIT.md](GOOGLE_API_AUDIT.md)), but **no successful call has been made yet, so still expect surprises on first contact**. Do the first reply, post and profile edit by hand on a test location you control: there is no sandbox.
6. Check that a reply shows Google's moderation state. A reply Google marks `REJECTED` must appear in FlowQR as failed, not published.

## What was actually verified against Google

Everything else in the test suite uses a labelled fake or a mocked HTTP transport. These are the only real exchanges with Google:

| Date | Call | Result |
|---|---|---|
| earlier session | token endpoint with a dummy client | HTTP 401 `invalid_client`, mapped to an error (not a revocation) |
| earlier session | Account Management API with a bogus token | HTTP 401, mapped to "reconnect" |
| **2026-11-10** | refresh-token exchange with the real client and a real stored token | **PASS**: access token issued, scope includes `business.manage` |
| **2026-11-10** | `accounts.list`, `accounts.locations.list`, `categories.list`, v4 `reviews.list`, performance `fetchMultiDailyMetricsTimeSeries` | **HTTP 403 `SERVICE_DISABLED`** on all five: the four APIs are not enabled on the project. FlowQR classified each correctly and named the API. |

**Not verified against Google:** any successful Business Profile read or write (accounts, locations, reviews, replies, posts, media, profile edits, performance), the quota-0 response of an unapproved project, rate-limit responses, and the consent-screen flow end to end in a browser during this audit.

## Official pages (checked 2026-11-10 unless marked 🔎 above)
* https://developers.google.com/my-business/content/prereqs
* https://developers.google.com/my-business/content/limits
* https://developers.google.com/my-business/content/faq
* https://developers.google.com/my-business/content/sunset-dates
* https://developers.google.com/my-business/content/basic-setup
* https://developers.google.com/identity/protocols/oauth2 (refresh-token expiry; production vs testing)
* https://support.google.com/cloud/answer/9110914 (OAuth app verification)
