"""Halcyon spec loading, the clip picture's manifest and placement, and the beat flag `captions` (video/halcyon/halcyon_spec.py). No GPU, no network."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_s = importlib.util.spec_from_file_location('halcyon_spec', Path(__file__).resolve().parent.parent / 'video' / 'halcyon' / 'halcyon_spec.py')
hs = importlib.util.module_from_spec(_s)
_s.loader.exec_module(hs)

WIN_FOOT = (364, 1340)           # layout thu-gon-r3-l2: FOOT window y 364-1340
FRAME_W, REC_W, PIC_X0 = 1080, 886, 97


def manifest(**over):
    m = dict(file='clip.mp4', w=762, h=850, fps=30, frames=120, duration=4.0, bg=[16, 24, 40], min_text_px=28, captured='2026-11-21T05:00:00+07:00',
             source='terminal footage of the pip install', date='2026-11-21', tool_sha='abc1234', stills=[dict(t=0.5, label='start'), dict(t=3.5, label='end')],
             segments=[dict(name='pip', a=0, b=4, speed=1, real_s=4.0)], proof=dict(cast_matches_log=True))
    m.update(over)
    return m


def write(tmp, m, name='clip.json', video=True):
    if video:
        (tmp / 'clip.mp4').write_bytes(b'mp4')
    p = tmp / name
    p.write_text(json.dumps(m), encoding='utf-8')
    return p


class ClipManifest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def refused(self, m, text, **kw):
        p = write(self.tmp, m, **kw)
        with self.assertRaises(SystemExit) as cm:
            hs.load_clip_manifest(p, 'beats[3].picture')
        self.assertIn(text, str(cm.exception))

    def test_complete_manifest_loads(self):
        man = hs.load_clip_manifest(write(self.tmp, manifest()))
        self.assertEqual((man['w'], man['h'], man['frames']), (762, 850, 120))
        self.assertEqual(man['video'], (self.tmp / 'clip.mp4').resolve())

    def test_every_provenance_field_is_required(self):
        for k in hs.CLIP_FIELDS:
            m = manifest(); del m[k]
            self.refused(m, f'has no "{k}"')

    def test_a_hand_made_clip_has_no_manifest(self):
        with self.assertRaises(SystemExit) as cm:
            hs.load_clip_manifest(self.tmp / 'missing.json', 'beats[3].picture')
        self.assertIn('does not exist', str(cm.exception))

    def test_empty_provenance_is_refused(self):
        self.refused(manifest(tool_sha='  '), '"tool_sha" must be a non-empty string')
        self.refused(manifest(proof={}), '"proof" must be a non-empty object')

    def test_clip_file_must_exist(self):
        self.refused(manifest(), 'clip file that does not exist', video=False)

    def test_text_floor_is_28_frame_px(self):
        self.refused(manifest(min_text_px=27), 'floor 28')
        hs.load_clip_manifest(write(self.tmp, manifest(min_text_px=28)))

    def test_duration_cap_and_frame_count(self):
        self.refused(manifest(frames=1230, duration=41.0), 'cap is 40 s')
        self.refused(manifest(frames=100, duration=4.0), 'a duration of')

    def test_odd_sizes_are_refused(self):
        self.refused(manifest(w=761), 'must be even')

    def test_bg_and_stills_shape(self):
        self.refused(manifest(bg=[1, 2]), '"bg"')
        self.refused(manifest(stills=[dict(t='x', label='a')]), '"stills"')


class ClipPlan(unittest.TestCase):
    def man(self, **over):
        return dict(manifest(**over), duration=4.0)

    def plan(self, man, **pic):
        return hs.plan_clip(man, dict(start=0, dur=4, **pic), WIN_FOOT, FRAME_W, REC_W, PIC_X0, 'beats[3].picture')

    def test_placed_one_to_one_and_centred(self):
        p = self.plan(self.man())
        self.assertEqual((p['x_at'], p['y_at']), ((1080 - 762) // 2, (364 + 1340) // 2 - 425))
        self.assertGreaterEqual(p['y_at'], WIN_FOOT[0]); self.assertLessEqual(p['y_at'] + 850, WIN_FOOT[1])

    def test_taller_than_window_is_refused_not_scaled(self):
        with self.assertRaises(SystemExit) as cm:
            self.plan(self.man(h=978))
        self.assertIn('never scaled', str(cm.exception))

    def test_wider_than_picture_column_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            self.plan(self.man(w=888))
        self.assertIn('never scaled', str(cm.exception))

    def test_span_must_lie_inside_the_clip(self):
        with self.assertRaises(SystemExit) as cm:
            hs.plan_clip(self.man(), dict(start=3, dur=2), WIN_FOOT, FRAME_W, REC_W, PIC_X0, 'beats[3].picture')
        self.assertIn('runs past the end', str(cm.exception))

    def test_start_and_dur_are_needed(self):
        with self.assertRaises(SystemExit) as cm:
            hs.plan_clip(self.man(), dict(start=0), WIN_FOOT, FRAME_W, REC_W, PIC_X0, 'beats[3].picture')
        self.assertIn('dur is missing', str(cm.exception))


class BeatCaptions(unittest.TestCase):
    def test_default_is_on(self):
        self.assertIs(hs.beat_captions({}, 'beats[1]'), True)

    def test_false_turns_them_off(self):
        self.assertIs(hs.beat_captions({'captions': False}, 'beats[1]'), False)

    def test_only_booleans(self):
        for v in ('false', 0, None, []):
            with self.assertRaises(SystemExit):
                hs.beat_captions({'captions': v}, 'beats[1]')


class EndUnitsAtSilences(unittest.TestCase):
    SIL = [dict(a=10.0, b=16.0)]

    def units(self):
        return [dict(s=4.0, e=9.0, T='A'), dict(s=9.0, e=16.0, T='LAST BEFORE'), dict(s=16.0, e=18.0, T='AFTER')]

    def test_the_last_unit_before_a_span_ends_at_its_start(self):
        u = hs.end_units_at_silences(self.units(), self.SIL)
        self.assertEqual([(x['s'], x['e']) for x in u], [(4.0, 9.0), (9.0, 10.0), (16.0, 18.0)])

    def test_no_silences_changes_nothing(self):
        self.assertEqual(hs.end_units_at_silences(self.units(), []), self.units())

    def test_a_unit_ending_before_or_at_the_start_is_left_alone(self):
        u = [dict(s=4.0, e=10.0, T='A'), dict(s=16.0, e=18.0, T='B')]
        self.assertEqual(hs.end_units_at_silences(u, self.SIL), [dict(s=4.0, e=10.0, T='A'), dict(s=16.0, e=18.0, T='B')])

    def test_a_unit_starting_inside_a_span_is_not_hidden(self):
        u = hs.end_units_at_silences([dict(s=12.0, e=18.0, T='INSIDE')], self.SIL)
        self.assertEqual(u[0]['e'], 18.0)

    def test_spec_carries_silences_and_builder_applies_them(self):
        self.assertIn("S['silences'] = d.get('silences', [])", Path(hs.__file__).read_text(encoding='utf-8'))
        src = (Path(__file__).resolve().parent.parent / 'video' / 'halcyon' / 'dung-video-gpu.py').read_text(encoding='utf-8')
        self.assertIn("spec_mod.end_units_at_silences(units, S['silences'])", src)


class BuilderWiring(unittest.TestCase):
    """The builder needs a GPU, so these read its source: the pieces this change adds are hooked in where they must be."""
    src = (Path(__file__).resolve().parent.parent / 'video' / 'halcyon' / 'dung-video-gpu.py').read_text(encoding='utf-8')

    def test_clip_kind_and_flag_are_wired(self):
        for needle in ("pic['kind'] == 'clip'", 'spec_mod.load_clip_manifest', 'spec_mod.plan_clip', 'spec_mod.beat_captions', "if not b['captions']", "if not bb['captions']"):
            self.assertIn(needle, self.src)

    def test_no_cpu_fallback_added(self):
        self.assertNotIn('libx264', self.src)
        self.assertIn('h264_nvenc', self.src)


if __name__ == '__main__':
    unittest.main()
