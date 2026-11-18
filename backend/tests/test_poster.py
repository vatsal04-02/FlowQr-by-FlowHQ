"""The branded FlowQR review poster: the approved artwork, with only the QR code replaced.

What these tests pin down:
  * the artwork outside the QR area is the approved poster, bit for bit (a pinned fingerprint of the approved image), and is identical
    for every business, campaign and card;
  * the code is a real, square, whole-pixel QR with a quiet zone, inside the same frame;
  * PNG (1x, 2x, 3x), SVG and PDF (approved size, A6, A5, A4) all decode, with an independent decoder, to exactly the URL they were made for;
  * a poster that cannot be proven scannable is not served; posters are only produced for a permanent HTTPS address when printing in bulk.
"""
import hashlib
import io
import random
import re
import time
import zipfile

import pytest
from PIL import Image, ImageChops, ImageDraw

from app.services import poster
from app.services import qr_style as qs
from tests.conftest import make_business
from tests.test_card_inventory import BASE, all_cards, new_batch
from tests.test_location_permissions import invite
from tests.test_qr import UA, campaign, opencv, photo, raster, zxing

pymupdf = pytest.importorskip("pymupdf")

# SHA-256 of the approved poster's pixels with the QR module area blacked out. The approved PDF (page 1) and the template built from it
# give the same value: everything outside the QR area is the approved artwork.
APPROVED_OUTSIDE_QR = "1e13727c0a9e3df9ad576fbfc1c35e4b0f8d2c4c1db4a619c7b2660f42304485"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
G = poster.G


def make_urls(count, seed=11, kind="q"):
    rng = random.Random(seed)
    return [f"{BASE}/{kind}/" + "".join(rng.choice(ALPHABET) for _ in range(24)) for _ in range(count)]


def outside_qr(img: Image.Image, scale: int = 1, serial_area: bool = False) -> bytes:
    """The poster's pixels with the QR area blacked out. serial_area=True also blanks the small corner where a card's serial is printed (see SERIAL_RIGHT)."""
    im = img.convert("RGB").copy()
    e = G["erase"]
    d = ImageDraw.Draw(im)
    d.rectangle([v * scale for v in e], fill=(0, 0, 0))
    if serial_area:
        d.rectangle([v for v in serial_box(scale)], fill=(0, 0, 0))
    return im.tobytes()


def qr_crop(img: Image.Image, lay: "poster.Layout", scale: int = 1, quiet: int = 4) -> Image.Image:
    """Just the code with `quiet` modules of white around it: how a scanner that has already framed the code sees it."""
    m, k = lay.m * scale, scale
    box = (lay.x0 * k - quiet * m, lay.y0 * k - quiet * m, (lay.x0 + lay.side) * k + quiet * m, (lay.y0 + lay.side) * k + quiet * m)
    c = img.convert("RGB").crop(box)
    w = Image.new("RGB", c.size, "white")
    inner = (quiet * m, quiet * m, quiet * m + lay.side * k, quiet * m + lay.side * k)
    w.paste(c.crop(inner), inner[:2])
    return w


# ------------------------------------------------------------------ the artwork is untouched
def test_the_template_is_the_approved_artwork_everywhere_outside_the_qr_area():
    t = poster._template()
    assert t.size == (1055, 1491)
    assert hashlib.sha256(outside_qr(t)).hexdigest() == APPROVED_OUTSIDE_QR
    # the cleared area is the card's own white: nothing of the old illustrative code is left
    x0, y0, x1, y1 = G["erase"]
    inside = t.crop((x0, y0, x1, y1)).convert("L")
    assert inside.getextrema() == (250, 255) or inside.getextrema()[0] >= 250


