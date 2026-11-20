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


HOOK = ["Tắt lịch sử rồi?", "Vẫn giữ 2 tháng"]
F = kb_mod.FLOOR["FOOT"]
FOOT_GLIMPSE_HOME = F["home"] + F["glimpse"]          # the home page of the first repo beat of a video


def stretch(timing, k):
    """The voice of paragraph 1 spoken k times slower: a repo beat needs seconds the real 4.28 s hook does not have. Later paragraphs move later by the same amount."""
    t = copy.deepcopy(timing); end0 = t["beats"][0]["end"]; shift = end0 * (k - 1)
    for w in t["words_whisper_medium"]:
        inside = w["s"] < end0 - 1e-6
        w["s"] = round(w["s"] * k if inside else w["s"] + shift, 2); w["e"] = round(w["e"] * k if inside else w["e"] + shift, 2)
    t["beats"][0]["end"] = round(end0 * k, 2)
    for b in t["beats"][1:]:
        b["start"] = round(b["start"] + shift, 2); b["end"] = round(b["end"] + shift, 2)
    t["duration_s"] = round(t["duration_s"] + shift, 2)
    return t


def repo_script(open_, i=None, k=3, level="FOOT"):
    """Video 05 with its recording hook replaced by a repo beat that opens `open_`; the voice of that paragraph is k times slower (12.84 s) so the pages fit."""
    i = i or inputs("05")
    i["kb"]["paragraphs"][0]["beats"][0] = {"kind": "repo", "headline": HOOK, "kicker": "Theo Google", "repo": {"ref": "pl", "open": open_}, "level": level}
    if k != 1:
        i["timing"] = stretch(i["timing"], k)
    return i


def assemble_repo(i, quay=True):
    return kb_mod.assemble(i["kb"], i["timing"], i["manifest"], i["out_dir"], i["timing_path"], i["out_dir"] / "quay.json" if quay else None)


def walk_of(open_, b=None, edit=None, k=3):
    """The walk of the first beat; with `b` the beat is made that long, so other lengths can be tested."""
    i = repo_script(open_, k=k)
    if edit:
        edit(i)
    r = kb_mod.Run(i["kb"], i["timing"], i["manifest"], i["out_dir"], i["timing_path"], i["out_dir"] / "quay.json")
    r.tokens(); r.edges()
    bt = dict(r.beats[0], b=b or r.beats[0]["b"])
    return [(w["page"], w["a"], w.get("via")) for w in r.repo_beat(bt, "beat 1")["walk"]]


