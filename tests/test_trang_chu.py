"""Checks for the site root (flat feed) page head, CSP, SEO, and carried-over elements."""

import base64
import hashlib
import json
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
        cls.bento_html = read(SITE / "bento.html")
        cls.feed_redirect = read(SITE / "feed.html")

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

    def test_reader_has_one_cloudflare_module_after_the_policy(self):
        scripts = re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>", self.html)
        beacons = [(attrs, body) for attrs, body in scripts if "cloudflareinsights.com" in attrs]
        self.assertEqual(len(beacons), 1)
        attrs, body = beacons[0]
        self.assertIn("type='module'", attrs)
        self.assertIn("src='https://static.cloudflareinsights.com/beacon.min.js'", attrs)
        config = json.loads(re.search(r"data-cf-beacon='([^']+)'", attrs).group(1))
        self.assertEqual(set(config), {"token"})
        self.assertRegex(config["token"], r"^[a-f0-9]{32}$")
        self.assertEqual(hashlib.sha256(config["token"].encode()).hexdigest(),
                         "ac50ff27adef59eaf1754c2f483debe1e7045b503e0486ea84015ad83590749f")
        self.assertEqual(body, "")
        self.assertIn(attrs, self.head)
        self.assertLess(self.head.index('http-equiv="Content-Security-Policy"'), self.head.index(attrs))
        self.assertLess(self.head.index('src="feed.js"'), self.head.index(attrs))
        self.assertLess(self.head.rindex('rel="modulepreload"'), self.head.index(attrs))

    def test_snapshot_preload_is_radar_ui(self):
        self.assertIn('<link rel="preload" href="data/radar-ui.json" as="fetch" crossorigin>', self.head)

    def test_canonical_and_seo_elements(self):
        self.assertIn(f'<link rel="canonical" href="{SITE_URL}">', self.head)
        self.assertIn('<meta name="referrer" content="strict-origin-when-cross-origin">', self.head)
        self.assertIn('<meta property="og:site_name" content="ai·radar">', self.head)
        self.assertIn('<meta property="og:type" content="website">', self.head)
        self.assertIn(f'<meta property="og:url" content="{SITE_URL}">', self.head)
        self.assertIn(f'<meta property="og:image" content="{SITE_URL}og-image.png">', self.head)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', self.head)
        # Root page is indexed
        self.assertNotIn('<meta name="robots" content="noindex">', self.head)

    def test_rollback_bento_is_not_indexed(self):
        self.assertIn('<meta name="robots" content="noindex">', self.bento_html)
        self.assertIn(f'<link rel="canonical" href="{SITE_URL}">', self.bento_html)

    def test_feed_redirect_is_not_indexed(self):
        self.assertIn('<meta name="robots" content="noindex">', self.feed_redirect)
        self.assertIn('<meta http-equiv="refresh" content="0; url=./">', self.feed_redirect)
        self.assertIn(f'<link rel="canonical" href="{SITE_URL}">', self.feed_redirect)

    def test_carried_features_in_root_html(self):
        # Search entry point
        self.assertRegex(self.html, r'<a\s+class="tc-link"\s+href="tra-cuu\.html"')
        # Daily edition link
        self.assertRegex(self.html, r'<a\s+class="ed-link"\s+href="ban-tin\.html">Bản tin sáng</a>')
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
        self.assertIn('id="picks"', self.html)
        self.assertIn('id="feed-grid"', self.html)
        self.assertIn('id="nguon"', self.html)
        # Shortcuts dialog
        self.assertIn('id="keys"', self.html)


if __name__ == "__main__":
    unittest.main()
