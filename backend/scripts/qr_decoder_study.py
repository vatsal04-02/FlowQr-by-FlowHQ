"""Repeatable study: how reliably do different QR decoders read FlowQR codes, plain and customised?

This is the evidence behind docs/QR_RELIABILITY.md and behind which decoders tests/test_qr.py trusts. It is not part of
the app or of the test suite; run it when changing the renderer, the default colours or the style rules.

    pip install -r requirements-dev.txt pyzbar        # pyzbar also needs the system library (Debian: apt install libzbar0)
    python scripts/qr_decoder_study.py [--codes 120] [--quick]

Decoders compared (none of them is the library that draws the codes):
    zxing        zxing-cpp                       - what the server uses to prove a style before saving it
    cv-aruco     cv2.QRCodeDetectorAruco         - OpenCV's newer detector
    cv-legacy    cv2.QRCodeDetector              - OpenCV's original detector
    zbar         pyzbar/ZBar                     - skipped if not installed

Everything is seeded, so two runs on the same library versions print the same numbers.
It reads rendered files only. It says nothing about printed paper, glossy lamination, curved surfaces or real phones.
"""
import argparse
import io
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import zxingcpp  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from app.services import qr_style as qs  # noqa: E402
from app.services.qr import qr_png  # noqa: E402

try:
    from pyzbar import pyzbar
except Exception:  # not installed, or libzbar missing
    pyzbar = None

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _bgr(img):
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


DECODERS = {
    "zxing": lambda img: (lambda r: r[0].text if r else "")(zxingcpp.read_barcodes(img.convert("L"))),
    "cv-aruco": lambda img: cv2.QRCodeDetectorAruco().detectAndDecode(_bgr(img))[0],
    "cv-legacy": lambda img: cv2.QRCodeDetector().detectAndDecode(_bgr(img))[0],
}
if pyzbar is not None:
    DECODERS["zbar"] = lambda img: (lambda r: r[0].data.decode() if r else "")(pyzbar.decode(img.convert("L")))


def photo(img, angle, blur, noise, seed, width=700, fill=(255, 255, 255)):
    """Rotated, shrunk, slightly out of focus, with sensor noise."""
    im = img.convert("RGB").rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=fill)
    im = im.resize((width, int(width * im.height / im.width)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(blur))
    arr = np.array(im).astype(np.int16) + np.random.default_rng(seed).normal(0, noise, (im.height, im.width, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def logo(color):
    im = Image.new("RGB", (400, 240), (255, 255, 255))
    ImageDraw.Draw(im).ellipse([20, 20, 380, 220], fill=color)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return qs.normalise_logo(buf.getvalue())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=120)
    ap.add_argument("--quick", action="store_true", help="fewer codes in the slow camera sections")
    args = ap.parse_args()
    rng = random.Random(20261110)
    urls = ["https://go.flowqr.co.in/c/" + "".join(rng.choice(ALPHABET) for _ in range(24)) for _ in range(args.codes)]
    red, dark = logo((200, 30, 30)), logo((20, 20, 20))
    print(f"opencv {cv2.__version__}; decoders: {', '.join(DECODERS)}" + ("" if pyzbar else "  (zbar not installed: skipped)"))

    print(f"\nA. Clean, straight-on renders: codes NOT read, out of {args.codes}")
    styles = [("old renderer (plain)", None, None), ("plain", {}, None), ("blue", {"dark": "#1B46B8"}, None), ("blue + logo 20%", {"dark": "#1B46B8", "use_logo": True}, red),
              ("black + logo 25%", {"use_logo": True, "logo_scale": 0.25}, red), ("black + dark logo 25%", {"use_logo": True, "logo_scale": 0.25}, dark)]
    for name, style, lg in styles:
        miss = dict.fromkeys(DECODERS, 0)
        for u in urls:
            img = Image.open(io.BytesIO(qr_png(u) if style is None else qs.render_png(u, style, lg)))
            for d, fn in DECODERS.items():
                miss[d] += fn(img) != u
        print(f"   {name:24s} " + "  ".join(f"{d} {n:3d}" for d, n in miss.items()))

    n = 12 if args.quick else 40
    shots = [(0, 0.6, 3), (4, 0.8, 4), (-9, 1.0, 6), (15, 1.2, 8), (30, 0.8, 6), (60, 1.0, 6), (90, 0.6, 4), (180, 1.0, 6)]
    print(f"\nB. Camera-like shots (rotation, blur, noise) {shots}: shots NOT read, out of {n * len(shots)}")
    for name, style, lg in styles[1:]:
        miss = dict.fromkeys(DECODERS, 0)
        for u in urls[:n]:
            img = Image.open(io.BytesIO(qs.render_png(u, style, lg)))
            for i, (a, b, s) in enumerate(shots):
                v = photo(img, a, b, s, i)
                for d, fn in DECODERS.items():
                    miss[d] += fn(v) != u
        print(f"   {name:24s} " + "  ".join(f"{d} {n_:3d}" for d, n_ in miss.items()))

    n = 8 if args.quick else 16
    angles = [0, 30, 40, 45, 50, 60]
    print(f"\nC. Steep rotation by colour (blur 1.0, noise 6, 700 px): codes NOT read, out of {n}, at {angles} degrees")
    colours = [("pure black #000000", "#000000", "#FFFFFF"), ("FlowQR default #111827", "#111827", "#FFFFFF"), ("green #0B5D1E", "#0B5D1E", "#FFFFFF"),
               ("blue #1B46B8", "#1B46B8", "#FFFFFF"), ("blue on cream", "#1B46B8", "#FFF8E7"), ("grey #757575 (4.6:1)", "#757575", "#FFFFFF")]
    for name, d_, l_ in colours:
        cells = {d: [] for d in DECODERS}
        for a in angles:
            miss = dict.fromkeys(DECODERS, 0)
            for u in urls[:n]:
                v = photo(Image.open(io.BytesIO(qs.render_png(u, {"dark": d_, "light": l_}))), a, 1.0, 6, 4)
                for d, fn in DECODERS.items():
                    miss[d] += fn(v) != u
            for d in DECODERS:
                cells[d].append(miss[d])
        print(f"   {name:24s} " + "  ".join(f"{d} {cells[d]}" for d in DECODERS))


if __name__ == "__main__":
    main()
