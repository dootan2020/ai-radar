"""Hand-written guides: the loader refuses an unapproved file, the bypasses stay narrow, no machine step rewrites one."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from radar import summary_gemini as gemini, summary_pipeline, translate
from radar.huong_dan import KIND, GuideError, guide_story, inject, is_guide, load_guides, validate
from radar.newsroom_decisions import apply_decisions
from radar.search_index import search_payload
from radar.story_pages import gated_stories, render_site, render_story_page

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "huong-dan"
NAME = "hd-thu-nghiem-fixture"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def row():
    return json.loads((FIXTURES / f"{NAME}.json").read_text(encoding="utf-8"))


def machine_story(story_id="abc123", **overrides):
    story = {"id": story_id, "title": "Machine story", "url": "https://publisher.example/a",
             "published_at": "2026-11-20T01:00:00Z", "kind": "product", "source_count": 1,
             "coverage": [{"source": "pub", "publisher": "Pub", "url": "https://publisher.example/a"}]}
    story.update(overrides)
    return story


class LoaderTests(unittest.TestCase):
    def test_fixture_loads_as_a_desk_shaped_story(self):
        stories, errors = load_guides(FIXTURES, NOW)
        self.assertEqual(errors, [])
        story = stories[0]
        self.assertEqual((story["id"], story["kind"]), (NAME, KIND))
        self.assertEqual(story["url"], f"https://hco.news/tin/{NAME}/")
        self.assertEqual(story["key_points_source"], "nguoi-viet")
        self.assertTrue(is_guide(story))

    def test_every_committed_guide_loads(self):
        stories, errors = load_guides(ROOT / "data" / "huong-dan", NOW)
        self.assertEqual(errors, [], "a guide file in data/huong-dan/ is refused; fix it before it reaches main")

    def refused(self, mutate, expect):
        data = row()
        mutate(data)
        with self.assertRaises(GuideError) as raised:
            validate(data, NAME, NOW)
        self.assertIn(expect, str(raised.exception))

    def test_a_file_without_approval_is_refused_with_a_clear_message(self):
        self.refused(lambda d: d.pop("approval"), "approval is missing")
        with tempfile.TemporaryDirectory() as directory:
            data = row()
            del data["approval"]
            Path(directory, f"{NAME}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            stories, errors = load_guides(directory, NOW)
        self.assertEqual(stories, [])
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith(f"{NAME}.json: approval is missing"), errors)

    def test_incomplete_or_future_approval_is_refused(self):
        self.refused(lambda d: d["approval"].pop("words"), "approval is incomplete")
        self.refused(lambda d: d["approval"].update(approved_by=" "), "approval is incomplete")
        self.refused(lambda d: d["approval"].update(approved_at="2026-11-20"), "approval is incomplete")
        self.refused(lambda d: d["approval"].update(approved_at="2027-01-01T00:00:00+07:00"), "approval is incomplete")
        self.refused(lambda d: d["approval"].update(extra="x"), "approval is incomplete")

    def test_other_malformed_files_are_refused(self):
        self.refused(lambda d: d.update(id="thu-nghiem"), "id must match")
        self.refused(lambda d: d.update(key_points=["Một.", "Hai."]), "key_points")
        self.refused(lambda d: d.update(summary_sources=[]), "summary_sources")
        self.refused(lambda d: d.update(body=[{"type": "video", "text": "x"}]), "body[0]")
        self.refused(lambda d: d["body"].append({"type": "image", "src": "http://x/y.png", "alt": "a"}), "src")
        self.refused(lambda d: d["body"].append({"type": "image", "src": "assets/huong-dan/a.png"}), "alt")
        self.refused(lambda d: d.update(published_at="2027-01-01T00:00:00+07:00"), "published_at")
        self.refused(lambda d: d.update(surprise=1), "unknown field")

    def test_inject_is_idempotent_and_withdraws_a_guide_whose_file_is_gone(self):
        guide = load_guides(FIXTURES, NOW)[0]
        payload = {"stories": [machine_story()]}
        inject(payload, guide)
        inject(payload, guide)
        self.assertEqual([s["id"] for s in payload["stories"]], ["abc123", NAME])
        inject(payload, [])
        self.assertEqual([s["id"] for s in payload["stories"]], ["abc123"])


class GateTests(unittest.TestCase):
    def setUp(self):
        self.guide = load_guides(FIXTURES, NOW)[0][0]

    def test_guide_passes_the_decision_gate_without_any_decision_and_other_stories_do_not(self):
        payload = {"stories": [machine_story(), deepcopy(self.guide)], "sections": {"hot": ["abc123", NAME]}}
        result = apply_decisions(payload, None)
        self.assertEqual([s["id"] for s in result["stories"]], [NAME])
        self.assertEqual(result["sections"], {"hot": [NAME]})
        self.assertEqual(result["stories"][0]["body"], self.guide["body"])

    def test_the_bypass_needs_the_kind_the_source_and_the_loader_flag(self):
        for mutate in (lambda s: s.pop("approved"), lambda s: s.update(approved="yes"),
                       lambda s: s.update(kind="product"), lambda s: s.update(source_id="elsewhere"),
                       lambda s: s.update(key_points=["Một."])):
            story = deepcopy(self.guide)
            mutate(story)
            self.assertEqual(apply_decisions({"stories": [story]}, None)["stories"], [])
        # A machine story that merely claims the kind is held like any other.
        claimed = machine_story(kind=KIND)
        self.assertEqual(apply_decisions({"stories": [claimed]}, None)["stories"], [])

    def test_story_pages_exist_only_for_guides_without_decisions(self):
        archive = {NAME: deepcopy(self.guide), "abc123": machine_story()}
        self.assertEqual(sorted(gated_stories(archive, None)), [NAME])
        forged = deepcopy(self.guide)
        forged.pop("approved")
        self.assertEqual(gated_stories({NAME: forged}, None), {})

    def test_a_withdrawn_guide_loses_its_page_and_search_entry_though_the_archive_keeps_it(self):
        archive = {NAME: deepcopy(self.guide), "abc123": machine_story()}
        payload = {"generated_at": "2026-11-20T00:00:00Z", "stories": [], "sources": []}
        with patch("radar.huong_dan.withdrawn_ids", return_value=frozenset({NAME})):
            self.assertFalse(is_guide(self.guide))
            self.assertEqual(gated_stories(archive, None), {})
            self.assertEqual(search_payload(payload, archive, None)["stories"], [])
            self.assertEqual(apply_decisions({"stories": [deepcopy(self.guide)]}, None)["stories"], [])
            with tempfile.TemporaryDirectory() as directory:
                shutil.copy(FIXTURES / f"{NAME}.json", directory)
                self.assertEqual(load_guides(directory, NOW), ([], []))

    def test_the_committed_withdrawal_list_names_the_removed_video_chain_guide(self):
        from radar.huong_dan import withdrawn_ids
        self.assertIn("hd-day-chuyen-video-halcyon", withdrawn_ids())
        self.assertFalse((ROOT / "data" / "huong-dan" / "hd-day-chuyen-video-halcyon.json").exists())

    def test_search_indexes_an_archived_guide_only_with_approval(self):
        payload = {"generated_at": "2026-11-20T00:00:00Z", "stories": [], "sources": []}
        forged = deepcopy(self.guide)
        forged.pop("approved")
        found = search_payload(payload, {NAME: self.guide, "x1": machine_story("x1")}, None)
        self.assertEqual([r["id"] for r in found["stories"]], [NAME])
        self.assertEqual(search_payload(payload, {NAME: forged}, None)["stories"], [])

    def test_the_page_carries_label_body_sources_and_no_original_link(self):
        page = render_story_page(self.guide)
        for needle in ('<p class="story-kicker">Hướng dẫn</p>', '<h2 class="guide-h2">Trước khi bắt đầu</h2>',
                       '<ol class="guide-steps">', '<pre tabindex="0"><code>mkdir -p thu-nghiem',
                       '<code>echo xin chao</code>', '<strong>Đây là nội dung giả cho kiểm thử.</strong>',
                       'src="https://hco.news/assets/huong-dan/thu-nghiem-man-hinh.svg"',
                       'https://example.com/tai-lieu-thu-nghiem', f'https://hco.news/tin/{NAME}/'):
            self.assertIn(needle, page)
        self.assertNotIn("story-origin-cta", page)
        self.assertNotIn("Đọc bài gốc", page)
        self.assertNotIn("Translated", page)

    def test_a_script_in_a_guide_is_escaped(self):
        story = deepcopy(self.guide)
        story["body"].append({"type": "paragraph", "text": "<script>alert(1)</script> **b**"})
        story["body"].append({"type": "code", "text": "<img src=x onerror=alert(1)>"})
        page = render_story_page(story)
        article = page[page.index('<article class="story-article"'):page.index("</article>")]
        self.assertNotIn("<script>alert", article)
        self.assertNotIn("<img src=x", article)

    def test_render_site_writes_the_guide_page_and_sitemap_entry_and_nothing_for_a_machine_story(self):
        with tempfile.TemporaryDirectory() as directory:
            count = render_site({NAME: self.guide, "abc123": machine_story()}, directory, decisions=None)
            self.assertEqual(count, 1)
            self.assertTrue((Path(directory) / "tin" / NAME / "index.html").is_file())
            self.assertFalse((Path(directory) / "tin" / "abc123").exists())
            self.assertIn(f"/tin/{NAME}/", (Path(directory) / "sitemap.xml").read_text(encoding="utf-8"))


class ApprovalStaysInTheFileTests(unittest.TestCase):
    def test_no_published_projection_holds_the_approver_or_his_words(self):
        from radar import site_payload
        data = row()
        secrets = [data["approval"]["approved_by"], data["approval"]["words"], data["approval"]["approved_at"],
                   '"approval"']
        guide = load_guides(FIXTURES, NOW)[0]
        payload = {"schema_version": 2, "generated_at": "2026-11-20T05:00:00Z", "sources": [], "repos": [],
                   "events": [], "live": [], "stories": [machine_story()], "sections": {}}
        inject(payload, guide)
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"RADAR_NEWSROOM_DECISIONS": str(Path(directory) / "none.json")}):
            site = Path(directory) / "site"
            (site / "data").mkdir(parents=True)
            site_payload.write_site_snapshot(payload, site / "data" / "radar.json")
            published = {p.name: p.read_text(encoding="utf-8") for p in (site / "data").iterdir()}
            ui = json.loads(published["radar-ui.json"])
            archive = {s["id"]: s for s in ui["stories"]}
            render_site(archive, site, decisions=None)
            for page in (site / "tin").rglob("*.html"):
                published[str(page.relative_to(site))] = page.read_text(encoding="utf-8")
            published["sitemap.xml"] = (site / "sitemap.xml").read_text(encoding="utf-8")
        self.assertTrue({"radar.json", "radar-ui.json", "radar-window.json", "radar-head.json",
                         "radar-search.json"} <= set(published), sorted(published))
        self.assertTrue(any(name.startswith("tin") and NAME in name for name in published), sorted(published))
        # radar-intake.json is the newsroom's unfiltered copy, never deployed, but it too carries only the flag.
        for name, text in published.items():
            for secret in secrets:
                self.assertNotIn(secret, text, name)
        self.assertIn('"approved":true', published["radar-ui.json"].replace(" ", ""))
        guide_row = next(s for s in ui["stories"] if s["id"] == NAME)
        self.assertNotIn("approval", guide_row)
        self.assertEqual(guide_row["body"], guide[0]["body"])


class MachineStepsLeaveGuidesAloneTests(unittest.TestCase):
    def test_translate_never_touches_a_guide(self):
        guide = load_guides(FIXTURES, NOW)[0][0]
        story = deepcopy(guide)
        story["title"] = "Cach giao viec cho tro ly AI trong nam buoc"      # no diacritics: the model would treat it as English
        story["title_vi"] = "giữ nguyên"
        payload = {"stories": [story, machine_story()], "live": [], "repos": []}
        before = deepcopy(story)
        translate.apply(payload, {})
        self.assertEqual(payload["stories"][0], before)
        self.assertNotIn(NAME, [obj.get("id") for obj, _src, _dst in translate.targets(payload)])

    def test_summarize_never_touches_a_guide(self):
        guide = load_guides(FIXTURES, NOW)[0][0]
        payload = {"generated_at": "2026-11-20T05:00:00Z", "stories": [deepcopy(guide)], "sources": []}
        before = deepcopy(payload["stories"][0])
        with tempfile.TemporaryDirectory() as directory:
            stats, _ = summary_pipeline.summarize_payload(
                payload, {}, config=gemini.Config(), article_inputs={},
                ledger_path=Path(directory) / "ledger.json", now=lambda: 100000.0)
        self.assertEqual(stats["desk_written"], 1)
        self.assertEqual(payload["stories"][0], before)


@unittest.skipUnless(shutil.which("node"), "Node required for offline reader rendering")
class ReaderRenderingTests(unittest.TestCase):
    def test_modal_and_page_show_label_and_body_and_hide_the_original_link(self):
        story_js = (ROOT / "site" / "story.js").as_uri()
        guide = guide_story(row())
        program = f"""
