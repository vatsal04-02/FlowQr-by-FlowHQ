"""QR generation: permanent identifiers, customisation that can never break scanning, PNG/SVG/PDF + bulk export,
pause/resume, scan tracking and isolation.

"Scans" in these tests means: the generated FILE is rasterised and read by two independent decoders, neither of which is
the library that drew the code:
  * ZXing (zxing-cpp)                 - also the decoder the server uses to prove a style before saving it
  * OpenCV's QRCodeDetectorAruco      - a second, unrelated implementation

Decoder choice is evidence-based (docs/QR_RELIABILITY.md, reproducible with scripts/qr_decoder_study.py):
  * OpenCV's older QRCodeDetector fails to LOCATE about 6% of codes in clean, straight-on images - plain FlowQR codes
    from the original renderer included - while every other decoder reads them. It cannot be a pass/fail gate, so it is
    only used in a test that pins that fact down (logo and style make no difference to it).
  * ZBar needs a system library and is exercised by the study script, not by this suite.
This is the strongest check available without a camera. It is not a test on physical phones or printed paper.
"""
import csv
import io
import itertools
import uuid
import zipfile

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.services import qr_style as qs
from tests.conftest import make_business, owner_query

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
zxingcpp = pytest.importorskip("zxingcpp")
pymupdf = pytest.importorskip("pymupdf")

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"}
UA2 = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile Safari/604.1"}
URL = "https://go.flowqr.co.in/c/abcdefghijklmnopqrstuvwx"


# ------------------------------------------------------------------ scanners
def raster(data: bytes, kind: str, page: int = 0) -> Image.Image:
    if kind == "png":
        return Image.open(io.BytesIO(data)).convert("RGB")
    doc = pymupdf.open(stream=data, filetype=kind)
    pm = doc[page].get_pixmap(dpi=150) if kind == "pdf" else doc[page].get_pixmap()
    return Image.frombytes("RGB", (pm.width, pm.height), pm.samples)


def zxing(img: Image.Image) -> list[str]:
    return [r.text for r in zxingcpp.read_barcodes(img.convert("L"))]


def opencv(img: Image.Image) -> str:
    """OpenCV's ArUco-based QR detector."""
    return cv2.QRCodeDetectorAruco().detectAndDecode(cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR))[0]


def opencv_legacy(img: Image.Image) -> str:
    """OpenCV's original QRCodeDetector: unreliable at locating codes (see module docstring). Not a gate."""
    return cv2.QRCodeDetector().detectAndDecode(cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR))[0]


