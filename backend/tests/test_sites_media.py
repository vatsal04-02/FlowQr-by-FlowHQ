"""Website image uploads: only JPEG, PNG and WebP; judged by content; SVG and disguised files refused; decompression bombs refused before decoding; EXIF and GPS removed; limits."""
import io
import struct

import pytest
from PIL import Image

from app.services.sites import media

GPS_IFD = 0x8825


def jpeg(size=(900, 600), color=(200, 30, 30), exif=False, orientation=None, icc=False, quality=90) -> bytes:
    im = Image.new("RGB", size, color)
    kw = {"format": "JPEG", "quality": quality}
    if exif or orientation:
        e = Image.Exif()
        if exif:
            e[0x010F] = "SecretPhoneMaker"
            e[0x0110] = "Pixel 8"
            e[GPS_IFD] = {1: "N", 2: (26.0, 27.0, 28.0), 3: "E", 4: (80.0, 21.0, 20.0)}  # a GPS position
        if orientation:
            e[0x0112] = orientation
        kw["exif"] = e.tobytes()
    if icc:
        kw["icc_profile"] = b"fake-icc-profile" * 20
    buf = io.BytesIO()
    im.save(buf, **kw)
    return buf.getvalue()


def png(size=(700, 500), mode="RGBA", color=(10, 100, 200, 128)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def webp(size=(700, 500)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (1, 2, 3)).save(buf, "WEBP")
    return buf.getvalue()


def out(p: media.Processed) -> Image.Image:
    return Image.open(io.BytesIO(p.data))


@pytest.mark.parametrize("make", [jpeg, png, webp])
def test_the_three_allowed_types_are_accepted_and_become_webp(make):
    p = media.process_image(make())
    assert p.content_type == "image/webp" and out(p).format == "WEBP" and p.storage_key == f"assets/{p.sha256[:16]}.webp" and len(p.sha256) == 64


def test_exif_and_gps_are_removed():
    raw = jpeg(exif=True)
    assert b"SecretPhoneMaker" in raw and b"Exif" in raw  # the test file really carries them
    p = media.process_image(raw)
    assert b"SecretPhoneMaker" not in p.data and b"Pixel 8" not in p.data and b"Exif" not in p.data and b"GPSLatitude" not in p.data
    assert not (media.FORBIDDEN_CHUNKS & set(media.riff_chunks(p.data)))
    im = out(p)
    assert dict(im.getexif()) == {} and "exif" not in im.info and "xmp" not in im.info and "icc_profile" not in im.info


def test_icc_profiles_are_removed_too():
    p = media.process_image(jpeg(icc=True))
    assert b"fake-icc-profile" not in p.data and "icc_profile" not in out(p).info and "ICCP" not in media.riff_chunks(p.data)


def test_orientation_is_applied_then_dropped():
    # a 900x600 landscape photo with orientation 6 (rotate 90) is shown upright: 600 wide, 900 tall
    p = media.process_image(jpeg(size=(900, 600), orientation=6))
    assert (p.width, p.height) == (600, 900) and dict(out(p).getexif()) == {}


def test_output_is_deterministic_and_deduplicable():
    assert media.process_image(jpeg()).sha256 == media.process_image(jpeg()).sha256


def test_large_photos_are_reduced():
    p = media.process_image(jpeg(size=(4000, 3000)), "photo")
    assert max(p.width, p.height) == 1600 and len(p.data) < 400_000
    logo = media.process_image(png((2000, 1000)), "logo")
    assert max(logo.width, logo.height) == 600


def test_a_logo_keeps_its_transparency():
    p = media.process_image(png((300, 200), "RGBA", (0, 0, 0, 0)), "logo")
    assert out(p).mode == "RGBA" and out(p).getpixel((5, 5))[3] == 0


# ---------------------------------------------------------------------------------------------------------------- refusals
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><script>alert(1)</script><rect width="400" height="400"/></svg>'


@pytest.mark.parametrize("raw,code", [
    (SVG, "unsupported_type"), (b"<html><script>alert(1)</script></html>", "unsupported_type"), (b"GIF89a" + b"\x00" * 50, "unsupported_type"), (b"BM" + b"\x00" * 60, "unsupported_type"),
    (b"%PDF-1.4 fake", "unsupported_type"), (b"MZ\x90\x00" + b"\x00" * 60, "unsupported_type"), (b"", "empty"), (b"\x89PNG\r\n\x1a\n" + b"junk" * 20, "corrupt"),
    (b"\xff\xd8\xff\xe0" + b"junk" * 50, "corrupt"), (b"RIFF\x04\x00\x00\x00WEBPjunk", "corrupt"),
])
def test_refused_uploads(raw, code):
    with pytest.raises(media.MediaError) as e:
        media.process_image(raw)
    assert e.value.code == code


def test_a_svg_cannot_be_smuggled_in_with_an_image_extension_or_content_type():
    # the function never receives a name or content type at all; a file is what its first bytes say it is
    with pytest.raises(media.MediaError):
        media.process_image(SVG, "logo")


def test_a_jpeg_with_an_appended_script_is_rebuilt_without_it():
    raw = jpeg() + b"<script>alert(1)</script><?php system($_GET[0]); ?>"
    p = media.process_image(raw)
    assert b"<script>" not in p.data and b"<?php" not in p.data


def test_a_polyglot_whose_header_says_png_but_whose_body_is_jpeg_is_refused():
    raw = b"\x89PNG\r\n\x1a\n" + jpeg()[2:]
    with pytest.raises(media.MediaError):
        media.process_image(raw)


def test_a_decompression_bomb_is_refused_before_it_is_decoded():
    # an 8000 x 8000 one-bit PNG is a few KB on disk but 64 million pixels in memory
    buf = io.BytesIO()
    Image.new("1", (8000, 8000), 0).save(buf, "PNG", optimize=True)
    assert len(buf.getvalue()) < 100_000
    with pytest.raises(media.MediaError) as e:
        media.process_image(buf.getvalue())
    assert e.value.code == "too_many_pixels"


def test_a_png_header_claiming_huge_dimensions_is_refused():
    raw = bytearray(png((100, 100), "RGB", (1, 2, 3)))
    raw[16:24] = struct.pack(">II", 60000, 60000)  # the IHDR width and height
    with pytest.raises(media.MediaError):
        media.process_image(bytes(raw))


def test_animated_images_are_refused():
    buf = io.BytesIO()
    frames = [Image.new("RGB", (400, 400), (i * 40, 0, 0)) for i in range(3)]
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=100)
    with pytest.raises(media.MediaError) as e:
        media.process_image(buf.getvalue())
    assert e.value.code == "animated"


def test_size_limits():
    with pytest.raises(media.MediaError) as e:
        media.process_image(b"\xff\xd8\xff" + b"\x00" * (media.MAX_UPLOAD_BYTES + 1))
    assert e.value.code == "too_large" and e.value.status == 413
    with pytest.raises(media.MediaError) as e:
        media.process_image(jpeg(size=(120, 90)))
    assert e.value.code == "too_small"
    assert media.process_image(png((70, 70)), "logo").width == 70


def test_unknown_kind_is_refused():
    with pytest.raises(media.MediaError):
        media.process_image(jpeg(), "banner")
