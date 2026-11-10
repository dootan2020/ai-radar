"""The stream player (captain, 10/11 22:12: "Làm trình phát tại halcyon"): a reader taps a stream on the front page's
"Sắp diễn ra" card or in the "Sắp diễn ra" view and watches it in Halcyon's modal frame. Nothing from YouTube loads
before the tap; the embed comes from youtube-nocookie.com; "Mở trên YouTube" is always there; closing removes the
iframe and gives focus back. The new tab keeps streams as links: YouTube refuses an embed from a chrome-extension://
page (no referrer). The drawn player is tests/capture-trinh-phat.mjs (offline: every other host is refused)."""
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from test_bento_trang_nhat import browser_ready
except ImportError:
    from tests.test_bento_trang_nhat import browser_ready

ROOT = Path(__file__).resolve().parent.parent
SITE, EXT = ROOT / "site", ROOT / "extension"
VIDEO = "Fls_onRviPM"
EMBED = f"https://www.youtube-nocookie.com/embed/{VIDEO}?autoplay=1&playsinline=1&rel=0"


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def csp(html):
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    return {w[0]: w[1:] for w in (p.split() for p in meta.group(1).split(";")) if w}


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class Helpers(unittest.TestCase):
    def test_only_a_youtube_id_plays_and_it_plays_from_nocookie(self):
        script = f"""
import {{ playable, embedSrc, watchURL }} from {json.dumps((SITE / 'trinh-phat.js').as_uri())};
process.stdout.write(JSON.stringify({{
  ok: [playable({{ video_id: '{VIDEO}' }}), playable({{ video_id: 'capture-live' }}), playable({{ video_id: '"><x>aaaa' }}), playable(null)],
  src: embedSrc('{VIDEO}'), watch: watchURL({{ video_id: '{VIDEO}' }}),
}}));"""
        run = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertEqual(out["ok"], [True, False, False, False])
        self.assertEqual(out["src"], EMBED)
        self.assertEqual(out["watch"], f"https://www.youtube.com/watch?v={VIDEO}")


