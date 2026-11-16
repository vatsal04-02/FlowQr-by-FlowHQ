# Marketing site

The public site lives in `frontend/src/app/(marketing)/` (its own layout, Inter Tight via `next/font`, tokens scoped to `.mkt`), built from the section kit in `frontend/src/components/marketing/`. All copy is in `frontend/src/content/marketing/en.ts`.

- `screenshots/`: the reference frames (layout, spacing and motion only; never its brand, text or photos).
- `compare/`: our pages at 1440px and 390px, to put beside the references.
- `FEATURE_STATUS.md`: what the site may claim.
- Add `PRD.md`, `DESIGN.md` and `BUILD_PROMPT.md` here (they were supplied in chat, not in the repo).

## Deliberate departures from DESIGN.md

- **Text on orange is navy, not white.** White on `#FE6A05` is 2.9:1 and fails WCAG AA; navy is 6.5:1. Accent words in headlines use `#E05A00` (3.4:1, large text) and small orange text uses `#C94C00`.
- **Muted text is `#5F6377`** (spec `#6B6F82`) so 13px text on the tinted cards passes 4.5:1. The unrevealed scroll-statement words start at `#80849A`, not `#A9ACBA`, so they pass 3:1 as large text.
- **Industries topics** avoid outcome words ("Pain relief" from the PRD example) on healthcare blocks.
- **WhatsApp button on /demo** shows only if `NEXT_PUBLIC_WHATSAPP_NUMBER` is set; the support email comes from the server's `/legal/info`.
- **Site address** for canonical URLs, the sitemap and social cards comes from `NEXT_PUBLIC_SITE_URL` (defaults to localhost).

## Checks

`BASE_URL=http://localhost:3000 node e2e/landing.js` (add `SUBMIT_LEAD=1` to save one real lead). Backend: `backend/tests/test_leads.py`.
