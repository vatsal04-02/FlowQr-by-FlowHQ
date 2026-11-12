"""Styled QR rendering (tenant branding): colours, logo, caption, size, margin, error correction; PNG, SVG and PDF.

`services/qr.py` is untouched and still produces the plain FlowQR code, so every code printed before this feature
renders exactly as it did.

The rule everything here serves: a style may change how a code LOOKS, never what it ENCODES and never whether it scans.
The encoded URL comes only from the permanent token / public id. Styles are validated (contrast, quiet zone, logo size,
error correction) and then proven by decoding the rendered image with an independent decoder before they are accepted.
"""
import base64
import hashlib
import io
import math
import zlib
from functools import lru_cache
from xml.sax.saxutils import escape as _xml

import segno
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError

from app.services.qr import QUIET_ZONE_MODULES

DEFAULT_STYLE: dict = {"dark": "#111827", "light": "#FFFFFF", "margin": QUIET_ZONE_MODULES, "error_correction": "H", "size_px": 1024,
                       "use_logo": False, "logo_scale": 0.2, "caption": None}
MIN_CONTRAST = 4.5  # WCAG contrast ratio between modules and background; below this, cheap phone cameras start to fail
MIN_MODULE_PX = 4  # never render a module smaller than this
MAX_LOGO_BYTES = 512 * 1024
LOGO_PX = 512
LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}
PDF_DPI = 300
SHEET_COLS, SHEET_ROWS = 3, 4


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hex_color: str) -> float:
    def lin(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hex_color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def style_problem(style: dict) -> str | None:
    """Why this style could make a code unreadable, or None. Checked before anything is saved or rendered."""
    dark, light = style["dark"], style["light"]
    if luminance(dark) >= luminance(light):
        return "The code colour must be darker than the background. Light-on-dark codes fail on many scanners."
    ratio = contrast_ratio(dark, light)
    if ratio < MIN_CONTRAST:
        return (f"These colours are too close (contrast {ratio:.1f}:1, need at least {MIN_CONTRAST}:1). "
                "Pick a darker code colour or a lighter background.")
    if style["margin"] < QUIET_ZONE_MODULES:
        return f"The margin must be at least {QUIET_ZONE_MODULES} modules (the QR quiet zone)."
    return None


def effective_style(style: dict | None, has_logo: bool) -> dict:
    """The style that will actually be drawn. A logo hides modules, so it always forces error correction H."""
    s = {**DEFAULT_STYLE, **{k: v for k, v in (style or {}).items() if k in DEFAULT_STYLE and v is not None}}
    s["dark"], s["light"] = s["dark"].upper(), s["light"].upper()
    s["use_logo"] = bool(s["use_logo"] and has_logo)
    if s["use_logo"]:
        s["error_correction"] = "H"
    s["margin"] = max(QUIET_ZONE_MODULES, int(s["margin"]))
    s["logo_scale"] = min(0.25, max(0.1, float(s["logo_scale"])))
    return s


def is_plain(style: dict) -> bool:
    return all(style.get(k) == v for k, v in DEFAULT_STYLE.items() if k != "size_px")


def normalise_logo(raw: bytes) -> bytes:
    """Validate an uploaded logo and re-encode it as a small PNG. Re-encoding drops metadata and anything that is not pixels."""
    if len(raw) > MAX_LOGO_BYTES:
        raise ValueError("Logo must be 512 KB or smaller")
    try:
        im = Image.open(io.BytesIO(raw))
        fmt, (w, h) = im.format, im.size
        if fmt in LOGO_FORMATS and w * h <= 16_000_000:
            im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError) as exc:
        raise ValueError("That file is not a readable image") from exc
    if fmt not in LOGO_FORMATS:
        raise ValueError("Logo must be a PNG, JPEG or WebP image")
    if w * h > 16_000_000:
        raise ValueError("Logo dimensions are too large")
    if min(w, h) < 64:
        raise ValueError("Logo must be at least 64 pixels on its shorter side")
    im = ImageOps.exif_transpose(im).convert("RGBA")
    im.thumbnail((LOGO_PX, LOGO_PX), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _matrix(url: str, ecc: str):
    rows = [bytes(r) for r in segno.make(url, error=ecc.lower(), micro=False).matrix]
    return rows, len(rows)


def _font(px: int):
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    while len(text) > 1 and draw.textlength(text, font=font) > width:
        text = text[:-1]
    return text


def _render(url: str, style: dict | None, logo: bytes | None, *, size_px: int | None = None, max_px: int | None = None,
            caption: bool = True) -> Image.Image:
    s = effective_style(style, bool(logo))
    rows, n = _matrix(url, s["error_correction"])
    margin = s["margin"]
    total = n + 2 * margin
    if max_px:  # fit inside a box (print sheets): whole pixels per module, never fractional
        scale = max(MIN_MODULE_PX, max_px // total)
    else:  # at least the requested size: rounding up keeps every module a whole number of pixels
        scale = max(MIN_MODULE_PX, math.ceil((size_px or s["size_px"]) / total))
    small = Image.new("L", (total, total), 255)
    px = small.load()
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                px[x + margin, y + margin] = 0
    side = total * scale
    mask = small.resize((side, side), Image.NEAREST)
    img = Image.composite(Image.new("RGB", (side, side), _rgb(s["light"])), Image.new("RGB", (side, side), _rgb(s["dark"])), mask)
    if s["use_logo"] and logo:
        box = int(n * scale * s["logo_scale"])
        plate = box + 2 * scale  # one module of clear space around the logo
        x0 = (side - plate) // 2
        ImageDraw.Draw(img).rectangle([x0, x0, x0 + plate - 1, x0 + plate - 1], fill=_rgb(s["light"]))
        mark = ImageOps.contain(Image.open(io.BytesIO(logo)).convert("RGBA"), (box, box), Image.LANCZOS)
        img.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2), mark)
    if caption and s["caption"]:
        font = _font(max(12, int(scale * 1.8)))
        band = int(scale * 3.2)
        out = Image.new("RGB", (side, side + band), _rgb(s["light"]))
        out.paste(img, (0, 0))
        d = ImageDraw.Draw(out)
        text = _fit(d, s["caption"], font, side - 2 * scale)
        d.text(((side - d.textlength(text, font=font)) / 2, side - scale * 1.4), text, fill=_rgb(s["dark"]), font=font)  # below the quiet zone
        img = out
    return img


