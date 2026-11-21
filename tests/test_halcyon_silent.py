"""Halcyon silent paragraphs and moving-picture beats: the script contract and its refusals, the silence put into the voice, the music lift and its loudness guard, the
three beat kinds assembled to picture specs, the producer table.

Standard library only, plus ffmpeg where a test needs real audio (those tests are skipped without it). Nothing here needs a GPU, Whisper or the network."""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HAL = ROOT / "video" / "halcyon"
FIX = ROOT / "tests" / "fixtures" / "halcyon"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


kbm = load_module("halcyon_kich_ban_s", HAL / "halcyon_kich_ban.py")
lang = load_module("halcyon_lang_s", HAL / "halcyon_lang.py")
ml = load_module("halcyon_mot_lenh_s", HAL / "halcyon_mot_lenh.py")
nhac = load_module("tron_nhac_s", HAL / "tron-nhac.py")

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SILENT_AT = 2                    # the silent paragraph sits at this index of the script: between voiced paragraphs 1 and 2 of video 05
CLIP_S = 6.0


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def man_clip(path, duration=CLIP_S, **kw):
    m = dict(file="clip.mp4", w=886, h=640, fps=30, frames=round(duration * 30), duration=duration, captured="2026-11-21T05:00:00+07:00", source="dojo.ag-ui.com", date="21/11/2026")
    m.update(kw)
    Path(path).write_text(json.dumps(m), encoding="utf-8")
    return str(path)


class Fixture:
    """Video 05's script and voice with one silent paragraph put between its second and third voiced paragraphs, the way the chain's `lang` step does it."""

    def __init__(self, tmp, silent_beat=None, kind="screen"):
        self.tmp = Path(tmp)
        base = FIX / "05"
        self.kb = load(base / "v3" / "kich-ban.json")
        self.voice_timing = load(base / "giong" / "v3" / "giong-day-du-timing.json")
        self.manifest = kbm.check_manifest(load(base / "v3" / "captures.json"))
        self.beat = silent_beat or {"kind": "screen", "screen": {"ref": "thu", "steps": [0, 1]}}
        self.key = kbm.parse_clip_beat(self.beat)[0]["key"]
        self.kb["paragraphs"].insert(SILENT_AT, {"silent": True, "beats": [copy.deepcopy(self.beat)]})
        marks = [dict(at=lang.gap_middle(self.voice_timing, SILENT_AT), dur=CLIP_S, key=self.key)]
        self.timing = lang.shift_timing(self.voice_timing, marks)
        self.clips = {self.key: man_clip(self.tmp / "clip.json")}
        self.out_dir = base / "v3"
        self.timing_path = base / "giong" / "v3" / "giong-day-du-timing.json"

    def assemble(self, **change):
        d = dict(kb=self.kb, timing=self.timing, manifest=self.manifest, out_dir=self.tmp, timing_path=self.timing_path, quay=None, clips=self.clips)
        d.update(change)
        return kbm.assemble(d["kb"], d["timing"], d["manifest"], d["out_dir"], d["timing_path"], d["quay"], d["clips"])

    def refuse(self, *words, **change):
        with self.testcase.assertRaises(SystemExit) as cm:
            self.assemble(**change)
        for w in words:
            self.testcase.assertIn(w, str(cm.exception))


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def fx(self, **kw):
        f = Fixture(self.tmp, **kw)
        f.testcase = self
        return f