def photo(img: Image.Image, angle: float, blur: float, noise: float, seed: int, width: int = 700) -> Image.Image:
    """A rough stand-in for a phone photo: rotated, shrunk, slightly out of focus, with sensor noise. Deterministic."""
    im = img.convert("RGB").rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    im = im.resize((width, int(width * im.height / im.width)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(blur))
    arr = np.array(im).astype(np.int16) + np.random.default_rng(seed).normal(0, noise, (im.height, im.width, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def scans_as(data: bytes, kind: str, url: str) -> bool:
    img = raster(data, kind)
    return zxing(img) == [url] and opencv(img) == url


def logo_png(color=(200, 30, 30), size=(400, 240)) -> bytes:
    im = Image.new("RGB", size, (255, 255, 255))
    ImageDraw.Draw(im).ellipse([20, 20, size[0] - 20, size[1] - 20], fill=color)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def put_logo(biz, data=None, content_type="image/png"):
    return biz.http.put("/api/v1/qr/style/logo", content=data or logo_png(), headers={"X-CSRF-Token": biz.csrf, "Content-Type": content_type})


def campaign(biz, name="Front desk"):
    r = biz.post("/review-growth/campaigns", json={"name": name, "location_id": biz.location_id})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def cards(admin, biz_a):
    batch = admin.post("/admin/batches", json={"name": "QR test batch", "quantity": 3}).json()
    items = admin.get("/admin/cards", params={"batch_id": batch["id"]}).json()["items"]
    for c in items:
        assert admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id}).status_code == 200
    return items


# ------------------------------------------------------------------ rendering: every style x format x decoder
STYLES = [
    {},  # plain
    {"dark": "#1B46B8"},
    {"dark": "#0B5D1E", "light": "#FFF8E7", "margin": 8},
    {"dark": "#7A1F5C", "error_correction": "L", "margin": 4, "size_px": 256},
    {"dark": "#000000", "error_correction": "M", "caption": "Scan to review Gomti Physio", "size_px": 2048},
    {"dark": "#1B46B8", "use_logo": True, "logo_scale": 0.25, "caption": "Tell us how we did"},
    {"dark": "#111827", "use_logo": True, "logo_scale": 0.1, "error_correction": "L", "margin": 16},
]
URLS = [URL, "https://go.flowqr.co.in/r/Zq3k9xLmP0aTtYw2bV7cNg", "https://qr.a-much-longer-custom-domain-for-a-business.example.co.in/c/abcdefghijklmnopqrstuvwx"]


@pytest.mark.parametrize("style, url", list(itertools.product(STYLES, URLS)), ids=lambda v: (v if isinstance(v, str) else ",".join(f"{k}={x}" for k, x in v.items()) or "plain")[-48:])
def test_every_style_scans_in_every_format_with_two_decoders(style, url):
    logo = qs.normalise_logo(logo_png())
    assert qs.style_problem(qs.effective_style(style, True)) is None
    for kind, render in (("png", qs.render_png), ("svg", qs.render_svg), ("pdf", qs.render_pdf)):
        data = render(url, style, logo)
        img = raster(data, kind)
        assert zxing(img) == [url], f"ZXing could not read the {kind}"
        assert opencv(img) == url, f"OpenCV could not read the {kind}"
    # and under the conditions the save-time check uses: small and slightly out of focus
    assert qs.scannable(url, style, logo) is True


def test_png_is_at_least_the_requested_size_with_whole_pixel_modules_and_the_full_quiet_zone():
    for size, margin in ((256, 4), (1000, 4), (1024, 9), (4096, 16)):
        img = Image.open(io.BytesIO(qs.render_png(URL, {"size_px": size, "margin": margin})))
        rows, n = qs._matrix(URL, "H")
        scale = img.width // (n + 2 * margin)
        assert img.width == img.height >= size and img.width == scale * (n + 2 * margin) and scale >= qs.MIN_MODULE_PX
        px = img.convert("L")
        border = margin * scale
        assert px.crop((0, 0, img.width, border)).getextrema() == (255, 255) and px.crop((0, 0, border, img.height)).getextrema() == (255, 255)
        assert px.getpixel((border + 1, border + 1)) < 50  # the finder pattern starts exactly where the quiet zone ends


def test_a_logo_always_forces_error_correction_h_and_never_changes_the_encoded_url():
    logo = qs.normalise_logo(logo_png())
    s = qs.effective_style({"use_logo": True, "error_correction": "L"}, True)
    assert s["error_correction"] == "H"
    assert qs.effective_style({"use_logo": True, "error_correction": "L"}, False)["error_correction"] == "L"  # no logo uploaded -> none drawn
    assert qs.effective_style({"margin": 1, "logo_scale": 0.9}, True)["margin"] == 4 and qs.effective_style({"logo_scale": 0.9}, True)["logo_scale"] == 0.25
    for style in STYLES:
        assert zxing(raster(qs.render_png(URL, style, logo), "png")) == [URL]


SHOTS = [(0, 0.6, 3), (4, 0.8, 4), (-9, 1.0, 6), (15, 1.2, 8), (30, 0.8, 6), (60, 1.0, 6), (90, 0.6, 4), (180, 1.0, 6)]  # (rotation, blur, noise)


def test_styled_and_logo_codes_survive_camera_like_conditions():
    """Rotation, blur and noise on every style, logo styles included: ZXing must read every shot. The ArUco detector is
    reported but only required to read the great majority, because it (not the code) drops the odd noisy rotated frame."""
    import random
    rng = random.Random(20261110)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    logo = qs.normalise_logo(logo_png())
    urls = ["https://go.flowqr.co.in/c/" + "".join(rng.choice(alphabet) for _ in range(24)) for _ in range(6)]
    total = aruco_ok = 0
    for style in STYLES:
        for url in urls:
            img = Image.open(io.BytesIO(qs.render_png(url, style, logo)))
            for i, (angle, blur, noise) in enumerate(SHOTS):
                shot = photo(img, angle, blur, noise, i)
                assert zxing(shot) == [url], f"ZXing lost {style} rotated {angle} degrees"
                total += 1
                aruco_ok += opencv(shot) == url
    assert aruco_ok >= total * 0.97, f"OpenCV ArUco read only {aruco_ok}/{total}"


def test_reliable_decoders_read_every_code_with_or_without_a_logo_and_the_legacy_detector_is_no_worse_with_one():
    """The investigation behind the decoder choice, as a regression test, on 120 random codes in three styles.

    * ZXing and OpenCV's ArUco detector read all 120 in every style: a logo costs them nothing.
    * OpenCV's legacy detector misses a handful of PLAIN codes, so its misses cannot be blamed on styling; with a logo it
      misses about the same number (the exact codes differ by one or two between styles, in either direction)."""
    import random
    rng = random.Random(7)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    logo = qs.normalise_logo(logo_png())
    urls = ["https://go.test.flowqr.example/c/" + "".join(rng.choice(alphabet) for _ in range(24)) for _ in range(120)]
    styles = {"plain": {}, "blue+logo": {"dark": "#1B46B8", "use_logo": True}, "black+big logo": {"use_logo": True, "logo_scale": 0.25}}
    read = {name: {"zxing": set(), "aruco": set(), "legacy": set()} for name in styles}
    for name, style in styles.items():
        for u in urls:
            img = Image.open(io.BytesIO(qs.render_png(u, style, logo)))
            if zxing(img) == [u]:
                read[name]["zxing"].add(u)
            if opencv(img) == u:
                read[name]["aruco"].add(u)
            if opencv_legacy(img) == u:
                read[name]["legacy"].add(u)
    missed = {name: 120 - len(read[name]["legacy"]) for name in styles}
    print("legacy OpenCV detector misses out of 120:", missed)
    for name in styles:
        assert len(read[name]["zxing"]) == 120 and len(read[name]["aruco"]) == 120, f"{name}: a reliable decoder missed a code"
        assert missed[name] <= missed["plain"] + 3, f"{name}: the legacy detector is clearly worse with this style: {missed}"
    assert 0 < missed["plain"] < 30, f"legacy OpenCV detector missed {missed['plain']}/120 plain codes; if this is now 0 it could become a gate again"
    # the codes it misses are perfectly readable: it fails to FIND them, and the old renderer's output fails the same way
    from app.services.qr import qr_png
    for u in sorted(set(urls) - read["plain"]["legacy"])[:5]:
        legacy_render = Image.open(io.BytesIO(qr_png(u)))
        assert zxing(legacy_render) == [u] and opencv(legacy_render) == u


@pytest.mark.parametrize("style, why", [
    ({"dark": "#FFFF00"}, "too close"), ({"dark": "#9CA3AF"}, "too close"), ({"dark": "#FF0000"}, "too close"),
    ({"dark": "#FFFFFF", "light": "#000000"}, "darker than the background"), ({"dark": "#777777", "light": "#777777"}, "darker than the background"),
])
def test_unreadable_colour_choices_are_named_as_problems(style, why):
    assert why in qs.style_problem(qs.effective_style(style, False))


def test_a_style_that_does_not_decode_is_replaced_by_the_plain_one_at_download_time():
    """Belt and braces: even if an unscannable style somehow got saved, a download must not hand it out."""
    logo = qs.normalise_logo(logo_png(color=(0, 0, 0), size=(400, 400)))
    hostile = {"dark": "#111827", "use_logo": True, "logo_scale": 0.25}
    real_render = qs._render
    try:  # simulate a renderer/logo combination that destroys the code: a plate covering 70% of it
        qs._scannable.cache_clear()
        qs._render = lambda url, style, logo=None, **kw: _ruin(real_render(url, style, logo, **kw))
        assert qs.scannable(URL, hostile, logo) is False
        style, used_logo, applied = qs.safe_style(URL, hostile, logo)
        assert applied is False and used_logo is None and qs.is_plain(style)
    finally:
        qs._render = real_render
        qs._scannable.cache_clear()
    assert qs.safe_style(URL, hostile, logo)[2] is True  # the real rendering of that style is fine


def _ruin(img: Image.Image) -> Image.Image:
    w = img.width
    ImageDraw.Draw(img).rectangle([w * 0.15, w * 0.15, w * 0.85, w * 0.85], fill=(255, 255, 255))
    return img


def test_logo_upload_validation():
    assert Image.open(io.BytesIO(qs.normalise_logo(logo_png(size=(3000, 1500))))).size == (512, 256)
    for bad, why in ((b"not an image", "readable"), (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "readable"), (logo_png(size=(40, 40)), "64 pixels"),
                     (b"\x00" * (qs.MAX_LOGO_BYTES + 1), "512 KB")):
        with pytest.raises(ValueError, match=why):
            qs.normalise_logo(bad)
    gif = io.BytesIO()
    Image.new("RGB", (100, 100)).save(gif, "GIF")
    with pytest.raises(ValueError, match="PNG, JPEG or WebP"):
        qs.normalise_logo(gif.getvalue())


def test_sheet_pdf_has_twelve_scannable_codes_per_page_and_stays_small():
    items = [(f"FQR-{i:04d}", f"{URL[:-2]}{i:02d}", {"dark": "#1B46B8", "use_logo": True}, qs.normalise_logo(logo_png())) for i in range(14)]
    data = qs.render_sheet_pdf(items)
    doc = pymupdf.open(stream=data, filetype="pdf")
    assert doc.page_count == 2 and len(data) < 200_000
    assert abs(doc[0].rect.width - 595.28) < 0.1 and abs(doc[0].rect.height - 841.89) < 0.1  # A4
    found = sorted(zxing(raster(data, "pdf", 0)) + zxing(raster(data, "pdf", 1)))
    assert found == sorted(u for _, u, _, _ in items)
    assert "FQR-0003" in doc[0].get_text() and "FQR-0013" in doc[1].get_text()
    single = qs.render_pdf(URL, {"caption": "Scan (to) review \\ us"})
    assert len(single) < 20_000 and "Scan (to) review \\ us" in pymupdf.open(stream=single, filetype="pdf")[0].get_text()


# ------------------------------------------------------------------ identifiers: random, unique, permanent
def test_identifiers_are_random_unique_and_survive_everything_but_an_explicit_replace(admin, biz_a, cards):
    tokens = [c["public_token"] for c in cards]
    assert len(set(tokens)) == 3 and all(len(t) == 24 and t.replace("-", "").replace("_", "").isalnum() for t in tokens)
    card = cards[0]
    second_loc = biz_a.post("/locations", json={"name": "Second branch", "review_url": "https://g.page/r/XYZ/review"}).json()["id"]
    c = campaign(biz_a)
    assert len(c["public_id"]) == 22
    assert put_logo(biz_a).status_code == 200
    assert biz_a.put("/qr/style", json={"dark": "#1B46B8", "use_logo": True, "caption": "Review us"}).status_code == 200
    assert biz_a.patch(f"/cards/{card['id']}", json={"location_id": second_loc, "label": "Till", "confirm": True}).status_code == 200  # editable destination (confirmed)
    assert biz_a.post(f"/cards/{card['id']}/pause").status_code == 200 and biz_a.post(f"/cards/{card['id']}/activate").status_code == 200
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"location_id": second_loc, "status": "paused", "qr_style": {"dark": "#0B5D1E"}}).status_code == 200
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"status": "active"}).status_code == 200
    for fmt in ("png", "svg", "pdf"):
        assert biz_a.get(f"/cards/{card['id']}/qr.{fmt}").status_code == 200 and biz_a.get(f"/review-growth/campaigns/{c['id']}/qr.{fmt}").status_code == 200
    after = next(x for x in biz_a.get("/cards").json() if x["id"] == card["id"])
    assert after["public_token"] == card["public_token"] and after["url"] == card["url"] and after["card_code"] == card["card_code"]
    assert biz_a.get(f"/review-growth/campaigns/{c['id']}").json()["public_id"] == c["public_id"]
    assert owner_query("SELECT count(*) FROM qr_cards WHERE public_token = ANY(:t)", t=tokens)[0][0] == 3