def render_png(url: str, style: dict | None = None, logo: bytes | None = None, *, size_px: int | None = None) -> bytes:
    buf = io.BytesIO()
    _render(url, style, logo, size_px=size_px).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_svg(url: str, style: dict | None = None, logo: bytes | None = None, *, size_px: int | None = None) -> bytes:
    """Vector output: one path for the modules (run-length per row), the logo embedded as a data URI. No external references."""
    s = effective_style(style, bool(logo))
    rows, n = _matrix(url, s["error_correction"])
    margin = s["margin"]
    total = n + 2 * margin
    cap = 3.2 if s["caption"] else 0
    px = max(MIN_MODULE_PX, math.ceil((size_px or s["size_px"]) / total))
    d = []
    for y, row in enumerate(rows):
        x = 0
        while x < n:
            if row[x]:
                run = 1
                while x + run < n and row[x + run]:
                    run += 1
                d.append(f"M{x + margin} {y + margin}h{run}v1h-{run}z")
                x += run
            else:
                x += 1
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{total * px}" height="{int((total + cap) * px)}" '
             f'viewBox="0 0 {total} {total + cap}" shape-rendering="crispEdges">',
             f'<rect width="{total}" height="{total + cap}" fill="{s["light"]}"/>', f'<path fill="{s["dark"]}" d="{"".join(d)}"/>']
    if s["use_logo"] and logo:
        box = n * s["logo_scale"]
        plate = box + 2
        p0, b0 = (total - plate) / 2, (total - box) / 2
        parts.append(f'<rect x="{p0:.3f}" y="{p0:.3f}" width="{plate:.3f}" height="{plate:.3f}" fill="{s["light"]}"/>')
        parts.append(f'<image x="{b0:.3f}" y="{b0:.3f}" width="{box:.3f}" height="{box:.3f}" preserveAspectRatio="xMidYMid meet" '
                     f'href="data:image/png;base64,{base64.b64encode(logo).decode()}"/>')
    if s["caption"]:
        parts.append(f'<text x="{total / 2}" y="{total + 1.2}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" '
                     f'font-size="1.8" fill="{s["dark"]}" shape-rendering="auto">{_xml(s["caption"])}</text>')
    parts.append("</svg>")
    return "".join(parts).encode()


# ---------------------------------------------------------------------------------------------------------------------
# PDF: a small vector writer. Modules are filled rectangles, so the file is a few KB and prints sharp at any size.
# (Pillow's PDF export embeds a raster image: either JPEG, which smears module edges, or megabytes of uncompressed pixels.)
# ---------------------------------------------------------------------------------------------------------------------
_HELV_NARROW, _HELV_WIDE = set(" iIjl.,:;!|'()[]ftr-/"), set("mwMW@%")


