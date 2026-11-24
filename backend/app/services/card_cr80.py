"""The FlowQR review card on a standard bank-card blank: CR80 / ID-1, 85.60 x 53.98 mm, printed PORTRAIT (53.98 wide, 85.60 tall).

The approved poster (`app/services/poster.py`) is 0.708 wide-to-tall and carries a side-by-side "Tap / Scan" layout, so shrinking it onto a
0.631 card would leave its QR code about 23 mm wide, with modules too small for a phone to read in a bad light. This module therefore
re-lays out the SAME approved artwork for the card: pieces are cut out of the approved poster template (heading, stars, the white QR
frame with its orange brackets, the Tap and Scan marks, the FlowQR footer, the corner swirls) and stacked lengthwise, with the QR code
enlarged to 31 mm. Nothing is redrawn except the QR code itself, which is drawn the way the poster draws it.

The same rule as the poster applies: a card file is only returned after the finished image has been decoded with an independent
decoder (ZXing) and has returned exactly the URL it was made for, at full size, shrunk and slightly blurred.

Files are built at 600 dpi. `bleed_mm` extends the artwork past the trim line on every side (a printer who die-cuts the card asks for
about 3 mm); the page then measures (54 + 2 x bleed) x (85.6 + 2 x bleed) mm and the trim is exactly 85.6 x 54 inside it.
"""
import io
from dataclasses import dataclass
from functools import lru_cache

import segno
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.services import poster as ps
from app.services import qr_style as qs

DPI = 600
PX_PER_MM = DPI / 25.4
CARD_W_MM, CARD_H_MM = 53.98, 85.60  # ISO/IEC 7810 ID-1, turned lengthwise
QR_MM = 31.0  # the code itself; 2.7 times the area of the poster's on a 54 mm card
MIN_MODULE_MM = 0.55
BLEEDS = (0.0, 3.0)

# Pieces of the approved poster template, in template pixels (left, top, right, bottom).
CROP_HEAD = (130, 108, 892, 400)  # Google mark, "Review us on Google", the five stars
CROP_FRAME = (225, 405, 835, 985)  # the white QR card with its orange brackets and soft shadow (cleared of modules)
CROP_TAP = (55, 555, 225, 790)
CROP_SCAN = (825, 555, 995, 790)
CROP_FOOT = (250, 1362, 810, 1448)  # hairline, FlowQR logo, "A FlowHQ Product"

# Where each piece lands, in millimetres from the trim's top-left corner: (x_centre or x_left, top, width).
HEAD_W, HEAD_TOP = 46.0, 4.4
FRAME_TOP = 23.2
FRAME_W_MM = QR_MM / (ps.QR_BOX[2] - ps.QR_BOX[0]) * (CROP_FRAME[2] - CROP_FRAME[0])  # the frame piece scaled so the code area is QR_MM wide
MARK_TOP, MARK_W, MARK_INSET = 65.2, 9.2, 7.5
FOOT_W, FOOT_TOP = 22.5, 79.2


class CardError(Exception):
    """The card could not be produced in a form that provably scans."""


def _mm(v: float) -> int:
    return round(v * PX_PER_MM)


@lru_cache(maxsize=1)
def _t() -> Image.Image:
    return ps._template()


def _piece(box: tuple, width_mm: float, white: int = 246) -> Image.Image:
    """A cut-out of the approved artwork. The poster's page is not pure white (it carries a faint warm glow), so each piece's near-white is
    levelled to white; otherwise every piece would show as a pale rectangle on the card."""
    p = _t().crop(box)
    w = _mm(width_mm)
    p = p.resize((w, round(p.height * w / p.width)), Image.LANCZOS)
    return p.point(lambda v: min(255, round(v * 255 / white)))