class RepoBeat(unittest.TestCase):
    def test_the_beat_becomes_a_repo_picture_with_a_walk(self):
        got = assemble_repo(repo_script(["packages"]))
        b = got["beats"][0]
        self.assertEqual(b["picture"]["kind"], "repo"); self.assertEqual(b["picture"]["manifest"], "quay.json")
        self.assertEqual(b["level"], "FOOT"); self.assertEqual(b["mark"], "wm"); self.assertEqual(b["chip"], {"text": "Ảnh chụp: GitHub"})
        w = b["picture"]["walk"]
        self.assertEqual([(x["page"], x.get("via")) for x in w], [("", None), ("packages", "tap")])
        self.assertEqual(w[0]["a"], 0.0)
        # the first repo beat: the home page needs 2.15 + 2.25 (the opening glimpse), the last page 0.7; the seconds above them are shared by the two pages
        self.assertAlmostEqual(w[1]["a"], FOOT_GLIMPSE_HOME + (b["b"] - FOOT_GLIMPSE_HOME - F["last"]) / 2, delta=0.006)
        self.assertEqual(got["beats"][-1]["picture"], {"kind": "same_as", "beat": "1"})

    def test_an_empty_open_list_is_the_home_page_alone(self):
        w = assemble_repo(repo_script([]))["beats"][0]["picture"]["walk"]
        self.assertEqual(w, [{"page": "", "a": 0.0}])

    def test_a_later_repo_beat_has_no_glimpse(self):
        i = repo_script(["packages"])
        i["kb"]["paragraphs"][2]["beats"][0] = {"kind": "repo", "headline": ["Toàn cầu,", "vài tuần tới"], "kicker": "Theo Google", "repo": {"ref": "pl", "open": ["docs"]}, "level": "FOOT"}
        got = assemble_repo(i); b = got["beats"][3]
        self.assertEqual((b["a"], b["b"]), (17.0, 21.25))
        # 4.25 s for the home page (2.15) and the last page (0.7): the 1.4 s above them shared by the two pages
        self.assertAlmostEqual(b["picture"]["walk"][1]["a"], 17.0 + F["home"] + (4.25 - F["home"] - F["last"]) / 2, delta=0.006)

    def test_a_slide_back_is_an_entry_of_its_own(self):
        w = walk_of(["packages", "packages/server", "docs"], b=11.0)
        self.assertEqual([x[0] for x in w], ["", "packages", "packages/server", "", "docs"])
        self.assertEqual([x[2] for x in w], [None, "tap", "tap", "back", "tap"])
        # floors 4.4 + 2.2 + 0.7 (a page followed by a slide back needs only its last-page time) + 1.15 + 0.7 = 9.15; the 1.85 s above them shared by the five entries
        for got, want in zip([x[1] for x in w], [0.0, 4.77, 7.34, 8.41, 9.93]):
            self.assertAlmostEqual(got, want, delta=0.006)

    def test_a_chain_entry_skips_the_folders_github_shows_as_one_row(self):
        w = walk_of([{"path": "x/y/z", "chain": True}, "x/y/z/f.md"], b=11.0)
        self.assertEqual([(x[0], x[2]) for x in w], [("", None), ("x/y/z", "tap"), ("x/y/z/f.md", "tap")])

    def test_an_anchor_opens_the_page_when_the_voice_says_it(self):
        w = walk_of([{"path": "a", "anchor": "Google"}, "a/b"], b=12.0)
        self.assertEqual([x[1] for x in w], [0.0, 5.98, 9.74])      # "Google" is heard at 6.06 s, minus the 0.08 s lead; then a and a/b share the 6.02 s left: 5.98 + 2.2 + (6.02 - 2.9) / 2

    def test_anchors_follow_the_order_of_the_list(self):
        with self.assertRaises(SystemExit) as cm:
            walk_of([{"path": "a", "anchor": "tháng"}, {"path": "b", "anchor": "khoảng"}], b=12.0)
        self.assertIn("anchors must follow the order", str(cm.exception))

    def test_an_anchor_that_leaves_a_page_under_its_floor(self):
        with self.assertRaises(SystemExit) as cm:
            walk_of([{"path": "a", "anchor": "Gemini"}], b=12.0)       # heard at 3.42 s: the home page would have 3.34 s, its floor is 4.4 s
        self.assertIn("the home page would be on screen 3.34 s, under its floor of 4.4 s", str(cm.exception))

    def test_an_anchor_not_spoken_in_the_beat(self):
        with self.assertRaises(SystemExit) as cm:
            walk_of([{"path": "a", "anchor": "huấn luyện"}], b=12.0)
        self.assertIn('the anchor "huấn luyện" is not among the words spoken', str(cm.exception))

    def test_a_beat_too_short_for_its_pages_names_the_seconds_needed(self):
        with self.assertRaises(SystemExit) as cm:      # 4.43 s for the home page (4.4 s with the glimpse), two pages and the slide back between them
            assemble_repo(repo_script(["packages", "docs"], k=1))
        e = str(cm.exception)
        self.assertTrue(e.startswith("kich-ban: ")); self.assertIn("gives this beat 4.43 s but its 4 pages need at least 7.0 s", e)

    def test_the_floors_are_the_seconds_the_builder_needs(self):
        # the builder's camera (PR #277) needs, FOOT / HOOK: home 2.05 / 3.05, a page whose next row needs a pan 2.1 / 3.15, a slide back 1.05, the last page 0.6
        for level, home, tap in (("FOOT", 2.05, 2.1), ("HOOK", 3.05, 3.15)):
            f = kb_mod.FLOOR[level]
            self.assertGreaterEqual(f["home"], home); self.assertGreaterEqual(f["tap"], tap)
            self.assertGreaterEqual(f["back"], 1.05); self.assertGreaterEqual(f["last"], 0.6)
        self.assertGreaterEqual(kb_mod.FLOOR["FOOT"]["home"] + kb_mod.FLOOR["FOOT"]["glimpse"], 4.3); self.assertGreaterEqual(kb_mod.FLOOR["HOOK"]["home"] + kb_mod.FLOOR["HOOK"]["glimpse"], 5.95)

    def test_a_repo_beat_needs_the_recorder_manifest(self):
        with self.assertRaises(SystemExit) as cm:
            assemble_repo(repo_script(["packages"]), quay=False)
        self.assertIn("no recorder manifest was given for \"pl\"", str(cm.exception))

    def test_the_manifest_can_be_given_per_ref(self):
        i = repo_script(["packages"])
        got = kb_mod.assemble(i["kb"], i["timing"], i["manifest"], i["out_dir"], i["timing_path"], {"pl": i["out_dir"] / "pl" / "quay.json"})
        self.assertEqual(got["beats"][0]["picture"]["manifest"], "pl/quay.json")

    def test_the_contract_is_refused_here_too(self):
        for open_, word in ((["../x"], 'holds "." or ".."'), (["a/b"], "neither the repo root nor an earlier entry"), (["a", "a"], "already opened"),
                            (["1", "2", "3", "4", "5", "6"], "most one beat may open is 5")):
            with self.assertRaises(SystemExit) as cm:
                assemble_repo(repo_script(open_))
            self.assertIn(word, str(cm.exception))

    def test_the_repo_beat_is_in_the_kinds_list(self):
        i = repo_script([]); i["kb"]["paragraphs"][0]["beats"][0]["kind"] = "videos"
        with self.assertRaises(SystemExit) as cm:
            assemble_repo(i)
        self.assertIn("capture, repo, recording", str(cm.exception))


