"""A tiny text-only PDF writer (Helvetica, A4, wrapped lines, page numbers) for the downloadable report. No external dependency."""
import textwrap
import zlib

PAGE_W, PAGE_H, MARGIN = 595.28, 841.89, 50.0
LEADING = {"h1": 26, "h2": 20, "p": 14, "small": 12}
SIZE = {"h1": 18, "h2": 12.5, "p": 10, "small": 8.5}
WRAP = {"h1": 60, "h2": 80, "p": 100, "small": 120}


def _esc(s: str) -> bytes:
    return s.encode("latin-1", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def render(blocks: list[tuple[str, str]], title: str) -> bytes:
    """blocks: (style, text) with style in h1|h2|p|small|gap. Returns the PDF bytes."""
    pages: list[list[bytes]] = [[]]
    y = PAGE_H - MARGIN

    def line(style: str, text: str):
        nonlocal y
        if y - LEADING[style] < MARGIN + 20:
            pages.append([])
            y = PAGE_H - MARGIN
        font = "/F2" if style in ("h1", "h2") else "/F1"
        pages[-1].append(b"BT " + font.encode() + f" {SIZE[style]} Tf {MARGIN:.1f} {y - SIZE[style]:.1f} Td (".encode() + _esc(text) + b") Tj ET")
        y -= LEADING[style]

    for style, text in blocks:
        if style == "gap":
            y -= 8
            continue
        for chunk in text.split("\n"):
            for ln in (textwrap.wrap(chunk, WRAP[style]) or [""]):
                line(style, ln)
    objs: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                         b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for n, ops in enumerate(pages, start=1):
        ops = ops + [b"BT /F1 8 Tf " + f"{PAGE_W / 2 - 20:.1f} 28 Td (Page {n} of {len(pages)}) Tj ET".encode()]
        data = zlib.compress(b"\n".join(ops))
        objs.append(f"<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n".encode() + data + b"\nendstream")
        content = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] /Contents {content} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>".encode())
        kids.append(len(objs))
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = f"<< /Type /Pages /Count {len(kids)} /Kids [{' '.join(f'{k} 0 R' for k in kids)}] >>".encode()
    info = len(objs) + 1
    objs.append(b"<< /Title (" + _esc(title) + b") /Producer (FlowQR) >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, body in enumerate(objs, start=1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