# ------------------------------------------------------------------ the spec of a silent paragraph
class SilentBeat(TmpCase):
    def test_the_silent_paragraph_becomes_a_clip_beat_with_no_captions(self):
        spec = self.fx().assemble()
        sil = spec["silences"]
        self.assertEqual(len(sil), 1)
        self.assertAlmostEqual(sil[0]["b"] - sil[0]["a"], CLIP_S, places=2)
        b = next(x for x in spec["beats"] if x.get("captions") is False)
        self.assertEqual((b["a"], b["b"]), (sil[0]["a"], sil[0]["b"]))
        self.assertEqual(b["picture"], dict(kind="clip", manifest="clip.json", start=0.0, dur=CLIP_S))
        self.assertEqual(b["level"], "FOOT")
        self.assertNotIn("text", b)
        self.assertEqual(b["chip"], {"text": "Chạy thật: 21/11/2026"})

    def test_the_voiced_beats_around_it_meet_it_exactly(self):
        spec = self.fx().assemble()
        beats = spec["beats"]
        i = next(k for k, x in enumerate(beats) if x.get("captions") is False)
        self.assertEqual(beats[i - 1]["b"], beats[i]["a"])
        self.assertEqual(beats[i]["b"], beats[i + 1]["a"])
        self.assertEqual(beats[i + 1]["a"], spec["silences"][0]["b"])

    def test_the_captions_are_the_voiced_paragraphs_only(self):
        f = self.fx()
        plain = kbm.assemble(copy.deepcopy(f.kb) | dict(paragraphs=[p for p in f.kb["paragraphs"] if not p.get("silent")]), f.voice_timing, f.manifest, f.tmp, f.timing_path)
        self.assertEqual(f.assemble()["captions"], plain["captions"])
        self.assertNotIn("silences", plain)

    def test_the_voiced_words_after_the_silence_are_found_at_their_shifted_times(self):
        f = self.fx()
        spec = f.assemble()
        later = next(x for x in spec["beats"] if x["a"] >= spec["silences"][0]["b"])
        self.assertGreater(later["b"], later["a"])
        self.assertAlmostEqual(spec["duration"], f.voice_timing["duration_s"] + CLIP_S + kbm.TAIL, places=2)

    def test_no_silent_paragraph_means_the_spec_is_what_it_was(self):
        f = self.fx()
        kb = copy.deepcopy(f.kb)
        kb["paragraphs"] = [p for p in kb["paragraphs"] if not p.get("silent")]
        spec = kbm.assemble(kb, f.voice_timing, f.manifest, f.tmp, f.timing_path)
        self.assertNotIn("silences", spec)
        self.assertTrue(all("captions" not in b for b in spec["beats"]))

    def test_refused_when_it_has_a_say_or_a_show(self):
        for key in ("say", "show"):
            f = self.fx()
            f.kb["paragraphs"][SILENT_AT][key] = "x"
            f.refuse("silent", "has no voice and no subtitle", f'"{key}"')

    def test_refused_first_last_and_next_to_another_silent_one(self):
        f = self.fx()
        f.kb["paragraphs"][0] = {"silent": True, "beats": [copy.deepcopy(f.beat)]}
        f.refuse("first paragraph")
        f = self.fx()
        f.kb["paragraphs"][-1] = {"silent": True, "beats": [copy.deepcopy(f.beat)]}
        f.refuse("last paragraph")
        f = self.fx()
        f.kb["paragraphs"][SILENT_AT + 1] = {"silent": True, "beats": [copy.deepcopy(f.beat)]}
        f.refuse("silent like the paragraph")

    def test_refused_with_two_beats_or_a_card_beat(self):
        f = self.fx()
        f.kb["paragraphs"][SILENT_AT]["beats"].append(copy.deepcopy(f.beat))
        f.refuse("exactly one beat")
        f = self.fx()
        f.kb["paragraphs"][SILENT_AT]["beats"] = [{"kind": "number", "kicker": "x", "line1": "a", "line2": "b"}]
        f.refuse("exactly one beat")

    def test_refused_when_the_timing_has_no_silence_for_it(self):
        f = self.fx()
        t = copy.deepcopy(f.timing)
        del t["silences"]
        f.refuse("silent paragraphs but the timing file has 0 silences", "halcyon_lang.py", timing=t)

    def test_refused_when_the_clip_changed_after_the_silence_was_made(self):
        f = self.fx()
        man_clip(f.tmp / "clip.json", duration=CLIP_S + 3)
        f.refuse("silent beat lasts", "lang")

    def test_refused_when_the_clip_manifest_is_missing_or_incomplete(self):
        f = self.fx()
        f.refuse("no manifest for the screen", "--clips", clips={})
        m = load(f.clips[f.key])
        del m["source"]
        Path(f.clips[f.key]).write_text(json.dumps(m), encoding="utf-8")
        f.refuse("source")

    def test_refused_when_frames_and_duration_disagree(self):
        f = self.fx()
        man_clip(f.tmp / "clip.json", frames=10)
        f.refuse("frames at 30 fps but duration")

    def test_a_paragraph_count_that_ignores_silent_ones_is_still_refused(self):
        f = self.fx()
        t = copy.deepcopy(f.timing)
        t["beats"] = t["beats"][:-1]
        f.refuse("voiced paragraphs but the timing file measured", timing=t)


