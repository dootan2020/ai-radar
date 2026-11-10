"""The front page's reading order (owner, 10/11 11:46: "mục 'Vừa đăng' nằm ở mãi dưới. khi click vào 'N tin mới' thì
trang kéo xuống tới đó nhưng cực kỳ khó nhận ra đó là thẻ tin mới"): the lead, "Vừa đăng" beside it, "Chuyện lớn",
the stories; the weather, the calendar and the next event after the first six stories in the page's order (a wider
screen pins them to its last column); "Đáng chú ý" on one card; the pill's batch marked "Mới" and lit up briefly."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = (ROOT / "site", ROOT / "extension")


def read(path):
    return path.read_text(encoding="utf-8")


class FrontOrder(unittest.TestCase):
    """Since the bento bands (captain, 10/11 17:51): "Hôm nay" holds the lead, "Vừa đăng" and the weather; "Điểm nhấn"
    holds "Chuyện lớn", "Đáng chú ý", the next event and the calendar. In each band the news comes before the widgets,
    so a phone (one column, the page's order) reads the news first."""

    def test_lead_then_fresh_then_top_list_then_the_stories(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            front = feed[feed.index("function frontHTML() {"):]
            front = front[:front.index("\n}\n")]
            order = ["leadHTML(PICKLIST)", "freshTileHTML()", "topListHTML(FRONT_TOP)", "bandHTML('news'", "renderLab()", "bandHTML('more'"]
            self.assertEqual([front.index(x) for x in order], sorted(front.index(x) for x in order))
            self.assertNotIn("const widgets = [", feed, "Vừa đăng and the tiles are no longer widgets deep in the stream")

    def test_each_band_puts_its_news_before_its_widgets(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            self.assertIn('${leadHTML(PICKLIST)}${freshTileHTML()}<i data-slot="wx"></i>', feed)
            self.assertIn("${topListHTML(FRONT_TOP)}${notable ? msnCard(notable, 'wide', true) : ''}${renderNext()}<i data-slot=\"cal\"></i>", feed)
            self.assertNotIn("FURNITURE_AFTER", feed)

    def test_fresh_holds_the_first_row_beside_the_lead_at_every_desktop_width(self):
        for folder in FOLDERS:
            css = read(folder / "trang-msn.css")
            self.assertIn(".band-cells > .msn-lead, .band-cells > .nc-wide, .band-cells > .tile-fresh { grid-column: span 2; }", css)
            four = css[css.index("@media (min-width: 1024px) and (max-width: 1439px)"):]
            self.assertIn(".band-today .band-cells > .tile-fresh { grid-column: span 1; }", four[:four.index("\n}\n")])
            three = css[css.index("@media (min-width: 768px) and (max-width: 1023px)"):]
            self.assertIn(".band-today .band-cells > .msn-lead { grid-column: 1 / -1; }", three[:three.index("\n}\n")])
            self.assertNotIn("@media (min-width: 1750px)", css)
            # The other views keep the weather and the calendar pinned to the grid's last column.
            self.assertIn(".msn-grid > .msn-wx { grid-area: 1 / -2; }", css)
            self.assertIn(".msn-grid > .msn-ev { grid-area: 2 / -3; }", css)

    def test_one_card_says_dang_chu_y(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            self.assertIn("${kicker ? '<p class=\"nc-kicker\">Đáng chú ý</p>' : ''}", feed)
            self.assertNotIn("${size ? '<p class=\"nc-kicker\">Đáng chú ý</p>' : ''}", feed)
            self.assertEqual(feed.count("Đáng chú ý</p>"), 1)
            # Only the second band's notable story is drawn with the label.
            self.assertEqual(len(re.findall(r"msnCard\([^)]*, true\)", feed)), 1)


class FreshPill(unittest.TestCase):
    def test_fresh_rows_carry_the_headline_alone(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            item = feed[feed.index("function freshItem(st) {"):feed.index("function freshInnerHTML()")]
            self.assertNotIn("titleHTML(", item, "no 'Đang bàn nhiều:' or flame before a Vừa đăng headline")
            self.assertIn('<span class="fresh-new" aria-hidden="true">Mới</span>${esc(t.text)}', item)
            self.assertIn("const pinned = freshIds.includes(st.id) && !read.has(st.id);", item)

    def test_the_pill_lands_on_fresh_and_lights_its_batch_briefly(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            go = feed[feed.index("function goFirstNew() {"):feed.index("function markSeen()")]
            self.assertIn("const rows = $$('#fresh-row li[data-pinned]');", go)
            self.assertIn("rows.forEach(li => li.classList.add('is-flash'));", go)
            self.assertIn("setTimeout(() => rows.forEach(li => li.classList.remove('is-flash')), FRESH_FLASH_MS);", go)
            self.assertIn("const FRESH_FLASH_MS = 2000;", feed)
            css = read(folder / "trang-msn.css")
            # The chip: Hot Coral fill with ink text (no small coral text on light), until the story is opened.
            self.assertIn(".fresh-list li[data-pinned]:not(.is-read) .fresh-new {", css)
            chip = css[css.index(".fresh-list li[data-pinned]:not(.is-read) .fresh-new {"):]
            chip = chip[:chip.index("}")]
            self.assertIn("background: var(--color-accent-fill); color: var(--color-on-accent);", chip)
            self.assertIn(".fresh-list li.is-flash { animation: fresh-flash var(--fresh-flash) var(--ease-flow) both; }", css)
            reduced = css[css.index("@media (prefers-reduced-motion: reduce)"):]
            self.assertIn(".fresh-list li.is-flash { animation: none; background: var(--color-accent-wash-strong); }", reduced)
            tokens = read(folder / "tokens.css")
            self.assertIn("--fresh-flash: 2000ms;", tokens)


if __name__ == "__main__":
    unittest.main()
