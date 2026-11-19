"""Halcyon script assembler (video/halcyon/halcyon_kich_ban.py): rebuilds the specs of two published videos from a script, the voice timing and a
capture manifest, and refuses each bad input with a message. Standard library only; no GPU, no network, no audio.

The fixtures hold only text already published in the videos (tests/fixtures/halcyon/<id>/). The published spec and plan are the reference; the
DIFFS below are the whole list of places the assembled spec is not byte-equal to it, each explained in video/halcyon/KICH-BAN.md."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "halcyon"
spec = importlib.util.spec_from_file_location("halcyon_kich_ban", ROOT / "video" / "halcyon" / "halcyon_kich_ban.py")
kb_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kb_mod)

VIDEOS = {"05": ("v3", "v3"), "03": ("v1", "v1")}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def inputs(vid):
    d, g = VIDEOS[vid]
    base = FIX / vid
    return dict(kb=load(base / d / "kich-ban.json"), timing=load(base / "giong" / g / "giong-day-du-timing.json"),
                manifest=kb_mod.check_manifest(load(base / d / "captures.json")), out_dir=base / d,
                timing_path=base / "giong" / g / "giong-day-du-timing.json")


def assemble(vid, **change):
    i = inputs(vid); i.update(change)
    return kb_mod.assemble(i["kb"], i["timing"], i["manifest"], i["out_dir"], i["timing_path"])


def diffs(a, b, p=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            out += [f"{p}.{k}"] if k not in a or k not in b else diffs(a[k], b[k], f"{p}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        out += [f"{p}[len]"] if len(a) != len(b) else [d for i, (x, y) in enumerate(zip(a, b)) for d in diffs(x, y, f"{p}[{i}]")]
    elif a != b:
        out.append(p)
    return out


# Every place the assembled spec differs from the published one. "at" for "word": the assembler writes a band time in seconds, the published
# spec named the caption word; "cuts[0]" seconds for a word; duration/b: the rule tail of 0.70 s against the published 0.71 / 0.68.
# ".layout": the posted videos were built with thu-gon-r2; a script now defaults to thu-gon-r3-l2 (owner 19/11/2026 22:54, "Chọn +2 dòng"), and the posted specs keep naming r2 so they still rebuild as before.
DIFFS = {
    "05": {".layout", ".duration", ".beats[8].b",
           ".beats[2].bands[0].at", ".beats[2].bands[0].word", ".beats[3].text.cuts[0]",
           ".beats[3].bands[0].at", ".beats[3].bands[0].word", ".beats[3].bands[1].at", ".beats[3].bands[1].word",
           ".beats[5].bands[0].at", ".beats[5].bands[0].word", ".beats[5].bands[1].at", ".beats[5].bands[1].word"},
    "03": {".layout", ".duration", ".beats[6].b", ".beats[3].level", ".beats[3].text.cuts[0]", ".beats[4].text.cuts[0]",
           ".beats[0].bands[0].at", ".beats[0].bands[0].word", ".beats[1].bands[0].at", ".beats[1].bands[0].word",
           ".beats[2].bands[0].at", ".beats[2].bands[0].word", ".beats[2].bands[1].at", ".beats[2].bands[1].word",
           ".beats[4].bands[0].at", ".beats[4].bands[0].word", ".beats[4].bands[1].at", ".beats[4].bands[1].word",
           ".beats[5].bands[0].at", ".beats[5].bands[0].word"},
}


class Reproduces(unittest.TestCase):
    def check(self, vid):
        d = VIDEOS[vid][0]
        got = assemble(vid); pub = load(FIX / vid / d / "video.published.json"); plan = load(FIX / vid / d / "video-plan.published.json")
        self.assertEqual(got["layout"], "thu-gon-r3-l2"); self.assertEqual(pub["layout"], "thu-gon-r2")
        self.assertEqual(set(diffs(got, pub)), DIFFS[vid])
        self.assertEqual(got["captions"], pub["captions"])
        self.assertEqual(got["word_aliases"], pub["word_aliases"])
        # the places that differ in form must still land on the published frames (30 fps; the builder's own rounding)
        self.assertEqual(round(got["duration"] * 30), round(pub["duration"] * 30))
        byid = {b["id"]: b for b in plan["beats"]}
        for b in got["beats"]:
            cuts = b.get("text", {}).get("cuts")
            if cuts and b["id"] in byid and byid[b["id"]]["kind"] != "still":
                self.assertEqual(byid[b["id"]]["switch"], [round(b["a"] * 30)] + [round(c * 30) for c in cuts], f"beat {b['id']} switch frames")
            for n, band in enumerate(b.get("bands", [])):
                self.assertEqual(plan["bands"][b["id"]][n]["frame"], max(round(band["at"] * 30), round(b["a"] * 30)), f"beat {b['id']} band {n}")

    def test_video_05(self):
        self.check("05")

    def test_video_03(self):
        self.check("03")

    def test_script_with_no_slash_uses_the_rule_and_still_assembles(self):
        for vid in VIDEOS:
            i = inputs(vid)
            for p in i["kb"]["paragraphs"]:
                p["show"] = p["show"].replace(" / ", " ")
            got = kb_mod.assemble(i["kb"], i["timing"], i["manifest"], i["out_dir"], i["timing_path"])
            self.assertGreater(len(got["captions"]), 20)

    def test_rule_captions_are_valid_units(self):
        for vid in VIDEOS:
            for p in inputs(vid)["kb"]["paragraphs"]:
                units = kb_mod.rule_pieces(p["show"].replace("/", " "))
                self.assertEqual(" ".join(units).split(), p["show"].replace("/", " ").split())
                self.assertTrue(all(len(u) <= 22 or " " not in u for u in units), units)


class Refuses(unittest.TestCase):
    def refuse(self, vid, text, edit):
        i = inputs(vid); edit(i)
        with self.assertRaises(SystemExit) as cm:
            kb_mod.assemble(i["kb"], i["timing"], i["manifest"], i["out_dir"], i["timing_path"])
        self.assertIn(text, str(cm.exception)); self.assertTrue(str(cm.exception).startswith("kich-ban: "))

    def test_caption_would_attach_to_a_later_equal_word(self):
        def edit(i):
            w = i["timing"]["words_whisper_medium"]; k = next(n for n, x in enumerate(w) if x["w"] == "Google"); del w[k]
        self.refuse("05", 'on a later "Google"', edit)

    def test_digits_differ_from_the_voice(self):
        def edit(i):
            i["kb"]["paragraphs"][1]["show"] = i["kb"]["paragraphs"][1]["show"].replace("72", "27")
        self.refuse("05", '"27" is on screen', edit)

    def test_number_without_a_declared_reading(self):
        def edit(i):
            del i["kb"]["paragraphs"][3]["numbers"]
        self.refuse("03", '"10,5" is on screen', edit)

    def test_declared_reading_must_be_in_the_voice_text(self):
        def edit(i):
            i["kb"]["paragraphs"][3]["numbers"]["10,5"] = "hai mươi"
        self.refuse("03", "which is not in the voice text", edit)

    def test_glyph_missing_from_the_fonts(self):
        def edit(i):
            i["kb"]["paragraphs"][0]["beats"][0]["headline"][0] = "Tắt \U0001F600 rồi?"
        self.refuse("05", "has no glyph", edit)

    def test_band_text_not_in_the_quote(self):
        def edit(i):
            i["kb"]["paragraphs"][1]["beats"][1]["capture"]["quote"] = "một câu khác hẳn"
        self.refuse("05", "is not in the quote", edit)

    def test_band_time_unknown(self):
        def edit(i):
            del i["kb"]["paragraphs"][1]["beats"][1]["capture"]["bands"][1]["at"]
        self.refuse("05", "is not spoken in this beat", edit)

    def test_anchor_not_spoken(self):
        def edit(i):
            i["kb"]["paragraphs"][5]["beats"][0]["rows"][0]["anchor"] = "tiền"
        self.refuse("05", 'the anchor "tiền" is not among the words spoken', edit)

    def test_anchor_ambiguous(self):
        def edit(i):
            del i["kb"]["paragraphs"][3]["beats"][0]["rows"][1]["occurrence"]
        self.refuse("05", 'occurs 2 times', edit)

    def test_paragraph_count_differs_from_the_voice(self):
        def edit(i):
            i["timing"]["beats"].pop()
        self.refuse("05", "must match one to one", edit)

    def test_chip_too_long(self):
        def edit(i):
            i["kb"]["paragraphs"][4]["beats"][1]["chip"] = "Ảnh chụp: một cái tên trang rất dài, 17/11/2026"
        self.refuse("05", "the limit is 43", edit)

    def test_capture_not_in_manifest(self):
        def edit(i):
            i["kb"]["paragraphs"][1]["beats"][1]["capture"]["ref"] = "khong-co"
        self.refuse("05", 'capture "khong-co" is not in the capture manifest', edit)

    def test_script_word_not_heard(self):
        def edit(i):
            w = i["timing"]["words_whisper_medium"]; k = next(n for n, x in enumerate(w) if x["w"] == "72"); del w[k]
        self.refuse("05", "was not heard in the voice", edit)

    def test_manifest_u_rows_must_contain_the_focus(self):
        m = load(FIX / "05" / "v3" / "captures.json"); m["captures"]["g-2b"]["u_rows"] = [500, 1000]
        with self.assertRaises(SystemExit) as cm:
            kb_mod.check_manifest(m)
        self.assertIn("must contain the focus rows", str(cm.exception))

    def test_manifest_field_missing(self):
        m = load(FIX / "05" / "v3" / "captures.json"); del m["captures"]["g-2b"]["captured"]
        with self.assertRaises(SystemExit) as cm:
            kb_mod.check_manifest(m)
        self.assertIn("captured is missing", str(cm.exception))


class Pieces(unittest.TestCase):
    def test_number_words(self):
        self.assertEqual(kb_mod.spoken_values("bảy mươi hai giờ, ba mươi ngày, hai tháng, mười hai, một trăm linh năm"), {72, 30, 2, 12, 105})

    def test_slug(self):
        self.assertEqual(kb_mod.slugify("Gemini giữ chat 2 tháng"), "gemini-giu-chat-2-thang")

    def test_font_cmap_reader_knows_vietnamese(self):
        chars = kb_mod.font_chars(kb_mod.FONTS["caps"][0])
        self.assertIn(ord("Ặ"), chars); self.assertNotIn(0x1F600, chars)


if __name__ == "__main__":
    unittest.main()