# Pre-printed cards, the FlowQR poster, and the five-workspace navigation

How to make cards before you know who they belong to, put each one's permanent QR on the approved poster, assign them later by scanning, and what is still to be proven on real hardware.

## 1. The idea in one paragraph

Every card has one permanent identity: a random 144-bit id (24 URL-safe characters). It is reachable two ways: the **printed QR** (`/q/<id>`) and the **NFC tag** (`/n/<id>`). Both resolve through the same database row, so the card, its business, location and review page can be changed at any time without reprinting the paper or rewriting the chip. Only the way in (QR or NFC) is recorded, for analytics.

Cards printed before this feature encode `/c/<id>`. That address keeps working and is never rewritten: a card remembers which path its own paper uses (`qr_cards.qr_path`: `c` for every existing card, `q` for new ones). `/n/<id>` works for every card, old and new.

## 2. Lifecycle

| State | Meaning | Customer sees |
|---|---|---|
| generated | created in a batch, not yet marked printed | "isn't set up yet" |
| unassigned | printed, in FlowHQ stock | "isn't set up yet" |
| reserved | set aside for one business (they can see it, it is not live) | "isn't set up yet" |
| assigned | has a location (and optionally a campaign); goes live on first real scan | the business's review page |
| active | live | the business's review page |
| paused | temporarily off, reversible | "switched off for now" |
| archived | taken out of stock lists, reversible, only while it belongs to nobody | "isn't set up yet" |
| retired | permanent; history kept; can never be used again | "no longer active" |

`deactivated` and `lost` (older states) still work as before. Customers never see a business name, tenant id or anything administrative on an inactive page (a test asserts the response is exactly `{state, message}`).

Every change of destination is a new row in `card_assignments` (who, when, business, location, campaign, why it ended). Nothing is overwritten.

## 3. Who can do what

| Action | Who |
|---|---|
| Generate a batch (50 / 100 / 250 / 500, API allows 1 to 2000), mark printed, export, reserve, assign any card, bulk-assign, retire, archive | FlowHQ platform admin |
| Look up, assign, re-point, pause, resume, retire a card **that already belongs to their business** (reserved or in use) | Business owner / admin, for locations they may access |
| See a card's own scan history | The business that owns it (RLS) |
| Anything | Nobody who is not logged in. A scan never claims, assigns or changes a card (tested) |

A business cannot claim stock: unclaimed stock and another business's cards answer exactly like a card that does not exist, so the lookup cannot be used to probe. Restricted teammates (limited to some locations) see only cards at their locations, and not reserved cards that have no location yet.

**Confirmation.** Changing where a live card points, moving it to another business, returning it to stock and retiring all require explicit confirmation on the server (`409 confirmation_required` with the current and the new destination), not only in the browser.

## 4. Printing is only allowed for a permanent address

Batch print exports (poster sheets, poster files, inventory CSV, plain-code ZIP, HTML sheet) and bulk poster exports are refused with `409 print_domain_not_permanent` unless `PUBLIC_CARD_BASE_URL` is `https://` on a real domain: not `localhost`, not a bare IP, not `.local`, and not a temporary tunnel (ngrok, trycloudflare, loca.lt, ts.net, nip.io, …). A single poster download is allowed on a development machine (and flagged "not for print") but refused in staging and production. Staging and production also refuse to start with a non-permanent address (existing config guard).

`python -m app.cli card-url-audit [--live]` checks `/c/`, `/q/` and `/n/` shapes and, with `--live`, that each serves the landing page over valid TLS.

## 5. The poster

`backend/app/assets/poster/poster_template.png` is page 1 of the approved `FlowQR_Review_Poster_Print_Readyfinal.pdf`, **pixel for pixel**, except that the module area inside the white QR card is cleared to the card's own white. The server draws a real QR into that area and puts the FlowQR "F" tile back in the middle. Nothing else is drawn.

- **Unchanged (proven):** compared against the supplied PDF, zero pixels differ outside the QR card area, for different codes (a test pins the fingerprint of the approved artwork, so an accidental change fails the build). Google heading, stars, orange corner artwork, the QR frame, Tap/Scan to Review, the AI Review Assistant pill, the description, the Write a Review button and the FlowQR footer are the approved image.
- **Only the code changes:** square, whole-pixel modules, centred in the card, at least 18 px of white card on every side, error correction Q (H if needed).
- **Formats:** PNG (1x, 2x, 3x), SVG (the artwork embedded, the code as vector shapes), PDF (approved size 89 × 126 mm, A6, A5, A4; the code is vector). Batch print sheets are A4, four posters per page, with crop marks and the serial; the artwork is embedded once, so 500 cards are a 125-page file under 15 MB (a test enforces it).
- **Verified before it is served:** every poster is decoded with ZXing and must return exactly its URL at full size, shrunk and slightly blurred; otherwise nothing is served.

