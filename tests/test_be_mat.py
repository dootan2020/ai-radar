"""The front page's surfaces and its events card (captain, 10/11 19:3x, approving the coordinator's proposal: "duyệt,
gộp vào"). The panel is a light cool tint and the cards on it white (in dark, the panel one step darker than the cards);
the card shadow is a shared token; "Đáng đọc nhất / Mới nhất" is the segmented control of "Giao diện" (a grey track,
the chosen side a raised pill). "Sắp diễn ra" lists the next events as a short schedule ("thẻ "sắp diễn ra" làm đang
xấu, cho nền nhạt hay làm gì đó cho nó đẹp hơn"); its wash went with the mockup the captain chose later that day.
The rendered checks reuse tests/verify-top-search.mjs (website and extension, offline)."""
import re
import unittest
from pathlib import Path

try:  # one rendering per run, shared with test_tim_kiem_giua, however the suite was started
    from test_tim_kiem_giua import browser_ready, rendered
except ImportError:
    from tests.test_tim_kiem_giua import browser_ready, rendered

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = (ROOT / "site", ROOT / "extension")


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def theme_blocks(tokens):
    """The light block and the two dark blocks of tokens.css."""
    light = tokens[tokens.index(':root, [data-theme="light"]{'):]
    dark = tokens[tokens.index('[data-theme="dark"]{'):]
    system = tokens[tokens.index("@media (prefers-color-scheme: dark){"):]
    return [b[:b.index("\n}")] for b in (light, dark)] + [system[:system.index("\n  }")]]


class Surfaces(unittest.TestCase):
    def test_the_panel_and_the_cards_differ_in_every_theme(self):
        for folder in FOLDERS:
            tokens, css = read(folder / "tokens.css"), read(folder / "trang-msn.css")
            light, dark, system = theme_blocks(tokens)
            self.assertIn("--color-panel-front: var(--gray-95);", light)
            self.assertIn("--color-surface: var(--brand-white);", light)
            for block in (dark, system):
                self.assertIn("--color-panel-front: var(--deep-24);", block)
                self.assertIn("--color-surface: var(--brand-card-dark);", block)
            panel = css[css.index(".feed-main.front.msn-panel {"):]
            self.assertIn("background: var(--color-panel-front);", panel[:panel.index("}")])
            self.assertIn("background: var(--color-surface); border: 0; border-radius: var(--msn-card-r); box-shadow: var(--msn-shadow-rest);", css)
            self.assertRegex(tokens, r"--msn-shadow-rest: 0 1px 2px oklch\(var\(--shadow-tint\) / 0\.08\), 0 4px 16px oklch\(var\(--shadow-tint\) / 0\.10\);")

    def test_the_order_control_is_the_giao_dien_segmented_control(self):
        for folder in FOLDERS:
            css = read(folder / "trang-msn.css")
            self.assertIn(".tc-seg, .msn-head .sort-switch { padding: var(--msn-tight); border-radius: var(--radius-8); background: var(--color-seg-track); }", css)
            self.assertIn(".tc-seg label:has(input:checked), .msn-head .sort-switch .tab-pill, .msn-head .sort-btn-compact::before {", css)
            self.assertIn("background: var(--color-seg-thumb); box-shadow: var(--msn-shadow-rest); border-radius: var(--seg-thumb-r);", css)
            self.assertIn(".msn-head .sort-switch::before { display: none; }", css)


class EventsCard(unittest.TestCase):
    def test_the_card_is_white_and_lists_the_next_events(self):
        """The coral wash of 10/11 19:3x went when the captain chose the "Hai mươi lăm" mockup (~21:05): a white card
        like its neighbours, the schedule at its foot (tests/test_the_su_kien.py has the card itself)."""
        for folder in FOLDERS:
            css, feed = read(folder / "trang-msn.css"), read(folder / "feed.js")
            card = css[css.index(".band .msn-ev {"):]
            self.assertEqual(card[:card.index("}") + 1], ".band .msn-ev { padding: var(--space-12) var(--space-16) var(--space-16); }")
            self.assertIn(".ev-more { display: flex; flex-direction: column; min-height: 0; margin: auto 0 calc(-1 * var(--space-8));", css)
            self.assertIn("${evMoreHTML(rows)}", feed)
            more = feed[feed.index("function evMoreHTML(list) {"):]
            self.assertIn('<ol class="ev-more" aria-label="Tiếp theo">', more[:more.index("\n}\n")])


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered surfaces")
class RenderedSurfaces(unittest.TestCase):
    def test_panel_card_and_the_order_control_as_drawn(self):
        for name, page in rendered()["pages"].items():
            s = page["surfaces"]
            self.assertNotEqual(s["panel"], s["card"], name)
            self.assertEqual(s["card"], "rgb(255, 255, 255)", name)
            self.assertNotIn(s["track"], (None, "rgba(0, 0, 0, 0)", s["panel"]), name)
            pill = s["pill"]
            self.assertIsNotNone(pill, name)
            self.assertEqual((pill["bg"], pill["opacity"]), ("rgb(255, 255, 255)", "1"), name)
            self.assertNotEqual(pill["bg"], s["track"], name)
            self.assertNotEqual(pill["shadow"], "none", name)
            self.assertGreaterEqual(pill["h"], 44, name)
            self.assertLessEqual(abs(pill["w"] - s["pressed"]), 1, name)


if __name__ == "__main__":
    unittest.main()
