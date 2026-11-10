"""Covers for stories without a picture: what they show, and that they only ever fill a gap."""

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar import covers  # noqa: E402
from radar.images import ImageCache, resolve_story_image  # noqa: E402

NODE = shutil.which("node")
FACTS = (ROOT / "covers" / "lib" / "facts.mjs").as_uri()
SOURCES = [
    {"id": "hn-front", "name": "Hacker News", "publisher": "hacker-news"},
    {"id": "verge-ai", "name": "The Verge AI", "publisher": "the-verge"},
    {"id": "techcrunch-ai", "name": "TechCrunch AI", "publisher": "techcrunch"},
]


def story(sid, **fields):
    base = {"id": sid, "title": "", "url": f"https://example.com/{sid}", "kind": "product",
            "coverage": [{"source": "verge-ai", "url": f"https://example.com/{sid}"}]}
    base.update(fields)
    return base


def facts_of(stories):
    script = (f"import {{ factsOf }} from {json.dumps(FACTS)};"
              "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const r=JSON.parse(s);"
              "const src=new Map(r.sources.map(x=>[x.id,x]));"
              "process.stdout.write(JSON.stringify(r.stories.map(st=>factsOf(st,src))));});")
    proc = subprocess.run([NODE, "--no-warnings", "--input-type=module", "-e", script], cwd=ROOT, check=True,
                          input=json.dumps({"stories": stories, "sources": SOURCES}), capture_output=True,
                          text=True, encoding="utf-8")
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "Node required for the cover facts")
class HeroOrderTest(unittest.TestCase):
    def test_figure_then_name_then_outlet(self):
        figure, name, outlet = facts_of([
            story("a", title="DeepX claims inference at less than 5 W",
                  editorial_headline_vi="DeepX hoàn tất thiết kế chip dưới 5 W",
                  key_points=["Vi mạch chạy mô hình AI tới 100 tỷ tham số ở mức dưới 5 W."]),
            story("b", title="Medium’s new app brings AI into writing",
                  editorial_headline_vi="Medium ra mắt ứng dụng viết có trợ lý AI",
                  key_points=["Công cụ hoạt động miễn phí trên web."]),
            story("c", title="AI chip financing hits a wall",
                  editorial_headline_vi="Nhà đầu tư tìm cách bán nợ trung tâm dữ liệu",
                  key_points=["Các khoản vay kéo dài hơn vòng đời của chip."]),
        ])
        self.assertEqual(figure["hero"], {"type": "figure", "value": "100", "unit": "tỷ tham số"})
        self.assertEqual(name["hero"], {"type": "name", "text": "Medium"})
        self.assertEqual(outlet["hero"], {"type": "outlet", "text": "The Verge"})

    def test_uncertain_names_fall_back_to_the_outlet(self):
        # "Big Tech" is a generic phrase and "TK" too short to be sure of: neither may be presented as the subject.
        (f,) = facts_of([story("d", title="Ex-official is using AI to take on Big Tech with TK",
                               editorial_headline_vi="Cựu quan chức dùng AI hỗ trợ kiện Big Tech bằng TK",
                               key_points=["Văn phòng có thể chỉ có 10 người cho một vụ kiện."])])
        self.assertEqual(f["hero"]["type"], "outlet")
        self.assertEqual(f["names"], [])

    def test_counts_never_reach_a_cover(self):
        # Many sources and many Hacker News points, but no figure in the story's own text: no count is shown.
        (f,) = facts_of([story("e", kind="forum", source_count=7, title="a thread",
                               url="https://blog.example.org/post", editorial_headline_vi="một bài viết",
                               coverage=[{"source": "hn-front", "url": "https://blog.example.org/post",
                                          "metrics": {"points": 812, "comments": 340}}])])
        self.assertEqual(f["hero"], {"type": "outlet", "text": "blog.example.org"})
        self.assertNotIn("812", json.dumps(f))
        self.assertNotIn("7", json.dumps({k: v for k, v in f.items() if k not in {"id", "face"}}))
        drawing = (ROOT / "covers" / "templates" / "con-so.html").read_text(encoding="utf-8")
        drawing += (ROOT / "covers" / "templates" / "cover.js").read_text(encoding="utf-8")
        for word in ("nguồn đưa tin", "điểm Hacker News", "points", "sourceCount"):
            self.assertNotIn(word, drawing)


class FillOnlyTheGapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name)
        (self.site / "assets" / "cover").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, sid, digest="0123456789"):
        entry = {"src": f"assets/cover/{sid}-{digest}.png", "tall": f"assets/cover/{sid}-{digest}-t.png", "hero": "name"}
        for key in ("src", "tall"):
            (self.site / entry[key]).write_bytes(b"png")
        return entry

    def test_photos_and_ai_illustrations_are_never_replaced(self):
        photo = {"src": "https://example.com/p.jpg", "via": "og:image", "kind": "photo"}
        ai = {"src": "assets/ai/ai1.jpg", "via": "ai", "kind": "photo"}
        stories = [{"id": "p1", "image": dict(photo)}, {"id": "ai1", "image": dict(ai)}, {"id": "n1"},
                   {"id": "old1", "image": {"src": "assets/cover/old1-aaaaaaaaaa.png", "via": "cover", "kind": "cover"}}]
        drawn = {sid: self.entry(sid) for sid in ("p1", "ai1", "n1", "old1")}
        counts = covers.attach_covers(stories, drawn, self.site)
        self.assertEqual(stories[0]["image"], photo)
        self.assertEqual(stories[1]["image"], ai)
        for st in stories[2:]:
            self.assertEqual(st["image"], {"src": drawn[st["id"]]["src"], "tall": drawn[st["id"]]["tall"],
                                           "via": "cover", "kind": "cover"})
        self.assertEqual(counts["attached"], 2)

    def test_a_cover_that_was_not_drawn_again_is_dropped(self):
        stories = [{"id": "s1", "image": {"src": "assets/cover/s1-aaaaaaaaaa.png", "via": "cover", "kind": "cover"}}]
        covers.attach_covers(stories, {}, self.site)
        self.assertNotIn("image", stories[0])

    def test_prune_keeps_current_covers_and_removes_superseded_ones(self):
        keep = self.entry("s1", "1111111111")
        self.entry("s1", "2222222222")
        self.entry("gone", "3333333333")
        (self.site / "assets" / "cover" / "README.txt").write_text("not a cover")
        covers.prune_covers(self.site / "assets" / "cover",
                            {"s1": {Path(keep["src"]).name, Path(keep["tall"]).name}})
        left = sorted(p.name for p in (self.site / "assets" / "cover").iterdir())
        self.assertEqual(left, ["README.txt", "s1-1111111111-t.png", "s1-1111111111.png"])

    def test_the_image_step_looks_again_past_a_carried_cover(self):
        # A cover carried from the last run is not the story's picture: it is neither kept nor remembered as one.
        cache = ImageCache(cache_path=self.site / "cache.json", seed_path=self.site / "no-seed.json")
        st = {"id": "c1", "url": "https://example.com/c1",
              "image": {"src": "assets/cover/c1-0123456789.png", "via": "cover", "kind": "cover"}}
        self.assertIsNone(resolve_story_image(st, cache=cache, allow_network=False, site_root=self.site))
        self.assertIsNone(cache.get(st["url"]))