### Two small differences inside the QR area, and why

The approved artwork draws the three corner "eyes" with strongly rounded rings and a bright orange centre. A decoder study found that both make real codes harder to find: OpenCV's detector fails on every code when the ring's corner radius is 0.6 module or more, and on every code when the centre is the exact brand orange (its brightness sits near the middle of the scale, so a decoder can read it as light). So inside the QR area only: the ring corners are lightly rounded (0.4 module) and the orange is 12% deeper. The orange block keeps its rounded shape. In the study (20 trials per shade, both decoders): the exact brand orange failed OpenCV 20 of 20; 3% deeper failed about half; from 6% deeper every trial passed. 12% was chosen to leave margin. The look is the same to the eye; the approved frame, logo and artwork are untouched. If the brand owner prefers the exact orange, it can be restored by changing `PALETTES` in `services/poster.py`, but only if a physical-phone test shows it still scans.

The reference poster's logo tile sits about 21 px below the centre of its illustrative code. On the generated poster it is centred on the real code, as a QR logo should be.

## 5b. The physical card (CR80, lengthwise)

The NFC/QR card is a standard bank-card blank: CR80 / ISO ID-1, 85.60 x 53.98 mm, printed **portrait** (54 wide, 85.6 tall). The poster is 0.708 wide-to-tall with a side-by-side Tap/Scan layout, so shrinking it onto a 0.631 card would leave a 23 mm code with modules of about 0.4 mm. `backend/app/services/card_cr80.py` therefore re-lays out the same artwork lengthwise: the heading and stars, the white QR frame with its orange brackets, the Tap and Scan marks and the FlowQR footer are cut from the approved template and stacked, and only the QR code is drawn new (31 mm square, modules 0.7 mm or more for a normal card address, error correction Q, H if needed). The two orange corner waves are redrawn in the same colours (they cannot be cut out of the poster without its page edge).

- **Files:** PNG or PDF at 600 dpi, exactly 53.98 x 85.60 mm, or with 3 mm bleed on every side (59.98 x 91.60 mm). Bleed only extends the corner artwork; the trim area is identical. The card's serial is printed small at the bottom right, inside the safe area.
- **Operator console:** Card inventory, per card ("Card" button: preview, PDF or PNG, bleed) and per batch ("Physical card files": a ZIP of up to 100 files per download).
- **Verified before it is served:** the same decode rule as the poster (ZXing at full size, shrunk and slightly blurred), plus a refusal when the link is too long for 0.55 mm modules.
- **Routes:** `GET /admin/cards/{id}/cr80.{png|pdf}?bleed=0|3`, `GET /admin/batches/{id}/cards.zip?fmt=pdf|png&bleed=0|3&offset&limit`. Platform admins only; the same permanent-address rule as every other print file.
- **Not checked:** a physical print and scan. Ask the printer for one proof of a card, and scan it with an Android and an iPhone, before ordering a batch. Also confirm with the printer whether they want 0 or 3 mm bleed and whether they round the corners themselves.

## 6. Where things are

| | |
|---|---|
| Migration | `0018_card_inventory_nfc.py` (additive; downgrade maps the new states back) |
| Lifecycle, assign, retire, bulk, scan parsing | `services/cards.py` |
| Poster | `services/poster.py`, assets in `app/assets/poster/`, rebuild with `scripts/build_poster_template.py <approved.pdf>` |
| Admin API | `/admin/batches`, `/admin/inventory`, `/admin/cards/lookup`, `/admin/cards/{id}/assign|reserve|unassign|retire|archive|unarchive|poster.{png,svg,pdf}`, `/admin/cards/bulk-assign`, `/admin/batches/{id}/release|inventory.csv|posters.pdf|posters.zip|export.zip` |
| Business API | `/cards`, `/cards/lookup`, `/cards/{id}/assign|retire|pause|activate|poster.{fmt}`, `/review-growth/campaigns/{id}/poster.{fmt}`, `/qr/bulk` (`design: poster`) |
| Public | `/q/<id>`, `/n/<id>`, `/c/<id>` (web) → `/api/v1/public/c/<id>?channel=qr|nfc` |
| UI | `/admin/cards` (FlowHQ), `Marketing & Reviews → QR & Print → Cards` (Inventory, Assign cards) |
| Deploy | `deploy/Caddyfile` card domain now also forwards `/q/*` and `/n/*` |

