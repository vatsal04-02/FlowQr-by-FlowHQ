# FlowQR app design system

This is the source of truth for how the logged-in app looks and behaves. (The earlier `DESIGN.md` that the code comments mention was supplied in chat and was never in the repository; this file replaces it for the app. The marketing site keeps its own tokens under `.mkt`, see `docs/marketing-site/README.md`.)

## 1. Who it is for

A shop, salon, clinic or restaurant owner on a phone, in a hurry, who does not know SEO, analytics or automation. The test for every page: *could this owner understand what the page does without asking a developer?* If not, change the name, the content or the hierarchy. Technical detail is kept (tooltips, "More detail", admin views) but is never the first thing seen.

Design order: **phone first, then tablet, then desktop.** Desktop is not a stretched phone and the phone is not a squeezed desktop; they share components and differ in navigation and density.

## 2. Tokens (unchanged from the existing app)

| Token | Value | Use |
|---|---|---|
| Canvas | `--c-canvas` warm grey, white surfaces `--c-surface` | page background, cards |
| Accent | `--c-accent` orange `#EA542E` (+ hi/lo/ink/tint/edge) | primary actions, the active page marker, one highlight per card. Never a large gradient panel. |
| Ink | `--c-ink` near-black (light) / near-white (dark) | text and the primary button |
| Status | `pos` green, `neg` red, `warn` amber (+ tints) | always paired with words, never colour alone |
| Type | Inter (app), Geist (marketing), Noto Sans Devanagari fallback; numbers use tabular figures | |
| Radius | data cards **16px** (`rounded-card`), wells and tiles **12px**, inner rows **10px**; nested radii are always smaller than their parent | |
| Shadow (premium pass, Phase 1) | `--shadow-card`: a top highlight plus three stacked shadows (contact, soft, long); `--shadow-lift` on hover; dark mode swaps the long shadow for a deeper one. Glass is allowed **only** on the sticky top bar (`.top-glass`, with an opaque fallback for reduced transparency). | |
| Tone hues | `--c-tone-teal / amber / rose / sky / blue` (light and dark values). One hue per metric family, the same on every screen: teal calls and goals, sky and blue searches and directions, amber ratings and website clicks, rose profile views, green done. A card carrying one metric uses `.tn .t-<hue>` (soft corner glow, tinted edge, coloured shadow); `.kic` is the small tinted icon chip. Text stays ink, so contrast is unchanged. | |
| Easing | `--ease-spring` (`ease-spring` in Tailwind) for things that appear or press; `--ease-out` for slides and fills. | |
| Dark mode | `html[data-theme="dark"]`, every token has a dark value; both themes are part of QA | |

Avoid: purple or indigo gradients, glass on cards, big orange hero panels, decorative charts, oversized empty cards, icon tiles on every row, pill-shaped containers for everything (pills are for status and the date filter only), huge page titles on a phone.

Page titles are 22px on a phone, 26px tablet, 30px desktop; subtitles are one or two short lines.

## 3. Shell and navigation (one system)

There is exactly one navigation system. Source: `frontend/src/lib/nav.ts`. Components: `components/shell/{Sidebar,BottomNav,parts}.tsx`, `components/AppShell.tsx`.

| Screen | Navigation |
|---|---|
| **Phone (< 768px)** | A fixed **bottom bar** with five items, each with an icon and a visible name: **Home, Reviews, Visibility, Results, More**. Targets are 56px tall, the bar sits above the home indicator (`env(safe-area-inset-bottom)`, `viewport-fit=cover`), and the page keeps a matching bottom padding. Active item: orange icon and name plus a 3px orange marker. |
| **More** | A bottom sheet in three named groups. **Business tools:** QR & NFC Cards, Campaigns, Locations. **Business assistant:** AI Assistant, Tasks & Approvals, Activity. **Account:** Settings, Billing (owner/admin), Help & Support. Closes with its button, the backdrop, Escape or choosing a page; focus stays inside and returns to the More button. |
| **Tablet (768 to ~1100px)** | The same **sidebar**, starting collapsed as a 68px icon rail (names in tooltips and accessible names). |
| **Desktop** | One left **sidebar**, 232px expanded, names visible, in groups: Home, Reviews, Visibility, Results / Business tools / Assistant / Account. The current page is marked by an orange bar and the pages inside the current destination fold open beneath it. It collapses to the rail with a button; the choice is remembered. |
| **Top bar (all sizes)** | Business switcher (avatar with a green dot and "Google connected" only when the API says so, from 860px), breadcrumb (from 1480px, built from `nav.ts`), the location filter (when there is more than one location), search ("Search or jump to…" and Ctrl K from 860px, an icon below), sync chip ("Synced 13m ago" from the newest synced location; owners and admins can press it to sync now; icon only below 1000px, hidden below 860px), trial chip (last five days of a trial; in the bar from 1280px, in the page below that), notifications and the account menu (name, email, role, Plan and billing, Team, theme, log out). No second navigation. The decision logic is in `lib/shell-status.ts` and unit-tested (`npm test`). **Sidebar badge:** Tasks & Approvals shows the count of things waiting (tasks to do + approvals), and each of its two pages its own, from `GET /agent/counts`. That endpoint is read-only (it never re-plans or writes, unlike `GET /agent/tasks`), scoped like the pages it counts, sent with `Cache-Control: private, max-age=60`, and the app asks again about once a minute. No badge when the plan or role cannot see the assistant. |
| **Page tabs** | The pages that belong to a destination (for example Results: Google activity, Reviews, QR & NFC, Campaigns, Reports) are an underlined tab strip under the top bar, scrolling sideways on a phone. A second, lighter row appears for pages that share a theme (Your Google profile: Improve, Business info, Opening hours, Posts, Photos). |

