"""Image uploads for websites.

What goes in is untrusted. What is stored is a NEW image that this code encoded:
  * the file type is decided from its first bytes (JPEG, PNG or WebP); the name, the declared content type and the extension are never trusted; SVG and everything else is refused
  * the dimensions are checked BEFORE the pixels are decoded (a small file can describe a huge image), animated images are refused
  * the picture is rotated as its EXIF orientation says, then rebuilt as a fresh WebP: EXIF (including GPS position), XMP, ICC profiles and every other metadata block are not carried over,
    and the finished file is checked chunk by chunk to prove none of them is present
  * the longest edge is limited (1600 px photos, 600 px logos), so a phone photo of 8 MB becomes a few hundred KB"""
from __future__ import annotations

import hashlib
import io
import struct
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000  # decoded size we are willing to open (the largest phone sensors are about 50 MP, which is refused with a clear message)
MAX_EDGE = {"photo": 1600, "logo": 600}
MIN_EDGE = {"photo": 300, "logo": 64}
MAX_ASSETS_PER_SITE = 24
MAX_SITE_BYTES = 12 * 1024 * 1024
ALLOWED = {"JPEG": b"\xff\xd8\xff", "PNG": b"\x89PNG\r\n\x1a\n"}


class MediaError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class Processed:
    data: bytes
    width: int
    height: int
    sha256: str
    content_type: str = "image/webp"

    @property
    def storage_key(self) -> str:
        return f"assets/{self.sha256[:16]}.webp"


def sniff(raw: bytes) -> str | None:
    """JPEG, PNG or WEBP from the leading bytes, else None."""
    for fmt, magic in ALLOWED.items():
        if raw.startswith(magic):
            return fmt
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


def riff_chunks(webp: bytes) -> list[str]:
    """The chunk names of a WebP file, for proving no metadata block survived."""
    out, pos = [], 12
    while pos + 8 <= len(webp):
        name, size = webp[pos:pos + 4].decode("latin-1"), struct.unpack("<I", webp[pos + 4:pos + 8])[0]
        out.append(name)
        pos += 8 + size + (size & 1)
    return out


FORBIDDEN_CHUNKS = {"EXIF", "XMP ", "ICCP"}


def process_image(raw: bytes, kind: str = "photo") -> Processed:
    if kind not in MAX_EDGE:
        raise MediaError("bad_kind", "Unknown image type.")
    if not raw:
        raise MediaError("empty", "No image was received.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise MediaError("too_large", "Images can be up to 8 MB. Choose a smaller photo.", 413)
    fmt = sniff(raw)
    if fmt is None:
        raise MediaError("unsupported_type", "Upload a JPEG, PNG or WebP image. Other types, including SVG, are not accepted.", 415)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(raw))
            if img.format != fmt:
                raise MediaError("type_mismatch", "That file is not the kind of image it claims to be.")
            w, h = img.size
            if w < 1 or h < 1 or w * h > MAX_PIXELS:
                raise MediaError("too_many_pixels", "That image is too large to process. Resize it to under 40 megapixels and try again.")
            if getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1:
                raise MediaError("animated", "Animated images are not supported. Upload a still image.")
            img.load()
        except MediaError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise MediaError("too_many_pixels", "That image is too large to process.")
        except Exception:  # truncated, corrupt or a polyglot that only looks like an image
            raise MediaError("corrupt", "That image could not be read. Try saving it again from your phone or computer.")
    img = ImageOps.exif_transpose(img)  # apply the orientation, then the metadata is dropped below
    longest = max(img.size)
    if longest < MIN_EDGE[kind]:
        raise MediaError("too_small", f"That image is too small. Use one at least {MIN_EDGE[kind]} pixels wide.")
    alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if alpha else "RGB")
    if longest > MAX_EDGE[kind]:
        img.thumbnail((MAX_EDGE[kind], MAX_EDGE[kind]), Image.LANCZOS)
    img.info = {}
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82 if kind == "photo" else 90, method=4, exif=b"", icc_profile=None, xmp=b"")
    out = buf.getvalue()
    bad = FORBIDDEN_CHUNKS & set(riff_chunks(out))
    if bad:  # cannot happen with the settings above; if an image library ever changes, refuse rather than publish metadata
        raise MediaError("metadata_present", "The image could not be cleaned of its metadata.", 500)
    return Processed(data=out, width=img.size[0], height=img.size[1], sha256=hashlib.sha256(out).hexdigest())