NFC: write the card's **NFC tag address** (shown on the card page, and in `inventory.csv` as `nfc_url`, with its byte length) as an NDEF **URL record**. It is 57 bytes on a 33-character domain, so it fits the smallest common tags (NTAG213 holds about 137 bytes).

## 7. Navigation: five workspaces

Sidebar: **Overview, Google Business, AI Growth, Marketing & Reviews, Inbox & Leads**, and Settings at the foot. Each workspace's pages are tabs; tabs that group several pages show a second row of small links. Every existing URL still opens and sits under exactly one workspace tab (a browser test visits all 43 of them). Integrations, team, billing, security and the audit log live under Settings.

| Workspace | Tabs |
|---|---|
| Overview | Dashboard, Reports |
| Google Business | Profile, Reviews, Posts, Photos & Media, Insights (Performance, Local visibility) |
| AI Growth | Today, Tasks (Recommendations, Waiting for approval), Activity, Business Brain, Automations |
| Marketing & Reviews | Content Studio (AI Creator, Calendar, Brand Kit, Asset Library, Social), Review Campaigns (Campaigns, Landing pages), QR & Print (Cards, Designs & export), AI Review Assistant, Analytics |
| Inbox & Leads | WhatsApp inbox, Leads, Appointments, Follow-ups (Follow-ups, Campaigns) |
| Settings | Business & account, Connections (All connections, Google Business), Locations, Team & permissions, AI usage & limits, Billing, Audit log |

## 8. What the automated tests prove, and what they do not

Proved (mocked Google and AI, real database, real browser):
- 500 unique cards; random, non-sequential ids; unique serials; both addresses present
- lifecycle, reservation, stock invisible to businesses, no claiming, tenant and location isolation, audit rows
- QR and NFC resolve to one card and are counted separately; old scans stay "untracked", never relabelled
- destination changes apply at once to the same printed code, need confirmation, keep history; retirement is permanent
- the permanent-HTTPS gate; poster fidelity; poster PNG/SVG/PDF decode to the exact URL in two independent decoders; simulated phone photos; 500-poster sheet
- a real **camera scan** in Chromium (Chrome's fake camera playing a video of the actual poster) → lookup → confirmation → assign and activate

Not proved, and needs you:

| Still to test on real hardware | How |
|---|---|
| A **printed** poster scans on real phones | Print the sheet from a batch made on the permanent domain at the approved size; scan with: Android (Google Lens and the stock camera), iPhone camera, and the FlowQR Assign screen on an iPhone (Safari uses the fallback decoder) and on Android Chrome (native detector). Try dim light, glare, 30 cm and 60 cm, a slight angle, and a creased print. Record failures with the phone model |
| The orange eyes on paper | Print one sheet with the shipped colours. If any phone struggles, try the "deep" palette (`PALETTES["deep"]`) and compare |
| **NFC tags** | Write `nfc_url` as an NDEF URL record onto real tags (NTAG213/215). Tap with several Android phones (NFC on, screen unlocked) and iPhones (XS and later, background tag reading). Confirm each opens `/n/<id>`, the review page, and that the tap is counted as NFC. Note that tags that are write-locked cannot be changed: leave unlocked until you are sure |
| Print colour | Compare the printed orange and the approved artwork under proof |
| `card-url-audit --live` on the real domain | After DNS, TLS and `PUBLIC_CARD_BASE_URL` are set |

No NFC tag is written or read by any test. "NFC works" has not been claimed and must not be until the tag test above is done.

## 9. Known limits

- The approved poster is a single flattened image at about 300 dpi for its size. A4 prints are the same image scaled (about 130 dpi for the artwork, A5 about 180); the QR stays sharp because it is vector. For a large wall poster, ask for a higher-resolution original.
- jsQR (the fallback scanner on iPhone Safari and Firefox) is sensitive to how large the code appears in the frame, so the scanner tries several frame sizes. Typing the serial always works.
- A bulk poster export of individual files is limited to 50 per request (each is about 1 MB); the A4 sheet holds any number.
- Business-side archive of its own cards is not offered; businesses pause or retire.
- The AI Review Assistant page has not yet been split into customer-behaviour, owner-configuration and usage views; the Business Brain and AI usage pages exist.