class PermanentPagesTest(unittest.TestCase):
    def test_a_page_never_links_a_pruned_cover(self):
        # Permanent pages are drawn again from the archive on every run; a cover pruned since is simply not shown.
        from unittest import mock
        from radar import story_pages
        cover = lambda sid: {"src": f"assets/cover/{sid}-0123456789.png", "tall": f"assets/cover/{sid}-0123456789-t.png",
                             "via": "cover", "kind": "cover"}
        archive = {sid: {"id": sid, "title": f"Story {sid}", "title_vi": f"Tin {sid}", "url": f"https://example.com/{sid}",
                         "published_at": "2026-11-10T00:00:00Z", "kind": "product", "image": cover(sid),
                         "coverage": [{"source": "verge-ai", "url": f"https://example.com/{sid}"}]}
                   for sid in ("kept", "pruned")}
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "assets" / "cover").mkdir(parents=True)
            (site / archive["kept"]["image"]["src"]).write_bytes(b"png")
            with mock.patch.object(story_pages, "gated_stories", lambda stories, decisions: stories):
                self.assertEqual(story_pages.render_site(archive, site), 2)
            kept = (site / "tin" / "kept" / "index.html").read_text(encoding="utf-8")
            pruned = (site / "tin" / "pruned" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="story-media-img is-cover"', kept)
        self.assertIn("assets/cover/kept-0123456789.png", kept)
        self.assertNotIn("assets/cover/", pruned)
        self.assertNotIn("story-media", pruned)
        self.assertIn("og-image.png", pruned)


class RendererFailureTest(unittest.TestCase):
    def test_retries_a_failed_drawing_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake_run(args, **kwargs):
                calls.append(args)
                result_path = Path(args[-1])
                result_path.write_text(json.dumps({
                    "covers": {} if len(calls) == 1 else {"r1": {"src": "assets/cover/r1.png"}},
                    "failed": {"r1": "page never reported ready"} if len(calls) == 1 else {},
                }), encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, "covers: done", "")

            with mock.patch.object(covers.subprocess, "run", side_effect=fake_run):
                result = covers.render([story("r1")], SOURCES, Path(tmp), node="node")

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["failed"], {})
        self.assertIn("r1", result["covers"])

    def test_reports_a_persistent_drawing_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake_run(args, **kwargs):
                calls.append(args)
                Path(args[-1]).write_text(json.dumps({"covers": {}, "failed": {"r1": "page never reported ready"}}),
                                          encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, "covers: 0 rendered, 1 failed", "")

            output = StringIO()
            with mock.patch.object(covers.subprocess, "run", side_effect=fake_run), redirect_stdout(output):
                result = covers.render([story("r1")], SOURCES, Path(tmp), node="node")

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["failed"], {"r1": "page never reported ready"})
        self.assertIn("Covers: r1 failed (attempt 2): page never reported ready", output.getvalue())

    # What render-site.mjs reports when covers/lib/cdp.mjs gives up waiting for Chrome's DevToolsActivePort file:
    # every story fails with the launch error and nothing is drawn. Seen on CI twice in a row in one run (2026-11-10).
    NO_START = {"covers": {}, "rendered": 0, "reused": 0,
                "failed": {"r1": "Chrome did not start: no DevToolsActivePort"}}

    def run_renderer(self, outcomes, timeout=covers.RENDER_TIMEOUT):
        """Run render() against a renderer that returns each outcome in turn; returns (result, calls, log, pauses)."""
        calls, pauses, output = [], [], StringIO()

        def fake_run(args, **kwargs):
            calls.append(args)
            Path(args[-1]).write_text(json.dumps(outcomes[min(len(calls), len(outcomes)) - 1]), encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "covers: done", "")

        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(output), \
                mock.patch.object(covers.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(covers.time, "sleep", side_effect=pauses.append):
            result = covers.render([story("r1")], SOURCES, Path(tmp), node="node", timeout=timeout)
        return result, calls, output.getvalue(), pauses

    def test_a_browser_that_did_not_start_twice_is_started_again(self):
        drawn = {"covers": {"r1": {"src": "assets/cover/r1.png", "tall": "assets/cover/r1-t.png"}},
                 "rendered": 1, "reused": 0, "failed": {}}
        result, calls, log, pauses = self.run_renderer([self.NO_START, self.NO_START, drawn])
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["failed"], {})
        self.assertIn("r1", result["covers"])
        self.assertEqual(len(pauses), 2)
        self.assertTrue(all(p > 0 for p in pauses))
        self.assertIn("Covers: r1 failed (attempt 2): Chrome did not start: no DevToolsActivePort", log)

    def test_a_browser_that_never_starts_is_reported_not_raised(self):
        result, calls, log, pauses = self.run_renderer([self.NO_START])
        self.assertEqual(len(calls), covers.START_ATTEMPTS)
        self.assertEqual(result["failed"], self.NO_START["failed"])
        self.assertEqual(result["covers"], {})
        self.assertIn(f"Covers: r1 failed (attempt {covers.START_ATTEMPTS}): Chrome did not start", log)

    def test_start_up_pauses_stay_inside_the_deadline(self):
        # 12 s of budget cannot hold the first 5 s pause plus a second 15 s one: the renderer runs twice, not four times.
        result, calls, _, pauses = self.run_renderer([self.NO_START], timeout=12)
        self.assertEqual(len(calls), 2)
        self.assertEqual(pauses, [covers.START_PAUSES[0]])
        self.assertEqual(result["covers"], {})


