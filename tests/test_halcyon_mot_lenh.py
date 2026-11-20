"""Halcyon one command (video/halcyon/halcyon_mot_lenh.py): the script checks, the step runner, the post text, the Vietnamese pack files.

Standard library only; no audio, GPU or network. The real steps are replaced by small stand-ins (Python callables, `python -c` processes);
the Whisper word list of published video 05 (tests/fixtures/halcyon/05/) stands in for the voice. mot-lenh.py itself is not run here."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "halcyon"


def load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


m = load_module("halcyon_mot_lenh", "video/halcyon/halcyon_mot_lenh.py")
g = load_module("halcyon_giong_t", "video/halcyon/halcyon_giong.py")
APPROVED = g.load_approved((ROOT / "video" / "halcyon" / "giong-da-nghe.txt").read_text(encoding="utf-8"))

POST = {"title": "Tắt lịch sử Gemini rồi, Google vẫn giữ chat của bạn khoảng 2 tháng",
        "body": "Theo Google và TechCrunch (17/11/2026), Gemini vẫn sẽ giữ đoạn chat của bạn khoảng hai tháng dù đã tắt lịch sử.\nLưu lại, và gửi cho người hay tâm sự với AI nhé.",
        "hashtags": ["#AI", "#gemini", "#halcyon"]}
SRC = {"urls": ["https://support.google.com/gemini/answer/13594961?hl=vi"], "locale": "vi-VN", "open": "Khi tôi tắt chế độ Nhật ký"}


def script():
    """Script of published video 05 with its hand-made recording hook replaced by a capture beat, plus the chain's `sources` and `post`."""
    kb = json.loads((FIX / "05" / "v3" / "kich-ban.json").read_text(encoding="utf-8"))
    quote = kb["paragraphs"][1]["beats"][1]["capture"]["quote"]
    kb["paragraphs"][0]["beats"] = [{"kind": "capture", "headline": ["Tắt lịch sử rồi?", "Vẫn giữ 2 tháng"], "kicker": "Theo Google",
                                     "capture": {"ref": "g-2b", "quote": quote, "bands": [{"text": "tạm thời"}]}}]
    kb["sources"] = {"g-2b": dict(SRC), "blog-google": {"urls": ["https://blog.google/x/"]}, "g-5a": dict(SRC), "hco-5b": {"urls": ["https://hco.news/tin/x/"]}}
    kb["post"] = copy.deepcopy(POST)
    return kb


def refused(test, kb, *words):
    with test.assertRaises(m.Refusal) as cm:
        m.check_script(kb)
    for w in words:
        test.assertIn(w, str(cm.exception))
    return cm.exception


class ScriptChecks(unittest.TestCase):
    def test_a_script_of_captures_and_cards_passes(self):
        plan = m.check_script(script())
        self.assertEqual(list(plan.refs), ["g-2b", "blog-google", "g-5a", "hco-5b"])
        self.assertEqual(len(plan.say), 7)
        self.assertEqual(plan.refs["g-2b"]["bands"], ["tạm thời", "khoảng hai", "tháng"])
        self.assertEqual(plan.refs["g-5a"]["urls"], SRC["urls"])
        self.assertEqual(plan.refs["g-2b"]["options"], {"locale": "vi-VN", "open": "Khi tôi tắt chế độ Nhật ký"})

    def test_the_example_script_in_the_repository_passes(self):
        kb = json.loads((FIX / "mot-lenh" / "kich-ban.json").read_text(encoding="utf-8"))
        plan = m.check_script(kb)
        self.assertEqual(list(plan.refs), ["g-2b", "blog-google", "g-5a", "hco-5b"])
        self.assertEqual(plan.warnings, [])
        self.assertEqual(plan.refs["g-2b"]["bands"], ["khoảng hai", "tháng", "tạm thời"])

    def test_a_recording_is_refused_with_the_reason(self):
        kb = json.loads((FIX / "05" / "v3" / "kich-ban.json").read_text(encoding="utf-8"))
        kb["sources"], kb["post"] = {}, copy.deepcopy(POST)
        e = refused(self, kb, "hand-made recording", "manual lane", "paragraph 1")
        self.assertEqual(e.step, "kiem-kich-ban")

    def test_a_photo_picture_is_refused_too(self):
        kb = script()
        kb["paragraphs"][1]["beats"][0]["picture"] = {"kind": "photo", "file": "x.jpg"}
        refused(self, kb, "hand-made recording or photo")

    def test_capture_needs_a_source_with_public_addresses(self):
        kb = script()
        del kb["sources"]["g-5a"]
        refused(self, kb, 'capture "g-5a" has no entry in "sources"')
        kb = script()
        kb["sources"]["g-5a"]["urls"] = ["http://localhost:8080/x"]
        refused(self, kb, "not a public http(s) address")
        kb = script()
        kb["sources"]["g-5a"]["urls"] = ["file:///c:/x.html"]
        refused(self, kb, "not a public http(s) address")
        kb = script()
        kb["sources"]["g-5a"]["tipo"] = 1
        refused(self, kb, "unknown key(s) tipo")

    def test_one_ref_is_one_sentence(self):
        kb = script()
        kb["paragraphs"][1]["beats"][1]["capture"]["quote"] = "a different sentence"
        refused(self, kb, 'ref "g-2b" is used with two different quotes')

    def test_the_last_beat_is_an_end(self):
        kb = script()
        kb["paragraphs"][-1]["beats"] = [{"kind": "list", "kicker": "k", "title": "t", "rows": []}]
        refused(self, kb, "end beat")

    def test_an_unused_source_is_a_warning(self):
        kb = script()
        kb["sources"]["spare"] = {"urls": ["https://example.com/"]}
        self.assertIn('sources["spare"] is not used', m.check_script(kb).warnings[0])

    def test_the_post_follows_the_owners_decisions(self):
        for bad, words in (({"body": "Đọc tại https://hco.news/x"}, "holds a link"), ({"body": "Dòng một\n\nDòng hai"}, "blank line"),
                           ({"body": "Tin hay\nNguồn: TechCrunch"}, "source line"), ({"body": "Tin hay\nNhạc: Voice Over Under"}, "music credit"),
                           ({"body": "Tin hay\nMusic by Kevin MacLeod"}, "music credit"), ({"hashtags": ["AI"]}, "hashtags"), ({"title": ""}, "post.title")):
            kb = script()
            kb["post"].update(bad)
            refused(self, kb, words)
        kb = script()
        del kb["post"]
        refused(self, kb, 'no "post" block')

    def test_the_post_text_is_in_the_owners_format(self):
        expected = ("Tiêu đề:\nTắt lịch sử Gemini rồi, Google vẫn giữ chat của bạn khoảng 2 tháng\nNội dung đăng:\n"
                    "Theo Google và TechCrunch (17/11/2026), Gemini vẫn sẽ giữ đoạn chat của bạn khoảng hai tháng dù đã tắt lịch sử.\n"
                    "Lưu lại, và gửi cho người hay tâm sự với AI nhé.\n#AI #gemini #halcyon\n")
        self.assertEqual(m.post_text(POST), expected)
        self.assertNotIn("\r", m.post_text(POST))
        # the same shape as the published file: Tiêu đề, title, Nội dung đăng, body lines, one hashtag line, one final newline
        self.assertEqual(m.post_text(POST).count("\n"), 6)