Removed: the horizontal section pill, the vertical icon rail with flyout, and the chip rows. Every old URL still works (`frontend/src/lib/legacy-routes.mjs`, 51 permanent redirects).

### Plain words

Technical names live in detail views and tooltips. The labels used in navigation and titles:

| Before | Now |
|---|---|
| Workspace / Reputation / Local SEO / Analytics / AI Growth | Home / Reviews / Visibility / Results / AI Assistant |
| Local Rank Tracking | Where you appear on Google Maps (and "Search words you track") |
| Geo-grid | Visibility across nearby areas |
| Google Profile Health | Improve your Google profile |
| Competitor Analysis | Nearby competitors |
| Performance | Google activity |
| Impressions / profile views | Times people saw your profile |
| Customer funnel / card analytics | From QR scan to Google |
| Review sentiment / Insights | What customers are saying |
| Pending approvals / Approvals | Waiting for your approval |
| Automations | Helpers |
| QR campaigns / Review analytics | Review campaigns / Review campaign results |
| Reply assistant | Draft replies |

## 4. Home

Short blocks, in the order an owner cares about. **Home may have several charts, but each must answer a different question and be drawn from numbers the API returned. A chart is never added to fill space**; if the numbers do not exist the block is hidden or says so in one sentence. The blocks:

1. **Business overview**: business name, location, date filter, and at most **four** numbers: Google rating, new reviews, reviews answered, and (only when Google has shared it) times people saw your profile. If Google has not shared it, that cell is one sentence: "Google hasn't shared these numbers with FlowQR yet." It never shows a number and that sentence together.
2. **Review growth**: one chart (this period against the one before) and a one-line insight.
3. **Things to take care of**: three items at most, most urgent first: a short title, one line of why, one clear action.
4. **From QR scan to Google**: scans, page visits, clicks to Google. A click is never called a review. No card: one button to set one up.
5. **What customers say**: rating distribution, often-mentioned topics and three recent reviews.

6. **Growth score** (ring and its five parts), **four numbers** (each toned, counting up, with its own small picture), **reviews by week** against the goal, **customer actions on Google** (calls, directions, website clicks, profile views; an area chart and a share ring), **rating mix** (ring) and the **latest reviews**.

The question each chart answers: score = am I getting better; four numbers = how am I doing right now; reviews by week = am I on pace for my goal; customer actions = what do people do after finding me on Google; rating mix = how good are the reviews; QR funnel = do my cards work.

**Daily charts use only stored daily data.** The customer-actions area chart is drawn from `GET /analytics/google-metrics` (`gbp_metric_daily`) and only when Google has shared at least three days in a row. A day Google has not reported is a gap, never a zero, and the line is never joined across it (`lib/charts.ts`: `dailyStack`, `runs`, `canDrawArea`). Fewer days: the totals are shown and the card says how many days exist. **Never generate, spread or estimate daily values from a total.** Share rings use the real counts and their percentages always add to 100.

Not on Home: long paragraphs, tables, or every feature. Detail belongs to Results, Reviews and Visibility.

## 5. Components

| Component | Rule |
|---|---|
| `Panel` / `.panel` | White, 16px radius, hairline shadow. `dense` for data-heavy cards. No card inside a card unless it is a 12px well. |
| `DataTable` (`components/ui/DataTable.tsx`) | A real table from 640px, a list of compact cards below it (first column = title, others = "label  value"). No wide table on a phone. |
| `SourceTag` | On Local SEO and Results cards: **Google** (reported by Google), **Measured · Places** (position among the first 20 results around the location, not what everyone sees in Maps), **Calculated** (our formula, shown). |
| `Unavailable` | The one state for "no data": says what is missing and why. Never a zero. |
| Buttons | At least 44px tall on a phone (enforced globally in `globals.css`), one primary per card. |
| Forms | Visible labels, helper text, errors next to the field. |

