# Local SEO engine V2: audit of the engine as it was

Read 2026-11-22/23 on branch `feature/local-seo-engine-v2`, cut from `origin/release/gbp-agency` @ `0604555` (alembic head 0065). Nothing was deployed, pushed or enabled. This file says what the old engine did and what Google's current documentation says; it is not a status report on the new code (see IMPLEMENTATION and TEST_MATRIX).

## 1. What the old engine actually did

One engine, already built: `AgentAction` + `executor` + `autonomy_policy` + `consent`. Verified in code:

| Piece | What it did |
|---|---|
| `seo_engine.scan_location` (every 6 h, `autonomy_scan`) | Proposed only two things: (1) a website/phone on Google that was **empty** when the business record had one, (2) a new description (AI draft from verified facts) when it was missing/weak or tracked terms were missing. |
| `optimizer.checks` | Detected ~12 areas (description, categories, services, hours, special hours, phone, website, name, photos, posts, visibility, freshness) but only description/contact/hours/categories were fixable. Services, special hours and name said "do it in Google". |
| `autonomy_policy.SPECS` | `service_update`, `attribute_change`, `service_area_change` existed as **recognised but `writable=False`**. |
| `provider.update_location` | Could write description, regular hours, primary/additional categories (merged with the live values), phone, website. |
| `executor` | propose, classify by code, approval bound to the exact value, claim before writing, write, read back, compare, history hash chain, retries, stuck recovery, emergency stop, failure suspension, per-field in-flight lock. Compared only the fields above. |
| Consent | `consent_grants` per location and action type, off by default, revocable, append-only. |
| Gaps found | No dry run before a write. No reads of attributes, service types, category service lists, `getGoogleUpdated` in the scan. Hours could not express closing after midnight (the close day was dropped). A supplied service list had no write path at all. Nothing detected an owner/Google edit that made a drafted change stale except at approval time. |

## 2. What Google's documentation says (read 2026-11-22; pages in section 5)

Facts that shaped the design, each from a page I read, with what the page did **not** say:

* `locations.patch`: `updateMask` required; `validateOnly` exists ("the request is validated without actually updating the location"). The page does **not** say what happens to a field that is in the body but not in the mask, and contradicts itself on the validateOnly response (empty vs a Location).
* **Services** (`serviceItems`): a list of `StructuredServiceItem{serviceTypeId, description<=300}` or `FreeFormServiceItem{category, label{displayName, description, languageCode}}`, optional price (Money; the Money page returned 404, so its fields are **unverified** and a price is carried through untouched). "Duplicated service items will be removed automatically." `metadata.canModifyServiceList` says whether the list can be edited. **No page states whether a patch replaces the whole list, nor a maximum count.** Therefore the engine always sends the complete merged list.
* **Categories**: `primaryCategory` + `additionalCategories`; "During updates, both fields must be set." The 9-additional cap is from Business Profile help, not the API reference.
* **Special hours**: `startDate` required; `endDate` equals or at most 1 day after; times required unless `closed`; period under 24 h; next-day close at 11:59 at most; "cannot be set without regular hours."
* **Regular hours**: close day may be a later day (after-midnight); 24:00 allowed; absence of a day is not defined on the page.
* **Attributes**: separate resource `locations/{id}/attributes`; `attributeMask` required; attributes not in the mask are ignored; deleting = mask entry with no body entry; `valueType` is output-only; deprecated attributes "will not result in an error, but updates will not be saved"; `attributes.list` with `parent` must not carry region/language/category. How a BOOL value is represented on the wire is **not documented** (the code sends `values: [true]`).
* **Service area**: `businessType`, up to 20 `placeInfos`, `regionCode` immutable; switching business type requires emptying `storefrontAddress`.
* **Category service types**: `categories:batchGet` returns them only with view FULL (inferred from BASIC omitting them).
* **`getGoogleUpdated`**: `diffMask` ("To accept these changes, patch the location. To reject, patch with your preferred values."), `pendingMask`.

### Policy page (developers.google.com/my-business/content/policies; no date on the page)

* "Any automatic or programmatic use ... by agencies or end-clients requires them to use their own Business Profile project"; you cannot give indirect access to your project; end users "need to manually sign in". The page does not reconcile this with FlowQR's shared-project model.
* No listing edit may be automated "without the user's prior specific and express consent". A separate notice to the end-client within 48 h of an account change.
* Stored Content "no more than 30 calendar days", "cannot be manipulated or aggregated".
* "You may not use the Business Profile APIs to automatically revert changes made by Google."
* The page says nothing about AI/ML, and nothing specific about editing names, categories, services, attributes, areas or hours beyond the consent rule.

**FlowHQ's written Google clarification is still pending.** A successful API call or an owner's button press is not policy clearance. This is why the V2 customer-write gate exists and is closed.

## 3. Unknowns the code does not hide

1. Whole-list vs merge semantics of `serviceItems` patches (mitigated: complete list sent).
2. Wire form of BOOL attribute values.
3. Money shape for prices.
4. Whether `validateOnly` accepts every V2 body (needs a live dry run: `google-readiness`).
5. Google's service/attribute behaviour for any given category.
6. The effect of any change on rankings (never claimed).

## 4. Pre-existing issues noticed, not changed

* The legacy scan's description draft uses AI before the 30-day-storage and AI-terms questions are answered (`GEMINI_DATA_TERMS_VERIFIED` governs review AI only).
* Competitor categories/services are not stored, so competitor evidence for categories is currently never supplied to the engine.

## 5. Sources

developers.google.com/my-business/content/policies · reference/businessinformation/rest/v1/{locations, locations/patch, locations/getGoogleUpdated, locations/updateAttributes, locations/getAttributes, attributes, attributes/list, Attributes, AttributeValueType, categories/list, categories/batchGet, CategoryView, accounts.locations} · content/location-data. `Money` returned 404.
