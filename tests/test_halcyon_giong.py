"""Halcyon voice step (video/halcyon/halcyon_giong.py): the reading gate, the listen list and the timing-file writer.

Standard library only, no audio: the voice is stood in for by the Whisper word lists of the published videos 05 and 03
(tests/fixtures/halcyon/<id>/giong/, text already published). lam-giong.py, which runs ffmpeg, Whisper and the voice model, is not imported."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "halcyon"


def load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


g = load_module("halcyon_giong", "video/halcyon/halcyon_giong.py")
kb_mod = load_module("halcyon_kich_ban", "video/halcyon/halcyon_kich_ban.py")
APPROVED = g.load_approved((ROOT / "video" / "halcyon" / "giong-da-nghe.txt").read_text(encoding="utf-8"))
VIDEOS = {"05": ("v3", "v3"), "03": ("v1", "v1")}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def video(vid):
    d, gd = VIDEOS[vid]
    kb = load(FIX / vid / d / "kich-ban.json")
    timing = load(FIX / vid / "giong" / gd / "giong-day-du-timing.json")
    return kb, timing, [p["say"] for p in kb["paragraphs"]]


def paragraph_words(timing, n):
    b = timing["beats"][n]
    return [w for w in timing["words_whisper_medium"] if b["start"] - 0.15 <= w["s"] < b["end"] + 0.05]


def without(words, drop):
    ids = {id(w) for w in drop}
    return [w for w in words if id(w) not in ids]


class PublishedVoices(unittest.TestCase):
    def test_gate_passes_the_published_word_lists(self):
        for vid in VIDEOS:
            kb, t, say = video(vid)
            for approved in ((), APPROVED):
                rep = g.check_reading(say, t["words_whisper_medium"], t["beats"], approved)
                self.assertEqual(rep["problems"], [], vid)
                self.assertLess(rep["rate"], 0.03, vid)
                self.assertLessEqual(rep["longest_run"], 1, vid)

    def test_what_is_not_a_mispronunciation_is_not_counted(self):
        # tuỳ / tùy, ChatGPT / chat GPT, bảy mươi hai / 72, hai / 2, ba mươi / 30 are all in video 05 and none is a residual
        kb, t, say = video("05")
        rep = g.check_reading(say, t["words_whisper_medium"], t["beats"])
        self.assertEqual([r["say"] for r in rep["residual"]], ["trò"])
        self.assertEqual(rep["residual"][0]["heard"], "cho")


class Refusals(unittest.TestCase):
    def setUp(self):
        self.kb, self.t, self.say = video("05")
        self.words = self.t["words_whisper_medium"]
        self.beats = self.t["beats"]

    def refused(self, words, beats=None):
        with self.assertRaises(SystemExit) as cm:
            g.gate(self.say, words, self.beats if beats is None else beats, APPROVED)
        msg = str(cm.exception)
        self.assertTrue(msg.startswith("giong: "), msg)
        return msg

    def test_a_sentence_of_five_words_removed(self):
        p2 = paragraph_words(self.t, 1)  # "Trước đây con số này là 72 giờ, chat tạm thời cũng bị giữ lâu như vậy."
        i = [w["w"] for w in p2].index("tạm")
        drop = p2[i:i + 5]
        self.assertEqual(" ".join(w["w"] for w in drop), "tạm thời cũng bị giữ")
        msg = self.refused(without(self.words, drop))
        self.assertIn("5 script words in a row were not heard", msg)
        self.assertIn("paragraph 2", msg)
        self.assertIn("tạm thời cũng bị giữ", msg)
        self.assertRegex(msg, r"near \d+\.\d s")

    def test_one_paragraph_missing(self):
        msg = self.refused(without(self.words, paragraph_words(self.t, 2)))
        self.assertIn("paragraph 3 (8.59-12.54 s)", msg)
        self.assertIn("Google nói thay đổi áp dụng toàn cầu", msg)
        # and the voice paragraphs counted on the final wav are one short
        msg = self.refused(without(self.words, paragraph_words(self.t, 2)), self.beats[:2] + self.beats[3:])
        self.assertIn("the script has 7 paragraphs but the voice has 6", msg)

    def test_the_voice_read_another_paragraph(self):
        # paragraph 3 of the voice reads paragraph 5's words: the heard text is a paragraph of the script, but not this one
        words = copy.deepcopy(self.words)
        p3, p5 = paragraph_words(self.t, 2), paragraph_words(self.t, 4)
        keep = [w for w in words if not any(w["s"] == x["s"] for x in p3)]
        t0 = p3[0]["s"]
        swapped = [dict(w, s=round(t0 + i * 0.3, 2), e=round(t0 + i * 0.3 + 0.25, 2)) for i, w in enumerate(copy.deepcopy(p5))]
        words = sorted(keep + swapped, key=lambda w: w["s"])
        msg = self.refused(words)
        self.assertIn("paragraph 3", msg)
        self.assertIn("thay đổi áp dụng toàn cầu", msg)
        self.assertIn("were not heard", msg)

    def test_words_that_are_not_in_the_script(self):
        words = list(self.words) + [dict(w="cho", s=30 + i, e=30.5 + i) for i in range(5)]
        msg = self.refused(words)
        self.assertIn("said 5 words in a row that are not in the script", msg)

    def test_the_rate_alone_refuses(self):
        # every sixth word wrong: no run of four, but far over 10 %
        words = [dict(w, w="xxx") if i % 6 == 0 else w for i, w in enumerate(self.words)]
        msg = self.refused(words)
        self.assertIn("more than the 10% allowed", msg)
        self.assertNotIn("in a row were not heard", msg)

    def test_a_wrong_number_is_a_mismatch(self):
        words = [dict(w, w="27") if w["w"] == "72" else w for w in self.words]
        rep = g.check_reading(self.say, words, self.beats)
        self.assertIn("bảy mươi hai", [r["say"] for r in rep["residual"]])


class Folding(unittest.TestCase):
    def say(self, text, heard, approved=()):
        words = [dict(w=w, s=i * 0.3, e=i * 0.3 + 0.25) for i, w in enumerate(heard.split())]
        return g.check_reading([text], words, None, approved)

    def test_numbers(self):
        for text, heard in [("tỷ đô một trăm mười lăm phẩy tám tỷ", "tỷ đô 115 ,8 tỷ"), ("hơn một trăm chín mươi ba ngàn người", "hơn 193 ngàn người"),
                            ("hai nghìn không trăm hai mươi sáu", "2026"), ("chậm mười giây rưỡi", "chậm 10,5 giây"), ("còn ba mươi ngày", "còn ba mươi ngày")]:
            self.assertEqual(self.say(text, heard)["residual"], [], text)
        self.assertEqual([r["say"] for r in self.say("doanh thu một trăm mười lăm phẩy tám tỷ", "doanh thu 15 ,8 tỷ")["residual"]],
                         ["một trăm mười lăm phẩy tám tỷ"])

    def test_tone_mark_place_and_case(self):
        self.assertEqual(self.say("Giấy tờ tuỳ thân, hoạ sĩ", "giấy tờ tùy thân họa sĩ")["residual"], [])
        self.assertNotEqual(self.say("má", "ma")["residual"], [])

    def test_approved_respelling_counts_as_heard_only_in_a_listed_reading(self):
        rep = self.say("chủ tịch En vi đi a nói thẳng", "chủ tịch NVDA nói thẳng", APPROVED)
        self.assertEqual((rep["residual"], rep["listen"]), ([], []))
        self.assertEqual(list(rep["approved"]), ["en vi đi a"])
        rep = self.say("chủ tịch En vi đi a nói thẳng", "chủ tịch NVGA nói thẳng", APPROVED)
        self.assertEqual(rep["residual"][0]["say"], "En vi đi a")
        self.assertEqual(rep["approved"], {})

    def test_the_approved_file_is_checked(self):
        with self.assertRaises(SystemExit):
            g.load_approved("no arrow here")


class ListenList(unittest.TestCase):
    def test_names_numbers_and_misses_of_video_05(self):
        kb, t, say = video("05")
        rep = g.check_reading(say, t["words_whisper_medium"], t["beats"], APPROVED)
        by = {(x["kind"], x["say"]): x for x in rep["listen"]}
        for k in [("name", "Gemini"), ("name", "Google"), ("name", "ChatGPT"), ("name", "AI"), ("number", "bảy mươi hai"), ("number", "ba mươi"),
                  ("number", "hai"), ("not heard", "trò")]:
            self.assertIn(k, by)
        self.assertEqual(len(by[("name", "Google")]["times"]), 3)
        self.assertEqual(by[("name", "ChatGPT")]["heard"], "chat GPT")
        self.assertEqual([x["t"] for x in rep["listen"]], sorted(x["t"] for x in rep["listen"]))
        self.assertLess(len(rep["listen"]), 12)  # short enough to listen to
        text = g.format_listen(rep["listen"], rep["approved"])
        self.assertIn("13,4 giây", text)
        self.assertIn('[tên] kịch bản nói "ChatGPT", máy nghe ra "chat GPT"', text)
        self.assertIn("[số]", text)
        self.assertIn("[không nghe thấy]", text)
        self.assertNotIn("Whisper wrote", text)


class TimingFile(unittest.TestCase):
    def test_silences_become_paragraph_spans(self):
        err = "\n".join(["[silencedetect @ 0x1] silence_start: 4.31", "[silencedetect @ 0x1] silence_end: 4.57 | silence_duration: 0.26",
                         "[silencedetect @ 0x1] silence_start: 8.3", "[silencedetect @ 0x1] silence_end: 8.9 | silence_duration: 0.6",
                         "[silencedetect @ 0x1] silence_start: 12.0", "[silencedetect @ 0x1] silence_end: 12.7 | silence_duration: 0.7"])
        self.assertEqual(g.paragraphs_from_silences(err, 20.0, 3),
                         [dict(start=0.0, end=8.3), dict(start=8.9, end=12.0), dict(start=12.7, end=20.0)])
        with self.assertRaises(SystemExit) as cm:
            g.paragraphs_from_silences(err, 20.0, 4)
        self.assertIn("found 3 paragraphs", str(cm.exception))

    def test_the_assembler_reads_what_the_writer_writes(self):
        for vid in VIDEOS:
            d, gd = VIDEOS[vid]
            kb, t, say = video(vid)
            show = [p["show"].replace(" / ", " ").replace("/", " ") for p in kb["paragraphs"]]
            made = g.build_timing(t["file"], t["sample_rate"], t["duration_s"], t["loudness"], t["pause_between_beats_s"],
                                  [dict(start=b["start"], end=b["end"]) for b in t["beats"]], t["words_whisper_medium"], say, show)
            self.assertEqual(set(made), set(t))
            self.assertLessEqual(set(t["beats"][0]), set(made["beats"][0]))
            man = kb_mod.check_manifest(load(FIX / vid / d / "captures.json"))
            out_dir, path = FIX / vid / d, FIX / vid / "giong" / gd / "giong-day-du-timing.json"
            self.assertEqual(kb_mod.assemble(kb, made, man, out_dir, path), kb_mod.assemble(kb, t, man, out_dir, path))

    def test_json_is_written_with_unix_newlines(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.json"
            g.write_json(p, {"a": "Tắt"})
            raw = p.read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertEqual(json.loads(raw.decode("utf-8")), {"a": "Tắt"})


if __name__ == "__main__":
    unittest.main()
