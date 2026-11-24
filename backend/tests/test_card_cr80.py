"""The review card on a bank-card blank (CR80 / ISO ID-1, 85.6 x 54 mm), printed lengthwise.

Pinned here:
  * the file is exactly the card's size, portrait, at 600 dpi, and with 3 mm bleed it is exactly 3 mm larger on every side;
  * the QR code is big enough to scan from a phone held at arm's length (31 mm square, modules of at least 0.7 mm for a normal card address);
  * PNG and PDF, with and without bleed, decode with an independent decoder to exactly the URL they were made for;
  * nothing is served that cannot be proven scannable; downloads are for platform admins only;
  * the batch download holds one file per card, each with its own address, in pages.
"""
import io
import zipfile

import pytest
from PIL import Image

from app.services import card_cr80 as c80
from tests.test_card_inventory import new_batch
from tests.test_poster import make_urls
from tests.test_qr import raster, zxing

pymupdf = pytest.importorskip("pymupdf")
URLS = make_urls(3) + ["https://go.flowqr.co.in/q/" + "Z" * 24]
MM_PT = 72 / 25.4


def mm(px: int) -> float:
    return px / c80.PX_PER_MM


def test_the_file_is_exactly_a_bank_card_turned_lengthwise_at_600_dpi():
    img = Image.open(io.BytesIO(c80.card_png(URLS[0])))
    assert img.height > img.width, "portrait"
    assert abs(mm(img.width) - 53.98) < 0.06 and abs(mm(img.height) - 85.60) < 0.06
    assert round(img.info["dpi"][0]) == 600
    bled = Image.open(io.BytesIO(c80.card_png(URLS[0], bleed_mm=3.0)))
    assert abs(mm(bled.width) - 59.98) < 0.1 and abs(mm(bled.height) - 91.60) < 0.1


def test_the_pdf_page_is_the_trim_size_or_trim_plus_bleed():
    for bleed, (w, h) in ((0.0, (53.98, 85.60)), (3.0, (59.98, 91.60))):
        page = pymupdf.open(stream=c80.card_pdf(URLS[0], bleed_mm=bleed), filetype="pdf")[0]
        assert len(pymupdf.open(stream=c80.card_pdf(URLS[0], bleed_mm=bleed), filetype="pdf")) == 1
        assert abs(page.rect.width - w * MM_PT) < 0.5 and abs(page.rect.height - h * MM_PT) < 0.5, bleed


@pytest.mark.parametrize("url", URLS)
def test_the_code_is_large_enough_to_scan_and_sits_inside_the_trim(url):
    plan = c80.resolve(url)
    side_mm = plan.n * plan.m / c80.PX_PER_MM
    assert 29.0 <= side_mm <= 31.0
    assert plan.m / c80.PX_PER_MM >= 0.7, "module size on the card, in mm"
    assert side_mm + 2 * 5 < c80.CARD_W_MM, "at least 5 mm of card either side of the code"


@pytest.mark.parametrize("url", URLS)
@pytest.mark.parametrize("bleed", (0.0, 3.0))
def test_png_and_pdf_decode_to_exactly_the_url(url, bleed):
    assert zxing(Image.open(io.BytesIO(c80.card_png(url, bleed_mm=bleed, serial="FQR-0001"))).convert("RGB")) == [url]
    assert zxing(raster(c80.card_pdf(url, bleed_mm=bleed, serial="FQR-0001"), "pdf")) == [url]


def test_the_bleed_is_artwork_not_blank_paper_and_the_card_centre_does_not_move():
    plain = c80.card_image(URLS[0])
    bled = c80.card_image(URLS[0], bleed_mm=3.0)
    b = round(3.0 * c80.PX_PER_MM)
    assert bled.crop((b, b, b + plain.width, b + plain.height)).tobytes() == plain.tobytes() or _near(bled.crop((b, b, b + plain.width, b + plain.height)), plain)
    # the orange corners run right out to the edge of the bled file, so a die-cut never leaves a white sliver
    r, g, bl = bled.getpixel((bled.width - 2, 2))
    assert r > 240 and g < 190 and bl < 120
    r, g, bl = bled.getpixel((2, bled.height - 2))
    assert r > 240 and g < 190 and bl < 120


def _near(a: Image.Image, b: Image.Image) -> bool:
    from PIL import ImageChops
    return max(ImageChops.difference(a.convert("L"), b.convert("L")).getextrema()) <= 8


def test_a_link_too_long_for_a_card_is_refused_not_shrunk():
    with pytest.raises(c80.CardError):
        c80.resolve("https://go.flowqr.co.in/q/" + "x" * 400)


def test_a_card_that_cannot_be_proven_scannable_is_not_produced(monkeypatch):
    c80.resolve.cache_clear()
    monkeypatch.setattr(c80, "_verified", lambda url, img: False)
    with pytest.raises(c80.CardError):
        c80.card_png("https://go.flowqr.co.in/q/" + "k" * 24)
    c80.resolve.cache_clear()


def test_an_unknown_bleed_is_refused():
    with pytest.raises(ValueError):
        c80.card_png(URLS[0], bleed_mm=2.0)


def test_admin_downloads_one_card_and_a_whole_batch_page(admin, biz_a):
    b, cards = new_batch(admin, 5, name="CR80 run")
    card = cards[0]
    for fmt, mime in (("png", "image/png"), ("pdf", "application/pdf")):
        for bleed in (0, 3):
            r = admin.get(f"/admin/cards/{card['id']}/cr80.{fmt}", params={"bleed": bleed})
            assert r.status_code == 200 and r.headers["content-type"] == mime and r.headers["x-flowqr-verified"] == "decoded"
            assert card["card_code"] in r.headers["content-disposition"] and "cr80" in r.headers["content-disposition"]
            img = Image.open(io.BytesIO(r.content)).convert("RGB") if fmt == "png" else raster(r.content, "pdf")
            assert zxing(img) == [card["url"]]
    assert admin.get(f"/admin/cards/{card['id']}/cr80.svg").status_code == 404
    assert admin.get(f"/admin/cards/{card['id']}/cr80.png", params={"bleed": 2}).status_code == 404
    assert biz_a.get(f"/admin/cards/{card['id']}/cr80.png").status_code == 403
    # a batch, in pages: every file is that card's own address
    z = admin.get(f"/admin/batches/{b['id']}/cards.zip", params={"fmt": "pdf", "offset": 0, "limit": 100})
    assert z.status_code == 200 and z.headers["x-flowqr-total"] == "5" and z.headers["x-flowqr-codes"] == "5"
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert sorted(zf.namelist()) == sorted(f"{x['card_code']}-cr80.pdf" for x in cards)
    for x in cards:
        assert zxing(raster(zf.read(f"{x['card_code']}-cr80.pdf"), "pdf")) == [x["url"]]
    last = admin.get(f"/admin/batches/{b['id']}/cards.zip", params={"fmt": "png", "bleed": 3, "offset": 4, "limit": 3})
    assert last.status_code == 200 and last.headers["x-flowqr-codes"] == "1"
    assert admin.get(f"/admin/batches/{b['id']}/cards.zip", params={"offset": 99}).status_code == 404
    assert admin.get(f"/admin/batches/{b['id']}/cards.zip", params={"fmt": "bmp"}).status_code == 422
    assert admin.get(f"/admin/batches/{b['id']}/cards.zip", params={"bleed": 5}).status_code == 422
    assert biz_a.get(f"/admin/batches/{b['id']}/cards.zip").status_code == 403
