# Navigation and Home redesign (2026-11-24)

Scope: the customer app shell (`frontend/src/lib/nav.ts`, `components/shell/*`, Home). The platform-admin app (`/admin`, `AdminShell`) is a separate shell and was not changed. Only existing pages are listed; no page, route, permission or API was removed or added.

| Before (sidebar sections) | After |
|---|---|
| (none) Home, Reviews, GBP, Growth | **Home** |
| Business: Locations, WhatsApp | **AI Marketing**: Marketing Studio (Campaigns, Posts, Photos) |
| Assistant: AI Assistant, Tasks & Approvals, Activity | **Business**: GBP (Overview, Rankings, Performance, Profile), Locations |
| Account: Settings, Billing | **Customers & reviews**: Reviews, Growth, WhatsApp |
| Marketing Studio buried under GBP; Posts/Photos were tabs under GBP > Profile | **Assistant**: AI Assistant, Tasks & Approvals, Activity |
| | **Administration**: Settings, Billing (owner/admin only, unchanged) |

Phone bottom bar: Home, **Studio**, Reviews, Google, More (Growth moved into More > Customers). Sidebar behaviour (collapsible 68px rail with tooltips, remembered state, active highlight, folding destination children) was already present and is unchanged.

Home gains a "Google marketing" band built from `/marketing/overview`, the scheduled-post queue and `/marketing/readiness`: counts, up to three upcoming posts, attention items (failed posts, lost Google authorization, posts waiting for approval) and quick actions. With no campaigns it shows one invitation instead of zeros. Nothing is sample data.

Unmatched from the proposal (no page exists, so not listed): Customer database/enquiries/communication history as separate pages (WhatsApp contacts and messages cover part), Campaign reports, API configuration, Roles & permissions as a standalone page (inside Settings > Team).

Fixed during testing: the campaign review page overflowed horizontally at 320 and 360 px (a long button label).