def _bezier(p0, p1, p2, p3, n: int = 60) -> list[tuple[float, float]]:
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0], u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def _corner(bleed_mm: float, w_mm: float, h_mm: float, lo: tuple, hi: tuple) -> Image.Image:
    """The brand's flowing orange corner (the approved poster's top-right and bottom-left), drawn as one smooth wave filled top to bottom
    with a gradient, on a canvas the size of the trim plus the bleed. Its shape is defined from the trim's own coordinates and runs on past
    the trim along its own tangents, so the part inside the trim is identical with or without bleed and a die-cut never leaves a white
    sliver. Returned for the TOP-RIGHT corner."""
    b = _mm(bleed_mm)
    tw, th = _mm(CARD_W_MM), _mm(CARD_H_MM)
    W, H = tw + 2 * b, th + 2 * b
    w, h = _mm(w_mm), _mm(h_mm)
    ss = 3
    pts = _bezier((tw - w, 0), (tw - w * 0.66, h * 0.06), (tw - w * 0.1, h * 0.22), (tw, h))
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts[0], pts[1], pts[-2], pts[-1]
    far = 12 * b + 40
    n0, n3 = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, ((x3 - x2) ** 2 + (y3 - y2) ** 2) ** 0.5
    start = (x0 - (x1 - x0) / n0 * far, y0 - (y1 - y0) / n0 * far)
    end = (x3 + (x3 - x2) / n3 * far, y3 + (y3 - y2) / n3 * far)
    poly = [start] + pts + [end, (tw + far, -far)]
    m = Image.new("L", (W * ss, H * ss), 0)
    ImageDraw.Draw(m).polygon([((x + b) * ss, (y + b) * ss) for x, y in poly], fill=255)
    m = m.resize((W, H), Image.LANCZOS)
    fill = Image.new("RGB", (W, H))
    fd = ImageDraw.Draw(fill)
    for y in range(H):
        t = min(1.0, max(0.0, (y - b) / max(1, h)))
        fd.line([(0, y), (W, y)], fill=tuple(round(lo[i] + (hi[i] - lo[i]) * t) for i in range(3)))
    out = fill.convert("RGBA")
    out.putalpha(m)
    return out


@lru_cache(maxsize=4)
def _swirls(bleed_mm: float) -> Image.Image:
    """Two layers per corner (a light wave with a deeper one inside it), top-right and, turned half a circle, bottom-left."""
    tr = _corner(bleed_mm, 20.0, 19.0, (255, 170, 70), (253, 150, 45))
    tr.alpha_composite(_corner(bleed_mm, 11.5, 10.5, (250, 130, 28), (246, 112, 14)))
    bl = _corner(bleed_mm, 15.0, 15.0, (254, 156, 54), (252, 139, 36))
    bl.alpha_composite(_corner(bleed_mm, 8.0, 8.0, (249, 124, 24), (246, 112, 14)))
    tr.alpha_composite(bl.rotate(180))
    return tr