def test_every_poster_is_the_same_artwork_for_any_business_campaign_or_card_and_only_the_code_differs():
    urls = make_urls(3) + make_urls(2, seed=5, kind="r") + [f"https://go.flowqr.co.in/q/{'x' * 24}"]
    approved = hashlib.sha256(outside_qr(poster._template())).hexdigest()
    insides = set()
    for u in urls:
        img = Image.open(io.BytesIO(poster.poster_png(u)))
        assert img.size == (1055, 1491)
        assert hashlib.sha256(outside_qr(img)).hexdigest() == approved, u  # frame, Google heading, stars, buttons, footer: untouched
        x0, y0, x1, y1 = G["erase"]
        insides.add(img.crop((x0, y0, x1, y1)).tobytes())
    assert len(insides) == len(urls)  # and the QR area is the only thing that differs
    for k in (2, 3):  # larger exports are the same artwork scaled, not a different design
        img = Image.open(io.BytesIO(poster.poster_png(urls[0], scale=k)))
        assert img.size == (1055 * k, 1491 * k)
        ref = poster._template().resize(img.size, Image.LANCZOS)
        assert hashlib.sha256(outside_qr(img, k)).hexdigest() == hashlib.sha256(outside_qr(ref, k)).hexdigest()


def test_the_code_is_square_whole_pixel_modules_inside_the_card_with_a_quiet_zone():
    cx0, cy0, cx1, cy1 = G["card"]
    for u in make_urls(8, seed=3) + [f"{BASE}/r/Zq3k9xLmP0aTtYw2bV7cNg", f"{BASE}/c/{'a' * 24}"]:
        lay = poster.resolve(u)
        assert lay.side == lay.n * lay.m and lay.m >= poster.MIN_MODULE_PX  # whole pixels per module: never stretched, never fractional
        assert lay.ecc in ("Q", "H")  # at least 25% error correction (a logo covers the middle)
        assert lay.x0 - cx0 >= 18 and cx1 - (lay.x0 + lay.side) >= 18 and lay.y0 - cy0 >= 18 and cy1 - (lay.y0 + lay.side) >= 18  # white card around the code
        assert abs((lay.x0 + lay.side / 2) - 527.5) <= 1 and abs((lay.y0 + lay.side / 2) - 693.5) <= 1  # centred in the card
        assert len(lay.rows) == lay.n and all(len(r) == lay.n for r in lay.rows)
    # the logo tile covers well under the error-correction budget
    lay = poster.resolve(make_urls(1)[0])
    tile_modules = (poster.G["tile_px"][0] / lay.m) ** 2
    assert tile_modules / (lay.n ** 2) < 0.12


# ------------------------------------------------------------------ every format decodes to exactly its URL
URL_SETS = make_urls(3) + [f"{BASE}/r/Zq3k9xLmP0aTtYw2bV7cNg", f"https://go.flowqr.co.in/q/{'Z' * 24}", f"{BASE}/c/{'k' * 24}"]


@pytest.mark.parametrize("url", URL_SETS)
def test_png_svg_and_pdf_all_decode_to_exactly_the_url(url):
    for k in (1, 2, 3):
        img = Image.open(io.BytesIO(poster.poster_png(url, scale=k)))
        assert zxing(img) == [url], f"png x{k}"
    assert zxing(raster(poster.poster_svg(url), "svg")) == [url], "svg"
    for size in ("ref", "a6", "a5", "a4"):
        assert zxing(raster(poster.poster_pdf(url, size=size), "pdf")) == [url], f"pdf {size}"


@pytest.mark.parametrize("url", URL_SETS[:3])
def test_a_second_independent_decoder_reads_the_code_too(url):
    lay = poster.resolve(url)
    one = Image.open(io.BytesIO(poster.poster_png(url)))
    assert opencv(qr_crop(one, lay)) == url
    three = Image.open(io.BytesIO(poster.poster_png(url, scale=3)))
    assert opencv(qr_crop(three, lay, 3)) == url