def test_new_tokens_never_collide_with_issued_ones(monkeypatch):
    from app.core.db import SessionLocal, set_rls_context
    from app.models import CardBatch, QRCard
    from app.services import cards as svc
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        batch = svc.create_batch(db, name="collide", quantity=2, prefix="FQR", created_by=None, notes=None)
        db.commit()
        taken = list(db.scalars(QRCard.__table__.select().with_only_columns(QRCard.public_token).where(QRCard.batch_id == batch.id)))
        fresh = iter(taken + ["dup-" + "a" * 20, "dup-" + "a" * 20, "new-" + "b" * 20, "new-" + "c" * 20])
        monkeypatch.setattr(svc, "new_public_token", lambda: next(fresh))  # a generator that first repeats issued tokens, then itself
        out = svc.new_public_tokens(db, 3)
        assert len(set(out)) == 3 and not set(out) & set(taken)
        db.delete(db.get(CardBatch, batch.id)); db.commit()
    finally:
        db.close()


def test_printed_codes_keep_working_after_new_codes_are_issued(biz_a, client, monkeypatch):
    """The printed-code guarantee: issuing new codes never kills earlier ones. Every code ever printed for the campaign opens
    the campaign as it is NOW (new destination, new configuration), and all of them feed the same statistics."""
    from app.core import rate_limit
    c = campaign(biz_a)
    url = f"/review-growth/campaigns/{c['id']}/regenerate-qr"
    first = c["public_id"]
    second = biz_a.post(url).json()
    third = biz_a.post(url, json={"confirm": "REPLACE"}).json()  # the old request shape is still accepted
    ids = [first, second["public_id"], third["public_id"]]
    assert len(set(ids)) == 3 and third["retired_codes"] == 2 and [o["public_id"] for o in third["old_codes"]] == [ids[1], ids[0]]
    assert all(o["active"] and o["url"].endswith("/r/" + o["public_id"]) for o in third["old_codes"])
    for pid in ids:
        r = client.get(f"/api/v1/public/reviews/{pid}", headers=UA)
        assert r.status_code == 200 and r.json()["location"]["name"].endswith("Main"), pid
    # edit the destination and the page: every printed code follows
    branch = biz_a.post("/locations", json={"name": "Branch Two", "review_url": "https://g.page/r/NEW/review"}).json()["id"]
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"location_id": branch, "customization": {"welcome_message": "Namaste"}}).status_code == 200
    rate_limit.reset_memory_limits()
    for pid in ids:
        r = client.get(f"/api/v1/public/reviews/{pid}", headers=UA2).json()
        assert r["location"]["name"] == "Branch Two" and r["branding"]["welcome_message"] == "Namaste" and r["review_url"] == "https://g.page/r/NEW/review", pid
    # the whole customer flow works through an OLD printed code, not just the landing request
    old_path = f"/api/v1/public/reviews/{first}"
    done = client.post(f"{old_path}/handoff", json={"final_text": "Lovely staff, very quick service and a clean clinic.", "rating": 5}, headers=UA)
    assert done.status_code == 200, done.text
    stats = biz_a.get(f"/review-growth/campaigns/{c['id']}").json()["stats"]
    assert stats["scans"] >= 2 and stats["google_redirects"] + stats["drafts_approved"] >= 1  # counted on the one campaign
    assert owner_query("SELECT count(DISTINCT campaign_id) FROM review_events WHERE campaign_id = :c", c=c["id"])[0][0] == 1
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'review_campaign.new_code' AND entity_id = :c", c=c["id"])[0][0] == 2
    # pausing and archiving are temporary for every code; resuming brings all of them back
    for off, on in (({"status": "paused"}, {"status": "active"}), ({"status": "archived"}, {"status": "active"})):
        assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json=off).status_code == 200
        assert [client.get(f"/api/v1/public/reviews/{p}", headers=UA).status_code for p in ids] == [410, 410, 410]
        assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json=on).status_code == 200
        assert [client.get(f"/api/v1/public/reviews/{p}", headers=UA).status_code for p in ids] == [200, 200, 200]


