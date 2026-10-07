"""The live page's favicon and share tags, and the standalone brand kit page.

Every icon and share image the pages point at must exist, with the pixel size read from the
file's own header, so a renamed or wrongly sized export fails here instead of on Facebook.
"""
import struct
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from radar.site_config import SITE_URL

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BRAND = ROOT / "brand"
PAGES_URL = SITE_URL


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.meta, self.refs = [], {}, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link":
            self.links.append(a)
        if tag == "meta" and "content" in a:
            key = a.get("property") or a.get("name")
            if key:
                self.meta[key] = a["content"]
        for attr in ("href", "src", "srcset"):
            if a.get(attr):
                self.refs.append(a[attr])


def parse(path):
    p = Head()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def png_size(path):
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise AssertionError(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


def ico_sizes(path):
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    if (reserved, kind) != (0, 1) or count == 0:
        raise AssertionError(f"{path} is not an ICO")
    sizes = set()
    for i in range(count):
        w, h, _, _, _, _, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        if offset + size > len(data):
            raise AssertionError(f"{path}: entry {i} runs past the end of the file")
        blob = data[offset:offset + size]
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", blob[16:24])
        sizes.add((w or 256, h or 256))
    return sizes


class LiveSiteHeadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.head = parse(SITE / "index.html")

    def link(self, rel):
        found = [l for l in self.head.links if rel in (l.get("rel") or "").split()]
        self.assertTrue(found, f'no <link rel="{rel}">')
        return found[0]

    def site_file(self, url):
        """Map an absolute Pages URL to the file in site/ that Pages will serve for it."""
        self.assertTrue(url.startswith(PAGES_URL), f"{url} is not an absolute Pages URL")
        path = SITE / urlsplit(url).path[len(urlsplit(PAGES_URL).path):]
        self.assertTrue(path.is_file(), f"{url} -> {path} does not exist")
        return path

    def test_favicon_is_an_ico_with_16_and_32(self):
        path = SITE / self.link("icon")["href"]
        self.assertTrue(path.is_file(), path)
        self.assertGreaterEqual(ico_sizes(path), {(16, 16), (32, 32)})

    def test_apple_touch_icon_is_180(self):
        path = SITE / self.link("apple-touch-icon")["href"]
        self.assertTrue(path.is_file(), path)
        self.assertEqual(png_size(path), (180, 180))

    def test_share_tags_are_vietnamese_and_absolute(self):
        m = self.head.meta
        for key in ("og:title", "og:description", "og:image", "og:url", "twitter:card", "twitter:image"):
            self.assertTrue(m.get(key), f"missing {key}")
        self.assertEqual(m["twitter:card"], "summary_large_image")
        self.assertEqual(m["og:url"], PAGES_URL)
        self.assertIn("Tin AI", m["og:description"])

    def test_share_image_exists_at_1200_by_630(self):
        m = self.head.meta
        self.assertEqual(m["og:image"], m["twitter:image"])
        path = self.site_file(m["og:image"])
        self.assertEqual(png_size(path), (1200, 630))
        self.assertEqual((m.get("og:image:width"), m.get("og:image:height")), ("1200", "630"))


class BrandKitTest(unittest.TestCase):
    SIZES = {
        "cover-facebook.png": (1640, 624),
        "cover-youtube.png": (2560, 1440),
        "avatar.png": (800, 800),
        "og-default.png": (1200, 630),
        "khung-9x16.png": (1080, 1920),
        "apple-touch-icon.png": (180, 180),
    }

    @classmethod
    def setUpClass(cls):
        cls.page = parse(BRAND / "index.html")

    def test_every_reference_stays_inside_brand(self):
        for ref in self.page.refs:
            if ref.startswith(("#", "data:", "http://", "https://")):
                continue
            target = (BRAND / urlsplit(ref).path).resolve()
            self.assertTrue(target.is_relative_to(BRAND.resolve()), f"{ref} leaves brand/")
            if urlsplit(ref).path:
                self.assertTrue(target.exists(), f"{ref} does not exist")

    def test_tokens_copy_matches_the_live_site(self):
        self.assertEqual((BRAND / "tokens.css").read_bytes(), (SITE / "tokens.css").read_bytes(),
                         "brand/tokens.css drifted: run python brand/build-assets.py")

    def test_upload_files_have_platform_sizes_and_are_offered(self):
        offered = set(self.page.refs)
        for name, size in self.SIZES.items():
            self.assertEqual(png_size(BRAND / "assets" / name), size, name)
            self.assertIn(f"assets/{name}", offered, f"{name} missing from the download list")
        self.assertGreaterEqual(ico_sizes(BRAND / "assets" / "favicon.ico"), {(16, 16), (32, 32)})
        self.assertIn("assets/favicon.ico", offered)

    def test_live_site_copies_match_the_kit(self):
        for kit, site in (("og-default.png", "og-image.png"), ("apple-touch-icon.png", "apple-touch-icon.png"),
                          ("favicon.ico", "favicon.ico")):
            self.assertEqual((BRAND / "assets" / kit).read_bytes(), (SITE / site).read_bytes(), site)

    def test_published_kit_matches_the_source(self):
        sys.path.insert(0, str(BRAND))
        try:
            import publish_kit
        finally:
            sys.path.remove(str(BRAND))
        dest = SITE / "brand"
        self.assertEqual(publish_kit.files(dest), publish_kit.files(BRAND), "site/brand/ file list drifted")
        for name in publish_kit.files(BRAND):
            self.assertEqual((dest / name).read_bytes(), (BRAND / name).read_bytes(),
                             f"site/brand/{name} drifted: run python brand/publish_kit.py")

    def test_published_page_resolves_inside_site_brand(self):
        dest = (SITE / "brand").resolve()
        for ref in parse(dest / "index.html").refs:
            if ref.startswith(("#", "data:", "http://", "https://")):
                continue
            path = urlsplit(ref).path
            if path:
                target = (dest / path).resolve()
                self.assertTrue(target.is_relative_to(dest) and target.exists(), f"{ref} not served from site/brand/")


if __name__ == "__main__":
    unittest.main()
