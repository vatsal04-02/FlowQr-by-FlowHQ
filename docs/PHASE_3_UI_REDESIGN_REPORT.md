# Phase 3: mobile-first UI redesign, report

Date: 2026-11-16. Design rules: [DESIGN.md](DESIGN.md). Screenshots: [ui-redesign/](ui-redesign/) (a local test business with clearly labelled test data; nothing from production).

Not pushed, not deployed, no production setting or migration touched.

## What changed

| Area | Change |
|---|---|
| **Navigation** | One responsive system replaces the horizontal section pill, the vertical icon rails with flyouts and the chip rows. Phones: bottom bar Home, Reviews, Visibility, Results, More (icon + name, 56px, safe-area aware) and a More sheet (Business tools, Business assistant, Account). Tablet/desktop: one 232px sidebar that folds to a 68px rail and remembers its state. Top bar: business, location, search, notifications, account only. Source of truth: `frontend/src/lib/nav.ts`. |
| **Words** | 23 page titles and subtitles rewritten in plain language (table in DESIGN.md §3). Technical names stay in tooltips and detail views. |
| **Home** | Rebuilt: four numbers at most, one review-growth chart with a one-line insight, three things to take care of, QR scan to Google funnel, what customers say. Setup progress is one slim card. |
| **Reviews** | Tabs renamed (Needs a reply, Waiting for you, Didn't send, Replied), page heading and promise ("nothing is posted until you approve it"); mobile list-to-detail already existed and is kept. |
| **Visibility** | Four areas: Google Maps (where you appear), Searches people use (new page, Google's impressions kept apart from positions), Nearby competitors, Your Google profile (improve). Tables became cards on phones. Geo-grid stays off and is renamed "Visibility across nearby areas". |
| **Results** | Google activity, Reviews, QR & NFC, Campaigns, Reports as tabs. Google activity reads one source only; "More detail from Google" appears only once Google has shared data, so a page never says "not shared yet" beside numbers. |
| **Design tokens** | Card radius 16px (tiles 12, inner 10), lighter shadow, compact titles, `viewport-fit=cover`, 44px touch targets enforced on phones for buttons, tabs, selects, summaries, sliders and text fields (app, marketing site, review page). |
| **Admin** | Same brand and components in a denser layout: 220px sidebar, scrolling tab strip on phones. |
| **Backend (one small change)** | A successful live Google performance read is now stored like the daily job's, so the stored and live views cannot disagree (`gbp.py`, test in `test_gbp.py`). |

## Features hidden, preserved, moved

* **Hidden from navigation, routes and code untouched:** WhatsApp inbox, Leads, Appointments, Follow-ups, Inbox campaigns; Content Studio calendar, brand kit, asset library, social publishing (nine pages). They still open by URL and still say "Setup required".
* **Preserved:** local rank tracking and the geo-grid (still disabled), stored competitor observations and following, review collection and card tracking, campaigns, AI approvals, reports, account and team, billing, onboarding, the emergency stop, every redirect.
* **Moved or renamed (URLs unchanged or redirected):** reply assistant to Draft replies; insights to What customers are saying; Brand voice, Business brain, Autonomy, Usage to Settings, AI & automation; Automations to Helpers; Content Studio AI Creator to Write a post.
* **Removed from the screen (code kept):** the old Home cards (rating card, key tiles, goal, competitors, profile health, rating trend, visibility card, health strip, growth tabs). Their data is on Reviews, Results and Visibility; the monthly review goal now lives on Results, Review results.
* **Not touched:** Cashfree, trial entitlements, subscription logic.

## Verification

| Check | Result |
|---|---|
| `npx tsc --noEmit` | clean |
| `npx next build` | clean (production build, all routes) |
| Backend tests touched by the one backend change (`test_gbp`, `test_seo_metrics`, `test_analytics`, `test_workspace_reports`, route-access audit) | 69 passed |
| **Playwright** `e2e/mobile-shell.js`, real Chrome against the production build | **113 checks, 0 failed** (bottom bar contents, 44px targets, bar on the bottom edge, content clear of the bar, More sheet groups, focus in and out, Escape, desktop sidebar names and widths, collapse remembered, tablet rail, tables as cards, redirects, hidden placeholders not advertised, dark + reduced motion, no console errors) |
| **Responsive sweep** (CDP, real Chrome) 45 customer pages, light, at 360×800, 375×812, 390×844, 430×932, 768×1024, 1024×768, 1440×900 | 0 pages with horizontal overflow, console errors or sub-44px targets on phones |
| Dark mode (390 and 1440) and reduced motion (390), same 45 pages | 0 flagged |
| Public pages (marketing, pricing, sign-in, register, the customer review page) at 360 and 390 | 0 flagged after the touch-target fix |
| Admin pages at 390, 768, 1440 (dark) | 0 flagged |

Issues found by this testing and fixed: six sections overflowed the old header at 1024 to 1280 (removed with the old header); a hidden table header widened a page on phones; the 44px rule shrank the 56px bottom-bar More button (fixed with an explicit minimum); the sidebar did not mark Home as current; marketing and review-page controls were 36px.

## Known limits

* QA used a seeded test business and the local API. The Google cards show Google's numbers only because test rows were inserted into the local database; in production they stay "not shared yet" until Business Profile access is approved.
* The dev-server overlay badge can cover the sidebar footer in development; it does not exist in the production build.
* Charts and a few older pages (reports, cards, locations, team) received the new tokens, titles and touch rules but not a bespoke re-layout; they pass the same QA.
* Old widget components that Home no longer uses are still in the repository (`components/overview/{widgets,summary}.tsx`) and can be pruned later.