@unittest.skipUnless(NODE, "Node required to start the cover browser")
class BrowserStartTest(unittest.TestCase):
    def test_a_browser_that_exits_fails_at_once_with_its_exit_code_and_stderr(self):
        # Node stands in for a Chrome that dies on start-up: it rejects Chrome's flags on stderr and exits 9. The
        # launch used to wait the whole start-up timeout and say only "no DevToolsActivePort".
        script = (f"import {{ launch }} from {json.dumps((ROOT / 'covers' / 'lib' / 'cdp.mjs').as_uri())};"
                  "const t0 = Date.now();"
                  "try { await (await launch()).close(); console.log('started'); }"
                  "catch (e) { console.log(JSON.stringify({ ms: Date.now() - t0, message: e.message })); }")
        proc = subprocess.run([NODE, "--no-warnings", "--input-type=module", "-e", script], cwd=ROOT,
                              env={**os.environ, "CHROME": NODE}, capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
        outcome = json.loads(proc.stdout)
        self.assertTrue(outcome["message"].startswith(covers.START_FAILURE), outcome["message"])
        self.assertIn("exited with code 9", outcome["message"])
        self.assertIn("bad option: --headless=new", outcome["message"])
        self.assertLess(outcome["ms"], 5000)


def chrome_available():
    if not NODE:
        return False
    probe = subprocess.run([NODE, "--no-warnings", "--input-type=module", "-e",
                            f"import {{ CHROME }} from {json.dumps((ROOT / 'covers' / 'lib' / 'cdp.mjs').as_uri())};"
                            "process.exit(CHROME ? 0 : 1)"], cwd=ROOT, capture_output=True)
    return probe.returncode == 0


def png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    return struct.unpack(">II", head[16:24])


@unittest.skipUnless(chrome_available(), "Node and Chrome required to draw covers")
class RenderTest(unittest.TestCase):
    def test_draws_both_files_once_and_reuses_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            payload = {"sources": SOURCES, "stories": [
                story("r1", title="DeepX chip", editorial_headline_vi="DeepX ra chip mới",
                      key_points=["Băng thông tăng lên 150 GB/s."]),
                story("r2", image={"src": "https://example.com/p.jpg", "via": "og:image", "kind": "photo"})]}
            log = StringIO()
            with redirect_stdout(log):
                first = covers.apply_covers(payload, site)
            # A cover that was not drawn fails here with the renderer's own reasons, not with a KeyError further down.
            self.assertEqual((first["attached"], first["failed"]), (1, 0), f"r1 was not drawn:\n{log.getvalue()}")
            image = payload["stories"][0]["image"]
            self.assertEqual(png_size(site / image["src"]), (622, 296))
            self.assertEqual(png_size(site / image["tall"]), (616, 616))
            self.assertEqual(payload["stories"][1]["image"]["via"], "og:image")
            again = covers.apply_covers(payload, site)
            self.assertEqual((again["attached"], again["pruned"]), (1, 0))
            self.assertEqual(payload["stories"][0]["image"], image)


if __name__ == "__main__":
    unittest.main()
