"""The branded FlowQR review poster: the approved artwork, with ONLY the QR code replaced.

`app/assets/poster/poster_template.png` is the approved poster pixel for pixel, except that the module area inside the white QR
card has been cleared to the card's own white (built once from the approved PDF by scripts/build_poster_template.py). Everything
else (the Google heading, stars, corner artwork, the QR frame, "Tap/Scan to Review", the AI Review Assistant pill, the
"Write a Review" button, the FlowQR footer) is that image, untouched.

This module draws, into the cleared area, a real QR code for a permanent FlowQR URL, in the poster's own style (black modules,
rounded black finder eyes with the brand-orange centre), and puts the FlowQR logo tile back in the middle. PNG is a raster
composite; SVG and PDF draw the code as vector shapes on top of the same template, so the code stays sharp at any print size.

The rule: a poster is only ever returned after the finished image has been decoded with an independent decoder (ZXing) and has
returned exactly the URL it was made for, at full size, shrunk, and slightly blurred. If no variant decodes, nothing is served.
"""
import base64
import hashlib
import io
import json
import struct
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFilter

from app.services import qr_style as qs

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "poster"
G = json.loads((ASSETS / "poster_geometry.json").read_text())
W, H = G["size"]
PAGE_PT = tuple(G["page_pt"])  # the approved PDF page: 253.2 x 357.84 pt
QR_BOX = tuple(G["qr_box"])
CX, CY = (QR_BOX[0] + QR_BOX[2]) / 2, (QR_BOX[1] + QR_BOX[3]) / 2
AVAIL = QR_BOX[2] - QR_BOX[0]
DARK = tuple(G["dark"])
TILE_SIZE = G["tile_size"][0]
MIN_MODULE_PX = 8  # at the approved 300 dpi this is 0.68 mm
# Finder-eye corner radii, in modules: the outer edge of the black ring, the inner edge of the ring, and the orange centre.
# The approved artwork draws the eyes with strongly rounded rings and a bright orange centre. A decoder study (tests/test_poster.py,
# docs/CARD_INVENTORY.md) found that BOTH make real QR codes harder to find: OpenCV's detector fails on every code once the ring's corner
# radius is 0.6 module or more, and on every code when the centre is the exact brand orange. So inside the QR area only, the ring corners
# are lightly rounded (0.4) and the orange is 12% deeper; the orange block keeps its rounded shape. Nothing outside the QR area changes.
EYE_R_OUTER, EYE_R_INNER, EYE_R_CENTER = 0.4, 0.2, 0.8
SS = 4  # supersampling for the rounded finder eyes
# The card's own serial (e.g. FQR-0001), printed small on the poster so a printed card can be told apart and tracked. Bottom right, on the plain white under the footer line,
# nowhere near the QR code. Only drawn when a serial is given: a poster with no serial (a campaign poster) is the approved artwork, unchanged.
SERIAL_RIGHT, SERIAL_BASELINE, SERIAL_PX, SERIAL_RGB = W - 125, 1456, 24, (118, 118, 118)
_HELV = {**{c: 556 for c in "0123456789_"}, "-": 333, ".": 278, " ": 278, **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611)))}


def serial_text(serial: str | None) -> str | None:
    """The serial as it will be drawn: letters, digits and . _ - only, at most 24 characters, otherwise nothing (it goes into SVG and PDF text, so it is never passed through raw)."""
    s = (serial or "").strip()
    if not s or len(s) > 24 or not all(c.isascii() and (c.isalnum() or c in "-_. ") for c in s):
        return None
    return s


A_SIZES_MM = {"a6": (105, 148.5), "a5": (148, 210), "a4": (210, 297)}  # same proportions as the approved poster (0.7076 vs 0.7071)

# Finder-eye centre. Scanners binarise by brightness and the approved orange sits near the middle of the scale (luma 139 to 115),
# where some decoders read it as "light" and lose the finder pattern. The same hue at 88% (luma 122 to 101) decodes everywhere we
# tried; the 62% shade is a fallback used only if a code fails verification with the first.
def _shade(c: tuple, k: float) -> tuple:
    return tuple(round(v * k) for v in c)


