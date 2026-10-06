"""Tests for the redesigned new items notice ("N tin mới") on the feed page."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def read(path):
    return Path(path).read_text(encoding="utf-8")


class NewItemsNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read(SITE / "index.html")
        cls.css = read(SITE / "feed.css")
        cls.tokens = read(SITE / "tokens.css")

    def test_markup_structure_and_accessibility(self):
        # Notice container is present and hidden by default
        self.assertIn('class="new-items" id="moi" hidden', self.html)
        # Jump button with keyboard shortcut U and icon
        self.assertIn('id="new-go" aria-keyshortcuts="U"', self.html)
        self.assertIn('<span id="new-items-text"></span>', self.html)
        self.assertIn('<use href="#i-down"/>', self.html)
        # Separator dot
        self.assertIn('class="new-sep', self.html)
        self.assertIn('aria-hidden="true"', self.html)
        # Mark seen button with shortcut M and class mark-seen-btn
        self.assertIn('id="mark-seen-btn" aria-keyshortcuts="M"', self.html)
        self.assertIn('class="text-btn mark-seen-btn"', self.html)

    def test_css_uses_quiet_editorial_tokens_no_capsule(self):
        # Direction 1: Subtle Editorial Inline. No box, no tinted capsule, quiet ink colours.
        notice_match = re.search(r"\.new-items\s*\{([^}]+)\}", self.css)
        self.assertIsNotNone(notice_match, "Missing .new-items CSS rule")
        notice_body = notice_match.group(1)
        self.assertIn("var(--color-ink-2)", notice_body)
        self.assertIn("flex-basis: 100%", notice_body)
        self.assertNotIn("var(--color-accent-wash)", notice_body)
        self.assertNotIn("var(--color-fill)", notice_body)

        # Separator dot styling
        self.assertIn(".new-sep", self.css)
        self.assertIn("var(--color-ink-3)", self.css)

        # Mark seen button styling with hairline underline
        self.assertIn(".new-items .mark-seen-btn", self.css)
        self.assertIn("var(--color-ink-3)", self.css)
        self.assertIn("var(--color-hair)", self.css)

        # New go button styling with accent icon
        self.assertIn(".new-go", self.css)
        self.assertIn("var(--color-accent)", self.css)

    def test_responsive_mobile_adaptation(self):
        # Mobile rule under 480px stacks notice cleanly and hides separator dot
        self.assertIn("@media (max-width: 480px)", self.css)
        mobile_match = re.search(r"@media\s*\(max-width:\s*480px\)\s*\{([\s\S]*?)\n\}", self.css)
        self.assertIsNotNone(mobile_match, "Missing @media (max-width: 480px) query in feed.css")
        mobile_css = mobile_match.group(1)
        self.assertIn("flex-direction: column", mobile_css)
        self.assertIn(".new-items .new-sep", mobile_css)
        self.assertIn("display: none", mobile_css)


if __name__ == "__main__":
    unittest.main()
