"""The brand avatar must show the whole Coral Tile mark, like the kit's own 1024 icon."""
import struct
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "brand" / "logo" / "coral-tile" / "icons" / "halcyon-icon-primary-1024.png"
AVATARS = (ROOT / "brand" / "assets" / "avatar.png", ROOT / "site" / "brand" / "assets" / "avatar.png")
CORAL = (0xF0, 0x44, 0x6E)


def flat(path):
    img = Image.open(path).convert("RGBA")
    page = Image.new("RGBA", img.size, (255, 255, 255, 255))
    return Image.alpha_composite(page, img).convert("RGB")


class BrandAvatarTest(unittest.TestCase):
    def test_avatar_is_800_square(self):
        for path in AVATARS:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(Image.open(path).size, (800, 800))

    def test_rounded_tile_corners_are_inside_the_frame(self):
        # A whole rounded tile leaves its four extreme corner pixels outside the coral.
        for path in AVATARS:
            img = flat(path)
            for xy in ((0, 0), (799, 0), (0, 799), (799, 799)):
                with self.subTest(path=path.relative_to(ROOT).as_posix(), corner=xy):
                    self.assertNotEqual(img.getpixel(xy), CORAL)

    def test_avatar_matches_the_kit_icon(self):
        icon = flat(ICON).resize((800, 800), Image.LANCZOS)
        for path in AVATARS:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                diff = ImageChops.difference(flat(path), icon)
                self.assertLess(max(ImageStat.Stat(diff).mean), 6.0)

    def test_both_copies_are_identical(self):
        self.assertEqual(AVATARS[0].read_bytes(), AVATARS[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