class RepoScriptChecks(unittest.TestCase):
    """The repo beat and the repo source: every refusal that needs no network (KICH-BAN.md section 1 and 7)."""

    def repo_script(self, open_=("packages", "packages/server", "package.json"), source=None):
        kb = script()
        kb["sources"]["pl"] = source if source is not None else {"repo": "backnotprop/plannotator"}
        kb["paragraphs"][2]["beats"].append({"kind": "repo", "headline": ["Mở thư mục", "từng cái một"], "kicker": "Theo GitHub", "from_sentence": 0,
                                             "repo": {"ref": "pl", "open": list(open_)}})
        return kb

    def beat(self, kb):
        return kb["paragraphs"][2]["beats"][-1]["repo"]

    def test_a_repo_beat_passes_and_is_planned_apart_from_the_captures(self):
        plan = m.check_script(self.repo_script())
        self.assertEqual(list(plan.refs), ["g-2b", "blog-google", "g-5a", "hco-5b"])
        self.assertEqual(plan.repos["pl"]["repo"], "backnotprop/plannotator"); self.assertIsNone(plan.repos["pl"]["branch"])
        self.assertEqual(plan.repos["pl"]["paths"], ["packages", "packages/server", "package.json"])
        self.assertEqual(plan.repos["pl"]["beats"][0]["open"], ["packages", "packages/server", "package.json"])
        self.assertEqual(plan.warnings, [])

    def test_a_branch_is_allowed_and_home_only_is_allowed(self):
        plan = m.check_script(self.repo_script([], {"repo": "a/b", "branch": "release/1.x"}))
        self.assertEqual((plan.repos["pl"]["branch"], plan.repos["pl"]["paths"]), ("release/1.x", []))

    def test_a_repo_that_is_not_owner_slash_name_is_refused(self):
        for bad in ("plannotator", "https://github.com/backnotprop/plannotator", "a/b/c", ""):
            refused(self, self.repo_script(source={"repo": bad}), "not owner/name", 'sources["pl"]')

    def test_a_source_with_both_urls_and_repo_is_refused(self):
        e = refused(self, self.repo_script(source={"repo": "a/b", "urls": ["https://github.com/a/b"]}), 'has both "urls" and "repo"')
        self.assertIn("to fix:", str(e))

    def test_a_repo_source_takes_nothing_else(self):
        refused(self, self.repo_script(source={"repo": "a/b", "open": "x"}), "unknown key(s) open", "a repo source takes: repo, branch")
        kb = self.repo_script(); kb["sources"]["g-2b"]["branch"] = "main"
        refused(self, kb, 'has "branch" but no "repo"')

    def test_a_path_that_is_empty_absolute_climbing_or_repeated_is_refused(self):
        for open_, word in (([""], "missing or empty"), (["/packages"], "is absolute"), (["a/../b"], '".."'), (["a\\b"], "backslash"),
                            (["packages", "packages"], "already opened"), (["a//b"], "empty part")):
            e = refused(self, self.repo_script(open_), word, "paragraph 3, beat 2", "open[")
            self.assertEqual(e.step, "kiem-kich-ban"); self.assertTrue(e.change)

    def test_a_parent_that_is_neither_root_nor_earlier_is_refused_and_a_chain_is_the_way_out(self):
        e = refused(self, self.repo_script(["packages", "packages/server/src"]), 'opened from "packages/server"', "neither the repo root nor an earlier entry")
        self.assertIn("to fix:", str(e)); self.assertIn("chain", e.change)
        m.check_script(self.repo_script(["packages", {"path": "packages/server/src", "chain": True}]))

    def test_more_than_five_entries_in_one_beat_are_refused(self):
        refused(self, self.repo_script(list("abcdef")), "most one beat may open is 5")
        m.check_script(self.repo_script(list("abcde")))

    def test_the_beats_of_one_repo_open_five_different_pages_at_most(self):
        kb = self.repo_script(list("abc"))
        kb["paragraphs"][3]["beats"][0] = {"kind": "repo", "headline": ["Mở thư mục", "từng cái một"], "kicker": "Theo GitHub", "repo": {"ref": "pl", "open": list("cdef")}}
        refused(self, kb, "open 6 different pages in all", 'repo "pl"')
        kb["paragraphs"][3]["beats"][0]["repo"]["open"] = list("cde")
        self.assertEqual(m.check_script(kb).repos["pl"]["paths"], list("abcde"))

    def test_a_repo_beat_needs_its_source_and_its_open_list(self):
        kb = self.repo_script(); del kb["sources"]["pl"]
        refused(self, kb, 'repo "pl" has no entry in "sources"', '"repo": "owner/name"')
        refused(self, self.repo_script(source={"urls": ["https://github.com/a/b"]}), 'sources["pl"] has no "repo"')
        kb = self.repo_script(); del self.beat(kb)["open"]
        refused(self, kb, "repo.open is missing", "[]")
        kb = self.repo_script(); kb["paragraphs"][2]["beats"][-1]["repo"] = "a/b"
        refused(self, kb, 'has no "repo" block')

    def test_a_capture_cannot_point_at_a_repo_source(self):
        kb = self.repo_script(); kb["sources"]["g-2b"] = {"repo": "a/b"}
        refused(self, kb, 'capture "g-2b" is a repo source', "repo beat")

    def test_a_repo_source_no_beat_uses_is_a_warning(self):
        kb = script(); kb["sources"]["unused"] = {"repo": "a/b"}
        self.assertEqual(m.check_script(kb).warnings, ['sources["unused"] is not used by any capture beat'])

    def test_a_recording_is_still_refused(self):
        kb = self.repo_script(); kb["paragraphs"][2]["beats"][-1]["picture"] = {"kind": "photo", "file": "x.jpg"}
        refused(self, kb, "hand-made recording or photo")