def test_only_an_explicit_deactivation_stops_an_old_code_and_it_can_be_undone(biz_a, biz_b, client):
    c = campaign(biz_a)
    first = c["public_id"]
    now = biz_a.post(f"/review-growth/campaigns/{c['id']}/regenerate-qr").json()
    base = f"/review-growth/campaigns/{c['id']}/codes"
    for bad in (None, {}, {"confirm": "yes"}, {"confirm": "REPLACE"}):
        assert biz_a.post(f"{base}/{first}/deactivate", **({"json": bad} if bad is not None else {})).status_code == 422
    assert client.get(f"/api/v1/public/reviews/{first}", headers=UA).status_code == 200  # nothing happened without the explicit word
    assert biz_a.post(f"{base}/{now['public_id']}/deactivate", json={"confirm": "DEACTIVATE"}).status_code == 404  # the current code is not an "old code"
    assert biz_a.post(f"{base}/{'x' * 22}/deactivate", json={"confirm": "DEACTIVATE"}).status_code == 404
    assert biz_b.post(f"{base}/{first}/deactivate", json={"confirm": "DEACTIVATE"}).status_code == 404  # another business
    other = campaign(biz_a, "Other campaign")
    assert biz_a.post(f"/review-growth/campaigns/{other['id']}/codes/{first}/deactivate", json={"confirm": "DEACTIVATE"}).status_code == 404  # wrong campaign

    r = biz_a.post(f"{base}/{first}/deactivate", json={"confirm": "DEACTIVATE"})
    assert r.status_code == 200 and r.json()["old_codes"][0]["active"] is False and r.json()["public_id"] == now["public_id"]
    dead = client.get(f"/api/v1/public/reviews/{first}", headers=UA)
    assert dead.status_code == 410 and dead.json()["detail"]["state"] == "deactivated"
    assert client.post(f"/api/v1/public/reviews/{first}/handoff", json={"final_text": "Lovely staff and a clean clinic.", "rating": 5}, headers=UA).status_code == 410
    assert client.get(f"/api/v1/public/reviews/{now['public_id']}", headers=UA).status_code == 200  # the current code is untouched
    again = biz_a.post(f"{base}/{first}/reactivate")
    assert again.status_code == 200 and again.json()["old_codes"][0]["active"] is True
    assert client.get(f"/api/v1/public/reviews/{first}", headers=UA).status_code == 200  # the same printed code is back
    actions = [a for (a,) in owner_query("SELECT action FROM audit_logs WHERE entity_id = :c AND action LIKE 'review_campaign.code_%' ORDER BY created_at", c=c["id"])]
    assert actions == ["review_campaign.code_deactivate", "review_campaign.code_reactivate"]


