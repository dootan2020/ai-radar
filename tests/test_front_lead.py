"""The lead picture is in the page the server sends (captain, 11/11 01:03: "Sửa ngay đi e", the last Chrome Web Store
performance blocker). Lighthouse mobile on https://hco.news measured an LCP of 7.0 s that night: the browser learned the
lead's picture only after the modules and the snapshot arrived. radar/front_lead.py now writes the lead's picture, its
preload and a preconnect into site/index.html when a snapshot is published, and feed.js adopts that picture.

These checks keep it so: the built page carries the slide and a preload matching its picture; the slide's story is the
one the real feed.js puts first (tests/verify-front-lead.mjs, headless Chrome); the extension's new tab carries no
baked-in story; the stylesheets the first screen does not draw do not block it."""
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from radar import front_lead, site_payload

try:
    from test_tim_kiem_giua import browser_ready
except ImportError:
    from tests.test_tim_kiem_giua import browser_ready

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
FIXTURE = ROOT / "tests" / "fixtures" / "radar-window-sample.json"
GENERATED = "2026-11-10T20:00:00Z"


def story(sid, src, via="feed-media", kind="photo", worth=1.0, tier="", hot=0, at="2026-11-10T18:00:00Z", **extra):
    image = {"src": src, "via": via, "kind": kind} if src else None
    return {"id": sid, "title": f"Story {sid}", "url": f"https://example.com/{sid}", "published_at": at,
            "latest_coverage_at": at, "importance_tier": tier, "hot_score": hot, "worth_score": worth,
            "worth_parts": {"breadth": 1}, "image": image, "image_screened": True, "coverage": [], **extra}


def window(*stories):
    return {"schema_version": 2, "generated_at": GENERATED, "ranking": {"window_hours": 72}, "stories": list(stories)}


SEMAFOR = "https://img.semafor.com/7f2a/lead.jpg?fit=crop&q=80"


