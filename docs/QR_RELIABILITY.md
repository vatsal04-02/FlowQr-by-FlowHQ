# QR reliability: permanence and scannability

Last updated 2026-11-10. Two separate guarantees are covered here: a printed code keeps **leading somewhere** (permanence), and a code can be **read** (scannability).

## 1. Permanence: what can and cannot stop a printed code

A code encodes only a permanent FlowQR link: `/c/{token}` for a card, `/r/{public_id}` for a campaign. Tokens and ids are random (144 and 128 bits from the OS random source), checked against every id ever issued, and never reused.

| Action | Effect on codes already printed |
|---|---|
| Change the destination (card or campaign moved to another location) | Keeps working, opens the new destination |
| Change the Google review link, landing page, name, label, QR design, logo | Keeps working |
| Download or bulk-export again | No effect |
| **Issue a new code for a campaign** | **The earlier code keeps working** as an alias of the same campaign |
| Reassign a card to another business (platform admin) | Same token, opens the new business |
| Pause a card or campaign | Stops until resumed; the same code comes back |
| Archive a campaign | Stops until restored; the same codes come back |
| Deactivate a card | Stops until reactivated; the same code comes back |
| Deactivate a location that live codes lead to | Stops those codes until the location is reactivated. Refused (HTTP 409 with counts) unless explicitly confirmed |
| Move a code to a deactivated location | Refused |
| **Switch off one earlier campaign code** | Stops that one code. Needs the typed word `DEACTIVATE`. Can be switched back on |
| Report a card lost | Stops; only FlowQR support can re-enable |
| Permanently delete an archived campaign (owner only) | Ends all its codes for good |

Rules the code enforces:

* Editing never invalidates anything. `PATCH` on a card or campaign cannot change a token or public id.
* Issuing a new code (`POST /review-growth/campaigns/{id}/regenerate-qr`) records the previous id in `review_campaign_retired_ids` and keeps resolving it. A campaign can hold up to 20 earlier codes.
* The only way to stop a code while its campaign is live is `POST .../codes/{public_id}/deactivate` with `{"confirm": "DEACTIVATE"}`. A scan then gets HTTP 410 with state `deactivated`. `.../reactivate` undoes it.
* Scan history is never rewritten. Card scans store the tenant and location at the time; campaign scans store the location at the time (`review_events.location_id`).
* All of the above are written to the audit log.

**History note.** Before migration 0014 a regenerated campaign code was overwritten and its old id was not stored anywhere, so codes replaced before that cannot be revived. Under 0014 (never released) a replaced code stopped working; migration 0015 turns any such row into a working alias.

**Not changed, by design:** unassigning a card (platform admin) makes it show "not set up yet" until it is assigned again.

Regression tests: `backend/tests/test_qr.py` (`test_printed_codes_keep_working_after_new_codes_are_issued`, `test_only_an_explicit_deactivation_stops_an_old_code_and_it_can_be_undone`, `test_old_ids_are_never_reissued_and_new_codes_are_capped`, `test_every_edit_keeps_the_printed_code_working_and_its_history`, `test_a_destination_that_would_break_the_code_is_refused`, `test_deactivating_a_location_with_live_codes_needs_explicit_confirmation`) and the browser test `e2e/qr-and-access.js`.

## 2. Scannability: how customised codes are kept readable

Rules applied before a design is saved or drawn (`backend/app/services/qr_style.py`):

* The code colour must be darker than the background, with a contrast ratio of at least 4.5:1.
* The quiet zone is at least 4 modules and cannot be lowered.
* A logo covers at most 25% of the code width, sits on a clear plate, and forces error correction to High.
* Modules are always a whole number of pixels, at least 4.
* **Decode check.** A sample code is drawn with the design and read back with ZXing at full size, shrunk to 240 px, and slightly blurred. If any of the three fails, the design is refused. At download time a design that fails the same check is replaced by the plain design, and the response says so (`X-FlowQR-Style: fallback-plain`).

## 3. Decoder study