import {{ renderStoryHTML }} from {json.dumps(story_js)};
const story = {json.dumps(guide, ensure_ascii=False)};
console.log(JSON.stringify({{page: renderStoryHTML(story, new Map(), {{isPage: true}}),
  modal: renderStoryHTML(story, new Map(), {{isModal: true}}),
  other: renderStoryHTML({{...story, kind: 'product', body: undefined}}, new Map(), {{isPage: true}})}}));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", program], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        for surface in ("page", "modal"):
            html = out[surface]
            for needle in ('<p class="story-kicker">Hướng dẫn</p>', '<h2 class="guide-h2">Trước khi bắt đầu</h2>',
                           '<ol class="guide-steps">', '<code>echo xin chao</code>', "<pre tabindex=\"0\">",
                           'https://example.com/tai-lieu-thu-nghiem'):
                self.assertIn(needle, html, surface)
            self.assertNotIn("story-origin-cta", html, surface)
            self.assertIn("assets/huong-dan/thu-nghiem-man-hinh.svg", html)
        self.assertNotIn("story-kicker", out["other"])
        self.assertIn("story-origin-cta", out["other"])

    def test_every_feed_card_and_row_carries_the_label_on_its_source_line(self):
        feed = (ROOT / "site" / "feed.js").read_text(encoding="utf-8")
        line = feed[feed.index("const srcOf = st =>"):]
        line = line[:line.index("\n")]
        self.assertIn("st.kind === 'huong-dan' ? `Hướng dẫn · ${name}`", line)
        self.assertIn("'hco-huong-dan': 'Halcyon'", feed)


if __name__ == "__main__":
    unittest.main()