def test_old_ids_are_never_reissued_and_new_codes_are_capped(biz_a, monkeypatch):
    from app.services import review_growth as svc
    c = campaign(biz_a)
    first = c["public_id"]
    biz_a.post(f"/review-growth/campaigns/{c['id']}/regenerate-qr")
    real = svc.new_public_id
    feed = iter([first, first])  # a generator that proposes an id already printed
    monkeypatch.setattr(svc, "new_public_id", lambda: next(feed, None) or real())
    nxt = biz_a.post(f"/review-growth/campaigns/{c['id']}/regenerate-qr").json()
    assert nxt["public_id"] != first and first in [o["public_id"] for o in nxt["old_codes"]]
    monkeypatch.setattr(svc, "new_public_id", real)
    codes = [biz_a.post(f"/review-growth/campaigns/{c['id']}/regenerate-qr").status_code for _ in range(20)]
    assert codes[:18] == [200] * 18 and codes[18:] == [409, 409]


# ------------------------------------------------------------------ style API
def test_style_api_saves_only_scannable_styles_and_downloads_use_them(biz_a, cards):
    assert biz_a.get("/qr/style").json() == {"style": {**qs.DEFAULT_STYLE, "dark": "#111827"}, "has_logo": False, "is_default": True, "verification": "decoded"}
    assert biz_a.put("/qr/style", json={"dark": "#FFFF00"}).status_code == 422
    assert biz_a.put("/qr/style", json={"dark": "#ffffff", "light": "#000000"}).status_code == 422
    assert biz_a.put("/qr/style", json={"margin": 3}).status_code == 422 and biz_a.put("/qr/style", json={"logo_scale": 0.4}).status_code == 422
    assert biz_a.put("/qr/style", json={"size_px": 100}).status_code == 422 and biz_a.put("/qr/style", json={"error_correction": "X"}).status_code == 422
    assert biz_a.put("/qr/style", json={"caption": "हमें रेट करें"}).status_code == 422  # label font is Latin-only; refused, not drawn as boxes
    assert biz_a.put("/qr/style", json={"use_logo": True}).status_code == 422  # no logo uploaded yet
    assert biz_a.get("/qr/style").json()["is_default"] is True  # none of the rejected styles was saved

    assert put_logo(biz_a, b"GIF89a-not-really").status_code == 422
    assert put_logo(biz_a, b"\x00" * (qs.MAX_LOGO_BYTES + 10)).status_code == 413
    assert put_logo(biz_a).json()["has_logo"] is True
    saved = biz_a.put("/qr/style", json={"dark": "#1b46b8", "use_logo": True, "error_correction": "L", "caption": "  Review   us ", "margin": 6})
    assert saved.status_code == 200 and saved.json()["style"]["dark"] == "#1B46B8" and saved.json()["style"]["caption"] == "Review us" and not saved.json()["is_default"]
    assert biz_a.get("/qr/style/logo.png").content[:8] == b"\x89PNG\r\n\x1a\n"

    card = cards[0]
    for fmt, mime in (("png", "image/png"), ("svg", "image/svg+xml"), ("pdf", "application/pdf")):
        r = biz_a.get(f"/cards/{card['id']}/qr.{fmt}")
        assert r.status_code == 200 and r.headers["content-type"].startswith(mime) and r.headers["x-flowqr-style"] == "applied"
        assert f'filename="{card["card_code"]}.{fmt}"' in r.headers["content-disposition"]
        assert scans_as(r.content, fmt, card["url"])
    png = Image.open(io.BytesIO(biz_a.get(f"/cards/{card['id']}/qr.png", params={"size": 600}).content)).convert("RGB")
    assert png.width >= 600 and (27, 70, 184) in {c for _, c in png.getcolors(1 << 20)}  # the brand colour is really used
    assert biz_a.get(f"/cards/{card['id']}/qr.gif").status_code == 404 and biz_a.get(f"/cards/{card['id']}/qr.png", params={"size": 99999}).status_code == 422

    preview = biz_a.post("/qr/preview.png", json={"dark": "#0B5D1E", "use_logo": True})
    assert preview.status_code == 200 and preview.headers["x-flowqr-scannable"] == "yes"
    assert zxing(raster(preview.content, "png"))[0].endswith("/c/PREVIEW-not-a-real-code0")  # a sample, not anyone's card

    assert biz_a.delete("/qr/style/logo").json() == {**biz_a.get("/qr/style").json(), "has_logo": False} and biz_a.get("/qr/style").json()["style"]["use_logo"] is False
    assert biz_a.delete("/qr/style").json()["is_default"] is True
    actions = {a for (a,) in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t AND action LIKE 'qr.%'", t=biz_a.tenant_id)}
    assert actions == {"qr.logo_update", "qr.style_update", "qr.logo_delete", "qr.style_reset"}


def test_campaign_style_override_and_reset(biz_a):
    c = campaign(biz_a)
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"qr_style": {"dark": "#FFFF00"}}).status_code == 422
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"qr_style": {"use_logo": True}}).status_code == 422  # no logo uploaded
    r = biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"qr_style": {"dark": "#7A1F5C", "caption": "Front desk"}})
    assert r.status_code == 200 and r.json()["qr_style"]["dark"] == "#7A1F5C" and r.json()["public_id"] == c["public_id"]
    for fmt in ("png", "svg", "pdf"):
        assert scans_as(biz_a.get(f"/review-growth/campaigns/{c['id']}/qr.{fmt}").content, fmt, c["url"])
    colours = {col for _, col in Image.open(io.BytesIO(biz_a.get(f"/review-growth/campaigns/{c['id']}/qr.png").content)).convert("RGB").getcolors(1 << 20)}
    assert (122, 31, 92) in colours
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"qr_style": None}).json()["qr_style"] is None
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"name": "Renamed desk"}).json()["qr_style"] is None  # other edits leave it alone