### Method

`backend/scripts/qr_decoder_study.py` renders random FlowQR links and reads them with four decoders, none of which is the library that draws the codes: ZXing (`zxing-cpp`), OpenCV `QRCodeDetectorAruco`, OpenCV's original `QRCodeDetector`, and ZBar (`pyzbar`). Everything is seeded, so a run on the same library versions prints the same numbers. "Camera-like" means the image is rotated, shrunk to 700 px, blurred and given sensor noise.

```
pip install -r requirements-dev.txt pyzbar     # pyzbar also needs the system library libzbar0
python scripts/qr_decoder_study.py [--quick]
```

### Results (run of 2026-11-10, `--quick`, OpenCV 5.0.0)

**A. Clean, straight-on renders: codes not read, out of 120**

| Style | ZXing | OpenCV ArUco | OpenCV legacy | ZBar |
|---|---|---|---|---|
| Old renderer, plain | 0 | 0 | 7 | 0 |
| New renderer, plain | 0 | 0 | 7 | 0 |
| Blue | 0 | 0 | 7 | 0 |
| Blue + logo 20% | 0 | 0 | 8 | 0 |
| Black + logo 25% | 0 | 0 | 7 | 0 |
| Black + dark logo 25% | 0 | 0 | 7 | 0 |

**B. Camera-like shots (8 per code, rotations 0° to 180°): shots not read, out of 96**

All four decoders read all 96 shots for every style, logo styles included.

**C. Steep rotation by colour: codes not read, out of 8, at 0°, 30°, 40°, 45°, 50°, 60°**

| Colour | ZXing | OpenCV ArUco | OpenCV legacy | ZBar |
|---|---|---|---|---|
| Pure black `#000000` | 0 at every angle | 1 at 45° | 0 | 0 at every angle |
| FlowQR default `#111827` | 0 | 0 | 0 | 7 at 40° |
| Green `#0B5D1E` | 0 | 0 | 0 | 7, 8, 8 at 40°, 45°, 50° |
| Blue `#1B46B8` | 0 | 0 | 0 | 7, 8, 8 at 40°, 45°, 50° |
| Blue on cream | 0 | 0 | 0 | 8, 0, 8 at 40°, 45°, 50° |
| Grey `#757575` (4.6:1) | 0 | 0 | 0 | 8, 8, 8 at 40°, 45°, 50° |

### What the results mean

1. **A logo does not reduce readability in these tests.** ZXing, OpenCV ArUco and ZBar read every clean render with and without a logo, and every camera-like shot.
2. **OpenCV's legacy detector is not a usable pass/fail gate.** It fails to locate about 6% of codes in clean images, and it fails on plain codes from the original renderer just as often. Its misses follow the individual code, not the styling. The test suite therefore uses ZXing and OpenCV ArUco as gates, and keeps one test that pins the legacy detector's behaviour down (`test_reliable_decoders_read_every_code_with_or_without_a_logo_and_the_legacy_detector_is_no_worse_with_one`).
3. **ZBar is sensitive to colour at 40° to 50° rotation.** With blur and noise it misses most codes that are not pure black, including FlowQR's long-standing default `#111827`, while reading them at 0°, 30° and 60°. This predates the customisation work. The default colour has **not** been changed; switching it to pure black is a product decision.

### Known limitations

* These are rendered files and synthetic distortions. **Nothing here was tested on printed paper or with a physical phone.** Glossy lamination, curved surfaces, low light, small print sizes and damaged cards are not covered.
* The save-time check uses one decoder (ZXing). Phone cameras use their own decoders, which may be stricter or more lenient.
* If the `zxing-cpp` package is missing on a server, only the colour and margin rules apply; the API reports this as `verification: "rules_only"`.
* The camera section of the study used the `--quick` sample sizes shown above. Run without `--quick` for larger samples.
* Captions and print-sheet labels support Latin characters only. Hindi captions are refused, not drawn as boxes.
* Print a test copy and scan it with at least two phones before any large print run.
