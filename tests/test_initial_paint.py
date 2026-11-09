"""First-screen resource contracts; rendered LCP/CLS are measured separately."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InitialPaintTests(unittest.TestCase):
    def test_head_and_thumbnail_are_preloaded_without_font_blocking(self):
        # Fonts must not choke initial slow-4G bandwidth
        feed_html = (ROOT / 'site/index.html').read_text(encoding='utf-8')
        self.assertIn('<link rel="preload" href="data/radar-window.json" as="fetch" crossorigin>', feed_html)
        self.assertEqual(re.findall(r'<link rel="preload" href="([^"]+)" as="font"', feed_html), [])


if __name__ == '__main__':
    unittest.main()
