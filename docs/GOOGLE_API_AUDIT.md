# Google Business Profile API audit

Audit date: **2026-11-10**. Code audited: `backend/app/services/google/provider.py` (`HttpGoogleProvider`), the only place FlowQR talks to Google.

## How much of this is verified, and against what

There are three different levels of evidence in this document. They are not interchangeable.

| Level | What it means | What it covers |
|---|---|---|
| **Checked against documentation** | Each request and response shape was compared with Google's published reference page (listed per call below). | Every call in the table below. |
| **Pinned by mocked tests** | `backend/tests/test_google_contract.py` runs the real provider code against a mock HTTP transport and asserts the exact method, URL, query and body, and the parsing of documented response shapes. No request leaves the machine. | Every call in the table below. |
| **Verified against live Google** | A real request was sent to Google with a real OAuth token and the real answer was observed. | **Only** the OAuth token refresh and the "API not enabled" error path. See "Live results". |

The mocked tests prove the code matches the documentation. They do not prove Google behaves as documented. **No successful Business Profile call (accounts, locations, reviews, replies, posts, media, performance) has ever been made by this code against live Google.**

## Live results (2026-11-10)

Run with `python -m app.cli google-smoke --connection <id>` (read-only) using the Google connection stored in the local development database.

| Call | Live result |
|---|---|
| OAuth refresh-token exchange (`oauth2.googleapis.com/token`) | **PASS**. Access token issued, `expires_in=3599`, granted scope includes `business.manage`. |
| `accounts.list` | **HTTP 403 `SERVICE_DISABLED`**: *My Business Account Management API has not been used in project … before or it is disabled.* |
| `accounts.locations.list`, `categories.list` | **HTTP 403 `SERVICE_DISABLED`** for `mybusinessbusinessinformation.googleapis.com` |
| v4 `reviews.list` | **HTTP 403 `SERVICE_DISABLED`** for `mybusiness.googleapis.com` |
| `fetchMultiDailyMetricsTimeSeries` | **HTTP 403 `SERVICE_DISABLED`** for `businessprofileperformance.googleapis.com` |

What this establishes:

1. **The OAuth client and consent work.** A real refresh token is stored (encrypted) and can be exchanged.
2. **The blocker today is that the four APIs are not enabled on the Cloud project**, which is something FlowHQ fixes in Cloud Console. It is *not yet* evidence about Google's access approval: a project can only show "quota 0 / not approved" once the API is enabled. An earlier build labelled this connection "awaiting approval (quota 0)"; that label was a guess and was wrong. The connection row still carries that old text until someone presses **Re-check** on the Google connection page, which re-runs the call and stores the accurate state.
3. **FlowQR's error classification for this case is correct on real data.** Google's actual body is `error.status = PERMISSION_DENIED` with a `google.rpc.ErrorInfo` detail whose `reason` is `SERVICE_DISABLED` and whose `metadata` holds `service`, `serviceTitle`, `consumer`, `containerInfo` and `activationUrl`. The captured bodies (project number removed) are fixtures in `test_google_contract.py` (`test_the_error_google_really_returns_for_a_disabled_api_names_that_api`).

Next step to learn more: enable the APIs listed in [GOOGLE_SETUP.md](GOOGLE_SETUP.md), run the smoke command again, and record the new result here. The expected outcomes are either success, or HTTP 429 on every call (quota 0: access request not approved).

## Call-by-call audit

"Doc" links are under `https://developers.google.com/my-business/reference/`.