def _text_width(text: str, size: float) -> float:
    """Approximate Helvetica advance width, good enough to centre a short label."""
    units = sum(300 if c in _HELV_NARROW else 860 if c in _HELV_WIDE else 680 if c.isupper() else 556 for c in text)
    return units / 1000 * size


def _pdf_text(text: str) -> bytes:
    raw = text.encode("latin-1", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class _Pdf:
    def __init__(self) -> None:
        self.objects: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]  # 1 catalog, 2 pages, 3 font
        self.pages: list[int] = []
        self.images: dict[str, tuple[int, int, int]] = {}  # logo hash -> (object number, width, height)

    def _add(self, body: bytes) -> int:
        self.objects.append(body)
        return len(self.objects)

    def _stream(self, head: str, data: bytes) -> int:
        packed = zlib.compress(data, 9)
        return self._add(f"<< {head} /Filter /FlateDecode /Length {len(packed)} >>\nstream\n".encode() + packed + b"\nendstream")

    def image(self, logo: bytes) -> tuple[int, int, int]:
        key = hashlib.sha256(logo).hexdigest()
        if key not in self.images:
            im = Image.open(io.BytesIO(logo)).convert("RGBA")
            im.thumbnail((256, 256), Image.LANCZOS)
            w, h = im.size
            mask = self._stream(f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray /BitsPerComponent 8", im.getchannel("A").tobytes())
            num = self._stream(f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /SMask {mask} 0 R",
                               im.convert("RGB").tobytes())
            self.images[key] = (num, w, h)
        return self.images[key]

    def page(self, width: float, height: float, ops: list[str], image_objs: set[int]) -> None:
        content = self._stream("", "\n".join(ops).encode("latin-1"))
        xobj = " ".join(f"/Im{n} {n} 0 R" for n in sorted(image_objs))
        self.pages.append(self._add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] /Contents {content} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> /XObject << {xobj} >> >> >>".encode()))

    def build(self) -> bytes:
        self.objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        self.objects[1] = f"<< /Type /Pages /Count {len(self.pages)} /Kids [{' '.join(f'{n} 0 R' for n in self.pages)}] >>".encode()
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(self.objects, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(self.objects) + 1}\n0000000000 65535 f \n".encode()
        out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
        out += f"trailer\n<< /Size {len(self.objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


def _fill(hex_color: str) -> str:
    r, g, b = _rgb(hex_color)
    return f"{r / 255:.4f} {g / 255:.4f} {b / 255:.4f} rg"


def _pdf_code(pdf: _Pdf, ops: list[str], images: set[int], x: float, top: float, side: float, url: str, style: dict | None,
              logo: bytes | None, label: str | None, label_size: float) -> None:
    """Draw one code with its top-left corner at (x, top) and `side` points wide (PDF's origin is bottom-left)."""
    s = effective_style(style, bool(logo))
    rows, n = _matrix(url, s["error_correction"])
    margin = s["margin"]
    m = side / (n + 2 * margin)  # points per module
    band = label_size * 2 if label else 0
    ops += [_fill(s["light"]), f"{x:.3f} {top - side - band:.3f} {side:.3f} {side + band:.3f} re f", _fill(s["dark"])]
    for yi, row in enumerate(rows):
        xi = 0
        while xi < n:
            if row[xi]:
                run = 1
                while xi + run < n and row[xi + run]:
                    run += 1
                # a hair of overlap so viewers never show seams between touching rectangles
                ops.append(f"{x + (xi + margin) * m:.3f} {top - (yi + margin + 1) * m:.3f} {run * m + 0.02:.3f} {m + 0.02:.3f} re")
                xi += run
            else:
                xi += 1
    ops.append("f")
    if s["use_logo"] and logo:
        num, w, h = pdf.image(logo)
        images.add(num)
        box = n * m * s["logo_scale"]
        plate = box + 2 * m
        cx, cy = x + side / 2, top - side / 2
        ops += [_fill(s["light"]), f"{cx - plate / 2:.3f} {cy - plate / 2:.3f} {plate:.3f} {plate:.3f} re f"]
        k = min(box / w, box / h)
        ops.append(f"q {w * k:.3f} 0 0 {h * k:.3f} {cx - w * k / 2:.3f} {cy - h * k / 2:.3f} cm /Im{num} Do Q")
    if label:
        text = label
        while len(text) > 1 and _text_width(text, label_size) > side - 4:
            text = text[:-1]
        tx = x + (side - _text_width(text, label_size)) / 2
        ops += [_fill(s["dark"]), f"BT /F1 {label_size:.2f} Tf {tx:.3f} {top - side - label_size * 1.1:.3f} Td ({_pdf_text(text).decode('latin-1')}) Tj ET"]


def render_pdf(url: str, style: dict | None = None, logo: bytes | None = None, *, size_px: int | None = None) -> bytes:
    """One vector page exactly the size of the code: size_px at 300 dpi, never smaller than 4 inches (~10 cm) across."""
    s = effective_style(style, bool(logo))
    side = max(size_px or s["size_px"], 1200) / PDF_DPI * 72
    label_size = side / 22
    height = side + (label_size * 2 if s["caption"] else 0)
    pdf, ops, images = _Pdf(), [], set()
    _pdf_code(pdf, ops, images, 0, height, side, url, s, logo, s["caption"], label_size)
    pdf.page(side, height, ops, images)
    return pdf.build()


def render_sheet_pdf(items: list[tuple[str, str, dict | None, bytes | None]]) -> bytes:
    """A4 print sheets, 12 codes per page (about 58 mm each), each with its label underneath. items: (label, url, style, logo)."""
    w, h, pad, label_size = 595.28, 841.89, 28.0, 9.0
    cell_w, cell_h = (w - 2 * pad) / SHEET_COLS, (h - 2 * pad) / SHEET_ROWS
    side = min(cell_w, cell_h - label_size * 2) - 14
    pdf, per_page = _Pdf(), SHEET_COLS * SHEET_ROWS
    for start in range(0, max(len(items), 1), per_page):
        ops, images = [], set()
        for slot, (label, url, style, logo) in enumerate(items[start:start + per_page]):
            x = pad + (slot % SHEET_COLS) * cell_w + (cell_w - side) / 2
            top = h - pad - (slot // SHEET_COLS) * cell_h
            _pdf_code(pdf, ops, images, x, top, side, url, {**(style or {}), "caption": None}, logo, label, label_size)
        pdf.page(w, h, ops, images)
    return pdf.build()


# ---------------------------------------------------------------------------------------------------------------------
# Scannability proof: decode what was rendered.
# ---------------------------------------------------------------------------------------------------------------------
def decoder_available() -> bool:
    try:
        import zxingcpp  # noqa: F401
        return True
    except ImportError:
        return False


def decode(img: Image.Image) -> str | None:
    """Read a QR code out of an image with ZXing (an independent decoder, not the library that drew it)."""
    import zxingcpp

    found = zxingcpp.read_barcodes(img.convert("L"))
    return found[0].text if found else None


def _key(style: dict) -> tuple:
    return tuple((k, style.get(k)) for k in sorted(DEFAULT_STYLE) if k != "size_px")


def scannable(url: str, style: dict | None, logo: bytes | None) -> bool | None:
    """True if the styled code decodes back to exactly `url` at full size, shrunk to ~240 px (small print / far away) and
    slightly blurred (out of focus). None if no decoder is installed (the style rules above are then the only guard)."""
    if not decoder_available():
        return None
    s = effective_style(style, bool(logo))
    used = logo if s["use_logo"] else None
    return _scannable(url, _key(s), hashlib.sha256(used).hexdigest() if used else "", used)


@lru_cache(maxsize=2048)
def _scannable(url: str, key: tuple, logo_hash: str, logo: bytes | None) -> bool:
    img = _render(url, dict(key), logo, size_px=1024)
    small = img.resize((240, max(1, int(240 * img.height / img.width))), Image.BOX)
    blurred = img.filter(ImageFilter.GaussianBlur(radius=img.width / 400))
    return all(decode(v) == url for v in (img, small, blurred))


def safe_style(url: str, style: dict | None, logo: bytes | None) -> tuple[dict, bytes | None, bool]:
    """(style, logo, applied). If the requested style is invalid or its rendering does not decode, the plain FlowQR style
    is used instead and `applied` is False: a download is never allowed to hand out an unscannable code."""
    s = effective_style(style, bool(logo))
    if is_plain(s):
        return s, None, True
    if style_problem(s) is None and scannable(url, s, logo) is not False:
        return s, (logo if s["use_logo"] else None), True
    return {**DEFAULT_STYLE, "size_px": s["size_px"]}, None, False
