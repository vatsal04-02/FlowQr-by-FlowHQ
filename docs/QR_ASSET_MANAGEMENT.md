# Dynamic QR + NFC asset management

**Status: built and tested locally on branch `feature/qr-asset-management`. Nothing is deployed, no production write was made, no live QR destination was changed.**

## What already existed (reused, not rebuilt)
Batches of 1-2000 cards with unguessable 144-bit public tokens (`secrets.token_urlsafe(18)`, uniqueness checked against the database and enforced by a UNIQUE constraint); serial numbers; QR PNG/SVG; batch ZIP of plain codes, poster ZIP (PNG/SVG/PDF), poster PDF sheets and a CSV for the tag writer; lifecycle statuses; scan-to-assign and bulk-assign by serial (all-or-nothing); explicit confirmation for moving a card in use; `card_assignments` history; audit entries for every admin card action; separate QR (`/q/`, `/c/`) and NFC (`/n/`) doors recorded as `channel`; bot flagging; salted daily visitor hash; RLS tenant isolation; rate limits on public routes; per-business analytics.

## What was missing and is now added (migration 0042, additive)
| Gap | Added |
|---|---|
| Redirect to an arbitrary destination | `qr_cards.destination_url`; `/public/c/{token}` answers `state: redirect` and the web page follows it (https only, checked again in the browser); `GET /api/v1/go/{token}` is a real **302**, `Cache-Control: no-store`. |
| Destination history | `card_destination_history` (append-only, RLS, SELECT+INSERT only) plus audit entries with old and new value. |
| Safe destinations | `services/destinations.py`: https only, no credentials, no IPs, no local/temporary hosts, only port 443, no FlowQR address (loop), max 2000 chars, IDNA-normalised. The server **never fetches** the address ("Check address" validates only; the admin opens it in their own browser). Nothing in a request can choose or alter the target. |
| NFC programming status | `qr_cards.nfc_programmed_at/by`. States: not programmed, marked programmed (an admin's statement), tap confirmed (a real, non-bot NFC visit after marking). FlowQR never claims it wrote a tag. |
| Event detail | `scan_events.referrer_host` (host only), `device` (mobile/tablet/desktop/other), `placement` (card label then), `campaign_id`. |
| Analytics | `GET /admin/cards/{id}/analytics`, `GET /admin/cards-analytics` (by batch, business, location, campaign): QR, NFC, unique visitors; automated visits counted separately; a visit is never a completed review. |
| Inventory filters | location, campaign, created date range, has destination, NFC state (business, status, batch, serial already existed). |
| Admin UI | Filters, row selection with bulk assign, Details dialog (overview + copy buttons + assignment history, destination editor with history, NFC steps, analytics), batch sizes 10/25/50/100/500 + custom. |
| Duplicate filter | The 20-second refresh filter is now per door, so verifying an NFC tag right after a QR scan registers. |

## Decisions that need the owner
1. **Domain.** The brief's example is `go.flowqr.site`. Production prints `https://flowqr.site/q/<code>` (`PUBLIC_CARD_BASE_URL`) and `go.flowqr.site` does not resolve. Changing the base is a DNS + Vercel/Caddy decision and applies only to cards printed AFTER it; existing printed codes keep working because their address never changes. Not done.
2. **Where the redirect happens.** QR/NFC addresses open a FlowQR page that follows the stored destination (so the existing review landing page, AI assistant and analytics keep working). `/api/v1/go/{token}` is available if a pure HTTP 302 on the print domain is preferred; it needs a Vercel rewrite or Caddy route, not done.
3. **Per-business destination edits.** Only platform admins can set a destination (a business cannot point its printed QR anywhere). Opening it to owners is a product decision.

## Not done / limits
- No NFC writing integration exists: tags are written by hand with a phone app; the UI says so.
- Assignment of one asset to a *different business* already requires explicit confirmation and is recorded in history and audit; cross-tenant assignment needs platform admin, as before.
- Soft deletion: cards are never deleted; `archived` and `retired` are the soft states.
- Bots are counted separately, not deleted. Device is a coarse class from the user agent.

## Rollback
Migration 0042 downgrades cleanly (tested). Code rollback is the previous image; the new columns are unused by it.
