"""Contracts for Chrome Web Store submission deliverables and store package."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'extension'
STORE = EXT / 'store'
SITE = ROOT / 'site'
PLANS = ROOT / 'plans/reports'
LIVE = 'https://radar-ai-vn.pages.dev/'


class ChromeStoreSubmissionTests(unittest.TestCase):
    def test_all_store_files_exist(self):
        expected_files = [
            STORE / 'listing-vi.md',
            STORE / 'listing-en.md',
            STORE / 'single-purpose.txt',
            STORE / 'permissions.md',
            STORE / 'data-disclosure.md',
            STORE / 'build-zip.py',
            STORE / 'SUBMIT.md',
            PLANS / 'tien-do-chrome-store.md',
            SITE / 'chinh-sach-rieng-tu.html',
        ]
        for path in expected_files:
            self.assertTrue(path.is_file(), f'Missing required store file: {path}')

    def test_listing_descriptions_and_metadata(self):
        vi_listing = (STORE / 'listing-vi.md').read_text(encoding='utf-8')
        en_listing = (STORE / 'listing-en.md').read_text(encoding='utf-8')

        # Check name
        self.assertIn('Halcyon', vi_listing)
        self.assertIn('Halcyon', en_listing)

        # Check short descriptions length <= 132 chars
        # VI short description
        vi_match = re.search(r'## Mô tả ngắn[^\n]*\n[^\n]*\n```[^\n]*\n([^\n]+)\n```', vi_listing)
        self.assertIsNotNone(vi_match, "Could not find VI short description in codeblock")
        vi_short = vi_match.group(1).strip()
        self.assertLessEqual(len(vi_short), 132, f"VI short description too long: {len(vi_short)}")
        self.assertGreater(len(vi_short), 20)

        # EN short description
        en_match = re.search(r'## Summary / Short Description[^\n]*\n[^\n]*\n```[^\n]*\n([^\n]+)\n```', en_listing)
        self.assertIsNotNone(en_match, "Could not find EN short description in codeblock")
        en_short = en_match.group(1).strip()
        self.assertLessEqual(len(en_short), 132, f"EN short description too long: {len(en_short)}")
        self.assertGreater(len(en_short), 20)

        # Category
        self.assertIn('News & Weather', vi_listing)
        self.assertIn('News & Weather', en_listing)

    def test_single_purpose_and_permissions_justifications(self):
        single = (STORE / 'single-purpose.txt').read_text(encoding='utf-8').strip()
        self.assertGreater(len(single), 50)
        self.assertIn('new tab', single.lower())

        perms = (STORE / 'permissions.md').read_text(encoding='utf-8')
        manifest = json.loads((EXT / 'manifest.json').read_text(encoding='utf-8'))
        for perm in manifest['permissions']:
            self.assertIn(f'`{perm}`', perms, f"Missing justification for permission: {perm}")
        for host in manifest['host_permissions']:
            self.assertIn(host, perms, f"Missing justification for host: {host}")

    def test_data_disclosure_and_three_certifications(self):
        disclosure = (STORE / 'data-disclosure.md').read_text(encoding='utf-8')
        self.assertIn('not sell user data', disclosure.lower())
        self.assertIn('not use or transfer user data for purposes that are unrelated', disclosure.lower())
        self.assertIn('not use or transfer user data to determine creditworthiness', disclosure.lower())
        self.assertIn(LIVE + 'chinh-sach-rieng-tu.html', disclosure)

    def test_privacy_policy_page_structure_and_links(self):
        html = (SITE / 'chinh-sach-rieng-tu.html').read_text(encoding='utf-8')
        self.assertIn('<!doctype html>', html.lower())
        self.assertIn('tieng-viet', html)
        self.assertIn('english', html)
        self.assertIn('storage', html)
        self.assertIn('alarms', html)
        self.assertIn('search', html)
        self.assertIn('https://radar-ai-vn.pages.dev/', html)
        # Must not contain stale host
        self.assertNotIn('ai-radar' + '.pages.dev', html)

    def test_privacy_policy_discloses_every_external_host_in_extension_sources(self):
        html = (SITE / 'chinh-sach-rieng-tu.html').read_text(encoding='utf-8').lower()
        external_hosts = set()
        for source in (*EXT.glob('*.js'), *EXT.glob('*.html')):
            contents = source.read_text(encoding='utf-8')
            external_hosts.update(
                match.group(1).lower()
                for match in re.finditer(r'https?://([a-z0-9.-]+)', contents, re.IGNORECASE)
            )
        for host in sorted(external_hosts):
            with self.subTest(host=host):
                self.assertIn(host, html, f'Privacy policy does not disclose extension host: {host}')

    def test_build_zip_execution_and_contents(self):
        result = subprocess.run(
            [sys.executable, str(STORE / 'build-zip.py')],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
        )
        self.assertEqual(result.returncode, 0, f"build-zip.py failed:\n{result.stderr}")
        self.assertIn('Built extension-halcyon-', result.stdout)
        self.assertIn('Files in zip', result.stdout)

        manifest = json.loads((EXT / 'manifest.json').read_text(encoding='utf-8'))
        zip_file = STORE / f"extension-halcyon-{manifest['version']}.zip"
        self.assertTrue(zip_file.is_file())
        self.assertGreater(zip_file.stat().st_size, 50000)

        with zipfile.ZipFile(zip_file, 'r') as zf:
            namelist = set(zf.namelist())
            # Crucial required files
            self.assertIn('manifest.json', namelist)
            self.assertIn('background.js', namelist)
            self.assertIn('newtab.html', namelist)
            self.assertIn('newtab.js', namelist)
            self.assertIn('icons/128.png', namelist)
            self.assertIn('icons/16.png', namelist)
            self.assertIn('icons/32.png', namelist)
            self.assertIn('icons/48.png', namelist)
            self.assertIn('fonts/be-vietnam-pro-400-vietnamese.woff2', namelist)

            # Strictly excluded files
            self.assertNotIn('README.md', namelist)
            self.assertNotIn('sync-site.py', namelist)
            for name in namelist:
                self.assertFalse(name.startswith('store/'), f"Store file leaked into zip: {name}")
                self.assertFalse(name.endswith('.py'), f"Python file leaked into zip: {name}")


if __name__ == '__main__':
    unittest.main()