class Wiring(unittest.TestCase):
    def test_the_page_holds_no_youtube_frame_or_script_until_a_tap(self):
        html, feed, player = read(SITE / "index.html"), read(SITE / "feed.js"), read(SITE / "trinh-phat.js")
        for src in (html, feed, player):
            self.assertNotIn("<iframe", src)
            self.assertNotIn("iframe_api", src)
        self.assertIn("document.createElement('iframe')", player)
        self.assertIn("body.replaceChildren();", player)
        dialog = html[html.index('<dialog class="story-dialog player-dialog"'):]
        dialog = dialog[:dialog.index("</dialog>")]
        self.assertIn("data-player-body></div>", dialog)
        self.assertIn('aria-label="Đóng video (phím Esc)"', dialog)

    def test_the_site_may_frame_nocookie_and_nothing_else(self):
        policy = csp(read(SITE / "index.html"))
        self.assertEqual(policy["frame-src"], ["https://www.youtube-nocookie.com"])
        self.assertEqual(policy["default-src"], ["'self'"])
        self.assertNotIn("youtube", " ".join(policy["script-src"]))

    def test_the_card_and_the_view_play_but_keep_their_youtube_link(self):
        feed = read(SITE / "feed.js")
        self.assertIn('<a class="ev-stream" href="${esc(safe(it.url))}" target="_blank" rel="noopener"${playAttr(it)}>', feed)
        self.assertIn('<a class="tile-video" href="${esc(safe(it.url))}" target="_blank" rel="noopener"${play}', feed)
        self.assertIn("Mở trên YouTube", feed)
        # A phone requests no thumbnail.
        self.assertIn("const thumb = PHONE.matches ? '' :", feed)

    def test_the_new_tab_keeps_streams_as_links_and_carries_no_player(self):
        feed, html = read(EXT / "feed.js"), read(EXT / "newtab.html")
        self.assertIn("const PLAYER_ON = false;", feed)
        self.assertFalse("from './trinh-phat.js'" in feed, "the new tab imports the player")
        self.assertNotIn("player-dialog", html)
        self.assertFalse((EXT / "trinh-phat.js").exists())
        for path in (*EXT.glob("*.js"), *EXT.glob("*.html")):
            self.assertNotIn("youtube-nocookie", read(path), path.name)

    def test_extension_matches_the_sync_output(self):
        spec = importlib.util.spec_from_file_location("extension_sync_player", EXT / "sync-site.py")
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "extension"
            shutil.copytree(EXT, copy)
            sync.EXT = copy
            sync.sync()
            for path in copy.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(copy)
                    with self.subTest(file=str(rel)):
                        self.assertEqual(path.read_bytes().replace(b"\r\n", b"\n"),
                                         (EXT / rel).read_bytes().replace(b"\r\n", b"\n"))
            self.assertEqual(sorted(p.relative_to(copy) for p in copy.rglob("*")), sorted(p.relative_to(EXT) for p in EXT.rglob("*")))


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered player")
class RenderedPlayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "tests/capture-trinh-phat.mjs", "--id", VIDEO], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", timeout=240)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        out = json.loads(run.stdout.strip().splitlines()[-1])
        if out["errors"]:
            raise AssertionError(out["errors"])
        cls.runs = out["runs"]

    def test_four_walks_ran(self):
        self.assertEqual(sorted(self.runs), ["sap-toi-1440", "sap-toi-375", "the-1440", "the-375"])

    def test_the_first_render_has_no_youtube_frame_and_asks_youtube_nothing(self):
        for name, run in self.runs.items():
            self.assertEqual((run["before"]["iframes"], run["before"]["open"]), (0, False), name)
            # The desktop view shows YouTube's poster; the card and a phone ask YouTube for nothing at all.
            if name != "sap-toi-1440":
                self.assertEqual(run["beforeRequests"], [], name)
            self.assertEqual(run["before"]["thumbs"], 0, name)
        self.assertEqual(self.runs["sap-toi-1440"]["beforeRequests"], [f"https://i.ytimg.com/vi/{VIDEO}/hqdefault.jpg"])

    def test_a_tap_inserts_the_nocookie_embed_for_the_right_video(self):
        for name, run in self.runs.items():
            opened = run["opened"]
            self.assertEqual(run["has"]["play"], VIDEO, name)
            self.assertTrue(opened["open"], name)
            self.assertEqual((opened["iframes"], opened["src"]), (1, EMBED), name)
            self.assertEqual(opened["referrer"], "strict-origin-when-cross-origin", name)
            self.assertIn("autoplay", opened["allow"], name)
            self.assertEqual(run["afterRequests"], [EMBED], name)
            self.assertEqual(opened["focus"], "close", name)
            self.assertEqual(opened["kicker"], "Trực tiếp · OpenAI", name)

    def test_the_youtube_link_is_always_there(self):
        for name, run in self.runs.items():
            link = run["opened"]["yt"]
            self.assertEqual((link["text"], link["href"]), ("Mở trên YouTube", f"https://www.youtube.com/watch?v={VIDEO}"), name)

    def test_closing_removes_the_frame_and_returns_focus(self):
        for name, run in self.runs.items():
            closed = run["closed"]
            self.assertEqual((closed["open"], closed["iframes"], closed["focus"]), (False, 0, "opener"), name)

    def test_text_targets_and_width(self):
        for name, run in self.runs.items():
            opened = run["opened"]
            self.assertGreaterEqual(opened["minText"], 12, name)
            for target in opened["targets"]:
                self.assertGreaterEqual(target["h"], 44, f"{name} {target['cls']}")
            self.assertFalse(opened["sideways"] or run["before"]["sideways"], name)
            frame = opened["frame"]
            self.assertAlmostEqual(frame["w"] / frame["h"], 16 / 9, delta=0.02, msg=name)
        self.assertEqual(self.runs["the-375"]["opened"]["frame"]["w"], 375)


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered player")
class HistoryAndFocus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "tests/capture-trinh-phat.mjs", "--cases", "--id", VIDEO, "--widths", "1440,375"],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        out = json.loads(run.stdout.strip().splitlines()[-1])
        if out["errors"]:
            raise AssertionError(out["errors"])
        cls.history, cls.focus = out["history"], out["focus"]

    def test_every_way_of_closing_was_walked(self):
        self.assertEqual(sorted(self.history), ["back-1440", "back-375", "backdrop-1440", "button-1440", "button-375",
                                                "escape-1440", "escape-375"])

    def test_history_and_the_dialog_agree_in_every_order(self):
        # open, close, Forward (the player is back on its own entry), Back, open again, Back: never off the page.
        expected = [("start", False, 0, False), ("open", True, 1, True), ("close", False, 0, False),
                    ("forward", True, 1, True), ("back", False, 0, False), ("open-again", True, 1, True),
                    ("back-again", False, 0, False)]
        for name, steps in self.history.items():
            with self.subTest(case=name):
                self.assertEqual([(s["step"], s["open"], s["iframes"], s["player"]) for s in steps], expected)
                self.assertTrue(all(s["same"] for s in steps), "a Back left the page")
                self.assertEqual({s["src"] for s in steps if s["open"]}, {EMBED})
                self.assertEqual(steps[-1]["len"], steps[-2]["len"])

    def test_focus_finds_the_redrawn_control_or_the_page(self):
        for width in (1440, 375):
            for name, cls in (("the", "ev-stream"), ("sap-toi", "tile-video")):
                case = self.focus[f"{name}-{width}"]
                with self.subTest(case=f"{name}-{width}"):
                    self.assertTrue(case["replaced"])
                    self.assertFalse(case["open"])
                    self.assertEqual((case["focus"]["orig"], case["focus"]["play"], case["focus"]["cls"], case["focus"]["connected"]),
                                     (False, VIDEO, cls, True))
            gone = self.focus[f"mat-luong-{width}"]
            self.assertEqual((gone["focus"]["id"], gone["focus"]["tag"]), ("top", "main"), width)


if __name__ == "__main__":
    unittest.main()
