"""Checks for the site root (flat feed) page head, CSP, SEO, and carried-over elements."""

import base64
import hashlib
from pathlib import Path
from radar.site_config import SITE_URL
import re
import unittest

from radar.site_config import SITE_URL

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def read(path):
    return Path(path).read_text(encoding="utf-8")


def csp_directives(html):
    match = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    if not match:
        return {}
    directives = {}
    for part in match.group(1).split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        directives[tokens[0]] = tokens[1:]
    return directives


class RootPageHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read(SITE / "index.html")
        cls.head = cls.html.split("</head>")[0]
        cls.csp = csp_directives(cls.html)

    def test_inline_script_is_allowed_by_its_hash(self):
        scripts = re.findall(r"<script>([\s\S]*?)</script>", self.html)
        self.assertEqual(len(scripts), 1, "one inline script, the theme-before-paint one")
        self.assertNotIn("\n", scripts[0])
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"'sha256-{digest}'", self.csp["script-src"])
        self.assertNotIn("'unsafe-inline'", self.csp["script-src"])
        self.assertLess(self.html.find("localStorage.getItem('air2:theme')"), self.html.find('<link rel="stylesheet"'))

    def test_policy_is_closed_by_default(self):
        self.assertEqual(self.csp["default-src"], ["'self'"])
        self.assertEqual(self.csp["object-src"], ["'none'"])
        self.assertEqual(self.csp["base-uri"], ["'self'"])
        self.assertEqual(self.csp["font-src"], ["'self'"])
        self.assertEqual(self.csp["form-action"], ["'none'"])
        self.assertIn("https:", self.csp["img-src"])
        self.assertTrue(re.search(r'<meta http-equiv="Content-Security-Policy" content="[^"]+;">', self.html))

    def test_analytics_is_the_one_beacon_cloudflare_injects(self):
        # Coordinator, 11/11: hco.news ran two beacons (this page's snippet and the one Cloudflare injects), so every view
        # was counted on two analytics sites. Only the injected one stays: no snippet here, its path in the policy.
        scripts = re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>", self.html)
        self.assertEqual([a for a, _ in scripts if "cloudflareinsights.com" in a], [])
        self.assertNotIn("data-cf-beacon", self.html)
        self.assertEqual([s for s in self.csp["script-src"] if "cloudflareinsights" in s],
                         ["https://static.cloudflareinsights.com/beacon.min.js/"])
        self.assertIn("https://cloudflareinsights.com", self.csp["connect-src"])

    def test_snapshot_preload_is_the_window_file(self):
        # The first screen draws from the window file; feed.js loads radar-ui.json after it (tests/test_feed_first_load.py).
        self.assertIn('<link rel="preload" href="data/radar-window.json" as="fetch" crossorigin>', self.head)
        self.assertNotIn('href="data/radar-ui.json"', self.head)

    def test_canonical_and_seo_elements(self):
        self.assertIn(f'<link rel="canonical" href="{SITE_URL}">', self.head)
        self.assertIn('<meta name="referrer" content="strict-origin-when-cross-origin">', self.head)
        self.assertIn('<meta property="og:site_name" content="Halcyon">', self.head)
        self.assertIn('<meta property="og:type" content="website">', self.head)
        self.assertIn(f'<meta property="og:url" content="{SITE_URL}">', self.head)
        self.assertIn(f'<meta property="og:image" content="{SITE_URL}og-image.png">', self.head)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', self.head)
        # Root page is indexed
        self.assertNotIn('<meta name="robots" content="noindex">', self.head)


    def test_retired_pages_land_on_the_home(self):
        # Captain, 09/11 13:16: scrolling replaced the bento home and the feed prototype's address. Pages answers their
        # old addresses with a redirect to the home; the search page's forwarder stays, as it carries ?q= into the search.
        for page in ("bento.html", "feed.html", "app.js"):
            self.assertFalse((SITE / page).exists(), page)
        rules = [line.split() for line in read(SITE / "_redirects").splitlines() if line.strip() and not line.startswith("#")]
        self.assertEqual(rules, [["/bento.html", "/", "301"], ["/bento", "/", "301"],
                                 ["/feed.html", "/", "301"], ["/feed", "/", "301"]])
        self.assertIn("location.replace('./' + (q ? '?q=' + encodeURIComponent(q) : '#tim'))", read(SITE / "tra-cuu.html"))

    def test_carried_features_in_root_html(self):
        # Search entry point: the news bar's inline search (captain, 07/11), no separate page
        self.assertIn('id="news-search"', self.html)
        self.assertIn('<input id="ns-q" type="search"', self.html)
        self.assertNotIn('tra-cuu.html', self.html)
        # Daily edition link
        self.assertRegex(self.html, r'<a\s+class="ed-link"\s+href="ban-tin\.html"\s+aria-label="Bản tin sáng"><span class="ed-label">')
        self.assertIn('<span class="ed-label">Bản tin sáng</span>', self.html)
        # Theme button
        self.assertIn('id="theme-btn"', self.html)
        # New items marker
        self.assertIn('id="fresh"', self.html)
        self.assertIn('id="fresh-go"', self.html)
        self.assertIn('id="fresh-announcement"', self.html)
        # Sort switch
        self.assertIn('id="sort-switch"', self.html)
        self.assertIn('data-sort="worth"', self.html)
        self.assertIn('data-sort="new"', self.html)
        # Sections
        self.assertIn('id="feed-sentinel"', self.html)
        self.assertIn('id="feed-grid"', self.html)
        self.assertNotIn('<footer', self.html)
        self.assertNotIn('src-link', self.html)
        nguon_html = read(SITE / "nguon.html")
        self.assertIn('id="nguon"', nguon_html)
        # Shortcuts dialog
        self.assertIn('id="keys"', self.html)


if __name__ == "__main__":
    unittest.main()
