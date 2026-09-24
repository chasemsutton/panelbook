"""Generate the Windows launcher icon without external image dependencies."""

from pathlib import Path
import struct
import zlib


ROOT = Path(__file__).resolve().parent
SIZES = (16, 24, 32, 48, 64, 128, 256)


def rounded(x, y, left, top, right, bottom, radius):
    near_x = min(max(x, left + radius), right - radius)
    near_y = min(max(y, top + radius), bottom - radius)
    return (x - near_x) ** 2 + (y - near_y) ** 2 <= radius ** 2


def color_at(x, y):
    if not rounded(x, y, 0.055, 0.055, 0.945, 0.945, 0.2):
        return (0, 0, 0, 0)
    gold = (239, 180, 77, 255)
    navy = (22, 38, 55, 255)
    if rounded(x, y, 0.265, 0.205, 0.735, 0.795, 0.04):
        if 0.305 <= x <= 0.695 and 0.245 <= y <= 0.755:
            if (0.365 <= x <= 0.405 or 0.485 <= x <= 0.525 or 0.605 <= x <= 0.645):
                return navy
            return gold
        return navy
    return gold


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def image(size):
    rows = bytearray()
    samples = 4
    for py in range(size):
        rows.append(0)
        for px in range(size):
            colors = [color_at((px + (sx + 0.5) / samples) / size,
                               (py + (sy + 0.5) / samples) / size)
                      for sy in range(samples) for sx in range(samples)]
            alpha = sum(c[3] for c in colors) / len(colors)
            if alpha:
                rgb = [round(sum(c[channel] * c[3] for c in colors) / (alpha * len(colors)))
                       for channel in range(3)]
            else:
                rgb = [0, 0, 0]
            rows.extend((*rgb, round(alpha)))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def main():
    pictures = [image(size) for size in SIZES]
    offset = 6 + 16 * len(pictures)
    entries = bytearray()
    for size, picture in zip(SIZES, pictures):
        entries.extend(struct.pack("<BBBBHHII", size if size < 256 else 0,
                                   size if size < 256 else 0, 0, 0, 1, 32,
                                   len(picture), offset))
        offset += len(picture)
    (ROOT / "panelbook.ico").write_bytes(struct.pack("<HHH", 0, 1, len(pictures)) +
                                          entries + b"".join(pictures))
    (ROOT / "panelbook-preview.png").write_bytes(pictures[-1])


if __name__ == "__main__":
    main()