def test_simulated_phone_photos_of_the_poster_decode():
    """Rotated, shrunk, slightly out of focus and noisy, like a phone photo. The whole poster, not a crop."""
    urls = make_urls(6, seed=21)
    tried = got = cv_got = cv_tried = 0
    for u in urls:
        img = Image.open(io.BytesIO(poster.poster_png(u)))
        lay = poster.resolve(u)
        for angle, blur, noise, width in ((0, 0.8, 3, 900), (8, 1.0, 4, 800), (-10, 1.1, 4, 700), (15, 0.9, 4, 800), (-5, 1.2, 5, 650)):
            p = photo(img, angle, blur, noise, 4, width)
            tried += 1
            got += u in zxing(p)
        for angle in (0, 6, -9):
            cv_tried += 1
            cv_got += opencv(photo(qr_crop(img, lay), angle, 0.9, 3, 2, 420)) == u
    assert got == tried, f"zxing read {got} of {tried} simulated photos"
    assert cv_got >= cv_tried * 0.85, f"opencv read {cv_got} of {cv_tried}"


def test_svg_is_self_contained_and_the_pdf_draws_the_code_as_vector_shapes():
    u = make_urls(1)[0]
    svg = poster.poster_svg(u).decode()
    assert svg.startswith("<svg") and "http://www.w3.org/2000/svg" in svg
    assert not re.findall(r'(?:href|src)="(?!data:)', svg) and "<script" not in svg and "javascript:" not in svg  # nothing external, nothing active
    doc = pymupdf.open(stream=poster.poster_pdf(u), filetype="pdf")
    page = doc[0]
    assert abs(page.rect.width - 253.2) < 0.02 and abs(page.rect.height - 357.84) < 0.02  # the approved PDF page
    assert tuple(G["page_pt"]) == (253.2, 357.84)
    assert len(page.get_images()) == 2  # the artwork and the logo tile: the code itself is not a picture
    assert sum(len(d["items"]) for d in page.get_drawings()) > 200  # modules are vector rectangles, so it stays sharp at any size
    for size, width_mm in (("a6", 105), ("a5", 148), ("a4", 210)):
        d = pymupdf.open(stream=poster.poster_pdf(u, size=size), filetype="pdf")[0]
        assert abs(d.rect.width / 72 * 25.4 - width_mm) < 0.2 and abs(d.rect.height / d.rect.width - 1491 / 1055) < 1e-3
    with pytest.raises(ValueError):
        poster.poster_pdf(u, size="a3")


def test_the_poster_is_refused_when_it_cannot_be_proven_scannable(monkeypatch):
    u = make_urls(1, seed=99)[0]
    poster.resolve.cache_clear()
    monkeypatch.setattr(qs, "decode", lambda img: None)  # a decoder that reads nothing
    with pytest.raises(poster.PosterError):
        poster.poster_png(u)
    with pytest.raises(poster.PosterError):
        poster.poster_pdf(u)
    monkeypatch.setattr(qs, "decode", lambda img: "https://evil.example/other")  # and one that reads the WRONG thing
    poster.resolve.cache_clear()
    with pytest.raises(poster.PosterError):
        poster.poster_svg(u)
    poster.resolve.cache_clear()
    with pytest.raises(poster.PosterError):  # a link too long to print legibly on the poster
        poster.poster_png(f"{BASE}/q/" + "a" * 400)


# ------------------------------------------------------------------ print sheets
def test_a4_print_sheet_has_four_posters_per_page_and_the_artwork_is_embedded_once():
    urls = make_urls(9, seed=31)
    data = poster.poster_sheet_pdf([(f"FQR-{i:04d}", u) for i, u in enumerate(urls, 1)])
    doc = pymupdf.open(stream=data, filetype="pdf")
    assert len(doc) == 3 and all((round(p.rect.width, 1), round(p.rect.height, 1)) == (595.3, 841.9) for p in doc)
    found = []
    for i, page in enumerate(doc):
        pm = page.get_pixmap(dpi=200)
        found.append(zxing(Image.frombytes("RGB", (pm.width, pm.height), pm.samples)))
    assert [len(f) for f in found] == [4, 4, 1] and sorted(sum(found, [])) == sorted(urls)
    assert "FQR-0001" in doc[0].get_text() and "FQR-0009" in doc[2].get_text()
    artwork = {x[0] for p in doc for x in p.get_images() if x[2] == 1055}
    assert len(artwork) == 1  # one copy of the artwork for every page
    assert len(data) < 3_000_000