class OpenContract(unittest.TestCase):
    def bad(self, open_):
        entries, problem = kb_mod.parse_open(open_)
        self.assertIsNone(entries); return problem

    def test_every_refused_path_says_what_to_change(self):
        for open_, word in (([""], "missing or empty"), ([" "], "missing or empty"), (["/packages"], "is absolute"), (["a\\b"], "backslash"),
                            (["a//b"], "empty part"), (["packages/"], "empty part"), (["a/../b"], '".."'), ([".."], '".."'), (["a", "a"], "already opened"),
                            (["a/b/c"], "neither the repo root nor an earlier entry"), ([5], "neither a path nor an object"), ("a", "not a list"),
                            ([{"path": "a", "x": 1}], "unknown key"), ([{"path": "a", "anchor": ""}], "anchor is empty"),
                            ([{"path": "a", "chain": "yes"}], "true or false")):
            reason, fix = self.bad(open_)
            self.assertIn(word, reason, open_); self.assertTrue(fix)

    def test_a_missing_parent_suggests_both_ways_out(self):
        reason, fix = self.bad(["a", "a/b/c"])
        self.assertIn('"a/b"', reason); self.assertIn('put "a/b" before it', fix); self.assertIn('"chain": true', fix); self.assertIn('page of "a"', fix)

    def test_entries_know_the_page_they_are_opened_from(self):
        e, problem = kb_mod.parse_open(["a", "a/b", {"path": "a/b/c/d", "chain": True}, {"path": "e/f", "chain": True}, "README.md"])
        self.assertIsNone(problem)
        self.assertEqual([(x["path"], x["parent"]) for x in e], [("a", ""), ("a/b", "a"), ("a/b/c/d", "a/b"), ("e/f", ""), ("README.md", "")])

    def test_five_entries_are_allowed(self):
        self.assertIsNone(kb_mod.parse_open(list("abcde"))[1])

    def test_repo_names(self):
        for ok in ("backnotprop/plannotator", "jlevy/the-art-of-command-line", "a/b.c_d"):
            self.assertIsNone(kb_mod.repo_problem(ok), ok)
        for bad in ("plannotator", "https://github.com/a/b", "a/b/c", "a/", "/b", "a b/c", "a/..", "", None, 5):
            self.assertIn("owner/name", kb_mod.repo_problem(bad)[0], bad)
        self.assertIsNone(kb_mod.repo_problem("a/b", "release/1.x")); self.assertIn("branch", kb_mod.repo_problem("a/b", "a..b")[0])