## 6. Charts

Trends use a line or bars, comparisons horizontal bars, progress a simple bar or ring, ratings distribution bars, the customer journey a three-step funnel. Titles are short; legends only when there is more than one series; grid lines are dotted and few. Every chart has a loading, an empty, an unavailable and an error state, a tooltip that also works from the keyboard (arrow keys), and a "View data as table" fallback. Series differ by line style as well as colour. On a phone, multi-series charts are kept to two series and axis labels are thinned; nothing scrolls the page sideways. Geo-grid maps stay off until costs and caps are approved (`docs/GEO_GRID_ENABLEMENT.md`).

### Cards, tone and motion on data screens (premium pass, Phase 2)

* Metric cards use a tone hue (`Card tone=…`, `.tn .t-<hue>`); the same metric keeps the same hue on every screen. Small cards also `tilt` toward a fine pointer (`data-tilt`, one global listener, off for touch and reduced motion).
* Numbers count up once when they first appear (`CountUp`; the real value is always in the accessible text). Rings and share rings draw in; the area chart wipes in. Everything stops for reduced motion.
* Share rings (`Donut` + `Legend`) always print every count and percentage beside the colour.
* A review's timeline (Reviews › detail) shows only steps that have a stored timestamp: received, drafted, approved, sent, or a reply made on Google.

### Data screens and motion, Phases 3 and 4 (premium pass)

* **Rankings:** "What people search" is a stacked share bar plus coloured rows from Google's stored search terms. A term Google reports only as "fewer than 15" has no number and is left out of the shares. With no tracked words the card says so and shows the real terms people already use.
* **Performance:** an all-actions area chart and share ring from stored daily figures (same rules as Home), then one toned card per metric with its own coloured daily bars and change against the period before.
* **Profile:** the shared score ring with count-up; "Why this matters" is the real `reason` the API returns for each check, in an accordion that opens by growing (`ui/Accordion`).
* **Goals:** pace row: cells filled by the real count, a marker at goal x share of the month gone. Funnel steps keep one hue each.
* **Tasks / Approvals:** a kind icon per task; snoozed and dismissed tasks slide out (380 ms) before the list reloads; Approvals shows a count strip of what is waiting.
* **Plan:** usage as rings with the exact "used / limit"; plan columns are tinted per tier.
* **Every page** eases in when you move between pages (`.fq-page`, keyed by destination and page so a list's state survives choosing another item). All other screens (Drafts, Reports, Campaigns, Cards, Locations, Helpers, Write a post, Activity, Settings, Payments) take the new card depth and tone tokens through the shared `.panel` and tokens with no content change.
* **Guided tour** (Account menu, tablet and desktop): a pointer opens Home, Reviews, Profile, Rankings and Goals with the person's own data. It only navigates; it never clicks anything that changes data. Any click or Escape stops it.

## 7. Data honesty

* No sample data in production, ever. An unavailable number says so; there are no fake zeros and no history is back-filled.
* Google Business Profile numbers come from one source (what FlowQR stored from Google, `gbp_metric_daily`); a live Google read is stored too, so two pages cannot disagree.
* Keyword impressions from Google ("Searches people use") are never mixed with Places positions ("Where you appear"), and neither is called a ranking by Google.
* A click to Google, a scan or a visit is never described as a review. Replies are never posted without a person approving them; there is no rating-based gating.

## 8. Accessibility and motion

* Contrast 4.5:1 for text, status always with words, visible keyboard focus (2px orange outline), a "Skip to content" link, labelled icon buttons, dialogs trap focus and return it.
* Touch targets 44px minimum on a phone; the bottom bar respects the safe area.
* Motion is short and meaningful (sheet slide, active marker, number count-up, chart draw-in). Everything respects `prefers-reduced-motion` (`MotionConfig reducedMotion="user"` plus a global CSS rule). No new animation library was added.

## 9. Quality gate (how this was checked)

Real headless Chrome, a throwaway local business with test data (deleted afterwards), the production build of the same code:

* Viewports: 360×800, 375×812, 390×844, 430×932, 768×1024, 1024×768, 1440×900; light and dark; reduced motion.
* Per page: no horizontal overflow, no console errors, no touch target under 44px (phones), bottom bar visible and flush with the bottom edge.
* `npx tsc --noEmit` and `npx next build` clean; backend suite unchanged.
* Scripts: `e2e/mobile-shell.js` (Playwright) and the CDP sweep described in `docs/PHASE_3_UI_REDESIGN_REPORT.md`.