class Settings(unittest.TestCase):
    def test_every_missing_setting_is_named_at_once(self):
        problems, _ = m.settings(env={"USERPROFILE": "u"}, which=lambda t: None if t in ("node", "magick") else "/bin/" + t, exists=lambda p: False)
        text = "\n".join(problems)
        for w in ("HALCYON_PYTHON", "HALCYON_OMNIVOICE_PYTHON", "HALCYON_VOICE_PROFILES", "HALCYON_MUSIC_TRACK", "node is not on PATH", "magick is not on PATH", "playwright-core"):
            self.assertIn(w, text)
        self.assertNotIn("ffmpeg is not", text)

    def test_nothing_missing(self):
        env = {"HALCYON_PYTHON": "p", "HALCYON_OMNIVOICE_PYTHON": "o", "HALCYON_VOICE_PROFILES": "v", "HALCYON_MUSIC_TRACK": "t"}
        problems, res = m.settings(env=env, which=lambda t: "/bin/" + t, exists=lambda p: True)
        self.assertEqual(problems, [])
        self.assertEqual(res["music"], "t")


class Runner(unittest.TestCase):
    def test_a_tool_over_its_deadline_is_killed_and_its_log_kept(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(m.Refusal) as cm:
                m.run_process([sys.executable, "-c", "import time,sys; print('hello', flush=True); sys.stderr.write('still working\\n'); sys.stderr.flush(); time.sleep(60)"],
                              1.5, Path(d) / "log" / "slow", step="giong")
            self.assertEqual(cm.exception.step, "giong")
            self.assertIn("deadline", str(cm.exception))
            self.assertIn("still working", str(cm.exception))
            self.assertIn("hello", (Path(d) / "log" / "slow.out").read_text())

    def test_exit_code_and_output_are_returned(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = m.run_process([sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"], 20, Path(d) / "x")
        self.assertEqual((code, out.strip(), err.strip()), (3, "out", "err"))

    def test_warnings_are_the_lines_that_say_so(self):
        text = "frame 0\nfield A: beat 3: source chip not drawn: x\nUserWarning: something\ncontrast gate: 12 blocks measured\nunit notes: {}\nunit notes: {'a': 1}\n\nrefused nothing"
        self.assertEqual(m.warnings_in(text), ["field A: beat 3: source chip not drawn: x", "UserWarning: something", "unit notes: {'a': 1}", "refused nothing"])


def stand_ins(log, fail_at=None):
    """Four small steps that write one file each, from the previous one, and count their runs."""
    runs = {"a": 0, "b": 0, "c": 0}

    def make(name, deps):
        def run(ctx):
            log.append(name)
            runs[name] += 1
            if fail_at == name:
                raise m.Refusal(name, f"{name} is wrong", f"change {name}")
            (ctx / f"{name}.txt").write_text("".join((ctx / f"{d}.txt").read_text() for d in deps) + name)
            return [f"warn from {name}"] if name == "b" else []
        return m.Step(name, run, inputs=lambda ctx: {"deps": [(ctx / f"{d}.txt").read_text() for d in deps], "src": ctx.joinpath("src.txt").read_text()},
                      outputs=lambda ctx: [ctx / f"{name}.txt"])
    a = m.Step("a", lambda ctx: (log.append("a"), runs.__setitem__("a", runs["a"] + 1), (ctx / "a.txt").write_text((ctx / "src.txt").read_text())) and [],
               inputs=lambda ctx: {"src": (ctx / "src.txt").read_text()}, outputs=lambda ctx: [ctx / "a.txt"])
    return [a, make("b", ["a"]), make("c", ["b"])], runs


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "src.txt").write_text("one")
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def chain(self):
        return m.Chain(self.d / "state.json", self.said.append)

    def test_steps_run_in_order_and_report_seconds_and_warnings(self):
        log = []
        steps, _ = stand_ins(log)
        rows = self.chain().go(steps, self.d)
        self.assertEqual(log, ["a", "b", "c"])
        self.assertEqual([r[:2] for r in rows], [("a", "run"), ("b", "run"), ("c", "run")])
        self.assertEqual(rows[1][3], ["warn from b"])
        self.assertTrue(any("warning: warn from b" in s for s in self.said))

    def test_the_first_failure_stops_the_chain_and_names_the_step(self):
        log = []
        steps, _ = stand_ins(log, fail_at="b")
        with self.assertRaises(m.Refusal) as cm:
            self.chain().go(steps, self.d)
        self.assertEqual(cm.exception.step, "b")
        self.assertIn("to fix: change b", str(cm.exception))
        self.assertEqual(log, ["a", "b"])          # c never ran
        self.assertFalse((self.d / "c.txt").exists())

    def test_an_unexpected_error_is_named_as_a_bug_of_the_command(self):
        steps = [m.Step("boom", lambda ctx: 1 / 0, always=True)]
        with self.assertRaises(m.Refusal) as cm:
            self.chain().go(steps, self.d)
        self.assertIn("ZeroDivisionError", str(cm.exception))
        self.assertEqual(cm.exception.step, "boom")

    def test_a_second_run_reuses_finished_steps_and_says_so(self):
        log = []
        steps, runs = stand_ins(log)
        self.chain().go(steps, self.d)
        del self.said[:]
        rows = self.chain().go(steps, self.d)
        self.assertEqual(runs, {"a": 1, "b": 1, "c": 1})
        self.assertEqual([r[1] for r in rows], ["reused"] * 3)
        self.assertTrue(all("reused" in s for s in self.said))
        self.assertEqual(rows[1][3], ["warn from b"])  # the warning of the earlier run is kept

    def test_a_fix_after_a_failure_redoes_only_the_failed_step_and_what_follows(self):
        log = []
        steps, runs = stand_ins(log, fail_at="c")
        with self.assertRaises(m.Refusal):
            self.chain().go(steps, self.d)
        steps, runs2 = stand_ins(log)             # c is fixed
        self.chain().go(steps, self.d)
        self.assertEqual((runs2["a"], runs2["b"], runs2["c"]), (0, 0, 1))   # a and b were not redone

    def test_changed_input_redoes_that_step_and_the_ones_that_depend_on_it(self):
        log = []
        steps, runs = stand_ins(log)
        self.chain().go(steps, self.d)
        (self.d / "src.txt").write_text("two")
        self.chain().go(steps, self.d)
        self.assertEqual(runs, {"a": 2, "b": 2, "c": 2})

    def test_a_missing_output_or_a_failed_validity_check_redoes_the_step(self):
        log = []
        steps, runs = stand_ins(log)
        self.chain().go(steps, self.d)
        (self.d / "c.txt").unlink()
        self.chain().go(steps, self.d)
        self.assertEqual(runs["c"], 2)
        self.assertEqual(runs["b"], 1)
        steps[0].valid = lambda ctx: False
        self.chain().go(steps, self.d)
        self.assertEqual(runs["a"], 2)

    def test_an_always_step_runs_every_time(self):
        n = []
        step = m.Step("check", lambda ctx: n.append(1), always=True)
        self.chain().go([step], self.d)
        self.chain().go([step], self.d)
        self.assertEqual(len(n), 2)

    def test_a_step_that_writes_nothing_is_a_failure(self):
        step = m.Step("lazy", lambda ctx: [], inputs=lambda ctx: {}, outputs=lambda ctx: [ctx / "never.txt"])
        with self.assertRaises(m.Refusal) as cm:
            self.chain().go([step], self.d)
        self.assertIn("did not write", str(cm.exception))


class RealStepsAndPack(unittest.TestCase):
    def ctx(self):
        kb = script()
        return m.Ctx("kich-ban.json", Path(tempfile.gettempdir()) / "halcyon-run-test", m.check_script(kb), kb, {"gpu_python": "p", "music": "t", "profiles": "v"})

    def test_the_real_steps_are_ordered_cheapest_refusal_first(self):
        names = [s.name for s in m.real_steps(self.ctx())]
        self.assertEqual(names, ["kiem-kich-ban", "kiem-may", "chup:g-2b", "chup:blog-google", "chup:g-5a", "chup:hco-5b", "giong", "lap-rap", "anh", "kiem-anh", "dung", "nhac", "goi"])

    def test_the_voice_is_reused_unless_a_say_text_changes(self):
        c = self.ctx()
        voice = next(s for s in m.real_steps(c) if s.name == "giong")
        profiles = Path(tempfile.mkdtemp())
        (profiles / m.VOICE_PROFILE).mkdir()
        (profiles / m.VOICE_PROFILE / "reference.wav").write_bytes(b"x")
        c.cfg["profiles"] = str(profiles)
        before = m.sha_json(voice.inputs(c))
        c.kb["paragraphs"][0]["show"] = "other / captions"      # captions are not the voice
        self.assertEqual(m.sha_json(voice.inputs(c)), before)
        c.plan.say[0] += " thêm"
        self.assertNotEqual(m.sha_json(voice.inputs(c)), before)

    def test_capture_deadline_is_sixty_seconds_per_attempt(self):
        self.assertEqual(m.chup_deadline(["a"], None), 150)
        self.assertEqual(m.chup_deadline(["a", "b"], "h"), 390)

    def test_the_manifest_points_pictures_relative_to_the_spec(self):
        with tempfile.TemporaryDirectory() as d:
            c = m.Ctx("s.json", d, m.check_script(script()), script(), {})
            for ref in c.plan.refs:
                (c.chup / ref).mkdir(parents=True)
                m.write_json(c.chup / ref / f"{ref}.capture.json", {"entry": {"file": f"{ref}.png", "captured": "2026-11-19T10:00:00+07:00", "source": "s", "date": "19/11/2026"}})
            caps = m.merged_captures(c)["captures"]
            self.assertEqual(caps["g-2b"]["file"], "../chup/g-2b/g-2b.png")

    def test_capture_age(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as d:
            c = m.Ctx("s.json", d, m.check_script(script()), script(), {})
            (c.chup / "g-2b").mkdir(parents=True)
            m.write_json(c.chup / "g-2b" / "g-2b.capture.json", {"entry": {"captured": "2026-11-19T10:00:00+07:00"}})
            at = lambda h, mi: datetime.fromisoformat(f"2026-11-19T{h:02d}:{mi:02d}:00+07:00")
            self.assertTrue(m.capture_age_ok(c, "g-2b", at(15, 59)))
            self.assertFalse(m.capture_age_ok(c, "g-2b", at(16, 1)))
            self.assertFalse(m.capture_age_ok(c, "none", at(11, 0)))


class PackFiles(unittest.TestCase):
    def rep(self):
        kb = json.loads((FIX / "05" / "v3" / "kich-ban.json").read_text(encoding="utf-8"))
        t = json.loads((FIX / "05" / "giong" / "v3" / "giong-day-du-timing.json").read_text(encoding="utf-8"))
        say = [p["say"] for p in kb["paragraphs"]]
        return g.check_reading(say, t["words_whisper_medium"], t["beats"], APPROVED), say

    def test_the_listen_list_is_in_vietnamese(self):
        rep, _ = self.rep()
        text = m.listen_text(rep, g)
        self.assertIn("Nghe lại những chỗ này", text)
        self.assertIn("13,4 giây", text)
        self.assertIn('[tên] kịch bản nói "ChatGPT", máy nghe ra "chat GPT"', text)
        self.assertNotIn("Whisper wrote", text)
        self.assertNotIn("say \"", text)

    def test_an_empty_listen_list_still_asks_for_one_listen(self):
        text = m.listen_text({"listen": [], "approved": {}}, g)
        self.assertIn("Không có chỗ nào cần nghe riêng", text)

    def facts(self):
        rep, say = self.rep()
        rows = [("kiem-kich-ban", "run", 0.0, [], ""), ("giong", "reused", 251.0, ["voice: 3 words"], "x"), ("dung", "run", 105.5, ["note: x"], "")]
        probe = dict(video=dict(codec="h264", width=1080, height=1920, frames=855), audio=dict(codec="aac"), duration=28.5)
        return dict(id="05", title="Gemini giữ chat 2 tháng", date_iso="2026-11-19", run_dir="X:/run", slug="gemini", final_mp4="a-co-nhac.mp4", plain_mp4="a.mp4",
                    tiktok_mp4="a-tiktok.mp4", post_file="noi-dung-dang.txt", music_json="a-co-nhac.json", duration_text="28,5 s", say=say, listen_count=len(rep["listen"]),
                    sources=[dict(ref="g-2b", url="https://support.google.com/x", http=200, captured="2026-11-19T10:00:00+07:00")], hashes={"script": "ab" * 32},
                    probe=probe, probe_text=m.probe_text(probe), music_text="OK bed -34 LUFS | loudness -15.0 -> -15.1 LUFS", rows=rows, total_s=400.0,
                    archive_cmd="py -3.12 luu-tru-video.py luu-tru.json --duyet")

    def test_the_summary_leads_with_what_the_owner_does_and_holds_the_evidence(self):
        md, data = m.summary_texts(self.facts())
        self.assertLess(md.index("Anh duyệt trong một phút"), md.index("Các bước"))
        for w in ("a-co-nhac.mp4", "nghe-lai.txt", "anh-tong-quan.jpg", "Máy chưa kiểm được", "dùng lại", "251.0 (lần trước)", "voice: 3 words", "(từ lần chạy trước)",
                  "https://support.google.com/x", "2026-11-19T10:00:00+07:00", "ab" * 32, "h264 1080x1920, 855 khung", "luu-tru-video.py"):
            self.assertIn(w, md)
        self.assertEqual([s["step"] for s in data["steps"]], ["kiem-kich-ban", "giong", "dung"])
        self.assertEqual(data["sources"][0]["ref"], "g-2b")

    def test_the_archive_manifest_waits_for_the_owner_and_fills_the_eight_folders(self):
        man = m.archive_manifest(self.facts())
        self.assertFalse(man["duyet"])
        self.assertTrue(all(it["cho_duyet"] for it in man["muc"]))
        self.assertEqual(man["thu_muc"], "05 - 2026-11-19 - Gemini giữ chat 2 tháng")
        dests = {it["dich"].split("/")[0] for it in man["muc"]}
        self.assertEqual(dests, {f"{n} - {t}" for n, t in ((1, "Video đăng"), (2, "Nội dung đăng"), (3, "Âm thanh"), (4, "Kịch bản và phụ đề"), (5, "Hình ảnh"), (6, "Nguồn"), (7, "Thông số dựng"))})
        self.assertIn("goi-duyet/noi-dung-dang.txt", [it["nguon"] for it in man["muc"]])
        self.assertEqual(m.safe_name('a: b/c?"'), "a bc")

    def test_render_checks(self):
        ok = dict(video=dict(codec="h264", width=1080, height=1920, frames=855), audio=dict(codec="aac"), duration=28.5)
        self.assertEqual(m.check_render(ok, 28.5), [])
        bad = dict(video=dict(codec="h264", width=1080, height=1080, frames=800), audio=None, duration=20.0)
        text = " ".join(m.check_render(bad, 28.5))
        for w in ("1080x1080", "800 frames", "855", "no audio", "20.00 s"):
            self.assertIn(w, text)


class RepoWiring(unittest.TestCase):
    """The repo recording inside the chain: the `quay:<ref>` step, what its reuse and the builder's reuse hash, the second witness in `kiem-anh`, the pack."""

    def plan_script(self):
        kb = RepoScriptChecks().repo_script(["packages", {"path": "packages/server/src", "chain": True}, "package.json"])
        return kb

    def ctx(self, run="halcyon-run-test"):
        kb = self.plan_script()
        return m.Ctx("kich-ban.json", Path(tempfile.gettempdir()) / run, m.check_script(kb), kb, {"gpu_python": "p", "music": "t", "profiles": "v"})

    def test_the_recording_comes_after_the_captures_and_before_the_voice(self):
        names = [s.name for s in m.real_steps(self.ctx())]
        self.assertEqual(names[:7], ["kiem-kich-ban", "kiem-may", "chup:g-2b", "chup:blog-google", "chup:g-5a", "chup:hco-5b", "quay:pl"])
        self.assertEqual(names[7], "giong")

    def test_a_script_without_a_repo_beat_has_no_such_step(self):
        c = m.Ctx("k.json", Path(tempfile.gettempdir()) / "halcyon-run-test", m.check_script(script()), script(), {"gpu_python": "p", "music": "t", "profiles": "v"})
        self.assertFalse([s for s in m.real_steps(c) if s.name.startswith("quay")])

    def test_the_arguments_and_the_deadline_follow_the_pages(self):
        c = self.ctx()
        self.assertEqual(m.quay_open_args(c.plan.repos["pl"]), ["--open", "packages", "--open", "packages/server/src#chain", "--open", "package.json"])
        self.assertEqual(m.quay_deadline(c.plan.repos["pl"]["paths"]), 90 * 4 + 30)
        self.assertEqual(m.quay_deadline([]), 120)

    def test_the_step_reuses_until_the_pages_the_tools_or_the_age_change(self):
        c = self.ctx()
        st = next(s for s in m.real_steps(c) if s.name == "quay:pl")
        before = m.sha_json(st.inputs(c))
        c.plan.repos["pl"]["paths"].append("docs"); c.plan.repos["pl"]["chain"]["docs"] = False
        self.assertNotEqual(m.sha_json(st.inputs(c)), before)
        c = self.ctx(); c.plan.repos["pl"]["chain"]["packages"] = True
        self.assertNotEqual(m.sha_json(st.inputs(c)), before)       # the same paths opened another way are another recording
        c = self.ctx(); c.plan.repos["pl"]["branch"] = "next"
        self.assertNotEqual(m.sha_json(st.inputs(c)), before)

    def test_the_recording_is_taken_again_after_six_hours(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as d:
            c = m.Ctx("s.json", d, m.check_script(self.plan_script()), self.plan_script(), {})
            (c.quay / "pl").mkdir(parents=True)
            m.write_json(c.quay / "pl" / "quay.json", {"captured": "2026-11-20T10:00:00+07:00"})
            at = lambda h, mi: datetime.fromisoformat(f"2026-11-20T{h:02d}:{mi:02d}:00+07:00")
            self.assertTrue(m.quay_age_ok(c, "pl", at(15, 59))); self.assertFalse(m.quay_age_ok(c, "pl", at(16, 1)))
            self.assertFalse(m.quay_age_ok(c, "none", at(11, 0)))
            m.write_json(c.quay / "pl" / "quay.json", {})
            self.assertFalse(m.quay_age_ok(c, "pl", at(11, 0)))

    def test_a_refusal_of_the_recorder_stops_the_chain_with_a_fix(self):
        cay = "cay: path: `packages/servr` is not in a/b at `abc1234`; `packages` holds: ai, server\nto fix: pick one of those (`packages/<name>`)\n"
        e = m.quay_refusal("pl", 1, "", cay)
        self.assertEqual(e.step, "quay:pl"); self.assertIn("packages/servr", e.reason); self.assertIn("pick one of those", e.change)
        self.assertNotIn("to fix:", e.reason)
        wall = "quay: https://github.com/a/b: wall: GitHub sent the page to /login, a sign-in page (one retry)\nquay: https://github.com/a/b: wall: GitHub sent the page to /login, a sign-in page\n"
        e = m.quay_refusal("pl", 1, "", wall)
        self.assertIn("/login", e.reason); self.assertIn("run the same command later", e.change); self.assertEqual(e.reason.count("quay:"), 1)
        e = m.quay_refusal("pl", 1, "", "quay: https://github.com/a/b/tree/main/x: listing: GitHub lists 3 entries and the page shows 2\n")
        self.assertIn("open", e.change)
        self.assertIn("without a message", m.quay_refusal("pl", 7, "", "").reason)

    def test_the_step_runs_the_recorder_with_the_pages_and_no_token(self):
        c = self.ctx("halcyon-run-test-step"); seen = {}
        def fake(cmd, deadline, log, env=None, cwd=None, step="?"):
            seen.update(cmd=[str(x) for x in cmd], deadline=deadline, env=env, step=step); return 1, "", "quay: https://github.com/a/b: status: HTTP 404 (200 needed)\n"
        real, m.run_process = m.run_process, fake
        try:
            with self.assertRaises(m.Refusal) as cm:
                m.step_quay(c, "pl")
        finally:
            m.run_process = real
        self.assertEqual(cm.exception.step, "quay:pl")
        self.assertEqual(seen["step"], "quay:pl"); self.assertEqual(seen["deadline"], 390); self.assertIsNone(seen["env"])
        cmd = seen["cmd"]
        self.assertEqual(cmd[4:6], ["run", "--repo"]); self.assertIn("backnotprop/plannotator", cmd); self.assertIn("packages/server/src#chain", cmd)
        self.assertNotIn("--branch", cmd)

    def run_with_voice(self, d, say_extra=""):
        """A run folder that holds the voice timing of video 05 for the script's own `say` texts (the fixture's words stand in for the voice)."""
        kb = script(); kb["sources"]["pl"] = {"repo": "a/b"}
        kb["paragraphs"][2]["beats"] = [{"kind": "repo", "headline": ["Mở thư mục", "từng cái một"], "kicker": "Theo GitHub", "level": "FOOT", "repo": {"ref": "pl", "open": ["packages", "docs"]}}]
        plan = m.check_script(kb)
        timing = json.loads((FIX / "05" / "giong" / "v3" / "giong-day-du-timing.json").read_text(encoding="utf-8"))
        for b, s in zip(timing["beats"], plan.say):
            b["text_spoken"] = g.voice_text(s) + say_extra
        (Path(d) / "cong-viec" / "giong").mkdir(parents=True)
        m.write_json(Path(d) / "cong-viec" / "giong" / "giong-day-du-timing.json", timing)
        return kb, plan

    def test_chi_kiem_refuses_a_repo_beat_too_short_for_its_pages_and_names_the_seconds(self):
        with tempfile.TemporaryDirectory() as d:
            kb, plan = self.run_with_voice(d)
            with self.assertRaises(m.Refusal) as cm:
                m.check_repo_seconds(kb, plan, d)
            e = cm.exception
            self.assertEqual(e.step, "kiem-kich-ban"); self.assertIn("pages need at least", e.reason); self.assertIn("s (the home page", e.reason); self.assertIn("lengthen", e.change)
            self.assertFalse(e.reason.startswith("kich-ban:"))

    def test_the_seconds_are_not_checked_without_a_voice_made_from_these_say_texts(self):
        with tempfile.TemporaryDirectory() as d:
            kb = RepoScriptChecks().repo_script(["packages"])
            self.assertFalse(m.check_repo_seconds(kb, m.check_script(kb), d))           # no voice yet: the seconds are not known
        with tempfile.TemporaryDirectory() as d:
            kb, plan = self.run_with_voice(d, say_extra=" thêm")
            self.assertFalse(m.check_repo_seconds(kb, plan, d))                          # another voice: its timing says nothing about this script
        self.assertFalse(m.check_repo_seconds(script(), m.check_script(script()), tempfile.gettempdir()))

    def spec_with_repo(self, d, still=b"png-1"):
        base = Path(d)
        (base / "q").mkdir(parents=True, exist_ok=True)
        (base / "q" / "0.png").write_bytes(still); (base / "q" / "1.png").write_bytes(b"png-2")
        m.write_json(base / "q" / "quay.json", {"scale": 2, "viewport": {"width": 1280}, "pages": [{"path": "", "picture": "0.png"}, {"path": "apps", "picture": "1.png"}]})
        return {"manifest": "q/quay.json", "kind": "repo", "walk": [{"page": "", "a": 0.0}, {"page": "apps", "a": 4.0, "via": "tap"}]}

    def test_the_builder_reuse_hash_covers_the_manifest_and_every_still(self):
        with tempfile.TemporaryDirectory() as d:
            lay = self.spec_with_repo(d)
            before = m.repo_picture_hashes(Path(d), lay)
            self.assertEqual(sorted(before), ["q/0.png", "q/1.png", "q/quay.json"])
            (Path(d) / "q" / "1.png").write_bytes(b"png-changed")
            after = m.repo_picture_hashes(Path(d), lay)
            self.assertEqual([k for k in before if before[k] != after[k]], ["q/1.png"])
            m.write_json(Path(d) / "q" / "quay.json", {"scale": 2, "viewport": {"width": 1280}, "pages": [{"path": "", "picture": "0.png"}, {"path": "apps", "picture": "1.png"}], "commit": "x"})
            self.assertNotEqual(m.repo_picture_hashes(Path(d), lay)["q/quay.json"], after["q/quay.json"])

    def test_the_builder_inputs_carry_the_repo_hashes_and_the_camera_code(self):
        with tempfile.TemporaryDirectory() as d:
            c = m.Ctx("s.json", Path(d) / "run", m.check_script(script()), script(), {})
            c.dung.mkdir(parents=True)
            lay = self.spec_with_repo(c.dung)
            (c.dung / "v.wav").write_bytes(b"w"); m.write_json(c.dung / "t.json", {"duration_s": 1, "beats": []})
            m.write_json(c.spec, {"voice": "v.wav", "timing": "t.json", "beats": [{"id": "1", "picture": lay}]})
            inputs = m.builder_inputs(c)
            self.assertEqual(sorted(inputs["pictures"]), ["q/0.png", "q/1.png", "q/quay.json"])
            self.assertIn("halcyon_repo_walk.py", inputs["builder"])

    def plan_of(self, frames):
        return {"beats": [{"id": "1", "kind": "repo", "notes": {"segments": [{"page": p, "frames": f} for p, f in frames]}}]}

    def spec_of(self):
        return {"beats": [{"id": "1", "picture": {"kind": "repo", "walk": [{"page": ""}, {"page": "apps"}, {"page": "apps/x"}]}}, {"id": "2", "picture": {"kind": "same_as", "beat": "1"}}]}

    def test_the_second_witness_wants_every_page_in_order_and_long_enough(self):
        ok = self.plan_of([("", [0, 130]), ("apps", [130, 200]), ("apps/x", [200, 230])])
        self.assertEqual(m.repo_plan_problems(self.spec_of(), ok), [])
        self.assertIn("shows the pages", m.repo_plan_problems(self.spec_of(), self.plan_of([("", [0, 130]), ("apps/x", [130, 200]), ("apps", [200, 230])]))[0])
        self.assertIn("shows the pages", m.repo_plan_problems(self.spec_of(), self.plan_of([("", [0, 130]), ("apps", [130, 230])]))[0])
        short = m.repo_plan_problems(self.spec_of(), self.plan_of([("", [0, 130]), ("apps", [130, 200]), ("apps/x", [200, 210])]))
        self.assertEqual(len(short), 1); self.assertIn('page "apps/x" is on screen 10 frames', short[0])
        self.assertIn("is not a repo beat", m.repo_plan_problems(self.spec_of(), {"beats": [{"id": "1", "kind": "capture"}]})[0])
        self.assertEqual(m.repo_plan_problems({"beats": [{"id": "1", "picture": {"kind": "capture"}}]}, {"beats": []}), [])

    def facts(self):
        f = PackFiles().facts()
        f["repos"] = [dict(ref="pl", repo="backnotprop/plannotator", branch="main", commit="edd45372aaaabbbbccccddddeeeeffff00001111", captured="2026-11-20T10:05:00+07:00",
                           pages=[dict(path="", address="https://github.com/backnotprop/plannotator", status=200, seconds=7.1),
                                  dict(path="apps", address="https://github.com/backnotprop/plannotator/tree/main/apps", status=200, seconds=5.0)])]
        return f

    def test_the_summary_lists_the_pages_the_commit_and_what_the_machine_could_not_check(self):
        md, data = m.summary_texts(self.facts())
        for w in ("## Nguồn đã quay (GitHub)", "backnotprop/plannotator", "edd45372aaaa", "2026-11-20T10:05:00+07:00", "https://github.com/backnotprop/plannotator/tree/main/apps", "HTTP 200, 5.0 giây",
                  "khớp danh sách của chính GitHub", "không phải quay màn hình trực tiếp", "anh-tong-quan.jpg"):
            self.assertIn(w, md)
        self.assertEqual(data["repos"][0]["commit"][:7], "edd4537")
        self.assertNotIn("Nguồn đã quay", m.summary_texts(PackFiles().facts())[0])

    def test_the_recording_goes_to_the_source_folder_of_the_archive_per_repo(self):
        man = m.archive_manifest(self.facts())
        it = next(x for x in man["muc"] if x["nguon"] == "cong-viec/quay/pl/*")
        self.assertEqual(it["dich"], "6 - Nguồn/anh-quay-repo"); self.assertEqual(it["tien_to"], "halcyon-05-pl-"); self.assertTrue(it["cho_duyet"])
        self.assertFalse([x for x in m.archive_manifest(PackFiles().facts())["muc"] if "quay" in x["nguon"]])


if __name__ == "__main__":
    unittest.main()
