"""Sitemap metadata belongs to the accepted data, never the wall clock."""

from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from radar.seo import SITE_URL, sitemap_xml, write_sitemap


class SitemapTests(unittest.TestCase):
    def test_only_canonical_homepage_and_original_timestamp_are_indexed(self):
        root = ET.fromstring(sitemap_xml("2026-10-01T10:00:00+07:00"))
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        entries = root.findall("s:url", ns)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].find("s:loc", ns).text, SITE_URL)
        self.assertEqual(entries[0].find("s:lastmod", ns).text, "2026-10-01T03:00:00Z")

    def test_invalid_timestamp_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sitemap.xml"
            path.write_bytes(b"old sitemap")
            for stamp in (None, "", "2026-10-01"):
                with self.assertRaises(ValueError):
                    write_sitemap(stamp, path)
                self.assertEqual(path.read_bytes(), b"old sitemap")

    def test_atomic_write_has_no_leftover_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "sitemap.xml"
            write_sitemap("2026-10-01T03:00:00Z", path)
            self.assertEqual(path.read_bytes(), sitemap_xml("2026-10-01T03:00:00Z"))
            self.assertEqual(list(path.parent.iterdir()), [path])
