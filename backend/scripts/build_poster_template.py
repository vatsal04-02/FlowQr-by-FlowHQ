"""Build the poster template assets from the approved FlowQR poster PDF (page 1).

    python scripts/build_poster_template.py <approved-poster.pdf> [out_dir]

Writes into app/assets/poster/:
  poster_template.png   the approved poster, pixel-for-pixel, except the module area inside the QR card, which is cleared to
                        the card's own white. Nothing else in the artwork is touched.
  poster_logo_tile.png  the FlowQR logo tile that sits in the centre of the QR (RGBA, rounded white tile + the "F")
  poster_geometry.json  where the QR goes, how it is drawn, and the colours measured from the approved artwork

The approved poster is a single flattened image, so this reads that image (not a re-drawing of it). Run once; the outputs are
committed so the server never needs the PDF.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter

pdf = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "app" / "assets" / "poster"
out.mkdir(parents=True, exist_ok=True)

doc = pymupdf.open(pdf)
page = doc[0]
imgs = page.get_images()
assert len(imgs) == 1, "expected the poster to be one flattened image"
info = doc.extract_image(imgs[0][0])
src = Image.open(__import__("io").BytesIO(info["image"])).convert("RGB")
W, H = src.size
a = np.asarray(src).astype(int)

# --- the QR card (white rounded rectangle) and the module area inside it, measured from the artwork ---------------------
CARD = (268, 445, 787, 942)      # x0, y0, x1, y1 of the white card
MODULES = (290, 466, 764, 920)   # bounding box of the original (illustrative) modules
ERASE = (286, 462, 769, 925)     # cleared area: just outside the modules, fully inside the card (corner radius ~35 px)
card_white = tuple(int(v) for v in np.median(a[452:458, 330:720].reshape(-1, 3), axis=0))

# --- the logo tile: bounding box from the artwork, glyph = the orange "F" -------------------------------------------------
TILE = (459, 646, 595, 782)      # 136 x 136 centred on x=527
tile_crop = src.crop(TILE)
tile_arr = np.asarray(tile_crop).astype(float)
whiteness = tile_arr.min(axis=2)  # white ~250, orange F has a blue channel of ~4
alpha = np.clip((235 - whiteness) / (235 - 40), 0, 1)  # 0 on the tile's white, 1 on the orange
glyph = np.zeros((tile_crop.height, tile_crop.width, 4), dtype=np.uint8)
glyph[..., :3] = np.where(alpha[..., None] > 0.02, tile_arr, 0).astype(np.uint8)
glyph[..., 3] = (alpha * 255).astype(np.uint8)
# keep only the interior of the tile (drop the tile's edge/shadow and any module pixels at the corners)
inner = Image.new("L", tile_crop.size, 0)
ImageDraw.Draw(inner).rounded_rectangle((14, 14, tile_crop.width - 15, tile_crop.height - 15), radius=12, fill=255)
glyph[..., 3] = (np.asarray(inner).astype(float) / 255 * glyph[..., 3]).astype(np.uint8)

# the tile itself: rounded white square with the soft shadow of the original
SS = 4
tw, th = tile_crop.size
pad = 8
tile = Image.new("RGBA", ((tw + 2 * pad) * SS, (th + 2 * pad) * SS), (0, 0, 0, 0))
shadow = Image.new("RGBA", tile.size, (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((pad * SS, (pad + 2) * SS, (pad + tw) * SS, (pad + th + 2) * SS), radius=34 * SS, fill=(235, 150, 90, 70))
tile = Image.alpha_composite(tile, shadow.filter(ImageFilter.GaussianBlur(3 * SS)))
ImageDraw.Draw(tile).rounded_rectangle((pad * SS, pad * SS, (pad + tw) * SS - 1, (pad + th) * SS - 1), radius=34 * SS, fill=(255, 255, 255, 255))
tile = tile.resize((tw + 2 * pad, th + 2 * pad), Image.LANCZOS)
tile.alpha_composite(Image.fromarray(glyph, "RGBA"), (pad, pad))
tile.save(out / "poster_logo_tile.png", optimize=True)

# --- finder eye colours, measured --------------------------------------------------------------------------------------
org = (a[..., 0] > 200) & (a[..., 1] < 160) & (a[..., 2] < 90)
sub = org[470:590, 290:410]
ys, xs = np.where(sub.any(1))[0], np.where(sub.any(0))[0]
y0, y1, x0, x1 = ys.min() + 470, ys.max() + 470, xs.min() + 290, xs.max() + 290
eye_top = [int(v) for v in a[y0 + 8, (x0 + x1) // 2]]
eye_bottom = [int(v) for v in a[y1 - 8, (x0 + x1) // 2]]
dark = [int(v) for v in np.median(a[(a.sum(2) < 120)], axis=0)]

# --- the template: original pixels, module area cleared to the card's white ---------------------------------------------
tpl = src.copy()
ImageDraw.Draw(tpl).rectangle((ERASE[0], ERASE[1], ERASE[2], ERASE[3]), fill=card_white)
tpl.save(out / "poster_template.png", optimize=True)

geom = {
    "size": [W, H], "page_pt": [round(page.rect.width, 2), round(page.rect.height, 2)],
    "card": list(CARD), "erase": list(ERASE), "original_modules": list(MODULES),
    # the new code is drawn inside this square (centred in the card); modules are whole pixels at 1x
    "qr_box": [300, 466, 755, 921], "tile_size": [tw + 2 * pad, th + 2 * pad], "tile_pad": pad,
    "tile_px": [tw, th], "dark": dark, "eye_top": eye_top, "eye_bottom": eye_bottom, "card_white": list(card_white),
}
(out / "poster_geometry.json").write_text(json.dumps(geom, indent=1))
print(json.dumps(geom))