def test_plain_codes_are_unchanged_for_businesses_that_never_customise(admin, biz_a, cards):
    """Existing printed cards: with no style saved, the code a business downloads has the same modules as the legacy renderer."""
    from app.services.qr import qr_png
    card = cards[0]
    def modules(data: bytes):  # dark/light per pixel by threshold (no dithering)
        im = Image.open(io.BytesIO(data)).convert("L")
        return im.size, im.point(lambda v: 255 if v > 127 else 0).tobytes()
    new = modules(biz_a.get(f"/cards/{card['id']}/qr.png", params={"size": 588}).content)
    old = modules(qr_png(card["url"], scale=new[0][0] // (qs._matrix(card["url"], "H")[1] + 8)))
    assert new == old
    assert admin.get(f"/admin/cards/{card['id']}/qr.png").content == qr_png(card["url"])  # the platform export is byte-identical to before


# ------------------------------------------------------------------ bulk
def test_bulk_export_zip_contains_every_code_in_every_format_all_scannable(biz_a, cards):
    c1, c2 = campaign(biz_a, "Front desk"), campaign(biz_a, "Front desk")  # same name: files must not overwrite each other
    put_logo(biz_a)
    assert biz_a.put("/qr/style", json={"dark": "#1B46B8", "use_logo": True}).status_code == 200
    r = biz_a.post("/qr/bulk", json={"all_cards": True, "campaign_ids": [c1["id"], c2["id"]]})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and r.headers["x-flowqr-codes"] == "5" and r.headers["x-flowqr-style-fallbacks"] == "0"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert len([n for n in names if n.startswith("png/")]) == len([n for n in names if n.startswith("svg/")]) == len([n for n in names if n.startswith("pdf/")]) == 5
    rows = list(csv.DictReader(io.StringIO(z.read("manifest.csv").decode())))
    by_name = {}
    for n in names:
        if "/" in n:
            by_name.setdefault(n.split("/")[1].rsplit(".", 1)[0], []).append(n)
    urls = sorted(row["permanent_url"] for row in rows)
    assert urls == sorted([c["url"] for c in cards] + [c1["url"], c2["url"]]) and len(by_name) == 5
    scanned = []
    for stem, files in by_name.items():
        got = {tuple(zxing(raster(z.read(f), f.rsplit(".", 1)[1]))) for f in files}
        assert len(got) == 1 and len(next(iter(got))) == 1, f"{stem}: formats disagree or failed to scan"
        assert all(opencv(raster(z.read(f), f.rsplit(".", 1)[1])) == next(iter(got))[0] for f in files)
        scanned.append(next(iter(got))[0])
    assert sorted(scanned) == urls
    sheet = z.read("print-sheet-A4.pdf")
    assert sorted(zxing(raster(sheet, "pdf"))) == urls
    assert owner_query("SELECT metadata->>'cards', metadata->>'campaigns' FROM audit_logs WHERE tenant_id = :t AND action = 'qr.bulk_export'", t=biz_a.tenant_id) == [("3", "2")]

    only = biz_a.post("/qr/bulk", json={"card_ids": [cards[0]["id"]], "formats": ["svg"], "sheet": False})
    assert zipfile.ZipFile(io.BytesIO(only.content)).namelist() == [f"svg/{cards[0]['card_code']}.svg", "manifest.csv"]
    assert biz_a.post("/qr/bulk", json={}).status_code == 422 and biz_a.post("/qr/bulk", json={"card_ids": [str(uuid.uuid4())]}).status_code == 404


def test_bulk_and_downloads_are_tenant_isolated_and_admin_only(biz_a, biz_b, cards):
    from tests.test_location_permissions import invite
    c = campaign(biz_a)
    assert biz_b.post("/qr/bulk", json={"card_ids": [cards[0]["id"]]}).status_code == 404
    assert biz_b.post("/qr/bulk", json={"campaign_ids": [c["id"]]}).status_code == 404
    assert biz_b.post("/qr/bulk", json={"all_cards": True, "all_campaigns": True}).status_code == 404  # B has none: A's are not included
    assert biz_b.get(f"/cards/{cards[0]['id']}/qr.pdf").status_code == 404 and biz_b.get(f"/review-growth/campaigns/{c['id']}/qr.pdf").status_code == 404
    assert biz_b.post(f"/cards/{cards[0]['id']}/pause").status_code == 404
    put_logo(biz_a)
    assert biz_b.get("/qr/style").json()["has_logo"] is False and biz_b.get("/qr/style/logo.png").status_code == 404  # styles and logos are per business
    staff = invite(biz_a)
    assert staff.get("/qr/style").status_code == 200  # read-only for staff
    for call in (lambda: staff.put("/qr/style", json={}), lambda: put_logo(staff), lambda: staff.post("/qr/bulk", json={"all_cards": True}),
                 lambda: staff.get(f"/cards/{cards[0]['id']}/qr.png"), lambda: staff.post(f"/cards/{cards[0]['id']}/pause"), lambda: staff.post("/qr/preview.png", json={})):
        assert call().status_code == 403
    from sqlalchemy import create_engine, text
    from app.core.config import settings
    with create_engine(settings.database_url).begin() as conn:  # app role: RLS applies to the new tables
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": biz_b.tenant_id})
        assert conn.execute(text("SELECT count(*) FROM qr_styles")).scalar() == 0


# ------------------------------------------------------------------ lifecycle + scan tracking
def test_pause_resume_deactivate_and_scan_counts(admin, biz_a, cards, client):
    card = cards[0]
    path = f"/api/v1/public/c/{card['public_token']}"
    assert client.get(path, headers=UA).json()["state"] == "ok"
    assert client.get(path, headers=UA).json()["state"] == "ok"  # same phone again within seconds: one scan
    assert client.get(path, headers=UA2).json()["state"] == "ok"
    assert client.get(path, headers={"User-Agent": "curl/8.5"}).json()["state"] == "ok"  # bots resolve but are not counted
    assert biz_a.post(f"/cards/{card['id']}/pause").json()["status"] == "paused"
    assert client.get(path, headers=UA).json()["state"] == "inactive"
    assert biz_a.post(f"/cards/{card['id']}/pause").status_code == 409
    assert biz_a.post(f"/cards/{card['id']}/activate").json()["status"] == "active"
    assert client.get(path, headers=UA2).json()["state"] == "ok"
    assert biz_a.post(f"/cards/{card['id']}/deactivate").json()["status"] == "deactivated"
    assert client.get(path, headers=UA).json()["state"] == "inactive"
    mine = next(x for x in biz_a.get("/cards").json() if x["id"] == card["id"])
    assert mine["stats"]["scan"] == 2 and mine["stats"]["unique_scan"] == 2 and mine["stats"]["fallback"] == 2 and mine["last_scan_at"]
    assert mine["location_id"] == biz_a.location_id
    actions = [a for (a,) in owner_query("SELECT action FROM audit_logs WHERE entity_id = :c ORDER BY created_at", c=card["id"])]
    assert [a for a in actions if a.startswith("card.")] == ["card.pause", "card.activate", "card.deactivate"]
    rows = owner_query("SELECT event_type, tenant_id::text, location_id::text, created_at IS NOT NULL FROM scan_events WHERE card_id = :c AND event_type = 'scan' AND NOT is_bot", c=card["id"])
    assert rows == [("scan", biz_a.tenant_id, biz_a.location_id, True)] * 2


def test_campaign_scans_record_unique_visitors_and_the_location_at_the_time(biz_a, client):
    c = campaign(biz_a)
    path = f"/api/v1/public/reviews/{c['public_id']}"
    for ua in (UA, UA, UA2):
        assert client.get(path, headers=ua).status_code == 200
    second = biz_a.post("/locations", json={"name": "Second branch", "review_url": "https://g.page/r/XYZ/review"}).json()["id"]
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"location_id": second}).status_code == 200  # re-point: same printed code
    from app.core import rate_limit
    rate_limit.reset_memory_limits()
    owner_query("SELECT 1")
    from tests.conftest import owner_exec
    owner_exec("UPDATE review_events SET created_at = created_at - interval '1 minute' WHERE campaign_id = :c", c=c["id"])  # step past the refresh window
    assert client.get(path, headers=UA).status_code == 200
    stats = biz_a.get(f"/review-growth/campaigns/{c['id']}").json()["stats"]
    assert stats["scans"] == 3 and stats["unique_scans"] == 2
    by_loc = dict(owner_query("SELECT location_id::text, count(*) FROM review_events WHERE campaign_id = :c AND event_type = 'scan' GROUP BY 1", c=c["id"]))
    assert by_loc == {biz_a.location_id: 2, second: 1}
    assert biz_a.get("/review-growth/analytics", params={"location_id": biz_a.location_id}).json()["totals"]["scans"] == 2
    assert biz_a.get("/review-growth/analytics", params={"location_id": second}).json()["totals"]["scans"] == 1
    assert biz_a.get("/review-growth/analytics", params={"location_id": str(uuid.uuid4())}).status_code == 404