# ------------------------------------------------------------------ the three beat kinds
class BeatKinds(TmpCase):
    def test_screen_and_scene3d_assemble_to_clip_pictures(self):
        for beat, key, kind in (({"kind": "screen", "screen": {"ref": "thu", "steps": [2, 3]}}, "screen:thu:2-3", "clip"),
                                ({"kind": "scene3d", "scene3d": {"ref": "giao-thuc"}}, "scene3d:giao-thuc", "clip")):
            f = self.fx(silent_beat=beat)
            self.assertEqual(f.key, key)
            b = next(x for x in f.assemble()["beats"] if x.get("captions") is False)
            self.assertEqual(b["picture"]["kind"], kind)
            self.assertEqual(b["picture"]["manifest"], "clip.json")

    def test_a_voiced_scene3d_beat_keeps_its_captions_and_may_be_shorter_than_its_beat(self):
        f = self.fx()
        f.kb["paragraphs"][1]["beats"][0] = {"kind": "scene3d", "scene3d": {"ref": "giao-thuc"}, "headline": ["Hai dòng", "chữ đây"]}
        f.clips["scene3d:giao-thuc"] = man_clip(f.tmp / "scene.json", duration=2.0, source="sự kiện thật")
        spec = f.assemble()
        b = spec["beats"][1]
        self.assertNotIn("captions", b)
        self.assertEqual(b["picture"], dict(kind="clip", manifest="scene.json", start=0.0, dur=2.0))
        self.assertEqual(b["text"]["lines"], ["HAI DÒNG", "CHỮ ĐÂY"])

    def test_a_voiced_clip_longer_than_its_beat_is_refused(self):
        f = self.fx()
        f.kb["paragraphs"][1]["beats"][0] = {"kind": "scene3d", "scene3d": {"ref": "giao-thuc"}}
        f.clips["scene3d:giao-thuc"] = man_clip(f.tmp / "scene.json", duration=30.0)
        f.refuse("would be cut")

    def test_demo_becomes_a_recording_of_the_part_between_from_and_to(self):
        beat = {"kind": "demo", "demo": {"ref": "dojo", "from": 2.0, "to": 8.0, "rect": [20, 300, 370, 700]}}
        f = self.fx(silent_beat=beat)
        f.clips = {f.key: str(f.tmp / "demo.json")}
        Path(f.clips[f.key]).write_text(json.dumps(dict(file="demo.webm", duration=20.0, captured="2026-11-21T05:00:00+07:00", source="dojo.ag-ui.com", date="21/11/2026")), encoding="utf-8")
        b = next(x for x in f.assemble()["beats"] if x.get("captions") is False)
        self.assertEqual(b["picture"], dict(kind="recording", file="demo.webm", start=2.0, dur=6.0, rect=[20, 300, 370, 700]))
        self.assertEqual(b["chip"], {"text": "Demo công khai: dojo.ag-ui.com, 21/11/2026"})
        self.assertEqual(b["level"], "HOOK")

    def test_demo_beyond_its_recording_is_refused(self):
        beat = {"kind": "demo", "demo": {"ref": "dojo", "from": 2.0, "to": 8.0, "rect": [20, 300, 370, 700]}}
        f = self.fx(silent_beat=beat)
        f.clips = {f.key: str(f.tmp / "demo.json")}
        Path(f.clips[f.key]).write_text(json.dumps(dict(file="demo.webm", duration=5.0, captured="x", source="s", date="d")), encoding="utf-8")
        f.refuse("lasts 5.0 s")

    def test_the_contract_refusals_name_the_field(self):
        bad = [({"kind": "screen", "screen": {"ref": "t", "steps": []}}, "screen.steps"),
               ({"kind": "screen", "screen": {"ref": "t", "steps": [1, 0]}}, "screen.steps"),
               ({"kind": "screen", "screen": {"ref": "t", "steps": [0], "x": 1}}, "unknown key"),
               ({"kind": "scene3d", "scene3d": {}}, "scene3d.ref"),
               ({"kind": "scene3d"}, 'no "scene3d" block'),
               ({"kind": "demo", "demo": {"ref": "d", "from": 5, "to": 4, "rect": [0, 0, 10, 10]}}, "demo.from/to"),
               ({"kind": "demo", "demo": {"ref": "d", "from": 0, "to": 4, "rect": [0, 0, 400, 10]}}, "demo.rect"),
               ({"kind": "demo", "demo": {"ref": "d", "from": 0, "to": 4}}, "demo.rect")]
        for beat, word in bad:
            info, problem = kbm.parse_clip_beat(beat)
            self.assertIsNone(info, beat)
            self.assertIn(word, problem[0], beat)