PALETTES = {"brand": (_shade(tuple(G["eye_top"]), 0.88), _shade(tuple(G["eye_bottom"]), 0.88)),
            "deep": (_shade(tuple(G["eye_top"]), 0.62), _shade(tuple(G["eye_bottom"]), 0.62))}


class PosterError(Exception):
    """The poster could not be produced in a form that provably scans."""


@dataclass(frozen=True)
class Layout:
    ecc: str
    palette: str
    rows: tuple[bytes, ...]
    n: int
    m: int  # pixels per module at the approved resolution
    side: int
    x0: int
    y0: int

    def in_eye(self, r: int, c: int) -> bool:
        n = self.n
        return (r < 7 and c < 7) or (r < 7 and c >= n - 7) or (r >= n - 7 and c < 7)

    def eyes(self) -> list[tuple[int, int]]:
        return [(0, 0), (self.n - 7, 0), (0, self.n - 7)]  # (row, col) of each finder's top-left module


def _layout(url: str, ecc: str, palette: str) -> Layout:
    rows = tuple(bytes(r) for r in segno.make(url, error=ecc.lower(), micro=False).matrix)
    n = len(rows)
    m = AVAIL // n
    if m < MIN_MODULE_PX:
        raise PosterError("This link is too long to print legibly on the poster.")
    side = n * m
    return Layout(ecc, palette, rows, n, m, side, round(CX - side / 2), round(CY - side / 2))


@lru_cache(maxsize=1)
def _template() -> Image.Image:
    return Image.open(ASSETS / "poster_template.png").convert("RGB")


@lru_cache(maxsize=1)
def _tile_img() -> Image.Image:
    return Image.open(ASSETS / "poster_logo_tile.png").convert("RGBA")


@lru_cache(maxsize=8)
def _template_scaled(k: int) -> Image.Image:
    return _template() if k == 1 else _template().resize((W * k, H * k), Image.LANCZOS)