@lru_cache(maxsize=8)
def _base(bleed_mm: float) -> Image.Image:
    """Everything except the QR code, ready to paste the code onto. Size: the trim plus the bleed on every side."""
    b = _mm(bleed_mm)
    W, H = _mm(CARD_W_MM) + 2 * b, _mm(CARD_H_MM) + 2 * b
    img = Image.new("RGB", (W, H), (255, 255, 255))
    rgba = img.convert("RGBA")
    rgba.alpha_composite(_swirls(bleed_mm))
    img = rgba.convert("RGB")

    def at(piece: Image.Image, x_mm: float, y_mm: float, centre: bool = False) -> None:
        x, y = _mm(x_mm) - (piece.width // 2 if centre else 0) + b, _mm(y_mm) + b
        box = (x, y, x + piece.width, y + piece.height)
        img.paste(ImageChops.multiply(img.crop(box), piece), box)  # multiply: the piece's white leaves the corner artwork behind it untouched

    at(_piece(CROP_HEAD, HEAD_W), CARD_W_MM / 2, HEAD_TOP, centre=True)
    at(_piece(CROP_FRAME, FRAME_W_MM, white=252), CARD_W_MM / 2, FRAME_TOP, centre=True)
    tap, scan = _piece(CROP_TAP, MARK_W), _piece(CROP_SCAN, MARK_W)
    at(tap, MARK_INSET, MARK_TOP)
    at(scan, CARD_W_MM - MARK_INSET - scan.width / PX_PER_MM, MARK_TOP)
    at(_piece(CROP_FOOT, FOOT_W), CARD_W_MM / 2, FOOT_TOP, centre=True)
    return img


def _frame_geometry(bleed_mm: float) -> tuple[float, int, int]:
    """(scale, qr_centre_x, qr_centre_y) of the frame piece in the finished image, in pixels."""
    k = _mm(FRAME_W_MM) / (CROP_FRAME[2] - CROP_FRAME[0])
    frame_w = round((CROP_FRAME[2] - CROP_FRAME[0]) * k)
    x0 = _mm(CARD_W_MM / 2) - frame_w // 2 + _mm(bleed_mm)
    y0 = _mm(FRAME_TOP) + _mm(bleed_mm)
    return k, x0 + round((ps.CX - CROP_FRAME[0]) * k), y0 + round((ps.CY - CROP_FRAME[1]) * k)


@dataclass(frozen=True)
class Plan:
    ecc: str
    palette: str
    rows: tuple[bytes, ...]
    n: int
    m: int  # pixels per module at 600 dpi


def _plan(url: str, ecc: str, palette: str) -> Plan:
    rows = tuple(bytes(r) for r in segno.make(url, error=ecc.lower(), micro=False).matrix)
    n = len(rows)
    avail = _mm(QR_MM)
    m = avail // n
    if m < MIN_MODULE_MM * PX_PER_MM:
        raise CardError("This link is too long to print legibly on a bank-card-sized card.")
    return Plan(ecc, palette, rows, n, m)


def _render(p: Plan, bleed_mm: float = 0.0, *, tile: bool = True) -> Image.Image:
    img = _base(bleed_mm).copy()
    _k, cx, cy = _frame_geometry(bleed_mm)
    side = p.n * p.m
    x0, y0 = cx - side // 2, cy - side // 2
    d = ImageDraw.Draw(img)

    def in_eye(r: int, c: int) -> bool:
        return (r < 7 and c < 7) or (r < 7 and c >= p.n - 7) or (r >= p.n - 7 and c < 7)

    for r, row in enumerate(p.rows):
        c = 0
        while c < p.n:
            if row[c] and not in_eye(r, c):
                run = 1
                while c + run < p.n and row[c + run] and not in_eye(r, c + run):
                    run += 1
                d.rectangle((x0 + c * p.m, y0 + r * p.m, x0 + (c + run) * p.m - 1, y0 + (r + 1) * p.m - 1), fill=ps.DARK)
                c += run
            else:
                c += 1
    eye = ps._eye(p.m, p.palette)
    for r, c in ((0, 0), (p.n - 7, 0), (0, p.n - 7)):
        img.paste(eye, (x0 + c * p.m, y0 + r * p.m), eye)
    if tile:
        t_side = round(ps.TILE_SIZE * _k)
        t = ps._tile_img().resize((t_side, t_side), Image.LANCZOS)
        img.paste(t, (cx - t_side // 2, cy - t_side // 2), t)
    return img


def _verified(url: str, img: Image.Image) -> bool:
    small = img.resize((img.width // 3, img.height // 3), Image.BOX)
    blurred = img.filter(ImageFilter.GaussianBlur(radius=img.width / 700))
    return all(qs.decode(v) == url for v in (img, small, blurred))


@lru_cache(maxsize=4096)
def resolve(url: str) -> Plan:
    """The plan for `url` that has been proven to decode back to exactly `url`. Raises CardError when none does."""
    if not qs.decoder_available():
        raise CardError("The scan check is unavailable on this server, so cards cannot be issued.")
    for palette in ("brand", "deep"):
        for ecc in ("Q", "H"):
            try:
                plan = _plan(url, ecc, palette)
            except CardError:
                continue
            if _verified(url, _render(plan)):
                return plan
    raise CardError("A card for this link could not be verified as scannable, so it was not produced.")


def _with_serial(img: Image.Image, serial: str | None, bleed_mm: float) -> Image.Image:
    text = ps.serial_text(serial)
    if not text:
        return img
    from PIL import ImageFont

    b = _mm(bleed_mm)
    ImageDraw.Draw(img).text((b + _mm(CARD_W_MM) - _mm(4.0), b + _mm(CARD_H_MM) - _mm(3.0)), text, fill=ps.SERIAL_RGB, font=ImageFont.load_default(_mm(1.45)), anchor="rs")
    return img


def card_image(url: str, *, bleed_mm: float = 0.0, serial: str | None = None) -> Image.Image:
    if bleed_mm not in BLEEDS:
        raise ValueError("bleed must be 0 or 3 mm")
    return _with_serial(_render(resolve(url), bleed_mm), serial, bleed_mm)


def card_png(url: str, *, bleed_mm: float = 0.0, serial: str | None = None) -> bytes:
    buf = io.BytesIO()
    card_image(url, bleed_mm=bleed_mm, serial=serial).save(buf, format="PNG", dpi=(DPI, DPI))
    return buf.getvalue()


def card_pdf(url: str, *, bleed_mm: float = 0.0, serial: str | None = None) -> bytes:
    """One page, exactly the trim size (or trim + bleed), the artwork at 600 dpi."""
    buf = io.BytesIO()
    card_image(url, bleed_mm=bleed_mm, serial=serial).save(buf, format="PDF", resolution=DPI)
    return buf.getvalue()
