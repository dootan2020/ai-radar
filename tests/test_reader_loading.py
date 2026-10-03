"""Offline reader startup regressions, discovered alongside Python tests."""

from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReaderLoadingTests(unittest.TestCase):
    def test_static_fallback_survives_missing_javascript(self):
        html = (ROOT / 'site/index.html').read_text(encoding='utf-8')
        css = (ROOT / 'site/styles.css').read_text(encoding='utf-8')
        fallback = re.search(r'<div class="[^"]*reader-fallback[^"]*"[^>]*>(.*?)</div>', html, re.S)
        self.assertIsNotNone(fallback, 'module failure leaves no visible fallback')
        self.assertIn('Đang mở bản tin', fallback.group(1))
        self.assertRegex(fallback.group(1), r'<a\b[^>]*href=""[^>]*>Tải lại trang</a>')
        self.assertRegex(fallback.group(1), r'<noscript>.*?JavaScript.*?</noscript>')
        rules = re.search(r'\.board\.is-loading\s+\.reader-fallback\s*\{([^}]+)\}', css)
        self.assertIsNotNone(rules)
        self.assertRegex(rules.group(1), r'visibility\s*:\s*visible')
        self.assertRegex(rules.group(1), r'position\s*:\s*absolute')

    @unittest.skipUnless(shutil.which('node'), 'Node required for reader behavior tests')
    def test_deadlines_fallback_and_error_rendering(self):
        result = subprocess.run(['node', str(ROOT / 'tests/verify-reader-loading.mjs')],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