| FlowQR method | Request sent | Doc page | Status after this audit |
|---|---|---|---|
| `build_auth_url` | `accounts.google.com/o/oauth2/v2/auth` with `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`, scope `openid email …/auth/business.manage` | identity `/protocols/oauth2/web-server` | Matches. `plus.business.manage` is a deprecated alias Google still lists; FlowQR accepts it when *checking* a granted scope but never requests it. |
| `exchange_code`, `refresh_access_token` | `POST oauth2.googleapis.com/token` (form) | same | Matches. `invalid_grant` → reconnect. **Refresh verified live.** |
| `revoke` | `POST oauth2.googleapis.com/revoke` | same | Matches. Best effort. |
| `list_accounts` | `GET mybusinessaccountmanagement…/v1/accounts?pageSize=20` (+`pageToken`) | `accountmanagement/rest/v1/accounts/list` | Matches. 20 is both default and maximum. |
| `list_locations` | `GET mybusinessbusinessinformation…/v1/{account}/locations?readMask=name,title,storefrontAddress,metadata&pageSize=100` | `businessinformation/rest/v1/accounts.locations/list` | Matches. `readMask` is required; 100 is the maximum. Reads `metadata.placeId` and `metadata.newReviewUri`. |
| `get_location_details` | `GET …/v1/{location}?readMask=…` | `businessinformation/rest/v1/locations/get` | Matches. `readMask` is required. Handles `openTime: {}` (Google omits zero values, so midnight arrives empty) and `closeTime.hours = 24`. |
| `update_location` | `PATCH …/v1/{location}?updateMask=…` | `businessinformation/rest/v1/locations/patch` | **Fixed.** Google documents that `phoneNumbers` and `categories` cannot be updated one sub-field at a time. The old code sent only the changed sub-field, which would have cleared additional phone numbers or the primary category. It now reads the current value and sends both. |
| `search_categories` | `GET …/v1/categories?regionCode=IN&languageCode=en&view=BASIC&filter=displayName=<text>` | `businessinformation/rest/v1/categories/list` | **Fixed.** The filter was sent with quotes (`displayName="x"`); the documented form has none. `regionCode`, `languageCode` and `view` are all required and all sent. Search is prefix-only by Google's design. |
| `list_reviews` | `GET mybusiness.googleapis.com/v4/{account}/{location}/reviews?pageSize=50&orderBy=updateTime desc` | `rest/v4/accounts.locations.reviews/list` | Matches. 50 is the maximum. **Added:** reads `reviewReply.reviewReplyState` and `policyViolation` (added by Google in 2026). |
| `reply_to_review` | `PUT …/v4/{review}/reply` body `{"comment": …}` | `rest/v4/accounts.locations.reviews/updateReply` | **Fixed.** A 200 means Google stored the reply, not that it is public: the returned state can be `PENDING` or `REJECTED`. FlowQR used to mark every 200 as "published". A rejected reply is now a failed publish with Google's reason. The 4096-**byte** limit is enforced before sending (Hindi text is about 3 bytes per character). |
| `list_posts` | `GET …/v4/{account}/{location}/localPosts?pageSize=100` (+`pageToken`) | `rest/v4/accounts.locations.localPosts/list` | **Improved.** Was a single page of 20; now pages up to 100 posts. |
| `create_post` | `POST …/localPosts` body `{languageCode, summary, topicType: "STANDARD", callToAction?, media?}` | `rest/v4/accounts.locations.localPosts` | Matches. `topicType` is required. **Fixed:** a `CALL` button never carries a `url` (Google: "should be left unset for Call CTA"). Action types offered: `BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, CALL` (not the deprecated `GET_OFFER`). |
| `update_post` | `PATCH …/v4/{post}?updateMask=summary[,callToAction]` | `rest/v4/accounts.locations.localPosts/patch` | Matches. A masked field absent from the body is cleared, which is how the button is removed. |
| `delete_post` | `DELETE …/v4/{post}` | `…/localPosts/delete` | Matches. |
| `list_media` | `GET …/v4/{account}/{location}/media?pageSize=100` | `rest/v4/accounts.locations.media/list` | Matches (single page; 100 is the default and also the most media a location can hold through the API). |
| `add_media` | `POST …/media` body `{mediaFormat: "PHOTO", sourceUrl, locationAssociation: {category}}` | `rest/v4/accounts.locations.media/create` | **Fixed.** `LOGO` is a deprecated alias and is now sent as `PROFILE`. Added the missing categories `MENU`, `COMMON_AREA`, `ROOMS`. |
| `delete_media` | `DELETE …/v4/{media}` | `…/media/delete` | Matches. |
| `fetch_performance` | `GET businessprofileperformance…/v1/{location}:fetchMultiDailyMetricsTimeSeries?dailyMetrics=…&dailyRange.start_date.year=…` | `performance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries`, `…/DailyMetric` | **Fixed**, see below. |

### Performance metrics