def test_a_sheet_of_five_hundred_posters(tmp_path):
    urls = make_urls(500, seed=77)
    assert len(set(urls)) == 500
    t = time.time()
    data = poster.poster_sheet_pdf([(f"FQR-{i:04d}", u) for i, u in enumerate(urls, 1)])
    took = time.time() - t
    doc = pymupdf.open(stream=data, filetype="pdf")
    assert len(doc) == 125 and len(data) < 15_000_000 and took < 240
    seen = []
    for i in (0, 62, 124):
        pm = doc[i].get_pixmap(dpi=200)
        seen += zxing(Image.frombytes("RGB", (pm.width, pm.height), pm.samples))
    assert len(seen) == 12 and set(seen) <= set(urls)
    assert len({x[0] for p in doc for x in p.get_images() if x[2] == 1055}) == 1


# ------------------------------------------------------------------ over the API
def test_poster_downloads_for_cards_and_campaigns_respect_permissions_and_formats(admin, biz_a, biz_b):
    b, cards = new_batch(admin, 2)
    card = cards[0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    camp = campaign(biz_a)
    for path, url in ((f"/cards/{card['id']}/poster", card["url"]), (f"/review-growth/campaigns/{camp['id']}/poster", camp["url"]),
                      (f"/admin/cards/{card['id']}/poster", card["url"])):
        who = admin if path.startswith("/admin") else biz_a
        for fmt, mime, kind in (("png", "image/png", "png"), ("svg", "image/svg+xml", "svg"), ("pdf", "application/pdf", "pdf")):
            r = who.get(f"{path}.{fmt}")
            assert r.status_code == 200 and r.headers["content-type"] == mime and r.headers["x-flowqr-verified"] == "decoded", (path, fmt)
            assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "private, no-store"
            img = Image.open(io.BytesIO(r.content)).convert("RGB") if fmt == "png" else raster(r.content, kind)
            assert zxing(img) == [url], (path, fmt)
        assert who.get(f"{path}.gif").status_code == 404
        assert who.get(f"{path}.png", params={"scale": 4}).status_code == 422
        assert who.get(f"{path}.pdf", params={"size": "a3"}).status_code == 422
    big = biz_a.get(f"/cards/{card['id']}/poster.png", params={"scale": 2})
    assert Image.open(io.BytesIO(big.content)).size == (2110, 2982)
    # another business, a teammate without admin rights, and nobody at all
    assert biz_b.get(f"/cards/{card['id']}/poster.png").status_code == 404
    assert biz_b.get(f"/review-growth/campaigns/{camp['id']}/poster.png").status_code == 404
    assert biz_a.get(f"/admin/cards/{card['id']}/poster.png").status_code == 403
    staff = invite(biz_a, "staff")
    assert staff.get(f"/cards/{card['id']}/poster.png").status_code == 403
    assert staff.get(f"/review-growth/campaigns/{camp['id']}/poster.png").status_code == 403
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get(f"/api/v1/cards/{card['id']}/poster.png").status_code in (401, 403)
    # a poster encodes the PERMANENT address and downloading it changes nothing
    now = biz_a.get(f"/review-growth/campaigns/{camp['id']}").json()
    assert (now["public_id"], now["url"]) == (camp["public_id"], camp["url"])


def test_tenant_bulk_posters_zip_and_the_large_selection_rule(admin, biz_a):
    b, cards = new_batch(admin, 3)
    for c in cards:
        admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    camp = campaign(biz_a)
    want = {c["card_code"]: c["url"] for c in cards}
    r = biz_a.post("/qr/bulk", json={"all_cards": True, "campaign_ids": [camp["id"]], "design": "poster", "formats": ["png", "pdf"], "sheet": True})
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "manifest.csv" in names and "print-sheet-A4-posters.pdf" in names
    pngs = [n for n in names if n.startswith("png/")]
    assert len(pngs) == 4 and len([n for n in names if n.startswith("pdf/")]) == 4
    seen = {zxing(Image.open(io.BytesIO(z.read(n))).convert("RGB"))[0] for n in pngs}
    assert seen == set(want.values()) | {camp["url"]}
    sheet = pymupdf.open(stream=z.read("print-sheet-A4-posters.pdf"), filetype="pdf")
    pm = sheet[0].get_pixmap(dpi=200)
    assert len(zxing(Image.frombytes("RGB", (pm.width, pm.height), pm.samples))) == 4
    assert r.headers["x-flowqr-codes"] == "4"
    assert biz_a.post("/qr/bulk", json={"all_cards": True, "design": "poster", "formats": []}).status_code == 200  # a print sheet only
    assert biz_a.post("/qr/bulk", json={"all_cards": True, "design": "code", "formats": []}).status_code == 422  # nothing to produce


def test_admin_batch_posters_decode_to_every_cards_own_address(admin):
    b, cards = new_batch(admin, 9, name="Poster run")
    r = admin.get(f"/admin/batches/{b['id']}/posters.pdf")
    assert r.status_code == 200 and r.headers["x-flowqr-verified"] == "decoded" and r.headers["x-flowqr-codes"] == "9"
    doc = pymupdf.open(stream=r.content, filetype="pdf")
    assert len(doc) == 3
    seen = []
    for page in doc:
        pm = page.get_pixmap(dpi=200)
        seen += zxing(Image.frombytes("RGB", (pm.width, pm.height), pm.samples))
    assert sorted(seen) == sorted(c["url"] for c in cards) and all("/q/" in u for u in seen)
    for c in cards:
        assert c["card_code"] in "".join(p.get_text() for p in doc)
    # individual files, paged
    page = admin.get(f"/admin/batches/{b['id']}/posters.zip", params={"fmt": "png", "offset": 8, "limit": 4})
    assert page.status_code == 200 and page.headers["x-flowqr-total"] == "9" and page.headers["x-flowqr-codes"] == "1"
    z = zipfile.ZipFile(io.BytesIO(page.content))
    only = z.namelist()
    assert only == [f"{sorted(c['card_code'] for c in cards)[8]}-poster.png"]
    last = next(c for c in cards if c["card_code"] == only[0].split("-poster")[0])
    assert zxing(Image.open(io.BytesIO(z.read(only[0]))).convert("RGB")) == [last["url"]]
    assert admin.get(f"/admin/batches/{b['id']}/posters.zip", params={"offset": 99}).status_code == 404
    assert admin.get(f"/admin/batches/{b['id']}/posters.zip", params={"fmt": "bmp"}).status_code == 422


def test_posters_for_several_businesses_and_campaigns_each_encode_their_own_permanent_link(admin):
    seen = {}
    b, cards = new_batch(admin, 3)
    for i, name in enumerate(("Alpha Physio", "Bravo Dental", "Charlie Eye")):
        biz = make_business(name)
        camp = campaign(biz, f"{name} front desk")
        admin.post(f"/admin/cards/{cards[i]['id']}/assign", json={"tenant_id": biz.tenant_id, "location_id": biz.location_id, "campaign_id": camp["id"], "activate": True})
        for label, path, url in (("campaign", f"/review-growth/campaigns/{camp['id']}/poster.png", camp["url"]), ("card", f"/cards/{cards[i]['id']}/poster.png", cards[i]["url"])):
            r = biz.get(path)
            assert r.status_code == 200
            assert zxing(Image.open(io.BytesIO(r.content)).convert("RGB")) == [url]
            seen[(name, label)] = (url, hashlib.sha256(outside_qr(Image.open(io.BytesIO(r.content)), serial_area=True)).hexdigest())  # a card poster also carries its serial, in its own corner
    assert len({v[0] for v in seen.values()}) == 6  # six different codes
    assert len({v[1] for v in seen.values()}) == 1  # one design


# ------------------------------------------------------------------ the card's serial, printed small on the poster so a printed card can be tracked
SERIAL_URL = f"{BASE}/c/" + "m" * 24


def serial_box(scale: int = 1):
    """Where the serial is drawn (bottom right, under the footer), with a little room around it."""
    return (poster.SERIAL_RIGHT * scale - 260 * scale, 1425 * scale, poster.SERIAL_RIGHT * scale + 12 * scale, 1478 * scale)


def test_a_poster_without_a_serial_is_exactly_what_it_was_before():
    """Campaign posters, and any caller that passes no serial, get the approved artwork byte for byte."""
    plain = poster.poster_png(SERIAL_URL)
    assert poster.poster_png(SERIAL_URL, serial=None) == plain == poster.poster_png(SERIAL_URL, serial="")
    assert poster.poster_svg(SERIAL_URL, serial=None) == poster.poster_svg(SERIAL_URL)
    assert poster.poster_pdf(SERIAL_URL, serial=None) == poster.poster_pdf(SERIAL_URL)
    assert hashlib.sha256(outside_qr(Image.open(io.BytesIO(plain)))).hexdigest() == APPROVED_OUTSIDE_QR


def test_the_serial_is_drawn_only_in_its_corner_and_changes_nothing_else_in_the_artwork():
    for k in (1, 2, 3):
        plain = Image.open(io.BytesIO(poster.poster_png(SERIAL_URL, scale=k))).convert("RGB")
        with_serial = Image.open(io.BytesIO(poster.poster_png(SERIAL_URL, scale=k, serial="FQR-0042"))).convert("RGB")
        diff = ImageChops.difference(plain, with_serial).getbbox()
        assert diff is not None, f"x{k}: the serial was not drawn"
        x0, y0, x1, y1 = serial_box(k)
        assert diff[0] >= x0 and diff[1] >= y0 and diff[2] <= x1 and diff[3] <= y1, f"x{k}: something outside the serial's corner changed: {diff}"
        assert (diff[3] - diff[1]) <= 30 * k, f"x{k}: the serial is not small ({diff})"  # about 2.5 mm tall at the approved size
    one = Image.open(io.BytesIO(poster.poster_png(SERIAL_URL, serial="FQR-0042")))
    plain1 = Image.open(io.BytesIO(poster.poster_png(SERIAL_URL)))
    assert outside_qr(one, serial_area=True) == outside_qr(plain1, serial_area=True)  # everything but the QR and the serial's corner is the approved artwork


@pytest.mark.parametrize("serial", ["FQR-0001", "FQR-0042", "QRC-0123456", "X" * 24])
def test_a_poster_with_a_serial_still_decodes_to_exactly_its_url_in_every_format(serial):
    for k in (1, 3):
        assert zxing(Image.open(io.BytesIO(poster.poster_png(SERIAL_URL, scale=k, serial=serial)))) == [SERIAL_URL], f"png x{k}"
    assert zxing(raster(poster.poster_svg(SERIAL_URL, serial=serial), "svg")) == [SERIAL_URL]
    for size in ("ref", "a6", "a4"):
        assert zxing(raster(poster.poster_pdf(SERIAL_URL, size=size, serial=serial), "pdf")) == [SERIAL_URL], size


def test_the_serial_is_real_text_in_the_svg_and_pdf_so_it_can_be_searched_and_copied():
    assert ">FQR-0042</text>" in poster.poster_svg(SERIAL_URL, serial="FQR-0042").decode()
    page = pymupdf.open(stream=poster.poster_pdf(SERIAL_URL, serial="FQR-0042"), filetype="pdf")[0]
    hits = page.search_for("FQR-0042")
    assert len(hits) == 1
    r = hits[0]  # on the poster itself (inside the page), bottom right, and small
    assert r.x1 <= page.rect.width and r.y1 <= page.rect.height and r.x0 > page.rect.width * 0.5 and r.y0 > page.rect.height * 0.9
    assert r.height < 12  # points: small


def test_the_sheet_prints_the_serial_on_every_poster_and_still_labels_the_margin():
    items = [(f"FQR-{i:04d}", make_urls(1, seed=100 + i)[0], f"FQR-{i:04d}") for i in range(1, 6)] + [("Summer campaign", make_urls(1, seed=9)[0])]
    doc = pymupdf.open(stream=poster.poster_sheet_pdf(items), filetype="pdf")
    assert len(doc) == 2
    text = doc[0].get_text() + doc[1].get_text()
    for i in range(1, 6):
        assert text.count(f"FQR-{i:04d}") == 2, f"FQR-{i:04d}: expected once on the poster and once in the margin"
    assert text.count("Summer campaign") == 1  # a campaign has no serial on its poster, only the margin label


@pytest.mark.parametrize("bad", ["", "   ", "x" * 25, "FQR-0001)\n/Evil", "<script>", "FQRé", "a/b", "FQR-0001<", None])
def test_an_unsafe_or_odd_serial_is_never_drawn(bad):
    """The serial goes into SVG and PDF text: anything that is not plain letters, digits, space, dot, dash or underscore is dropped, never escaped half-way."""
    assert poster.serial_text(bad) is None
    assert poster.poster_svg(SERIAL_URL, serial=bad) == poster.poster_svg(SERIAL_URL)
    assert poster.poster_pdf(SERIAL_URL, serial=bad) == poster.poster_pdf(SERIAL_URL)


def _has(pdf: bytes, text: str, page: int = 0) -> bool:
    return bool(pymupdf.open(stream=pdf, filetype="pdf")[page].search_for(text))


def test_every_route_that_serves_a_card_poster_prints_that_cards_own_serial(admin, biz_a):
    b, cards = new_batch(admin, 3)
    card = cards[0]
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True}).status_code == 200
    code = card["card_code"]
    # a single poster: admin and the business that owns the card
    assert _has(admin.get(f"/admin/cards/{card['id']}/poster.pdf").content, code)
    assert _has(biz_a.get(f"/cards/{card['id']}/poster.pdf").content, code)
    assert b">" + code.encode() + b"</text>" in admin.get(f"/admin/cards/{card['id']}/poster.svg").content
    png = Image.open(io.BytesIO(admin.get(f"/admin/cards/{card['id']}/poster.png").content)).convert("RGB")
    assert png.size == (1055, 1491) and png.crop(serial_box()).convert("L").getextrema()[0] < 200  # dark text pixels in the serial's corner
    # the admin batch files: each card's own serial in its own file, and nobody else's
    z = zipfile.ZipFile(io.BytesIO(admin.get(f"/admin/batches/{b['id']}/posters.zip", params={"fmt": "pdf"}).content))
    assert len(z.namelist()) == 3
    for c in cards:
        pdf = z.read(f"{c['card_code']}-poster.pdf")
        assert _has(pdf, c["card_code"]), c["card_code"]
        assert not any(_has(pdf, o["card_code"]) for o in cards if o is not c)
    # the admin print sheet: each serial on its poster and in its margin
    sheet = pymupdf.open(stream=admin.get(f"/admin/batches/{b['id']}/posters.pdf").content, filetype="pdf")
    assert sum(len(sheet[i].search_for(c["card_code"])) for i in range(len(sheet)) for c in cards) == 6
    # the business's own bulk export
    r = biz_a.post("/qr/bulk", json={"card_ids": [card["id"]], "design": "poster", "formats": ["pdf"], "sheet": True})
    assert r.status_code == 200, r.text
    zz = zipfile.ZipFile(io.BytesIO(r.content))
    assert _has(zz.read(f"pdf/{code}-poster.pdf"), code)
    assert _has(zz.read("print-sheet-A4-posters.pdf"), code)


def test_a_campaign_poster_has_no_serial(biz_a):
    camp = campaign(biz_a)
    r = biz_a.get(f"/review-growth/campaigns/{camp['id']}/poster.pdf")
    assert r.status_code == 200
    text = pymupdf.open(stream=r.content, filetype="pdf")[0].get_text()
    assert "FQR-" not in text and "QRC-" not in text
