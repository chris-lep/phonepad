"""Draw the app icons (PNG + SVG) into src/phonepad/static/icons/. Standard library only.

Run: make icons. The shapes are signed-distance functions rendered with 4x4 supersampling.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "phonepad" / "static" / "icons"
BG = (0x14, 0x1A, 0x22)
EDGE = (0x2F, 0x7F, 0x78)
ACCENT = (0x4F, 0xD1, 0xC5)
SAMPLES = 4

# (kind, params, colour, alpha); coordinates in 0..1
PAD = (0.5, 0.5, 0.32, 0.32, 0.11)  # centre x, y, half width, half height, corner radius
STROKE = 0.04
DOTS = [((0.62, 0.62), 0.085, 1.0), ((0.48, 0.47), 0.05, 0.55), ((0.38, 0.38), 0.032, 0.3)]


def rounded_rect_distance(x: float, y: float) -> float:
    cx, cy, hw, hh, r = PAD
    qx = abs(x - cx) - (hw - r)
    qy = abs(y - cy) - (hh - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - r


def colour_at(x: float, y: float) -> tuple[float, float, float]:
    r, g, b = (float(c) for c in BG)
    if abs(rounded_rect_distance(x, y)) <= STROKE / 2:
        r, g, b = (float(c) for c in EDGE)
    for (dx, dy), radius, alpha in DOTS:
        if math.hypot(x - dx, y - dy) <= radius:
            r = r + (ACCENT[0] - r) * alpha
            g = g + (ACCENT[1] - g) * alpha
            b = b + (ACCENT[2] - b) * alpha
    return r, g, b


def render(size: int) -> bytes:
    rows = bytearray()
    step = 1.0 / (size * SAMPLES)
    for py in range(size):
        rows.append(0)  # PNG filter: none
        for px in range(size):
            acc = [0.0, 0.0, 0.0]
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    x = (px * SAMPLES + sx + 0.5) * step
                    y = (py * SAMPLES + sy + 0.5) * step
                    for i, c in enumerate(colour_at(x, y)):
                        acc[i] += c
            rows.extend(round(c / SAMPLES**2) for c in acc)
    return png(size, size, bytes(rows))


def png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def svg() -> str:
    def hexc(c: tuple[int, int, int]) -> str:
        return "#" + "".join(f"{v:02x}" for v in c)

    cx, cy, hw, hh, r = PAD
    dots = "".join(
        f'<circle cx="{x * 100:g}" cy="{y * 100:g}" r="{rad * 100:g}" fill="{hexc(ACCENT)}" '
        f'fill-opacity="{a:g}"/>'
        for (x, y), rad, a in DOTS
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<rect width="100" height="100" rx="22" fill="{hexc(BG)}"/>'
        f'<rect x="{(cx - hw) * 100:g}" y="{(cy - hh) * 100:g}" width="{hw * 200:g}" '
        f'height="{hh * 200:g}" rx="{r * 100:g}" fill="none" stroke="{hexc(EDGE)}" '
        f'stroke-width="{STROKE * 100:g}"/>{dots}</svg>\n'
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        (OUT / name).write_bytes(render(size))
        print(f"wrote {OUT / name}")
    (OUT / "icon.svg").write_text(svg(), encoding="utf-8")
    print(f"wrote {OUT / 'icon.svg'}")


if __name__ == "__main__":
    main()