# ------------------------------------------------------------------ the silence in the voice
def write_wav(path, seconds, rate=8000, value=1000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((value).to_bytes(2, "little", signed=True) * int(seconds * rate))


def small_timing():
    words = [dict(w="a", s=0.2, e=0.5), dict(w="b", s=0.6, e=1.0), dict(w="c", s=2.0, e=2.4), dict(w="d", s=3.6, e=4.0)]
    beats = [dict(beat=1, start=0.2, end=1.0), dict(beat=2, start=2.0, end=2.4), dict(beat=3, start=3.6, end=4.0)]
    return dict(file="v.wav", sample_rate=8000, duration_s=4.5, beats=beats, words_whisper_medium=words)


class VoiceSilence(TmpCase):
    def run_lang(self, inserts, timing=None):
        write_wav(self.tmp / "v.wav", 4.5)
        timing = timing or small_timing()
        (self.tmp / "t.json").write_text(json.dumps(timing), encoding="utf-8")
        return lang.run(self.tmp / "t.json", self.tmp / "v.wav", inserts, self.tmp / "out")

    def test_silence_goes_in_the_middle_of_the_gap_and_everything_after_moves(self):
        _, wav, new = self.run_lang([dict(before=1, dur=3.0, key="k")])
        self.assertEqual(new["silences"], [dict(a=1.5, b=4.5, key="k")])       # the gap 1.0-2.0 has its middle at 1.5
        self.assertEqual([(b["start"], b["end"]) for b in new["beats"]], [(0.2, 1.0), (5.0, 5.4), (6.6, 7.0)])
        self.assertEqual([(w["s"], w["e"]) for w in new["words_whisper_medium"]], [(0.2, 0.5), (0.6, 1.0), (5.0, 5.4), (6.6, 7.0)])
        self.assertEqual(new["duration_s"], 7.5)
        with wave.open(str(wav), "rb") as w:
            self.assertEqual(w.getnframes(), int(7.5 * 8000))

    def test_the_voice_outside_the_silence_is_the_original_samples_and_the_silence_is_digital(self):
        timing = small_timing()
        t, wav, new = self.run_lang([dict(before=1, dur=3.0), dict(before=2, dur=2.0)])
        self.assertEqual(lang.check_result(timing, new, self.tmp / "v.wav", wav), [])
        self.assertEqual(len(new["silences"]), 2)
        self.assertEqual(lang.peak_dbfs(wav, 1.5, 4.5), -200.0)
        self.assertGreater(lang.peak_dbfs(wav, 0.0, 1.0), -60)
        self.assertEqual(json.loads(Path(t).read_text(encoding="utf-8"))["silences"], new["silences"])

    def test_the_check_goes_red_on_planted_violations(self):
        timing = small_timing()
        _, wav, new = self.run_lang([dict(before=1, dur=3.0)])
        raw = bytearray(Path(wav).read_bytes())
        a, b = int(1.5 * 8000), int(4.5 * 8000)
        raw[44 + 2 * (a + 100): 44 + 2 * (a + 102)] = (5000).to_bytes(2, "little", signed=True)      # a click in the silence
        planted = self.tmp / "planted.wav"
        planted.write_bytes(bytes(raw))
        bad = lang.check_result(timing, new, self.tmp / "v.wav", planted)
        self.assertTrue(any("not digital silence" in p for p in bad), bad)
        self.assertTrue(any("dBFS inside the silence" in p for p in bad), bad)
        late = json.loads(json.dumps(new))
        late["words_whisper_medium"][1]["e"] = 2.0                                                       # a word that runs into the silence
        self.assertTrue(any("heard inside" in p for p in lang.check_result(timing, late, self.tmp / "v.wav", wav)))
        short = json.loads(json.dumps(new))
        short["duration_s"] = 5.0
        self.assertTrue(any("timing says" in p for p in lang.check_result(timing, short, self.tmp / "v.wav", wav)))

    def overrun_case(self, loud_in_pause):
        """Gap 1.0-2.0 (silence goes in at 1.5). Whisper says word b ends at 1.3, past the measured end of the speech (1.0), into the pause."""
        rate, quiet = 8000, bytes(2)
        voice = (1000).to_bytes(2, "little", signed=True)
        frames = voice * int(1.0 * rate) + quiet * int(1.0 * rate) + voice * int(2.5 * rate)
        if loud_in_pause:    # real speech runs on past the cut, to 1.55 s
            frames = voice * int(1.55 * rate) + quiet * int(0.45 * rate) + voice * int(2.5 * rate)
        with wave.open(str(self.tmp / "v.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes(frames)
        timing = small_timing()
        timing["words_whisper_medium"][1]["e"] = 1.6        # runs past the middle of the gap, where the silence goes
        (self.tmp / "t.json").write_text(json.dumps(timing), encoding="utf-8")
        return timing

    def test_a_word_end_that_overruns_into_measured_quiet_is_cut_at_the_silence(self):
        # the failure of 21/11: "hình." ended 0.43 s after the speech did, and the silence was refused ("the word changed length ... heard inside the silence")
        timing = self.overrun_case(loud_in_pause=False)
        _, wav, new = lang.run(self.tmp / "t.json", self.tmp / "v.wav", [dict(before=1, dur=3.0)], self.tmp / "out")
        self.assertEqual(new["silences"], [dict(a=1.5, b=4.5, key=None)])
        self.assertEqual(new["words_whisper_medium"][1]["e"], 1.5)
        self.assertEqual(new["word_ends_cut_at_silence"], [dict(index=1, w="b", was=1.6, now=1.5)])
        self.assertEqual(lang.check_result(timing, new, self.tmp / "v.wav", wav), [])

    def test_speech_energy_inside_the_silence_is_still_refused(self):
        self.overrun_case(loud_in_pause=True)
        with self.assertRaises(lang.Refusal) as cm:
            lang.run(self.tmp / "t.json", self.tmp / "v.wav", [dict(before=1, dur=3.0)], self.tmp / "out")
        self.assertIn("heard inside the silence", str(cm.exception))

    def test_an_overrun_longer_than_allowed_is_still_refused(self):
        self.overrun_case(loud_in_pause=False)
        t = small_timing()
        t["words_whisper_medium"][1]["e"] = 2.1             # 0.6 s past the cut
        (self.tmp / "t.json").write_text(json.dumps(t), encoding="utf-8")
        with self.assertRaises(lang.Refusal):
            lang.run(self.tmp / "t.json", self.tmp / "v.wav", [dict(before=1, dur=3.0)], self.tmp / "out")

    def test_a_planted_cut_over_loud_voice_is_caught_by_the_check(self):
        timing = self.overrun_case(loud_in_pause=False)
        _, wav, new = lang.run(self.tmp / "t.json", self.tmp / "v.wav", [dict(before=1, dur=3.0)], self.tmp / "out")
        write_wav(self.tmp / "loud.wav", 4.5)               # the same claim made against a voice that is loud there
        bad = lang.check_result(timing, new, self.tmp / "loud.wav", wav)
        self.assertTrue(any("not quiet there" in p for p in bad), bad)

    def test_refusals(self):
        for inserts, word in (([dict(before=0, dur=3.0)], "between two"), ([dict(before=3, dur=3.0)], "between two"), ([dict(before=1, dur=0.1)], "between 0.5 and 120"),
                              ([dict(before=1, dur=3.0), dict(before=1, dur=3.0)], "same gap")):
            with self.assertRaises(lang.Refusal) as cm:
                self.run_lang(inserts)
            self.assertIn(word, str(cm.exception))

    def test_no_pause_between_paragraphs_is_refused(self):
        t = small_timing()
        t["beats"][1]["start"] = t["beats"][0]["end"]
        with self.assertRaises(lang.Refusal) as cm:
            self.run_lang([dict(before=1, dur=3.0)], timing=t)
        self.assertIn("no pause", str(cm.exception))

    def test_the_command_line_writes_both_files(self):
        write_wav(self.tmp / "v.wav", 4.5)
        (self.tmp / "t.json").write_text(json.dumps(small_timing()), encoding="utf-8")
        self.assertEqual(lang.main(["--timing", str(self.tmp / "t.json"), "--wav", str(self.tmp / "v.wav"), "--insert", "1:3:thu-0", "--out-dir", str(self.tmp / "o")]), 0)
        self.assertEqual(load(self.tmp / "o" / "t.json")["silences"][0]["key"], "thu-0")
        self.assertEqual(lang.main(["--timing", str(self.tmp / "t.json"), "--wav", str(self.tmp / "v.wav"), "--insert", "x", "--out-dir", str(self.tmp / "o")]), 2)


# ------------------------------------------------------------------ the music lift
class MusicLift(unittest.TestCase):
    def test_windows_are_checked(self):
        self.assertEqual(nhac.parse_windows(["5:11", "30:40"], 60), [(5.0, 11.0), (30.0, 40.0)])
        for bad, word in ((["x"], "A:B"), (["5:4"], "outside"), (["5:99"], "outside"), (["5:11", "11.5:20"], "closer than two ramps")):
            with self.assertRaises(nhac.Refusal) as cm:
                nhac.parse_windows(bad, 60)
            self.assertIn(word, str(cm.exception))

    def test_the_lift_expression_is_twelve_db_by_default_with_ramps(self):
        f = nhac.lift_filter([(5.0, 11.0)], nhac.LIFT_DB)
        self.assertIn("volume='1+(3.98107-1)*(", f)
        self.assertIn("(t-5.000)/0.4", f)
        self.assertIn("(11.000-t)/0.4", f)
        self.assertTrue(f.endswith(":eval=frame"))
        self.assertEqual(nhac.LIFT_DB, 12.0)

    def test_voiced_and_silent_parts_are_complements(self):
        spans = nhac.widen([(5.0, 11.0)], nhac.LIFT_MARGIN_S, 16.0)
        self.assertEqual(spans, [(4.8, 11.2)])
        self.assertEqual(nhac.complement(spans, 16.0), [(0.0, 4.8), (11.2, 16.0)])
        self.assertEqual(nhac.widen([(5.0, 11.0)], -nhac.LIFT_MARGIN_S, 16.0), [(5.2, 10.8)])

    def test_the_chain_passes_the_spec_silences_and_the_owner_setting(self):
        spec = dict(silences=[dict(a=96.2, b=113.2), dict(a=120.0, b=137.0)])
        self.assertEqual(ml.nhac_lift_args(spec, {}), ["--silence", "96.2:113.2", "--silence", "120.0:137.0"])
        self.assertEqual(ml.nhac_lift_args(spec, {"HALCYON_LIFT_DB": "9"})[-2:], ["--lift-db", "9"])
        self.assertEqual(ml.nhac_lift_args({}, {"HALCYON_LIFT_DB": "9"}), [])


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg")
class MusicLiftGuard(TmpCase):
    """A real mix: 5 s of tone, 6 s of silence, 5 s of tone, under a pink-noise bed at about the channel's level."""

    def setUp(self):
        super().setUp()
        t = self.tmp
        ff = lambda *a: subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True, cwd=t)
        ff("-f", "lavfi", "-i", "sine=f=300:d=5", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=6", "-f", "lavfi", "-i", "sine=f=500:d=5", "-filter_complex",
           "[0:a]volume=2,aformat=sample_rates=48000:channel_layouts=mono[a];[1:a]aformat=sample_rates=48000:channel_layouts=mono[s];"
           "[2:a]volume=2,aformat=sample_rates=48000:channel_layouts=mono[b];[a][s][b]concat=n=3:v=0:a=1[o]", "-map", "[o]", "voice.wav")
        ff("-f", "lavfi", "-i", "color=c=black:s=64x64:r=30:d=16", "-i", "voice.wav", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", "vid.mp4")
        ff("-f", "lavfi", "-i", "anoisesrc=d=60:c=pink:a=0.75:r=48000", "track.wav")

    def mix(self, *extra, voice="vid.mp4", out="out.mp4"):
        env = dict(os.environ, HALCYON_MUSIC_TRACK=str(self.tmp / "track.wav"), PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HAL / "tron-nhac.py"), str(self.tmp / voice), "--out", str(self.tmp / out), *extra],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        return p.returncode, p.stdout + p.stderr

    def test_without_silent_spans_it_is_the_old_mix(self):
        code, out = self.mix()
        self.assertEqual(code, 0, out)
        self.assertNotIn("lift", out)
        self.assertNotIn("lift", load(self.tmp / "out.json"))

    def test_twelve_db_in_the_silent_span_passes_the_guard_and_is_recorded(self):
        code, out = self.mix("--silence", "5:11")
        self.assertEqual(code, 0, out)
        rec = load(self.tmp / "out.json")
        self.assertEqual(rec["lift"]["db"], 12.0)
        self.assertGreater(rec["lift"]["lifted_bed_lufs"], rec["bed_alone_lufs"] + 9)
        self.assertLess(abs(rec["lufs_shift"]), nhac.MAX_LU_SHIFT)
        self.assertEqual(rec["frames_input"], rec["frames_output"])

    def test_an_absurd_lift_is_refused_by_the_loudness_guard(self):
        code, out = self.mix("--silence", "5:11", "--lift-db", "30")
        self.assertEqual(code, 2, out)
        self.assertIn("the lifted bed measures", out)
        self.assertFalse((self.tmp / "out.mp4").exists())

    def test_a_voice_inside_the_silent_span_is_refused(self):
        code, out = self.mix("--silence", "3:8")
        self.assertEqual(code, 2, out)
        self.assertIn("inside the silent spans", out)

    def test_a_span_outside_the_video_is_refused(self):
        code, out = self.mix("--silence", "5:40")
        self.assertEqual(code, 2, out)
        self.assertIn("outside the video", out)


# ------------------------------------------------------------------ the chain: script checks, producer table, steps
POST = {"title": "Tiêu đề thử", "body": "Dòng một.\nDòng hai.", "hashtags": ["#AI", "#halcyon"]}
AGUI_SRC = "https://raw.githubusercontent.com/ag-ui-protocol/ag-ui/main/README.md"
RUN = {"files": [{"name": "server.py", "dir": "agent", "from": AGUI_SRC, "fence": "# server.py"}, {"name": "client.ts", "dir": "client", "from": AGUI_SRC, "fence": "// client.ts"}],
       "packages": {"fastapi": "fastapi/fastapi", "uvicorn": "Kludex/uvicorn", "tsx": "privatenumber/tsx"},
       "steps": [{"cmd": "pip install ag-ui-protocol fastapi uvicorn", "cwd": "agent"},
                 {"cmd": "uvicorn server:app --port 8000", "cwd": "agent", "serve": True, "ready": "Uvicorn running", "port": 8000},
                 {"cmd": "npm install @ag-ui/client tsx", "cwd": "client"},
                 {"cmd": "npx tsx client.ts", "cwd": "client", "expect": ["Hello from AG-UI!"]}]}


def v3_script(silent_beat=None, extra_sources=None):
    """A small v3-style script: voiced paragraphs, a silent block of terminal footage, a voiced scene and a voiced demo, then the end."""
    voiced = lambda say, beats: {"say": say, "show": say, "beats": beats}
    kb = {"id": "07", "title": "AG-UI", "tiktok_caption": ["x"], "outlet": "GitHub", "date": "21/11/2026", "post": copy.deepcopy(POST),
          "sources": {"thu": {"run": copy.deepcopy(RUN)}, "dojo": {"demo": {"entry": "https://dojo.ag-ui.com/x", "page": "https://showcase.example.com/demo", "say": "Hãy nhớ giúp tôi.",
                                                                           "expect": {"events": ["RUN_STARTED"], "effect": "one note"}}},
                      "giao-thuc": {"scene": {"name": "giao-thuc", "events_from": "thu", "counts_from": "dojo"}}},
          "paragraphs": [voiced("Một.", [{"kind": "demo", "headline": ["a", "b"], "demo": {"ref": "dojo", "from": 1.0, "to": 6.0, "rect": [0, 300, 390, 700]}}]),
                         voiced("Hai.", [{"kind": "scene3d", "scene3d": {"ref": "giao-thuc"}}]),
                         {"silent": True, "beats": [silent_beat or {"kind": "screen", "screen": {"ref": "thu", "steps": [0, 1]}}]},
                         voiced("Ba.", [{"kind": "end"}])]}
    kb["sources"].update(extra_sources or {})
    return kb


class ScriptContract(unittest.TestCase):
    def refused(self, kb, *words):
        with self.assertRaises(ml.Refusal) as cm:
            ml.check_script(kb)
        for w in words:
            self.assertIn(w, str(cm.exception))
        self.assertEqual(cm.exception.step, "kiem-kich-ban")

    def test_a_script_with_a_silent_block_and_each_new_beat_kind_passes(self):
        plan = ml.check_script(v3_script())
        self.assertEqual(plan.say, ["Một.", "Hai.", "Ba."])
        self.assertEqual(sorted(plan.clips), ["demo:dojo", "scene3d:giao-thuc", "screen:thu:0-1"])
        self.assertEqual([(x["info"]["key"], x["before"]) for x in plan.silent], [("screen:thu:0-1", 2)])
        self.assertEqual(plan.runs["thu"]["blocks"], [[0, 1]])
        self.assertEqual(list(plan.scenes), ["giao-thuc"])
        self.assertEqual(list(plan.demos), ["dojo"])
        self.assertEqual(plan.warnings, [])

    def test_a_silent_paragraph_with_say_or_show_is_refused(self):
        kb = v3_script()
        kb["paragraphs"][2]["say"] = "x"
        self.refused(kb, "silent but has", "paragraph 3")
        kb = v3_script()
        kb["paragraphs"][2]["show"] = "x"
        self.refused(kb, "silent but has")

    def test_silent_first_last_adjacent_or_with_a_card_is_refused(self):
        kb = v3_script()
        kb["paragraphs"][0] = {"silent": True, "beats": kb["paragraphs"][2]["beats"]}
        self.refused(kb, "first paragraph")
        kb = v3_script()
        kb["paragraphs"][3] = {"silent": True, "beats": kb["paragraphs"][2]["beats"]}
        self.refused(kb, "silent like the paragraph")
        kb = v3_script()
        kb["paragraphs"][2]["beats"] = [{"kind": "list", "kicker": "k", "title": "t", "rows": []}]
        self.refused(kb, "exactly one beat of kind")

    def test_the_source_of_a_clip_beat_must_exist_and_be_the_right_kind(self):
        kb = v3_script()
        del kb["sources"]["giao-thuc"]["scene"]["events_from"]
        del kb["sources"]["thu"]
        self.refused(kb, 'screen "thu" has no source with "run"')
        kb = v3_script({"kind": "screen", "screen": {"ref": "thu", "steps": [0, 7]}})
        self.refused(kb, "are not steps of")
        kb = v3_script()
        kb["sources"]["dojo"]["demo"]["page"] = "http://localhost:3000/"
        self.refused(kb, "not a public https address")
        kb = v3_script()
        kb["sources"]["giao-thuc"]["scene"]["events_from"] = "nowhere"
        self.refused(kb, 'events_from "nowhere" is not a source with "run"')
        kb = v3_script()
        kb["sources"]["dojo"]["demo"]["expect"] = {}
        self.refused(kb, "demo.expect")
        kb = v3_script()
        kb["sources"]["giao-thuc"]["scene"]["name"] = "a b"
        self.refused(kb, "scene.name")

    def test_a_hand_made_recording_is_still_refused(self):
        kb = v3_script()
        kb["paragraphs"][0]["beats"] = [{"kind": "recording", "headline": ["a", "b"]}]
        self.refused(kb, "hand-made recording")


class Producers(unittest.TestCase):
    def test_the_table_names_three_producers_and_the_unbuilt_ones_are_missing(self):
        self.assertEqual({k: v["step"] for k, v in ml.PRODUCERS.items()}, {"run": "chay", "scene": "canh", "demo": "demo"})
        plan = ml.check_script(v3_script())
        miss = dict((n, r) for n, r in ml.missing_producers(plan))
        want = {"run": "thu", "scene": "giao-thuc", "demo": "dojo"}
        self.assertTrue(ml.producer_ready("run"))
        self.assertTrue(ml.producer_ready("scene"))
        self.assertEqual(miss, {n: r for n, r in want.items() if not ml.producer_ready(n)})

    def test_a_stub_refuses_with_a_clear_message(self):
        r = ml.producer_stub("demo", "dojo")
        self.assertEqual(r.step, "demo:dojo")
        self.assertIn("producer not built yet", str(r))
        self.assertIn("halcyon_demo.py", str(r))
        self.assertIn("pull request E", str(r))
        self.assertIn("producer not built yet", str(ml.producer_stub("scene", "giao-thuc")))
        self.assertIn("producer not built yet", str(ml.producer_stub("run", "thu")))

    def test_the_steps_refuse_before_anything_slow_runs(self):
        kb = v3_script()
        plan = ml.check_script(kb)
        ctx = ml.Ctx("s.json", tempfile.gettempdir() + "/x", plan, kb, {"gpu_python": "python"})
        steps = [s.name for s in ml.real_steps(ctx)]
        self.assertEqual(steps[:3], ["kiem-kich-ban", "kiem-may", "kiem-nguon-clip"])
        for name in ("demo:dojo", "canh:giao-thuc", "lang"):
            self.assertIn(name, steps)
        self.assertLess(steps.index("chay:thu"), steps.index("demo:dojo"))
        self.assertLess(steps.index("demo:dojo"), steps.index("canh:giao-thuc"))
        self.assertLess(steps.index("giong"), steps.index("lang"))
        self.assertLess(steps.index("lang"), steps.index("lap-rap"))
        # all three producers are built (they would install, record or render for real): each step is checked with its producer
        # marked unbuilt, so no unit test ever runs a real producer
        with mock.patch.object(ml, "producer_ready", side_effect=lambda name: name != "scene"):
            with self.assertRaises(ml.Refusal) as cm:
                ml.step_kiem_nguon_clip(ctx)
            self.assertEqual(cm.exception.step, "canh:giao-thuc")
            self.assertIn("producer not built yet", str(cm.exception))
            with self.assertRaises(ml.Refusal) as cm:
                ml.step_producer(ctx, "scene", "giao-thuc")
            self.assertIn("producer not built yet", str(cm.exception))
        with mock.patch.object(ml, "producer_ready", return_value=False):
            with self.assertRaises(ml.Refusal) as cm:
                ml.step_chay(ctx, "thu")
        self.assertIn("producer not built yet", str(cm.exception))

    def test_a_script_without_moving_pictures_has_no_new_steps(self):
        kb = json.loads((FIX / "mot-lenh" / "kich-ban.json").read_text(encoding="utf-8"))
        plan = ml.check_script(kb)
        ctx = ml.Ctx("s.json", tempfile.gettempdir() + "/x", plan, kb, {"gpu_python": "python"})
        names = [s.name for s in ml.real_steps(ctx)]
        for gone in ("kiem-nguon-clip", "lang"):
            self.assertNotIn(gone, names)
        self.assertEqual(ml.missing_producers(plan), [])

    def test_a_producer_that_says_it_is_built_is_run_and_its_manifest_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            here = Path(d) / "tools"
            here.mkdir()
            for dep in ("halcyon_kich_ban.py", "halcyon_chay.py"):
                shutil.copy2(HAL / dep, here / dep)
            (here / "halcyon_demo.py").write_text("CLIP_PRODUCER = 1\nimport json, sys\nout = sys.argv[sys.argv.index('--out') + 1]\n"
                                                   "json.dump(dict(file='demo.webm', duration=20.0, captured='2026-11-21T05:00:00+07:00', source='dojo.ag-ui.com', date='21/11/2026'), "
                                                   "open(out + '/demo.json', 'w'))\nopen(out + '/demo.webm', 'wb').write(b'x')\n", encoding="utf-8")
            old = ml.HERE
            ml.HERE = here
            try:
                self.assertTrue(ml.producer_ready("demo"))
                self.assertFalse(ml.producer_ready("scene"))
                kb = v3_script()
                plan = ml.check_script(kb)
                ctx = ml.Ctx(Path(d) / "s.json", Path(d) / "run", plan, kb, {"gpu_python": sys.executable})
                ctx.logs.mkdir(parents=True)
                ml.step_producer(ctx, "demo", "dojo")
                self.assertTrue((ctx.demo / "dojo" / "demo.json").exists())
                self.assertEqual(ml.clip_length(ctx, plan.clips["demo:dojo"]), 5.0)
                (ctx.demo / "dojo" / "demo.webm").unlink()
                with self.assertRaises(ml.Refusal) as cm:
                    ml.check_clip_manifest(ctx, plan.clips["demo:dojo"])
                self.assertIn("which is not there", str(cm.exception))
            finally:
                ml.HERE = old

    def test_chi_kiem_checks_the_script_and_warns_about_missing_producers(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "kb.json"
            script.write_text(json.dumps(v3_script()), encoding="utf-8")
            old = ml.settings
            ml.settings = lambda *a, **k: ([], {})
            lines = []
            try:
                with mock.patch.object(ml, "producer_ready", side_effect=lambda name: name != "scene"):   # every producer is built now: the warning is checked on one marked unbuilt
                    code = ml.main([str(script), "--out", str(Path(d) / "run"), "--chi-kiem"], say=lines.append)
            finally:
                ml.settings = old
        text = "\n".join(lines)
        self.assertEqual(code, 0, text)
        self.assertIn("1 silent block(s): screen:thu:0-1", text)
        self.assertIn("producer not built yet", text)
        self.assertIn("kiem-nguon-clip", text)


class SilentWitness(unittest.TestCase):
    SPEC = dict(silences=[dict(a=10.0, b=16.0)], beats=[dict(id="3", a=10.0, b=16.0, captions=False), dict(id="4", a=16.0, b=20.0)])
    PLAN = dict(units=[dict(s=4.0, e=9.8, T="X", wstart=[4.0]), dict(s=16.0, e=18.0, T="Y", wstart=[16.0])])
    TIMING = dict(words_whisper_medium=[dict(w="a", s=9.0, e=9.6), dict(w="b", s=16.1, e=16.5)])

    def test_a_clean_plan_has_no_problems(self):
        self.assertEqual(ml.silent_problems(self.SPEC, self.PLAN, self.TIMING), [])

    def test_a_caption_unit_that_runs_into_the_span_is_found(self):
        plan = dict(units=[dict(s=4.0, e=16.0, T="STUCK", wstart=[4.0])])           # what the builder does today: the last unit lasts until the next one starts
        bad = ml.silent_problems(self.SPEC, plan, self.TIMING)
        self.assertEqual(len(bad), 1)
        self.assertIn('"STUCK"', bad[0])

    def test_the_corrected_plan_passes_and_a_unit_inside_the_span_still_fails(self):
        import importlib.util
        s = importlib.util.spec_from_file_location("halcyon_spec_for_silent", Path(__file__).resolve().parent.parent / "video" / "halcyon" / "halcyon_spec.py")
        hs = importlib.util.module_from_spec(s); s.loader.exec_module(hs)
        stuck = dict(units=[dict(s=4.0, e=16.0, T="STUCK", wstart=[4.0]), dict(s=16.0, e=18.0, T="Y", wstart=[16.0])])
        self.assertTrue(ml.silent_problems(self.SPEC, stuck, self.TIMING))
        hs.end_units_at_silences(stuck["units"], self.SPEC["silences"])
        self.assertEqual(ml.silent_problems(self.SPEC, stuck, self.TIMING), [])
        planted = dict(units=[dict(s=12.0, e=14.0, T="PLANTED", wstart=[12.0])])           # a caption that really starts inside the span is not cut away
        hs.end_units_at_silences(planted["units"], self.SPEC["silences"])
        self.assertTrue(any('"PLANTED"' in p for p in ml.silent_problems(self.SPEC, planted, self.TIMING)))

    def test_a_heard_word_a_missing_flag_and_a_stray_flag_are_found(self):
        t = dict(words_whisper_medium=[dict(w="oops", s=12.0, e=12.4)])
        self.assertIn('the word "oops"', ml.silent_problems(self.SPEC, self.PLAN, t)[0])
        spec = dict(self.SPEC, beats=[dict(id="3", a=10.0, b=16.0), dict(id="4", a=16.0, b=20.0, captions=False)])
        bad = ml.silent_problems(spec, self.PLAN, self.TIMING)
        self.assertTrue(any("no beat with" in p for p in bad), bad)
        self.assertTrue(any("no silent span covers" in p for p in bad), bad)

    def test_a_loud_voice_file_inside_the_span_is_found(self):
        with tempfile.TemporaryDirectory() as d:
            write_wav(Path(d) / "v.wav", 20.0, rate=1000)
            bad = ml.silent_problems(self.SPEC, self.PLAN, self.TIMING, Path(d) / "v.wav", lang)
        self.assertTrue(any("dBFS inside the silent span" in p for p in bad), bad)


if __name__ == "__main__":
    unittest.main()