class Pieces(unittest.TestCase):
    def test_number_words(self):
        self.assertEqual(kb_mod.spoken_values("bảy mươi hai giờ, ba mươi ngày, hai tháng, mười hai, một trăm linh năm"), {72, 30, 2, 12, 105})

    def test_slug(self):
        self.assertEqual(kb_mod.slugify("Gemini giữ chat 2 tháng"), "gemini-giu-chat-2-thang")

    def test_font_cmap_reader_knows_vietnamese(self):
        chars = kb_mod.font_chars(kb_mod.FONTS["caps"][0])
        self.assertIn(ord("Ặ"), chars); self.assertNotIn(0x1F600, chars)


TERM_ENTRY = {"file": "thu/s5.png", "focus": {"rows": [72, 344]}, "u_rows": [48, 356], "source": "Chạy thật trên máy Halcyon", "date": "20/11/2026",
              "captured": "2026-11-20T20:00:00+07:00", "bands": [{"rect": [63, 208, 493, 68], "text": "Hello from AG-UI!"}],
              "text": "$ npx tsx client.ts\nrun started (AG-UI 1.0)\nHello from AG-UI!\nrun finished"}


def terminal_script(**term):
    i = inputs("05")
    t = dict(ref="thu", step=5, bands=[{"text": "Hello from AG-UI!", "at": 1.0}])
    t.update(term)
    i["kb"]["paragraphs"][0]["beats"][0] = {"kind": "terminal", "headline": HOOK, "level": "FOOT", "terminal": t}
    i["manifest"] = dict(i["manifest"], **{kb_mod.terminal_key("thu", 5): TERM_ENTRY})
    return i


class TerminalBeat(unittest.TestCase):
    def build(self, i):
        return kb_mod.assemble(i["kb"], i["timing"], i["manifest"], i["out_dir"], i["timing_path"])

    def test_it_assembles_to_the_spec_of_a_capture_beat(self):
        b = self.build(terminal_script())["beats"][0]
        self.assertEqual(b["level"], "FOOT")
        self.assertEqual(b["picture"], {"kind": "capture", "file": "thu/s5.png", "rows": [72, 344], "u_rows": [48, 356]})
        self.assertEqual(b["bands"], [{"rect": [63, 208, 493, 68], "at": 1.0}])
        self.assertEqual(b["chip"], {"text": "Chạy thật: 20/11/2026"})

    def test_the_key_names_the_run_and_the_step(self):
        self.assertEqual(kb_mod.terminal_key("thu", 5), "thu-s5")

    def refused(self, i, *words):
        with self.assertRaises(SystemExit) as cm:
            self.build(i)
        for w in words:
            self.assertIn(w, str(cm.exception))

    def test_a_step_without_a_picture_is_refused(self):
        self.refused(terminal_script(step=6), "step 6 of run \"thu\" has no picture")
        self.refused(terminal_script(step="5"), "terminal.step must be the number")
        self.refused(terminal_script(step=-1), "terminal.step must be the number")

    def test_a_phrase_that_is_not_in_the_picture_is_refused(self):
        self.refused(terminal_script(bands=[{"text": "Goodbye", "at": 1.0}]), "no band \"Goodbye\"")

    def test_a_beat_without_its_block_is_refused(self):
        i = terminal_script()
        del i["kb"]["paragraphs"][0]["beats"][0]["terminal"]
        self.refused(i, "terminal")


if __name__ == "__main__":
    unittest.main()