def test_scan_validation_and_guessing_is_rate_limited(client, cards):
    assert client.get("/api/v1/public/c/short", headers=UA).status_code == 404
    assert client.get("/api/v1/public/c/" + "a" * 23 + "%27", headers=UA).status_code == 404  # characters tokens never contain
    assert client.get("/api/v1/public/c/" + "a" * 65, headers=UA).status_code == 404
    before = owner_query("SELECT count(*) FROM scan_events")[0][0]
    codes = [client.get(f"/api/v1/public/c/{uuid.uuid4().hex}", headers=UA).status_code for _ in range(40)]
    assert codes[:27] == [404] * 27 and codes[-1] == 429 and 429 in codes
    assert owner_query("SELECT count(*) FROM scan_events")[0][0] == before  # guesses are never recorded
    from app.core import rate_limit
    rate_limit.reset_memory_limits()
    codes = [client.get(f"/api/v1/public/reviews/{uuid.uuid4().hex[:22]}", headers=UA).status_code for _ in range(40)]
    assert codes[0] == 404 and codes[-1] == 429


# ------------------------------------------------------------------ permanence: nothing but an explicit replace ends a printed code
def _resolves(client, card=None, campaign=None) -> str:
    if card:
        return client.get(f"/api/v1/public/c/{card['public_token']}", headers=UA).json()["state"]
    r = client.get(f"/api/v1/public/reviews/{campaign['public_id']}", headers=UA)
    return r.json()["state"] if r.status_code == 200 else r.json()["detail"]["state"]


