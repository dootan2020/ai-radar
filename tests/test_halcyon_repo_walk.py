"""Halcyon repo picture: manifest reading and the camera plan (video/halcyon/halcyon_repo_walk.py). No GPU, no network."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_s = importlib.util.spec_from_file_location('halcyon_repo_walk', Path(__file__).resolve().parent.parent / 'video' / 'halcyon' / 'halcyon_repo_walk.py')
rw = importlib.util.module_from_spec(_s)
_s.loader.exec_module(rw)

WW, HH_FOOT, HH_HOOK = 763, 850, 502


def rows(prefix, n, x=338, y0=375):
    return [dict(path=f'{prefix}{i}', rect=[x, y0 + 41 * i, 925, 41], name_rect=[x + 42, y0 + 12 + 41 * i, 70, 19], font_px=14) for i in range(n)]


def make_manifest(tmp):
    for n in ('0.png', '1.png', '2.png'):
        (tmp / n).write_bytes(b'png')
    home_rows = [dict(path='apps', rect=[33, 608, 902, 41], name_rect=[75, 620, 30, 19], font_px=14), dict(path='docs', rect=[33, 731, 902, 41], name_rect=[75, 743, 30, 19], font_px=14)]
    pg = {
        '': dict(picture='0.png', type='home', css_height=14729, rows=home_rows, boxes=dict(file_list=[32, 363, 904, 1353], about=None), row_font_px=14, background='rgb(255, 255, 255)'),
        'apps': dict(picture='1.png', type='tree', css_height=1572, rows=[dict(path='apps', rect=[338, 335, 925, 40])] + rows('apps/x', 14), boxes=dict(file_list=[337, 294, 927, 1230]), row_font_px=14),
        'docs': dict(picture='1.png', type='tree', css_height=1572, rows=[], boxes=dict(file_list=[337, 294, 927, 1230]), row_font_px=14),
        'apps/x5': dict(picture='2.png', type='blob', css_height=5539, rows=[], boxes=dict(readme=[370, 372, 861, 5086], code=None), row_font_px=None),
    }
    d = dict(version=1, viewport=dict(width=1280, height=800), scale=2, pages=[dict(path=k, **v) for k, v in pg.items()])
    (tmp / 'quay.json').write_text(json.dumps(d), encoding='utf-8')
    return rw.load_manifest(tmp / 'quay.json')


class RepoWalk(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.man = make_manifest(Path(self._t.name))
        self.walk = [dict(page='', a=0.0), dict(page='apps', a=8.0), dict(page='apps/x5', a=14.0)]

    def plan(self, walk=None, f0=0, f1=22 * 30, hh=HH_FOOT, **kw):
        return rw.plan_walk(self.man, walk or self.walk, f0, f1, hh, WW, **kw)

    def test_manifest_skips_parent_row_and_reads_bg(self):
        self.assertEqual(self.man['bg'], (255, 255, 255))
        self.assertNotIn('..', [r['path'] for r in self.man['pages']['apps']['rows']])

    def test_plan_tiles_the_beat_and_holds_are_readable(self):
        p = self.plan()
        segs = p['segments']
        self.assertEqual([(s['s'], s['e']) for s in segs], [(0, 240), (240, 420), (420, 660)])
        for h in p['holds']:
            if h['kind'] != 'overview':
                self.assertGreaterEqual(h['text_frame_px'], rw.PX_MIN - 0.05, h)

    def test_speed_caps_hold_and_are_reported(self):
        for hh in (HH_FOOT, HH_HOOK):
            p = self.plan(hh=hh, default_overview=1.0 if hh == HH_HOOK else 0.0)
            self.assertLessEqual(p['max_pan_px_per_frame'], p['pan_cap_px_per_frame'])
            self.assertLessEqual(p['max_zoom_per_frame'], p['zoom_cap_per_frame'])
            self.assertGreater(p['max_pan_px_per_frame'], 0)

    def test_camera_is_still_for_the_pointer_lead_and_a_pure_function_of_the_frame(self):
        p = self.plan()
        for sg in p['segments'][:-1]:
            a = rw.cam_at(sg, sg['e'] - rw.LEAD); b = rw.cam_at(sg, sg['e'] - 1)
            self.assertEqual(a, b)
            self.assertEqual(rw.cam_at(sg, sg['e'] - 5), rw.cam_at(sg, sg['e'] - 5))
            ptr, hover, press = rw.pointer_at(sg, sg['e'] - 1)
            self.assertIsNotNone(ptr); self.assertEqual(press, 1.0)
            self.assertIsNone(rw.pointer_at(sg, sg['e'] - rw.LEAD - 1)[0])
            x, y = sg['ptr']['p1']
            self.assertTrue(0 <= x <= WW and 0 <= y <= HH_FOOT)

    def test_zoom_from_the_overview_keeps_the_crop_on_the_top_of_the_page(self):
        p = self.plan(default_overview=1.0)
        sg = p['segments'][0]
        (fa, fb, _, _), = sg['tweens'][:1]
        for f in range(fa, fb + 1):
            cx, cy, cw = rw.cam_at(sg, f)
            self.assertAlmostEqual(cy - cw * sg['ratio'] / 2, 0.0, places=6)

    def test_walk_without_a_camera_field_and_with_tap_via_plans(self):
        p = self.plan([dict(page='', a=0.0), dict(page='apps', a=8.0, via='tap'), dict(page='apps/x5', a=14.0, via='tap')])
        self.assertEqual([s['via'] for s in p['segments']], [None, 'click', 'click'])

    def test_last_page_reads_downwards_and_stops_at_the_page_end(self):
        p = self.plan(f1=40 * 30)
        last = p['segments'][-1]
        c0, c1, c2 = rw.cam_at(last, last['read']['f0']), rw.cam_at(last, last['read']['f0'] + 60), rw.cam_at(last, last['e'] - 1)
        self.assertLess(c0[1], c1[1])
        self.assertLessEqual(c2[1], last['read']['cy_max'] + 1e-9)

    def test_overview_only_on_the_first_step_and_at_most_1_2_seconds(self):
        p = self.plan(default_overview=1.0)
        self.assertEqual(p['segments'][0]['cam0'][2], 1280)
        self.assertNotEqual(p['segments'][1]['cam0'][2], 1280)
        with self.assertRaisesRegex(SystemExit, '1.2 s'):
            self.plan([dict(page='', a=0, camera=dict(overview=1.5)), dict(page='apps', a=9.0)])

    def test_refuses_text_under_22_frame_px(self):
        with self.assertRaisesRegex(SystemExit, 'small: .*floor 22'):
            self.plan([dict(page='', a=0, camera=dict(width=900)), dict(page='apps', a=9.0)])

    def test_refuses_a_row_that_is_not_on_the_page(self):
        with self.assertRaisesRegex(SystemExit, 'has no row for "docs"'):
            self.plan([dict(page='apps', a=0), dict(page='docs', a=8.0)])
        with self.assertRaisesRegex(SystemExit, 'is not in the manifest'):
            self.plan([dict(page='apps', a=0), dict(page='nothing', a=8.0)])

    def test_refuses_a_step_too_short_for_its_pan_and_names_the_seconds(self):
        with self.assertRaisesRegex(SystemExit, r'the camera needs \d+\.\d+ s'):
            self.plan([dict(page='', a=0), dict(page='apps', a=1.5), dict(page='apps/x5', a=14.0)])

    def test_back_restores_the_camera_the_page_was_left_on(self):
        walk = [dict(page='apps', a=0.0), dict(page='apps/x5', a=6.0), dict(page='apps', a=11.0, via='back')]
        p = self.plan(walk, f1=16 * 30)
        first, again = p['segments'][0], p['segments'][2]
        self.assertEqual(again['cam0'], rw.cam_at(first, first['e'] - 1))
        self.assertEqual(again['via'], 'back')


if __name__ == '__main__':
    unittest.main()
