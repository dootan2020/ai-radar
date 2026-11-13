"""New stories load by themselves (captain, 13/11 20:1x: "làm cho anh cái tính năng tự tải tin mới, animate mượt mà,
user không cần click 'có N tin mới' hoặc tải lại trình duyệt, tin mới tự tải").

The "N tin mới" pill is gone. A polled snapshot that brings new stories is taken in while the reader is at the top of
the front page and not busy (a story or dialog open, the search open, a finger or button down, a scroll still
moving); further down it waits until they come back up, so nothing above them changes and the page never scrolls.
The arrivals lead "Vừa đăng"; what stays on the page slides to its new place (FLIP, transform and opacity only, on the
motion tokens), what is new fades in, the arrivals glow for a moment; with reduced motion nothing moves. One polite
announcement per batch. tests/capture-tu-tai-tin.mjs renders it at 375 and 1440 px; tests/verify-feed-content.mjs
runs the waiting rules against a stubbed page."""
import importlib.util
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE, EXT = ROOT / "site", ROOT / "extension"
FOLDERS = (SITE, EXT)
ARRIVALS = ["tu-tai-tin-2", "tu-tai-tin-1"]   # newest first, as "Vừa đăng" reads


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def function(source, name, until):
    start = source.index(f"function {name}(")
    return source[start:source.index(until, start)]