def load_sync():
    spec = importlib.util.spec_from_file_location("sync_site", ROOT / "extension" / "sync-site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LeadChoice(unittest.TestCase):
    def test_the_first_story_with_a_photograph_by_front_score_leads(self):
        page = window(story("cover", None, worth=9), story("graphic", "https://x.test/g.png", via="hf-thumbnail", kind="graphic", worth=9),
                      story("low", "https://x.test/l.jpg", worth=1), story("high", "https://x.test/h.jpg", tier="notable", worth=2))
        lead, image = front_lead.lead_story(page)
        self.assertEqual(lead["id"], "high")
        self.assertEqual(image["src"], "https://x.test/h.jpg")

    def test_an_editor_pick_leads_and_an_expired_one_does_not(self):
        page = window(story("a", "https://x.test/a.jpg", worth=8), story("b", "https://x.test/b.jpg", worth=1))
        now = front_lead._ms(GENERATED)
        self.assertEqual(front_lead.lead_story(page, [{"id": "b"}], now)[0]["id"], "b")
        self.assertEqual(front_lead.lead_story(page, [{"id": "b", "until": "2026-11-01T00:00:00Z"}], now)[0]["id"], "a")

    def test_a_story_outside_the_window_never_leads(self):
        page = window(story("old", "https://x.test/o.jpg", worth=9, at="2026-11-01T00:00:00Z"), story("new", "https://x.test/n.jpg"))
        self.assertEqual(front_lead.lead_story(page)[0]["id"], "new")

    def test_an_unknown_choice_keeps_the_plain_placeholder(self):
        unscreened = story("u", "https://x.test/u.jpg")
        unscreened.update(image=None, image_screened=False)
        self.assertIsNone(front_lead.lead_story(window(unscreened, story("b", "https://x.test/b.jpg"))))
        unscored = story("s", "https://x.test/s.jpg")
        del unscored["worth_score"]
        self.assertIsNone(front_lead.lead_story(window(unscored)))


class BuiltPage(unittest.TestCase):
    def build(self, page):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "data").mkdir()
        (tmp / "index.html").write_text((SITE / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp / "editor-picks.json").write_text('{"picks": []}', encoding="utf-8")
        payload = dict(page, sources=[], sections={}, events=[], live=[], repos=[])
        # The newsroom's gate (apply_decisions) is tested on its own; here every story passes it.
        with mock.patch.object(site_payload, "apply_decisions", lambda p, d: p):
            site_payload.write_site_snapshot(payload, tmp / "data" / "radar.json")
        return (tmp / "index.html").read_text(encoding="utf-8")

    def test_the_built_page_carries_the_lead_slide_and_a_matching_preload(self):
        html = self.build(window(story("lead1", SEMAFOR, worth=5), story("other", "https://x.test/o.jpg")))
        slide = re.search(r'<section class="band band-today">.*?data-id="([^"]+)".*?<img ([^>]+)>', html)
        self.assertIsNotNone(slide, "no lead slide in the built page")
        self.assertEqual(slide.group(1), "lead1")
        img = dict(re.findall(r'(\w+)="([^"]*)"', slide.group(2)))
        preload = re.search(r'<link rel="preload" as="image" ([^>]+)>', html)
        self.assertIsNotNone(preload)
        link = dict(re.findall(r'(\w+)="([^"]*)"', preload.group(1)))
        self.assertEqual(link["imagesrcset"], img["srcset"])
        self.assertEqual(link["imagesizes"], img["sizes"])
        self.assertEqual(link["href"], img["src"])
        self.assertEqual(link["fetchpriority"], "high")
        self.assertEqual(link["referrerpolicy"], img["referrerpolicy"])
        self.assertIn("w=828", img["src"])
        self.assertIn('<link rel="preconnect" href="https://img.semafor.com">', html)
        self.assertEqual(html.index('<link rel="preconnect"'), html.index("<!-- lead picture") + len(front_lead.HEAD_OPEN))

    def test_a_host_that_cannot_resize_is_preloaded_by_its_one_address(self):
        html = self.build(window(story("lead1", "https://cdn.i-scmp.com/a/b.jpg?itok=x&v=1")))
        self.assertIn('<link rel="preload" as="image" href="https://cdn.i-scmp.com/a/b.jpg?itok=x&amp;v=1" fetchpriority="high"', html)
        self.assertIn('src="https://cdn.i-scmp.com/a/b.jpg?itok=x&amp;v=1"', html)

    def test_no_photograph_leaves_the_plain_placeholder(self):
        html = self.build(window(story("c", None)))
        self.assertNotIn('rel="preload" as="image" href="https://', html.split("<!-- /lead picture -->")[0].split("<!-- lead picture")[1])
        self.assertIn(front_lead.BODY_OPEN + front_lead.SKELETON_LEAD + front_lead.BODY_CLOSE, html)

    def test_the_committed_page_holds_the_empty_blocks(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertEqual(front_lead.render_index(html, None), html)

    def test_feed_js_sizes_match_the_build(self):
        feed = (SITE / "feed.js").read_text(encoding="utf-8")
        self.assertIn(f"lead: [{', '.join(map(str, front_lead.LEAD_WIDTHS))}]", feed)
        self.assertIn(f"lead: '{front_lead.LEAD_SIZES}'", feed)
        self.assertIn("picksMax: 5", (SITE / "worth-score.js").read_text(encoding="utf-8"))

    def test_the_resizers_follow_feed_js(self):
        cases = {SEMAFOR: "https://img.semafor.com/7f2a/lead.jpg?fit=crop&q=80&w=480",
                 "https://techcrunch.com/wp-content/uploads/a.png?resize=1200,675": "https://techcrunch.com/wp-content/uploads/a.png?resize=1200%2C675&w=480",
                 "https://i0.wp.com/x.com/a.jpg?w=2000&fit=1920%2C1280": "https://i0.wp.com/x.com/a.jpg?w=480&fit=1920%2C1280",
                 "https://media.wired.com/photos/1/master/pass/a.jpg": "https://media.wired.com/photos/1/master/w_480,c_limit/a.jpg",
                 "https://cdn.i-scmp.com/a.jpg": None}
        for src, want in cases.items():
            self.assertEqual(front_lead.sized_src(src, 480), want, src)


class Extension(unittest.TestCase):
    def test_the_new_tab_has_no_baked_in_story(self):
        sync = load_sync()
        lead = front_lead.lead_story(window(story("lead1", SEMAFOR)))
        built = front_lead.render_index((SITE / "index.html").read_text(encoding="utf-8"), lead)
        self.assertIn('data-id="lead1"', built)
        for html in (sync.adapt_html(built), (ROOT / "extension" / "newtab.html").read_text(encoding="utf-8")):
            self.assertNotIn("lead1", html)
            self.assertNotIn("band-today", html)
            self.assertNotIn('rel="preload" as="image"', html)
            self.assertNotIn("lead picture", html)
            self.assertIn('<div class="msn-card msn-sk msn-lead"></div>', html)


class LateStyles(unittest.TestCase):
    def test_only_first_screen_styles_block_the_first_paint(self):
        head = (SITE / "index.html").read_text(encoding="utf-8").split("</head>")[0]
        blocking = re.findall(r'<link rel="stylesheet" href="([^"]+)"', head)
        self.assertEqual(blocking, ["tokens.css", "feed.css", "trang-nhat.css", "trang-msn.css", "menu-cong-cu.css"])
        feed = (SITE / "feed.js").read_text(encoding="utf-8")
        self.assertIn("const LATE_STYLES = ['arena.css', 'story.css'];", feed)


@unittest.skipUnless(browser_ready(), "node, puppeteer and Chrome are needed for the rendered check")
class RenderedLead(unittest.TestCase):
    def test_feed_js_puts_the_build_story_first_and_adopts_its_picture(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        lead = front_lead.lead_story(data)
        self.assertIsNotNone(lead, "the fixture should have a lead with a photograph")
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text(front_lead.render_index((SITE / "index.html").read_text(encoding="utf-8"), lead), encoding="utf-8")
            run = subprocess.run(["node", "tests/verify-front-lead.mjs", "--index", str(index), "--data", str(FIXTURE)],
                                 cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        result = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(result["errors"], [])
        for width, r in result["widths"].items():
            with self.subTest(width=width):
                self.assertEqual(r["before"]["id"], lead[0]["id"])
                self.assertEqual(r["after"]["id"], lead[0]["id"], "feed.js put another story first")
                self.assertTrue(r["after"]["adopted"], "feed.js drew its own picture instead of adopting the build's")
                self.assertEqual([r["before"][k] for k in ("top", "left", "width")], [r["after"][k] for k in ("top", "left", "width")])
                self.assertEqual(r["after"]["shift"], 0)
                self.assertEqual(r["leadRequests"], 1)
                self.assertEqual(r["after"]["lateStyles"], [True, True])


if __name__ == "__main__":
    unittest.main()