def test_every_edit_keeps_the_printed_code_working_and_its_history(admin, biz_a, cards, client):
    """Destination, labels, look, landing-page configuration, pausing and business re-mapping: after each one the SAME
    printed token/link still resolves, and earlier scans are still there."""
    card, c = cards[0], campaign(biz_a)
    assert _resolves(client, card=card) == "ok" and _resolves(client, campaign=c) == "ok"
    second = biz_a.post("/locations", json={"name": "Second branch", "review_url": "https://g.page/r/XYZ/review"}).json()["id"]
    put_logo(biz_a)
    edits = [
        lambda: biz_a.patch(f"/cards/{card['id']}", json={"location_id": second, "confirm": True}),
        lambda: biz_a.patch(f"/cards/{card['id']}", json={"label": "Reception"}),
        lambda: biz_a.patch(f"/locations/{second}", json={"review_url": "https://g.page/r/NEW/review", "name": "Renamed branch"}),
        lambda: biz_a.put("/qr/style", json={"dark": "#1B46B8", "use_logo": True, "error_correction": "Q", "margin": 8, "caption": "Hi"}),
        lambda: biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"location_id": second}),
        lambda: biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"name": "New name", "qr_style": {"dark": "#0B5D1E"}}),
        lambda: biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"customization": {"brand_color": "#AA0000", "welcome_message": "Namaste"}}),
        lambda: biz_a.patch("/tenant", json={"name": "Alpha Physio Renamed"}),
        lambda: biz_a.delete("/qr/style"),
    ]
    for i, edit in enumerate(edits):
        r = edit()
        assert r.status_code == 200, f"edit {i}: {r.status_code} {r.text[:200]}"
        from app.core import rate_limit
        rate_limit.reset_memory_limits()
        assert _resolves(client, card=card) == "ok" and _resolves(client, campaign=c) == "ok", f"edit {i} broke a printed code"
    # pause is temporary and resuming restores the same code
    assert biz_a.post(f"/cards/{card['id']}/pause").status_code == 200 and _resolves(client, card=card) == "inactive"
    assert biz_a.post(f"/cards/{card['id']}/activate").status_code == 200 and _resolves(client, card=card) == "ok"
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"status": "paused"}).status_code == 200 and _resolves(client, campaign=c) == "inactive"
    assert biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"status": "active"}).status_code == 200 and _resolves(client, campaign=c) == "ok"
    # identifiers and history are intact
    now_card = next(x for x in biz_a.get("/cards").json() if x["id"] == card["id"])
    now_c = biz_a.get(f"/review-growth/campaigns/{c['id']}").json()
    assert (now_card["public_token"], now_card["card_code"], now_card["url"]) == (card["public_token"], card["card_code"], card["url"])
    assert (now_c["public_id"], now_c["url"], now_c["qr_rotated_at"], now_c["retired_codes"], now_c["old_codes"]) == (c["public_id"], c["url"], None, 0, [])
    assert now_card["stats"]["scan"] >= 1 and now_c["stats"]["scans"] >= 1
    assert owner_query("SELECT count(*) FROM scan_events WHERE card_id = :c AND location_id = :l", c=card["id"], l=biz_a.location_id)[0][0] >= 1  # old scans keep their old location
    assert owner_query("SELECT count(*) FROM card_assignments WHERE card_id = :c", c=card["id"])[0][0] == 2  # assignment history, not overwritten

    # re-mapping the card to ANOTHER business keeps the token; the first business's scan history stays theirs
    other = make_business("Other Clinic")
    assert admin.post(f"/admin/cards/{card['id']}/unassign", json={"confirm": True}).status_code == 200
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": other.tenant_id, "location_id": other.location_id}).status_code == 200
    assert client.get(f"/api/v1/public/c/{card['public_token']}", headers=UA).json()["business"]["name"] == "Other Clinic"
    assert owner_query("SELECT count(*) FROM scan_events WHERE card_id = :c AND tenant_id = :t", c=card["id"], t=biz_a.tenant_id)[0][0] >= 1
    assert owner_query("SELECT public_token FROM qr_cards WHERE id = :c", c=card["id"]) == [(card["public_token"],)]


def test_a_destination_that_would_break_the_code_is_refused(biz_a, cards, client):
    card, c = cards[0], campaign(biz_a)
    dead = biz_a.post("/locations", json={"name": "Closed branch"}).json()["id"]
    assert biz_a.delete(f"/locations/{dead}").status_code == 204  # nothing points at it: no confirmation needed
    r = biz_a.patch(f"/cards/{card['id']}", json={"location_id": dead})
    assert r.status_code == 400 and "deactivated" in r.json()["detail"]
    r = biz_a.patch(f"/review-growth/campaigns/{c['id']}", json={"location_id": dead})
    assert r.status_code == 400 and "deactivated" in r.json()["detail"]
    assert _resolves(client, card=card) == "ok" and _resolves(client, campaign=c) == "ok"
    assert biz_a.get(f"/review-growth/campaigns/{c['id']}").json()["location_id"] == biz_a.location_id


def test_deactivating_a_location_with_live_codes_needs_explicit_confirmation(biz_a, cards, client):
    c = campaign(biz_a)
    loc = biz_a.location_id
    for call in (lambda **kw: biz_a.delete(f"/locations/{loc}", **kw), lambda **kw: biz_a.patch(f"/locations/{loc}", json={"is_active": False}, **kw)):
        r = call()
        assert r.status_code == 409 and r.json()["detail"]["code"] == "codes_would_stop"
        assert (r.json()["detail"]["cards"], r.json()["detail"]["campaigns"]) == (3, 1) and "3 card(s) and 1 QR campaign(s)" in r.json()["detail"]["message"]
        assert biz_a.get(f"/locations/{loc}").json()["is_active"] is True and _resolves(client, card=cards[0]) == "ok"  # nothing happened
    assert biz_a.patch(f"/locations/{loc}", json={"name": "Just a rename"}).status_code == 200  # ordinary edits never ask
    assert biz_a.delete(f"/locations/{loc}", params={"confirm": "true"}).status_code == 204
    assert _resolves(client, card=cards[0]) == "inactive" and _resolves(client, campaign=c) == "inactive"
    # reactivating brings the SAME printed codes back
    assert biz_a.patch(f"/locations/{loc}", json={"is_active": True}).status_code == 200
    from app.core import rate_limit
    rate_limit.reset_memory_limits()
    assert _resolves(client, card=cards[0]) == "ok" and _resolves(client, campaign=c) == "ok"
    meta = owner_query("SELECT metadata->'codes_stopped' FROM audit_logs WHERE tenant_id = :t AND action = 'location.deactivate'", t=biz_a.tenant_id)
    assert meta == [({"cards": 3, "campaigns": 1},)]