| Metric | Before | Now | Why |
|---|---|---|---|
| `BUSINESS_IMPRESSIONS_DESKTOP_MAPS`, `…_DESKTOP_SEARCH`, `…_MOBILE_MAPS`, `…_MOBILE_SEARCH`, `CALL_CLICKS`, `WEBSITE_CLICKS`, `BUSINESS_DIRECTION_REQUESTS`, `BUSINESS_BOOKINGS` | requested | requested | Current in the `DailyMetric` enum. |
| `BUSINESS_CONVERSATIONS` | requested | **removed** | Deprecated 2024-07-31 with a published removal date of 2026-01-31. One invalid enum value fails the whole request. |
| `BUSINESS_FOOD_ORDERS` | not requested | not requested | Deprecated 2025-10-22. |
| `MESSAGING_CLICKS` | not requested | **added** | Added by Google 2026-10-14. |
| `BUSINESS_FOOD_MENU_CLICKS` | not requested | **added** | Current. |

Other fixes: the date parameters are now spelled as in the example on Google's reference page (`dailyRange.start_date.year`); `value` is read as a string integer and treated as 0 when Google omits it; a metric returned as several series (one per `dailySubEntityType`) is summed into one daily total.

## Error and approval detection

| Google's signal | Source of the claim | FlowQR's reaction |
|---|---|---|
| `ErrorInfo.reason = SERVICE_DISABLED` | documented, **and observed live** | "A required Google API is not enabled on FlowQR's project (*service*)". Connection `api_access = api_disabled`. Not retried. |
| HTTP 429 / `RATE_LIMIT_EXCEEDED` / `RESOURCE_EXHAUSTED` | documented | Rate limited; background sync backs off (5 min doubling to 6 h, or `Retry-After`). |
| Quota of 0 means the project is not approved | documented on the prerequisites page | See the caveat below. |
| `ErrorInfo.reason = ACCESS_TOKEN_SCOPE_INSUFFICIENT` | documented | Treated like a revocation: reconnect and grant the scope. |
| HTTP 401 | documented | Connection marked revoked; user asked to reconnect. |

In the UI these are three separate states and never shown together: **API switched off** (`api_disabled`), **Awaiting Google approval** (`awaiting_approval`) and **Needs attention / Reconnect** (connection `revoked`). A revoked connection hides the other two until the owner reconnects. The browser test `e2e/qr-and-access.js` checks this with seeded connection rows (not live Google).
| `invalid_grant` on refresh | documented | Connection marked revoked. |
| Token response without `business.manage` | Google's consent screen lets people untick permissions | The connection is refused and the token revoked at connect time. |
| HTTP 403 `PERMISSION_DENIED` (not disabled) | documented (also returned when Business Profile is off for a Workspace organisation) | Shown as "the connected account may not manage this location". Nothing is retried. |
| A 2xx response that is not JSON | defensive | Treated as a failure, never as success. |

**Caveat on quota 0.** Google documents that an unapproved project has a quota of 0, but does not document any field in the error body that says so. A quota-0 project and a busy approved project both answer HTTP 429. FlowQR therefore does this: if the body happens to carry `metadata.quota_limit_value = "0"` it reports "awaiting approval"; otherwise, a 429 on the **first ever** Business Profile call of a connection is reported as "most likely awaiting approval" (and says "most likely"); any later 429 is an ordinary rate limit. This rule is a reasoned guess. It has not been observed against a real quota-0 project.

## Limits FlowQR enforces itself

| Limit | Google's rule | FlowQR |
|---|---|---|
| Profile edits | 10 per minute per Business Profile, cannot be raised | The 11th edit to one location in a minute is refused locally with a clear message, before any request is sent. |
| Requests | 300 per minute per API by default once approved | Sync runs every 30 minutes per location; far below the limit. |
| Reply length | 4096 bytes | Refused when drafting and again before sending. |

## Not covered, and why

* **No write call has been made against live Google** (reply, post, photo, profile edit). The smoke command never writes by design. First real writes should be done by hand on a test location.
* `locations.patch?validateOnly=true` is available as `--validate-patch` on the smoke command but could not be exercised (the API is disabled).
* Media upload from a file (`media.startUpload`), offer and event posts, recurring posts, `reviews.deleteReply`, `batchGetReviews` and Pub/Sub review notifications are not implemented.
* `ACCESS_TOKEN_SCOPE_INSUFFICIENT`, 401, 429 and `PERMISSION_DENIED` handling follow documentation only.
* The Q&A API was discontinued by Google on 2025-11-03 and is not used.
