"""Publish and site-restore checks: python -m unittest wallpaper/test_publish.py

Uses small local git repositories as the remote; no network, no Blender.
"""
import contextlib
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily  # noqa: E402
import publish  # noqa: E402
import site_restore  # noqa: E402

TODAY = dt.date(2026, 11, 20)


def make_day(out, day, family='silicon-die'):
    png = out / f'halcyon-{day}.png'
    Image.new('RGB', (daily.WIDTH, daily.HEIGHT), (12, 14, 30)).save(png)
    entry = dict(date=day, family=family, png=png.name, width=daily.WIDTH, height=daily.HEIGHT,
                 sha256=daily.sha256(png))
    entry.update(daily.encode_web(png, day))
    return entry


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'out'
        cls.out.mkdir()
        days = [(TODAY + dt.timedelta(days=k)).isoformat() for k in range(-3, 3)]
        cls.manifest = dict(wallpapers=[make_day(cls.out, d) for d in days])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        patcher = mock.patch.object(publish, 'MIN_WEB_BYTES', 0)  # flat test images compress to almost nothing
        patcher.start()
        self.addCleanup(patcher.stop)

    def entries(self):
        return json.loads(json.dumps(self.manifest))  # a fresh copy each test


class VerifyAndPlanTest(Fixture):
    def test_good_entry_passes(self):
        self.assertEqual(publish.verify(self.entries()['wallpapers'][0], self.out), [])

    def test_checksum_mismatch_is_caught(self):
        entry = self.entries()['wallpapers'][0]
        entry['web_sha256'] = '0' * 64
        entry['sha256'] = '1' * 64
        problems = publish.verify(entry, self.out)
        self.assertIn('PNG sha256 differs from manifest', problems)
        self.assertIn('web sha256 differs from manifest', problems)

    def test_missing_web_file_is_caught(self):
        entry = self.entries()['wallpapers'][0]
        entry['web'] = 'halcyon-1999-01-01.avif'
        self.assertIn('web file missing', publish.verify(entry, self.out))

    def test_wrong_size_is_caught(self):
        entry = self.entries()['wallpapers'][0]
        small = self.out / 'small.png'
        Image.new('RGB', (64, 36)).save(small)
        entry.update(png=small.name, sha256=daily.sha256(small))
        self.assertIn('PNG is (64, 36)', publish.verify(entry, self.out))

    def test_old_web_settings_are_refused(self):
        entry = self.entries()['wallpapers'][0]
        entry['web_settings'] = dict(format='WEBP', quality=82)
        self.assertIn('web file not encoded with current settings', publish.verify(entry, self.out))

    def test_window_keeps_recent_days_and_prunes_older_ones(self):
        lich, files = publish.plan(self.entries(), self.out, TODAY, back=1, ahead=2)
        dates = [d['date'] for d in lich['days']]
        self.assertEqual(dates, ['2026-11-19', '2026-11-20', '2026-11-21'])
        self.assertEqual(sorted(files), ['2026-11-19.avif', '2026-11-20.avif', '2026-11-21.avif'])
        self.assertEqual(lich['days'][0], dict(date='2026-11-19', file='2026-11-19.avif', family='silicon-die',
                                               w=2560, h=1440))

    def test_a_missing_future_day_blocks_publishing(self):
        with self.assertRaises(publish.PublishError) as caught:
            publish.plan(self.entries(), self.out, TODAY, back=1, ahead=5)
        self.assertIn('2026-11-23: not rendered', str(caught.exception))

    def test_one_bad_day_blocks_the_whole_set(self):
        manifest = self.entries()
        manifest['wallpapers'][3]['sha256'] = '2' * 64  # 2026-11-20
        with self.assertRaises(publish.PublishError):
            publish.plan(manifest, self.out, TODAY, back=1, ahead=2)


class BranchRoundTripTest(Fixture):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.remote = str(self.root / 'remote.git')
        subprocess.run(['git', 'init', '--quiet', '--bare', self.remote], check=True)

    def publish(self, back, ahead, name):
        lich, files = publish.plan(self.entries(), self.out, TODAY, back=back, ahead=ahead)
        staging = self.root / name
        publish.stage(lich, files, staging)
        return publish.push(staging, self.remote)

    def branch_files(self):
        out = subprocess.run(['git', '--git-dir', self.remote, 'ls-tree', '--name-only', publish.BRANCH],
                             capture_output=True, text=True, check=True).stdout
        return sorted(out.split())

    def restore(self, site):
        with tempfile.TemporaryDirectory() as workdir:
            return site_restore.restore(self.remote, site, workdir)

    def test_missing_branch_leaves_the_site_alone(self):
        site = self.root / 'site' / 'nen'
        self.assertIsNone(self.restore(site))
        self.assertFalse(site.exists())

    def test_publish_then_restore_copies_web_files_and_lich(self):
        self.publish(1, 2, 'first')
        site = self.root / 'site' / 'nen'
        self.assertEqual(self.restore(site), 3)
        self.assertEqual(sorted(p.name for p in site.iterdir()),
                         ['2026-11-19.avif', '2026-11-20.avif', '2026-11-21.avif', 'lich.json'])
        lich = json.loads((site / 'lich.json').read_text(encoding='utf-8'))
        self.assertEqual([d['file'] for d in lich['days']], ['2026-11-19.avif', '2026-11-20.avif', '2026-11-21.avif'])

    def test_republishing_prunes_days_that_left_the_window(self):
        self.publish(3, 3, 'wide')
        self.assertIn('2026-11-17.avif', self.branch_files())
        self.publish(0, 2, 'narrow')
        self.assertEqual(self.branch_files(), ['2026-11-20.avif', '2026-11-21.avif', 'lich.json'])
        log = subprocess.run(['git', '--git-dir', self.remote, 'rev-list', '--count', publish.BRANCH],
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(log, '1')  # one orphan commit, history does not grow

    def test_unexpected_content_falls_back_without_failing_the_build(self):
        staging = self.root / 'evil'
        lich, files = publish.plan(self.entries(), self.out, TODAY, back=0, ahead=1)
        publish.stage(lich, files, staging)
        (staging / 'index.html').write_text('<script></script>', encoding='utf-8')
        publish.push(staging, self.remote)
        site = self.root / 'site' / 'nen'
        with self.assertRaises(site_restore.RestoreError):
            self.restore(site)
        argv = ['site_restore.py', '--remote', self.remote, '--site', str(site)]
        printed = io.StringIO()
        with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(printed):
            self.assertEqual(site_restore.main(), 0)
        self.assertIn('::warning::', printed.getvalue())
        self.assertFalse(site.exists())

    def test_validate_rejects_a_lich_entry_without_its_file(self):
        with self.assertRaises(site_restore.RestoreError):
            site_restore.validate(['lich.json'], json.dumps(dict(days=[dict(
                date='2026-11-20', file='2026-11-20.avif', family='x', w=2560, h=1440)])))


if __name__ == '__main__':
    unittest.main()
