"""The built front page names every script and stylesheet by its content, so a deploy reaches a returning phone.

The host lets a browser keep /feed.js and the stylesheets for four hours (cache-control max-age=14400, measured on
hco.news 11/11) while / is asked for on every load; the captain's phone missed the "Sự kiện" page the morning after it
shipped. The build (radar/site_payload.py -> radar/front_lead.py update_index_lead) stamps index.html: every local
script and stylesheet carries ?v=<hash of the file>, and an import map, allowed by its hash in the page's policy, gives
the modules those scripts import the same versions. tests/capture-mobile-sap-xep.mjs --site <a built copy> loads such a
page in Chrome and lists every address it asked for.
"""
import base64
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from radar import front_lead

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
REF = re.compile(r'<(?:script|link)\b[^>]*?\b(?:src|href)="([^"]+\.(?:js|css)(?:\?[^"]*)?)"')


def content_version(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:front_lead.VERSION_LEN]


def built_site():
    """A copy of site/'s top-level files whose index.html went through the build's writer."""
    tmp = Path(tempfile.mkdtemp(prefix="asset-versions-"))
    for path in SITE.iterdir():
        if path.is_file():
            shutil.copy2(path, tmp / path.name)
    front_lead.reset_index_lead(tmp / "index.html")
    return tmp


def load_sync():
    spec = importlib.util.spec_from_file_location("sync_site_versions", ROOT / "extension" / "sync-site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuiltPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = built_site()
        cls.html = (cls.site / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.site, ignore_errors=True)

    def test_every_script_and_stylesheet_carries_its_content_version(self):
        refs = [r for r in REF.findall(self.html) if "://" not in r]
        self.assertGreaterEqual(len(refs), 20)
        for ref in refs:
            name, _, query = ref.partition("?")
            with self.subTest(ref=ref):
                self.assertEqual(query, f"v={content_version(self.site / name)}")
        for name in ("feed.js", "nen.js", "thanh-tren.js", "menu-cong-cu.js", "tokens.css", "feed.css", "trang-msn.css"):
            self.assertIn(f"{name}?v={content_version(self.site / name)}", self.html)

    def test_a_changed_file_gets_a_new_address(self):
        before = re.search(r'src="feed\.js\?v=([0-9a-f]+)"', self.html).group(1)
        original = (self.site / "feed.js").read_bytes()
        with (self.site / "feed.js").open("ab") as stream:
            stream.write(b"\n// changed\n")
        try:
            front_lead.reset_index_lead(self.site / "index.html")
            after = (self.site / "index.html").read_text(encoding="utf-8")
            self.assertNotEqual(re.search(r'src="feed\.js\?v=([0-9a-f]+)"', after).group(1), before)
            self.assertIn(f'"./feed.js":"./feed.js?v={content_version(self.site / "feed.js")}"', after)
            # Nothing else moved, and the old map's hash left the policy.
            self.assertIn(re.search(r'href="feed\.css\?v=[0-9a-f]+"', self.html).group(0), after)
            self.assertEqual(after.count("'sha256-"), 2)
        finally:
            (self.site / "feed.js").write_bytes(original)
            (self.site / "index.html").write_text(self.html, encoding="utf-8", newline="\n")

    def test_the_import_map_versions_every_module_and_late_stylesheet(self):
        block = re.search(r'<script type="importmap">(.*?)</script>', self.html, re.S)
        self.assertIsNotNone(block)
        imports = json.loads(block.group(1))["imports"]
        for name in ("faces.js", "time-text.js", "lich-am.js", "story.js", "live.js", "arena.css", "story.css"):
            self.assertEqual(imports[f"./{name}"], f"./{name}?v={content_version(self.site / name)}", name)
        # The map comes before any module or module preload, or a browser would not apply it to them.
        first_module = min(self.html.index('type="module"'), self.html.index('rel="modulepreload"'))
        self.assertLess(block.start(), first_module)
        feed = (SITE / "feed.js").read_text(encoding="utf-8")
        self.assertIn("import.meta.resolve(`./${name}`)", feed)
        self.assertIn("link.href = versioned(href);", feed)

    def test_the_policy_allows_each_inline_script_by_hash_and_nothing_more(self):
        policy = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', self.html).group(1)
        script_src = re.search(r"script-src ([^;]+);", policy).group(1).split()
        inline = re.findall(r"<script(?: type=\"importmap\")?>(.*?)</script>", self.html, re.S)
        self.assertEqual(len(inline), 2)
        hashes = ["'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'" for s in inline]
        self.assertEqual(sorted(h for h in script_src if h.startswith("'sha256-")), sorted(hashes))
        self.assertNotIn("'unsafe-inline'", script_src)
        committed = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertEqual(policy.replace(" " + hashes[1], ""),
                         re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', committed).group(1))

    def test_stamping_twice_changes_nothing(self):
        self.assertEqual(front_lead.stamp_assets(self.html, self.site), self.html)

    def test_the_committed_page_stays_plain(self):
        committed = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("?v=", re.sub(r"<!--.*?-->", "", committed, flags=re.S))
        self.assertIn(front_lead.ASSETS_OPEN + front_lead.ASSETS_CLOSE, committed)


class ExtensionCopy(unittest.TestCase):
    def test_the_new_tab_carries_no_versions_and_still_validates(self):
        sync = load_sync()
        site = built_site()
        try:
            built = (site / "index.html").read_text(encoding="utf-8")
        finally:
            shutil.rmtree(site, ignore_errors=True)
        plain = (SITE / "index.html").read_text(encoding="utf-8")
        from_built, from_plain = sync.adapt_html(built), sync.adapt_html(plain)
        self.assertEqual(from_built, from_plain)
        newtab = (ROOT / "extension" / "newtab.html").read_text(encoding="utf-8")
        for html in (from_built, newtab):
            sync.validate_html(html)
            self.assertNotIn("?v=", html)
            self.assertNotIn("importmap", html)
            self.assertNotIn("asset versions", html)
            self.assertIn('<script type="module" src="feed.js"></script>', html)


if __name__ == "__main__":
    unittest.main()
