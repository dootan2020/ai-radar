"""The brand avatar must show the whole Coral Tile mark, like the kit's own 1024 icon.

Standard library only: a small 8-bit, non-interlaced PNG decoder reads the files.
"""
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "brand" / "logo" / "coral-tile" / "icons" / "halcyon-icon-primary-1024.png"
AVATARS = (ROOT / "brand" / "assets" / "avatar.png", ROOT / "site" / "brand" / "assets" / "avatar.png")
CORAL = (0xF0, 0x44, 0x6E)
CHANNELS = {2: 3, 6: 4}


def read_png(path):
    """Return (width, height, rows) with rows as lists of (r, g, b) flattened on white."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, header = 8, [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + length
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or color not in CHANNELS or interlace:
        raise ValueError(f"{path}: only 8-bit RGB/RGBA non-interlaced PNG is supported")
    bpp = CHANNELS[color]
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    rows, prev = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        ftype, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:
                line[i] = (line[i] + a) & 255
            elif ftype == 2:
                line[i] = (line[i] + b) & 255
            elif ftype == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
            elif ftype != 0:
                raise ValueError(f"{path}: bad filter {ftype}")
        prev = line
        pixels = []
        for x in range(0, stride, bpp):
            r, g, bl = line[x], line[x + 1], line[x + 2]
            if bpp == 4:
                al = line[x + 3]
                r, g, bl = ((v * al + 255 * (255 - al)) // 255 for v in (r, g, bl))
            pixels.append((r, g, bl))
        rows.append(pixels)
    return width, height, rows


class BrandAvatarTest(unittest.TestCase):
    def test_avatar_is_800_square(self):
        for path in AVATARS:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                width, height, _ = read_png(path)
                self.assertEqual((width, height), (800, 800))

    def test_rounded_tile_corners_are_inside_the_frame(self):
        # A whole rounded tile leaves its four extreme corner pixels outside the coral.
        for path in AVATARS:
            _, _, rows = read_png(path)
            for x, y in ((0, 0), (799, 0), (0, 799), (799, 799)):
                with self.subTest(path=path.relative_to(ROOT).as_posix(), corner=(x, y)):
                    self.assertNotEqual(rows[y][x], CORAL)

    def test_avatar_matches_the_kit_icon(self):
        iw, ih, icon = read_png(ICON)
        for path in AVATARS:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                _, _, rows = read_png(path)
                total = count = 0
                for y in range(2, 800, 4):
                    for x in range(2, 800, 4):
                        a, b = rows[y][x], icon[y * ih // 800][x * iw // 800]
                        total += sum(abs(p - q) for p, q in zip(a, b)) / 3
                        count += 1
                self.assertLess(total / count, 6.0)

    def test_both_copies_are_identical(self):
        self.assertEqual(AVATARS[0].read_bytes(), AVATARS[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
