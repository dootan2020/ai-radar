"""Real renderer/disclosure regression checks; CSS wiring is not browser geometry proof."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "site/styles.css").read_text(encoding="utf-8")


class LeadPhoneLayoutContractTests(unittest.TestCase):
    def test_desktop_contents_and_phone_disclosure_are_separate(self):
        self.assertRegex(CSS, r"\.lead-details\{display:contents\}")
        self.assertRegex(CSS, r"\.lead-disclosure\{display:none\}")
        phone = CSS[CSS.index('/* Phone lead:'):]
        self.assertIn('@media (max-width: 767px)', phone)
        self.assertIn('.t-lead .lead-details{display:none}', phone)
        self.assertIn('.t-lead.is-expanded .lead-details{display:flex', phone)
        self.assertNotRegex(phone, r"lead-(?:title|sum)[^}]*line-clamp")
        self.assertRegex(phone, r"\.lead-toggle\{[^}]*min-height:var\(--btn-h\)")
        tokens = (ROOT / 'site/tokens.css').read_text(encoding='utf-8')
        self.assertIn('--btn-h: 44px', tokens)


if __name__ == '__main__':
    unittest.main()
