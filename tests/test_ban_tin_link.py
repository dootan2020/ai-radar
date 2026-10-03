"""The home page leads to the daily edition page in one tap, on a phone and on a desktop.

The link is static HTML in the top bar, outside #nav (hidden under 1100px) and outside the five bottom tabs,
so it needs no JavaScript, never shifts the layout, and is visible at every width.
"""

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
VOID = {"meta", "link", "br", "img", "input", "hr"}


class BarLinks(HTMLParser):
    """Collects every <a> inside <header id="bar">, with the ids of the elements that enclose it."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        a = dict(attrs)
        self.stack.append((tag, a.get("id")))
        if tag == "a" and ("header", "bar") in self.stack:
            self.links.append({"attrs": a, "inside": [i for _, i in self.stack if i], "text": ""})

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k][0] == tag:
                del self.stack[k:]
                break

    def handle_data(self, data):
        if self.links and any(t == "a" for t, _ in self.stack):
            self.links[-1]["text"] += data


class HomeLinksToEdition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (SITE / "styles.css").read_text(encoding="utf-8")
        parsed = BarLinks()
        parsed.feed((SITE / "index.html").read_text(encoding="utf-8"))
        cls.found = [l for l in parsed.links if l["attrs"].get("href") == "ban-tin.html"]

    def test_top_bar_renders_a_ban_tin_link_to_the_edition_page(self):
        self.assertEqual(len(self.found), 1, "exactly one link from the top bar to ban-tin.html")
        self.assertEqual(self.found[0]["text"].strip(), "Bản tin sáng")
        self.assertTrue((SITE / "ban-tin.html").is_file(), "link target exists")

    def test_link_sits_outside_the_parts_that_disappear_on_a_phone(self):
        # #nav is display:none under 1100px and the bottom tabs are a fixed set of five.
        self.assertNotIn("nav", self.found[0]["inside"])
        self.assertNotIn("tabs", self.found[0]["inside"])
        self.assertEqual(self.found[0]["attrs"].get("class"), "ed-link")

    def test_link_is_never_hidden_by_the_stylesheet(self):
        rules = re.findall(r"\.ed-link[^{]*\{[^}]*\}", self.css)
        self.assertTrue(rules, "the link has its own style")
        for rule in rules:
            self.assertNotRegex(rule, r"display\s*:\s*none", rule)
            self.assertNotRegex(rule, r"visibility\s*:\s*hidden", rule)

    def test_link_is_neutral_because_blue_is_for_action_and_selection(self):
        rule = re.search(r"\.ed-link\{[^}]*\}", self.css).group(0)
        self.assertNotIn("--color-accent", rule)


if __name__ == "__main__":
    unittest.main()
