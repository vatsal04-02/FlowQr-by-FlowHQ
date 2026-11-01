# Google OAuth & Business Profile API: setup and approval requirements

> **Verification status.** `developers.google.com` was **not reachable** from the session that wrote this document, so the *Google-side process* below (approval form, eligibility rules, quota numbers, verification requirements) is written from prior knowledge and is **UNVERIFIED**. Every item marked 🔎 must be checked against the linked Google page before you rely on it. The *FlowQR-side* items (env vars, redirect URI, scopes, endpoints used, behaviour without credentials) are taken from this repository and **are** accurate.

## What FlowQR needs from Google

| Need | Detail |
|---|---|
| One Google Cloud project | owned by FlowHQ (not per customer). Each customer signs in with **their own** Google account through FlowQR's OAuth flow; no per-customer setup. |
| OAuth 2.0 Web client | gives `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| Authorised redirect URI | exactly `https://<APP_DOMAIN>/api/v1/google/callback` (= `GOOGLE_REDIRECT_URI`; staging and production need separate entries or separate clients) |
| Scope | `https://www.googleapis.com/auth/business.manage` (+ `openid email` to display the connected account). Nothing else is requested. |
| API access approval | Google must approve **this Cloud project** for the Business Profile APIs 🔎 |

## APIs FlowQR calls (enable all of them on the Cloud project)

| Google API 🔎 (names as they appear in the API Library) | Used for | Endpoint family in `services/google/provider.py` |
|---|---|---|
| My Business Account Management API | list accounts | `mybusinessaccountmanagement.googleapis.com/v1/accounts` |
| My Business Business Information API | locations; description, hours, categories, phone, website | `mybusinessbusinessinformation.googleapis.com/v1/...` |
| Google My Business API (v4, legacy surface) | **reviews and replies**, local posts, media | `mybusiness.googleapis.com/v4/accounts/{a}/locations/{l}/reviews|localPosts|media` |
| Business Profile Performance API | impressions / calls / website clicks / directions | `businessprofileperformance.googleapis.com/v1/locations/{id}:fetchMultiDailyMetricsTimeSeries` |

If Google has moved or retired any of these surfaces since this was written, the corresponding method in `HttpGoogleProvider` is the **only** place to change (everything else talks to the `GoogleBusinessProvider` interface).

## Step-by-step 🔎

1. **Create the Cloud project** (e.g. "FlowQR Production") under a FlowHQ-owned Google account/organisation. Note the **project number**.
2. **Request Business Profile API access** for that project via Google's *Business Profile API access request* form (linked from https://developers.google.com/my-business/content/prereqs 🔎). Expect to be asked for: project number, business/company name, a **business email on your own domain**, your website, a clear description of the use case (see template below), and whether you manage locations for others.
   - Typical prerequisites 🔎: a Google Business Profile account that is **verified and has been active for some time** (Google has stated a minimum age; check the current number), and a legitimate business website.
   - Until approved, API calls usually fail with a **quota of 0 / permission-denied** error. FlowQR then shows the connection as errored, and **manual review-link mode keeps working**.
3. **Enable the four APIs** above on the project once access is granted (approval is what unlocks them; enabling alone is not enough 🔎).
4. **Confirm quota** in Cloud Console → APIs & Services → each API → Quotas. Google has documented a default requests-per-minute figure after approval 🔎; FlowQR's sync (every 30 min per location, with backoff on 429) is far below any plausible limit.
5. **Configure the OAuth consent screen**
   - User type **External**; app name "FlowQR by FlowHQ"; support email; developer contact email.
   - App home page `https://<MARKETING_DOMAIN>`, **privacy policy URL** and terms URL (these pages **do not exist yet**: build them first).
   - **Authorised domains**: your marketing/app root domain, verified in Google Search Console 🔎.
   - Add the scope `business.manage`.
   - **Publishing status: set to "In production".** While an External app is in *Testing*, Google expires refresh tokens after **7 days** 🔎, which would silently disconnect every customer weekly. FlowQR handles `invalid_grant` by marking the connection *revoked* and asking to reconnect, but this is not an acceptable steady state.
6. **OAuth app verification** 🔎. Because the scope is sensitive, expect Google to require verification before more than a small number of users (Google's "unverified app" limit and warning screen) can connect. Typical requirements: verified domain ownership, privacy policy that discloses the data you access and why, a justification for the scope, and **a demo video** showing the OAuth flow and the in-product use of the data. Allow **days to weeks**.
7. **Create the OAuth client** (Credentials → OAuth client ID → Web application) with the redirect URI above. Put the values in the server `.env`:
   ```
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=https://app.flowqr.co.in/api/v1/google/callback
   ```
   then `docker compose ... up -d api worker beat`. The *Configuration pending* banner disappears.

## Use-case text for the access request (edit before sending)

> FlowQR (https://flowqr.co.in) is a SaaS for small local businesses in India. Business owners connect **their own** Google Business Profile account to FlowQR to (1) read their reviews, (2) draft replies that **the owner reviews and approves before anything is posted**, and (3) update their own profile information, posts and photos. We do not post on behalf of anyone without explicit per-action owner approval, we do not request or incentivise reviews in exchange for rewards, we do not filter or gate reviews by rating, and we store OAuth refresh tokens encrypted and never expose them to browsers. We access only the locations the owner selects.

## Testing sequence once credentials exist (staging)

1. Put real values in `.env.staging` (`GOOGLE_*`, redirect URI on the staging host, which must be a **public** domain Google can redirect to; use a real staging subdomain with a public certificate, not the `.dev` local-CA example).
2. Sign in as a business owner → *Google connection* → **Connect Google**. Expected: consent screen → redirect back to `/google?connected=1` → locations listed.
3. Map a location, *Save & sync*; reviews appear in *Reviews* and `google_locations.last_sync_status = ok`.
4. Draft → approve → publish a reply on a **test location you control**; confirm it appears on Google and `reply_logs.success = true`. Retry/failed paths: temporarily revoke access in your Google account security settings and confirm FlowQR marks the connection *revoked*.
5. Try each Profile tool (info/hours/category, post, photo, performance). **Expect to adjust field names on first contact** with the real API (the code has only ever run against a fake and against Google's error responses; see `STAGING_READINESS.md`).

## What was actually verified against Google (this session)

* `HttpGoogleProvider.build_auth_url` produces a well-formed authorization URL (client id, redirect URI, `access_type=offline`, `prompt=consent`, state).
* Real call to `oauth2.googleapis.com/token` with a dummy client → **HTTP 401 `invalid_client`**, mapped correctly to a `GoogleAPIError`.
* Real call to the Account Management API with a bogus token → **HTTP 401**, mapped to `GoogleAuthRevoked`.
* **Not verified:** any successful call (consent, token exchange, accounts, locations, reviews, replies, posts, media, performance). **BLOCKED** on credentials and API approval.

## Official pages to check 🔎
* https://developers.google.com/my-business/content/prereqs
* https://developers.google.com/my-business/content/basic-setup
* https://developers.google.com/identity/protocols/oauth2 (refresh-token expiry; production vs testing)
* https://support.google.com/cloud/answer/9110914 (OAuth app verification)
