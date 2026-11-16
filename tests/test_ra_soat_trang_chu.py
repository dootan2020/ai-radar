"""The front page, the shared shell and the phone after the UI audit of 16/11 (captain: "Duyệt theo em"). Each test names
what a reader met before the fix; the rendered numbers (contrast, first screen, 200 % text, a phone turned sideways) were
measured in headless Chrome and are in the audit's report, these tests keep the rules that produced them."""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def read(name):
    return (SITE / name).read_text(encoding="utf-8")


def rule(css, selector):
    m = re.search(r"(?:^|[\s}])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


class FirstScreenStates(unittest.TestCase):
    def test_a_failed_load_says_so_above_the_weather_and_the_calendar(self):
        # The message and "Tải lại" sat under the fold of an empty panel (1440: y 938 in a 900 px window).
        js = read("feed.js")
        catch = js[js.index("console.error('feed load failed', err);"):js.index("const reopen = history.state")]
        self.assertIn("grid.before(em);", catch)
        self.assertIn("'Chưa nạp được sự kiện'", catch)   # "Sự kiện" names its own loss
        self.assertIn("role', 'alert'", catch)
        self.assertIn(".msn-panel .feed-empty.is-error {", read("trang-msn.css"))

    def test_the_loading_placeholder_shows_on_the_panel(self):
        # Its cells had the panel's own colour (light) and, from 700 px, no height in the bands' column.
        css = read("trang-msn.css")
        self.assertIn("background: var(--color-surface)", rule(css, ".msn-sk"))
        self.assertIn("#feed-skeleton.msn-grid.is-front:not(:has(> .band)) { display: grid; }", css)


class ReadableAndReachable(unittest.TestCase):
    def test_the_lead_headline_is_never_cut_mid_word_on_a_desktop(self):
        self.assertIn("-webkit-line-clamp: 3", rule(read("trang-msn.css"), ".slide-title"))

    def test_the_lead_grows_with_a_large_text_size_on_a_phone(self):
        css = read("trang-msn.css")
        self.assertIn(".msn-lead { grid-column: 1 / -1; display: grid; height: auto; min-height: var(--msn-lead-h-phone); }", css)
        self.assertIn(".band .msn-lead { height: auto; min-height: var(--msn-lead-h-phone); }", css)

    def test_the_dock_current_label_reads_in_dark(self):
        # Coral-light on its wash read 3.64:1 at 12 px; the ink reads 10:1 (measured).
        tokens = read("tokens.css")
        current = [line.split("/*")[0].strip() for line in tokens.splitlines() if line.strip().startswith("--color-current:")]
        self.assertEqual(current, ["--color-current: var(--color-accent);", "--color-current: var(--color-ink);",
                                   "--color-current: var(--color-ink);"])
        self.assertIn('.mobile-nav-link[aria-current="page"]{background:var(--color-accent-wash);color:var(--color-current)}',
                      read("menu-cong-cu.css"))

    def test_the_dock_grows_with_the_text_and_turns_into_a_rail_sideways(self):
        css = read("menu-cong-cu.css")
        self.assertIn("--mobile-nav-h:max(64px,", css)
        self.assertNotIn("white-space:nowrap;-webkit-tap-highlight-color", css)   # labels wrap at 200 %
        self.assertIn("@media(max-width:767px) and (max-height:500px) and (orientation:landscape){", css)

    def test_a_short_window_keeps_a_headline_on_the_first_screen(self):
        css = read("trang-msn.css")
        self.assertIn("@media (min-width: 768px) and (max-height: 500px) and (orientation: landscape) {\n  .slide-box { top: var(--btn-h); bottom: auto; }", css)


class EventsPage(unittest.TestCase):
    def test_no_empty_heading_and_no_tab_marked(self):
        js, css = read("feed.js"), read("trang-msn.css")
        self.assertIn("bt-replays-only", js)
        self.assertIn(".bt.bt-replays-only > #bt-h1 { display: none; }", css)
        self.assertIn("line.classList.toggle('is-away', !active)", js)
        self.assertIn(".msn-head .sections .tab-pill.is-away { opacity: 0; }", css)


class SettingsSheet(unittest.TestCase):
    def test_the_sheet_leads_to_the_sources_and_the_privacy_policy(self):
        probe = r"""
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const tt = await import(pathToFileURL(path.resolve('site/thanh-tren.js')).href);
console.log(JSON.stringify({ site: tt.pagesHTML(tt.pageBase({ protocol: 'https:' })), ext: tt.pageBase({ protocol: 'chrome-extension:' }) }));
"""
        run = subprocess.run(["node", "--input-type=module", "-e", probe], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        r = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertIn('href="/nguon"><span>Nguồn tin</span>', r["site"])
        self.assertIn('href="/chinh-sach-rieng-tu"><span>Chính sách riêng tư</span>', r["site"])
        self.assertEqual(r["ext"], "https://hco.news/")   # the new tab has no copy of those pages


class OneSystem(unittest.TestCase):
    def test_floating_sheets_share_one_radius_and_no_outline(self):
        menu = read("menu-cong-cu.css")
        panel = re.search(r"\.tool-launcher-panel\{([^}]*)\}", menu).group(1)
        self.assertIn("border:0", panel)
        self.assertIn("border-radius:var(--msn-panel-r)", panel)
        self.assertNotIn("460px", panel)   # the cap hid "Thêm từ Google"
        self.assertIn("border-radius: var(--msn-panel-r)", rule(read("trang-nhat.css"), ".ns-results"))
        self.assertIn("outline:var(--focus-ring)", menu)

    def test_small_capitals_use_one_tracking(self):
        css = read("trang-msn.css")
        upper = [m.group(0) for m in re.finditer(r"[^{}]*text-transform: uppercase[^{}]*", css)]
        self.assertTrue(upper)
        for block in upper:
            if "var(--text-micro)" in block:
                self.assertIn("letter-spacing: var(--tracking-label)", block)

    def test_motion_uses_one_curve_and_one_speed(self):
        css = read("trang-msn.css")
        self.assertIn("transition: opacity var(--duration-250) var(--ease-flow)", rule(css, ".slide.is-active"))
        self.assertIn("--motion-tab-glide: var(--motion-state);", read("feed.css"))

    def test_reduced_motion_keeps_the_fades_and_stops_the_movement(self):
        # Captain, 16/11 ("Duyệt theo em"): keep the fades, stop the sliding.
        feed = read("feed.css")
        block = feed[feed.index("@media (prefers-reduced-motion: reduce){\n  *, *::before, *::after {"):]
        block = block[:block.index("}")]
        self.assertIn("transition-property: opacity, visibility, color, background-color, border-color, box-shadow !important;", block)
        self.assertIn("transition-duration: var(--motion-feedback) !important;", block)
        self.assertNotIn("transform", block)

    def test_chuyen_lon_headlines_are_a_card_headline(self):
        # Captain, 16/11: 15 px; a row that no longer fits is left out (fitBandLists), never cut.
        self.assertIn("font-size: var(--msn-title)", rule(read("trang-msn.css"), ".msn-toplist .top-title"))
        self.assertIn(".band-focus .msn-toplist ol", read("feed.js"))


class NotFoundDock(unittest.TestCase):
    def test_the_404_page_marks_no_destination(self):
        # Under /tin/ the dock took the page for the feed and marked "Dòng tin" on the 404 page (coordinator, 16/11).
        js = read("menu-cong-cu.js")
        self.assertIn("const lost = !!document.getElementById('nf');", js)
        self.assertIn("const here = !lost && (", js)
        self.assertIn('id="nf"', read("404.html"))


if __name__ == "__main__":
    unittest.main()