def browser_ready():
    if not shutil.which("node"):
        return False
    chrome = [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"), Path("/usr/bin/google-chrome"),
              Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    if not any(p.exists() for p in chrome):
        return False
    probe = subprocess.run(["node", "--input-type=module", "-e", "await import('puppeteer')"], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
    return probe.returncode == 0


def rendered():
    if not hasattr(rendered, "out"):
        run = subprocess.run(["node", "tests/capture-tu-tai-tin.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=420)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        rendered.out = json.loads(run.stdout.strip().splitlines()[-1])
    return rendered.out


class NoPill(unittest.TestCase):
    def test_the_pill_is_gone_from_both_copies(self):
        for page in (SITE / "index.html", EXT / "newtab.html"):
            html = read(page)
            for removed in ('id="fresh"', 'id="fresh-go"', 'id="fresh-text"', "fresh-btn"):
                self.assertNotIn(removed, html, f"{page.name}: {removed}")
            self.assertEqual(html.count('id="fresh-announcement" role="status" aria-live="polite" aria-atomic="true"'), 1, page.name)
        for folder in FOLDERS:
            feed, css = read(folder / "feed.js"), read(folder / "feed.css")
            for removed in ("offerNewItems", "noticeIds", "dismissNewItems", "renderNewItems", "#fresh-go", "$('#fresh')",
                            "is-flash"):
                self.assertNotIn(removed, feed, f"{folder.name}: {removed}")
            self.assertNotIn(".fresh-btn", css, folder.name)
            self.assertIn("announce(`Đã thêm ${batch.length} tin mới`)", feed)

    def test_the_extension_is_the_synced_site(self):
        spec = importlib.util.spec_from_file_location("extension_sync_tu_tai", EXT / "sync-site.py")
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        self.assertEqual(sync.adapt_feed(read(SITE / "feed.js")), read(EXT / "feed.js"))
        self.assertEqual(sync.adapt_html(read(SITE / "index.html")), read(EXT / "newtab.html"))
        for name in ("feed.css", "trang-msn.css", "tokens.css"):
            self.assertEqual(read(SITE / name), read(EXT / name), name)


class WhenItIsTakenIn(unittest.TestCase):
    def test_a_poll_never_redraws_by_itself(self):
        for folder in FOLDERS:
            poll = function(read(folder / "feed.js"), "pollSnapshot", "\n}\n")
            self.assertIn("pendingIds = pendingNewIds(j);", poll)
            self.assertIn("watchPending();", poll)
            self.assertNotIn("applyPending", poll)
            self.assertNotIn("renderAll", poll)

    def test_only_at_the_top_and_only_when_the_reader_is_free(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            busy = function(feed, "readerBusy", "\n}\n")
            for part in ("currentModalStoryId", "dialog[open]", "#news-search", "#ns-results", "swipe", "pointerDown"):
                self.assertIn(part, busy, part)
            top = function(feed, "readerAtTop", "\n}\n")
            self.assertIn("filter !== 'all'", top)
            self.assertIn("$('#fresh-row')", top)
            apply = function(feed, "maybeApply", "\n}\n")
            self.assertIn("if (!pending || !pendingIds.length || document.hidden || scrollMoving) return;", apply)
            self.assertIn("if (readerBusy() || !readerAtTop()) return;", apply)

    def test_a_keyboard_action_does_not_animate(self):
        for folder in FOLDERS:
            go = function(read(folder / "feed.js"), "goFirstNew", "\n}\n")
            self.assertIn("if (pending) applyPending({ motion: false });", go)


class Motion(unittest.TestCase):
    def test_transform_and_opacity_on_the_motion_tokens(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            apply = function(feed, "applyPending", "\n}\n")
            self.assertIn("const before = motion && !RM.matches ? captureLayout() : null;", apply)
            self.assertIn("if (before) playLayout(before, new Set(batch));", apply)
            moving = function(feed, "playLayout", "\n}\n") + function(feed, "arrive", "\n}\n")
            self.assertIn("motionToken('--motion-arrive')", moving)
            self.assertIn("motionToken('--ease-flow')", moving)
            keyframes = re.findall(r"\.animate\(\[(.*?)\], \{ duration, easing \}\)", moving)
            self.assertEqual(len(keyframes), 2)
            for frames in keyframes:
                props = set(re.findall(r"(\w+):", frames))
                self.assertIn("transform", props, frames)
                self.assertLessEqual(props, {"transform", "opacity"}, frames)

    def test_the_glow_is_opacity_only_and_off_under_reduced_motion(self):
        for folder in FOLDERS:
            css = read(folder / "trang-msn.css")
            glow = re.search(r"@keyframes fresh-glow \{(.*?)\} \}", css).group(1) + "}"
            self.assertEqual(set(re.findall(r"([\w-]+):", glow)), {"opacity"})
            reduced = css[css.index("@media (prefers-reduced-motion: reduce) {\n  .nen-img"):]
            self.assertIn(".fresh-list > li.is-arriving::after { animation: none; opacity: 0; }", reduced[:reduced.index("\n}\n")])


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered page")
class Rendered(unittest.TestCase):
    WIDTHS = ("375", "1440")

    def test_no_errors(self):
        self.assertEqual(rendered()["errors"], [])
        self.assertEqual(sorted(rendered()["runs"]), sorted(self.WIDTHS))

    def test_at_the_top_the_arrivals_lead_vua_dang_without_a_click(self):
        for w in self.WIDTHS:
            top = rendered()["runs"][w]["top"]
            before, applied, after = top["before"], top["applied"], top["after"]
            self.assertFalse(set(ARRIVALS) & set(before["rows"]), w)
            self.assertEqual(applied["rows"][:2], ARRIVALS, w)
            self.assertEqual(after["rows"][:2], ARRIVALS, w)
            self.assertFalse(after["pill"], w)
            self.assertEqual(after["twice"], [], f"{w}: every story once")
            self.assertEqual(after["live"], "Đã thêm 2 tin mới", w)
            self.assertEqual((before["scrollY"], after["scrollY"]), (0, 0), f"{w}: the page does not scroll")
            self.assertEqual(before["tileTop"], after["tileTop"], f"{w}: the tile stays where it was")
            self.assertGreater(applied["moving"], 0, f"{w}: what stays slides to its place")
            self.assertEqual((applied["glow"], applied["arriving"]), (2, 2), f"{w}: the arrivals glow")
            self.assertLessEqual(top["motion"]["over50"], 1, f"{w}: {top['motion']['gaps']}")
            self.assertLessEqual(top["motion"]["shift"], 0.01, f"{w}: nothing jumps; what moves, slides")
            # The pictures already on screen stay drawn through the redraw; only a story new to the screen may still
            # be loading its own.
            pics_before, pics_now = before["pictures"], applied["pictures"]
            self.assertEqual(pics_before["blank"], 0, w)
            self.assertLessEqual(pics_now["blank"], max(0, pics_now["shown"] - pics_before["shown"]), f"{w}: {pics_now['which']}")

    def test_down_the_page_nothing_moves_until_the_reader_is_back_at_the_top(self):
        for w in self.WIDTHS:
            mid = rendered()["runs"][w]["middle"]
            before, held = mid["before"], mid["held"]
            self.assertIsNone(mid["appliedWhileDown"], w)
            self.assertEqual(before["scrollY"], 1500, w)
            for key in ("scrollY", "held", "rows", "generated", "tileTop"):
                self.assertEqual(held[key], before[key], f"{w}: {key}")
            self.assertIsNotNone(before["held"], f"{w}: an element was in view")
            self.assertIsNotNone(mid["applied"], f"{w}: taken in back at the top")
            self.assertEqual(mid["back"]["rows"][:2], ARRIVALS, w)
            self.assertEqual(mid["back"]["twice"], [], w)
            self.assertEqual(mid["back"]["scrollY"], 0, w)

    def test_an_open_story_holds_it_and_focus_survives(self):
        for w in self.WIDTHS:
            modal = rendered()["runs"][w]["modal"]
            self.assertIsNone(modal["whileOpen"]["applied"], w)
            self.assertTrue(modal["whileOpen"]["open"], w)
            self.assertTrue(modal["afterClose"]["applied"], w)
            self.assertFalse(modal["afterClose"]["open"], w)
            self.assertRegex(modal["focusBefore"], r"^a#\.brief\[\w+\]$", w)
            self.assertEqual(modal["focusAfter"], modal["focusBefore"], f"{w}: keyboard focus stays on the story")

    def test_reduced_motion_takes_it_in_without_any_motion(self):
        for w in self.WIDTHS:
            reduced = rendered()["runs"][w]["reduced"]
            applied, after = reduced["applied"], reduced["after"]
            self.assertIsNotNone(applied, w)
            self.assertEqual((applied["moving"], applied["glow"], applied["arriving"]), (0, 0, 0), w)
            self.assertEqual(after["rows"][:2], ARRIVALS, w)
            self.assertEqual(after["twice"], [], w)
            self.assertEqual(after["live"], "Đã thêm 2 tin mới", w)
            self.assertEqual(after["scrollY"], 0, w)


if __name__ == "__main__":
    unittest.main()