@lru_cache(maxsize=32)
def _eye(px: int, palette: str) -> Image.Image:
    """One finder eye of 7 x 7 modules (`px` = pixels per module): rounded black ring and a rounded orange centre."""
    size = 7 * px * SS
    u = px * SS
    ring = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(ring)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(EYE_R_OUTER * u), fill=255)
    d.rounded_rectangle((u, u, size - u - 1, size - u - 1), radius=int(EYE_R_INNER * u), fill=0)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (size, size), DARK + (255,)), (0, 0), ring)
    # orange centre: 3 x 3 modules, vertical gradient like the approved artwork
    top, bottom = PALETTES[palette]
    c0, c1 = 2 * u, 5 * u
    grad = Image.new("RGBA", (c1 - c0, c1 - c0))
    gd = ImageDraw.Draw(grad)
    for y in range(c1 - c0):
        t = y / max(1, c1 - c0 - 1)
        gd.line([(0, y), (c1 - c0, y)], fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    cm = Image.new("L", grad.size, 0)
    ImageDraw.Draw(cm).rounded_rectangle((0, 0, grad.width - 1, grad.height - 1), radius=int(EYE_R_CENTER * u), fill=255)
    out.paste(grad, (c0, c0), cm)
    return out.resize((7 * px, 7 * px), Image.LANCZOS)


def _tile_scaled(k: int) -> Image.Image:
    t = _tile_img()
    return t if k == 1 else t.resize((t.width * k, t.height * k), Image.LANCZOS)


def _render(lay: Layout, k: int = 1, *, tile: bool = True) -> Image.Image:
    """The finished poster at k x the approved resolution (1055 x 1491 px at k = 1)."""
    img = _template_scaled(k).copy()
    d = ImageDraw.Draw(img)
    mk = lay.m * k
    X0, Y0 = lay.x0 * k, lay.y0 * k
    for r, row in enumerate(lay.rows):
        c = 0
        while c < lay.n:
            if row[c] and not lay.in_eye(r, c):
                run = 1
                while c + run < lay.n and row[c + run] and not lay.in_eye(r, c + run):
                    run += 1
                d.rectangle((X0 + c * mk, Y0 + r * mk, X0 + (c + run) * mk - 1, Y0 + (r + 1) * mk - 1), fill=DARK)
                c += run
            else:
                c += 1
    eye = _eye(mk, lay.palette)
    for r, c in lay.eyes():
        img.paste(eye, (X0 + c * mk, Y0 + r * mk), eye)
    if tile:
        t = _tile_scaled(k)
        img.paste(t, (round((CX - TILE_SIZE / 2) * k), round((CY - TILE_SIZE / 2) * k)), t)
    return img


def _verified(url: str, img: Image.Image) -> bool:
    small = img.resize((img.width // 3, img.height // 3), Image.BOX)
    blurred = img.filter(ImageFilter.GaussianBlur(radius=img.width / 700))
    return all(qs.decode(v) == url for v in (img, small, blurred))


@lru_cache(maxsize=4096)
def resolve(url: str) -> Layout:
    """The layout for `url` that has been proven to decode back to exactly `url`. Raises PosterError when none does."""
    if not qs.decoder_available():
        raise PosterError("The scan check is unavailable on this server, so posters cannot be issued.")
    for palette in ("brand", "deep"):
        for ecc in ("Q", "H"):
            try:
                lay = _layout(url, ecc, palette)
            except PosterError:
                continue
            if _verified(url, _render(lay, 1)):
                return lay
    raise PosterError("A poster for this link could not be verified as scannable, so it was not produced.")


# ------------------------------------------------------------------------------------------------------------------ PNG
def poster_png(url: str, *, scale: int = 1, serial: str | None = None) -> bytes:
    """scale 1 = the approved 1055 x 1491 px; 2 and 3 give 2110 x 2982 and 3165 x 4473 for large prints."""
    if scale not in (1, 2, 3):
        raise ValueError("scale must be 1, 2 or 3")
    lay = resolve(url)
    img = _render(lay, scale)
    text = serial_text(serial)
    if text:
        from PIL import ImageFont

        ImageDraw.Draw(img).text((SERIAL_RIGHT * scale, SERIAL_BASELINE * scale), text, fill=SERIAL_RGB, font=ImageFont.load_default(SERIAL_PX * scale), anchor="rs")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=scale == 1, dpi=(300 * scale, 300 * scale))
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------------------------ SVG
def _rr(x: float, y: float, w: float, h: float, r: float) -> str:
    return (f"M{x + r:.2f} {y:.2f}h{w - 2 * r:.2f}a{r:.2f} {r:.2f} 0 0 1 {r:.2f} {r:.2f}v{h - 2 * r:.2f}a{r:.2f} {r:.2f} 0 0 1 -{r:.2f} {r:.2f}"
            f"h-{w - 2 * r:.2f}a{r:.2f} {r:.2f} 0 0 1 -{r:.2f} -{r:.2f}v-{h - 2 * r:.2f}a{r:.2f} {r:.2f} 0 0 1 {r:.2f} -{r:.2f}z")


def _modules_path(lay: Layout) -> str:
    out = []
    for r, row in enumerate(lay.rows):
        c = 0
        while c < lay.n:
            if row[c] and not lay.in_eye(r, c):
                run = 1
                while c + run < lay.n and row[c + run] and not lay.in_eye(r, c + run):
                    run += 1
                out.append(f"M{lay.x0 + c * lay.m} {lay.y0 + r * lay.m}h{run * lay.m}v{lay.m}h-{run * lay.m}z")
                c += run
            else:
                c += 1
    return "".join(out)


@lru_cache(maxsize=1)
def _template_b64() -> str:
    return base64.b64encode((ASSETS / "poster_template.png").read_bytes()).decode()


@lru_cache(maxsize=1)
def _tile_b64() -> str:
    return base64.b64encode((ASSETS / "poster_logo_tile.png").read_bytes()).decode()


def poster_svg(url: str, *, serial: str | None = None) -> bytes:
    """Self-contained SVG: the approved artwork as an embedded image, the QR code as vector shapes on top."""
    lay = resolve(url)
    m = lay.m
    top, bottom = PALETTES[lay.palette]
    hexc = lambda c: "#%02X%02X%02X" % c  # noqa: E731
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<defs><linearGradient id="eye" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{hexc(top)}"/><stop offset="1" stop-color="{hexc(bottom)}"/></linearGradient></defs>',
             f'<image width="{W}" height="{H}" href="data:image/png;base64,{_template_b64()}"/>',
             f'<path fill="{hexc(DARK)}" shape-rendering="crispEdges" d="{_modules_path(lay)}"/>']
    for r, c in lay.eyes():
        x, y = lay.x0 + c * m, lay.y0 + r * m
        parts.append(f'<path fill="{hexc(DARK)}" fill-rule="evenodd" d="{_rr(x, y, 7 * m, 7 * m, EYE_R_OUTER * m)}{_rr(x + m, y + m, 5 * m, 5 * m, EYE_R_INNER * m)}"/>')
        parts.append(f'<path fill="url(#eye)" d="{_rr(x + 2 * m, y + 2 * m, 3 * m, 3 * m, EYE_R_CENTER * m)}"/>')
    tx, ty = CX - TILE_SIZE / 2, CY - TILE_SIZE / 2
    parts.append(f'<image x="{tx:.2f}" y="{ty:.2f}" width="{TILE_SIZE}" height="{TILE_SIZE}" href="data:image/png;base64,{_tile_b64()}"/>')
    text = serial_text(serial)
    if text:
        parts.append(f'<text x="{SERIAL_RIGHT}" y="{SERIAL_BASELINE}" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="{SERIAL_PX}" fill="#%02X%02X%02X">{text}</text>' % SERIAL_RGB)
    parts.append("</svg>")
    return "".join(parts).encode()


# ------------------------------------------------------------------------------------------------------------------ PDF
def _png_idat(png: bytes) -> tuple[int, int, bytes] | None:
    """(width, height, deflate stream) of an 8-bit RGB, non-interlaced PNG, so it can be embedded without recompressing."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, hdr = 8, [], None
    while pos < len(png):
        ln, kind = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + ln]
        if kind == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + ln
    if not hdr or hdr[2:] != (8, 2, 0, 0, 0):
        return None
    return hdr[0], hdr[1], b"".join(idat)


class _PosterPdf(qs._Pdf):
    """The shared vector writer, plus the poster template (embedded once and drawn on every page) and axial shadings."""

    def __init__(self) -> None:
        super().__init__()
        self._tpl: int | None = None
        self._shadings: dict[tuple, int] = {}

    def template(self) -> int:
        if self._tpl is None:
            png = (ASSETS / "poster_template.png").read_bytes()
            got = _png_idat(png)
            if got:  # the PNG's own compressed pixels, with its row filters declared as a PDF predictor: nothing is re-encoded
                w, h, data = got
                self._tpl = self._add(
                    (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                     f"/Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns {w} >> /Length {len(data)} >>\nstream\n").encode()
                    + data + b"\nendstream")
            else:
                im = Image.open(io.BytesIO(png)).convert("RGB")
                self._tpl = self._stream(f"/Type /XObject /Subtype /Image /Width {im.width} /Height {im.height} /ColorSpace /DeviceRGB /BitsPerComponent 8", im.tobytes())
        return self._tpl

    def shading(self, x: float, y_top: float, y_bottom: float, c0: tuple, c1: tuple) -> int:
        key = (round(x, 2), round(y_top, 2), round(y_bottom, 2), c0, c1)
        if key not in self._shadings:
            f = " ".join(f"{v / 255:.4f}" for v in c0), " ".join(f"{v / 255:.4f}" for v in c1)
            self._shadings[key] = self._add(
                (f"<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [{x:.2f} {y_top:.2f} {x:.2f} {y_bottom:.2f}] /Extend [true true] "
                 f"/Function << /FunctionType 2 /Domain [0 1] /C0 [{f[0]}] /C1 [{f[1]}] /N 1 >> >>").encode())
        return self._shadings[key]

    def page(self, width: float, height: float, ops: list[str], image_objs: set[int], shadings: set[int] = frozenset()) -> None:  # type: ignore[override]
        content = self._stream("", "\n".join(ops).encode("latin-1"))
        xobj = " ".join(f"/Im{n} {n} 0 R" for n in sorted(image_objs))
        sh = " ".join(f"/Sh{n} {n} 0 R" for n in sorted(shadings))
        self.pages.append(self._add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] /Contents {content} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> /XObject << {xobj} >> /Shading << {sh} >> >> >>".encode()))


def _pdf_rr(x: float, y: float, w: float, h: float, r: float) -> str:
    """Rounded rectangle path in PDF coordinates (y up); (x, y) is the bottom-left corner."""
    k = 0.5523 * r
    return (f"{x + r:.3f} {y:.3f} m {x + w - r:.3f} {y:.3f} l {x + w - r + k:.3f} {y:.3f} {x + w:.3f} {y + r - k:.3f} {x + w:.3f} {y + r:.3f} c "
            f"{x + w:.3f} {y + h - r:.3f} l {x + w:.3f} {y + h - r + k:.3f} {x + w - r + k:.3f} {y + h:.3f} {x + w - r:.3f} {y + h:.3f} c "
            f"{x + r:.3f} {y + h:.3f} l {x + r - k:.3f} {y + h:.3f} {x:.3f} {y + h - r + k:.3f} {x:.3f} {y + h - r:.3f} c "
            f"{x:.3f} {y + r:.3f} l {x:.3f} {y + r - k:.3f} {x + r - k:.3f} {y:.3f} {x + r:.3f} {y:.3f} c h")


def _draw_poster(pdf: _PosterPdf, ops: list[str], images: set[int], shades: set[int], lay: Layout, x: float, top: float, width: float, serial: str | None = None) -> None:
    """Draw one poster with its top-left corner at (x, top) and `width` points wide. Height follows the approved proportions."""
    f = width / W
    height = H * f
    tpl = pdf.template()
    images.add(tpl)
    ops.append(f"q {width:.3f} 0 0 {height:.3f} {x:.3f} {top - height:.3f} cm /Im{tpl} Do Q")
    X = lambda px: x + px * f  # noqa: E731
    Y = lambda py: top - py * f  # noqa: E731
    r, g, b = DARK
    ops.append(f"{r / 255:.4f} {g / 255:.4f} {b / 255:.4f} rg")
    for ri, row in enumerate(lay.rows):
        c = 0
        while c < lay.n:
            if row[c] and not lay.in_eye(ri, c):
                run = 1
                while c + run < lay.n and row[c + run] and not lay.in_eye(ri, c + run):
                    run += 1
                ops.append(f"{X(lay.x0 + c * lay.m):.3f} {Y(lay.y0 + (ri + 1) * lay.m):.3f} {run * lay.m * f + 0.02:.3f} {lay.m * f + 0.02:.3f} re")
                c += run
            else:
                c += 1
    ops.append("f")
    m = lay.m
    top_c, bot_c = PALETTES[lay.palette]
    for ri, c in lay.eyes():
        ex, ey = lay.x0 + c * m, lay.y0 + ri * m
        ops.append(f"{r / 255:.4f} {g / 255:.4f} {b / 255:.4f} rg")
        ops.append(_pdf_rr(X(ex), Y(ey + 7 * m), 7 * m * f, 7 * m * f, EYE_R_OUTER * m * f) + " " + _pdf_rr(X(ex + m), Y(ey + 6 * m), 5 * m * f, 5 * m * f, EYE_R_INNER * m * f) + " f*")
        cx0, cy0 = ex + 2 * m, ey + 2 * m
        sh = pdf.shading(X(cx0), Y(cy0), Y(cy0 + 3 * m), top_c, bot_c)
        shades.add(sh)
        ops.append("q " + _pdf_rr(X(cx0), Y(cy0 + 3 * m), 3 * m * f, 3 * m * f, EYE_R_CENTER * m * f) + f" W n /Sh{sh} sh Q")
    tile_png = (ASSETS / "poster_logo_tile.png").read_bytes()
    num, w, h = pdf.image(tile_png)
    images.add(num)
    ts = TILE_SIZE * f
    ops.append(f"q {ts:.3f} 0 0 {ts:.3f} {X(CX - TILE_SIZE / 2):.3f} {Y(CY + TILE_SIZE / 2):.3f} cm /Im{num} Do Q")
    text = serial_text(serial)
    if text:
        size = SERIAL_PX * f
        tw = sum(_HELV.get(c, 556) for c in text) / 1000 * size  # Helvetica advance widths, so the text ends at the same right edge as in the PNG and SVG
        gr = [c / 255 for c in SERIAL_RGB]
        ops.append(f"q {gr[0]:.3f} {gr[1]:.3f} {gr[2]:.3f} rg BT /F1 {size:.2f} Tf {X(SERIAL_RIGHT) - tw:.2f} {Y(SERIAL_BASELINE):.2f} Td ({qs._pdf_text(text).decode('latin-1')}) Tj ET Q")


def poster_pdf(url: str, *, size: str = "ref", serial: str | None = None) -> bytes:
    """One page, exactly the poster. size: 'ref' = the approved PDF page (89 x 126 mm), or 'a6', 'a5', 'a4' (same proportions)."""
    lay = resolve(url)
    if size == "ref":
        width = PAGE_PT[0]
    elif size in A_SIZES_MM:
        width = A_SIZES_MM[size][0] / 25.4 * 72
    else:
        raise ValueError("size must be ref, a6, a5 or a4")
    height = width * H / W
    pdf, ops, images, shades = _PosterPdf(), [], set(), set()
    _draw_poster(pdf, ops, images, shades, lay, 0, height, width, serial)
    pdf.page(width, height, ops, images, shades)
    return pdf.build()


def poster_sheet_pdf(items: list[tuple]) -> bytes:
    """A4 sheets, four posters per page at the approved size, each with crop marks and its serial in the margin.
    items: (label, url) or (label, url, serial); the serial is also printed small ON each poster. The template image is embedded once for the whole file."""
    pw, ph = 595.28, 841.89
    width = PAGE_PT[0]
    height = width * H / W
    gx, gy = (pw - 2 * width) / 3, (ph - 2 * height) / 3
    pdf, per_page = _PosterPdf(), 4
    for start in range(0, max(len(items), 1), per_page):
        ops, images, shades = [], set(), set()
        for slot, (label, url, *rest) in enumerate(items[start:start + per_page]):
            col, row = slot % 2, slot // 2
            x = gx + col * (width + gx)
            top = ph - gy - row * (height + gy)
            _draw_poster(pdf, ops, images, shades, resolve(url), x, top, width, rest[0] if rest else None)
            ops.append("0.4 g")
            ops.append(f"BT /F1 6 Tf {x:.2f} {top - height - 8:.2f} Td ({qs._pdf_text(label).decode('latin-1')}) Tj ET")
            ops.append("0 G 0.25 w")
            for cx, cy in ((x, top), (x + width, top), (x, top - height), (x + width, top - height)):
                sx, sy = (-1 if cx == x else 1), (1 if cy == top else -1)
                ops.append(f"{cx + sx * 3:.2f} {cy:.2f} m {cx + sx * 9:.2f} {cy:.2f} l S {cx:.2f} {cy + sy * 3:.2f} m {cx:.2f} {cy + sy * 9:.2f} l S")
        pdf.page(pw, ph, ops, images, shades)
    return pdf.build()


def fingerprint(url: str) -> str:
    """Stable id of what a poster for `url` looks like (layout, not pixels): used by tests and manifests."""
    lay = resolve(url)
    return hashlib.sha256(f"{lay.n}|{lay.ecc}|{lay.palette}|".encode() + b"".join(lay.rows)).hexdigest()[:16]
