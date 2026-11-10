"""The lead carousel's dots (captain, 10/11 15:52: "bỏ cái nền của mấy dấu chấm trên tim thẻ tin đầu tiên cho a. chỉ để
mấy dấu chấm, có bao nhiêu tin ở carousel này thì từng ấy chấm"): no chip behind them, one dot per story, none for one."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

HARNESS = r"""
const esc = s => String(s ?? '');
const pickImage = () => ({ kind: 'photo', src: 'x.jpg' });
const titleOf = st => ({ text: st.title });
const statusClass = () => '', storyStatus = () => 'new', storyHref = st => `tin/${st.id}/`, langAttr = () => '';
const metaHTML = () => '', mediaHTML = () => '<img>';
__LEAD__
const out = {};
for (const n of [1, 2, 4, 6]) {
  const html = leadHTML(Array.from({ length: n }, (_, i) => ({ id: 's' + i, title: 'Tin ' + i })));
  out[n] = { slides: (html.match(/<article class="slide/g) || []).length, dots: (html.match(/data-slide="/g) || []).length,
    current: (html.match(/aria-current="true"/g) || []).length, group: html.includes('class="lead-dots pager-dots"') };
}
process.stdout.write(JSON.stringify(out));
"""


class LeadDots(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required for the carousel test")
    def test_one_dot_per_story_and_none_for_a_single_story(self):
        feed = (SITE / "feed.js").read_text(encoding="utf-8")
        start = feed.index("function leadHTML(list) {")
        lead = feed[start:feed.index("\n}\n", start) + 2]
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "lead.mjs"
            harness.write_text(HARNESS.replace("__LEAD__", lead), encoding="utf-8", newline="\n")
            run = subprocess.run(["node", str(harness)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        got = json.loads(run.stdout)
        self.assertEqual(got["1"], {"slides": 1, "dots": 0, "current": 0, "group": False})
        for n in (2, 4, 6):
            self.assertEqual(got[str(n)], {"slides": n, "dots": n, "current": 1, "group": True}, n)

    def test_the_dots_sit_on_the_photo_with_no_chip(self):
        css = (SITE / "trang-msn.css").read_text(encoding="utf-8")
        self.assertNotIn(".lead-dots::before", css)
        self.assertNotIn("--msn-lead-dots-bg", (SITE / "tokens.css").read_text(encoding="utf-8"))
        dot = re.search(r"\.pager-dots button::before \{([^}]*)\}", css).group(1)
        self.assertIn("box-shadow: var(--pager-dot-shadow);", dot)
        # Each dot stays a 44 px tall button: the group keeps its touch target without the chip.
        self.assertIn("height: var(--btn-h);", re.search(r"\.pager-dots button \{([^}]*)\}", css).group(1))


class PagerDots(unittest.TestCase):
    """Captain, 10/11 18:54: "2 dấu chấm của thẻ thời tiết nó nằm xa nhau quá / các dấu chấm trên carousel thì có viền, bỏ
    viền đi. bảo đảm các dấu chấm trên carousel phải đồng bộ với nhau". One dot style for every row of dots, no ring."""

    def test_one_shared_dot_style_with_no_ring(self):
        for folder in (SITE, ROOT / "extension"):
            css = (folder / "trang-msn.css").read_text(encoding="utf-8")
            tokens = (folder / "tokens.css").read_text(encoding="utf-8")
            # The look is defined once: only .pager-dots draws a dot; the rows place their group and nothing else.
            self.assertEqual(len(re.findall(r"button::before \{", css[css.index(".pager-dots {"):css.index(".msn-lead { touch-action")])), 1)
            for row in ("lead-dots", "wx-dots"):
                for rule in re.findall(rf"\.{row}[^{{,]*\{{([^}}]*)\}}", css):
                    for prop in ("width:", "height:", "background", "box-shadow", "border"):
                        self.assertNotIn(prop, rule.replace("padding-inline", ""), f"{folder.name} .{row}: {rule}")
            # No ring: neither a zero-blur spread in the shadow nor a border or outline on a dot at rest.
            shadow = re.search(r"--pager-dot-shadow: ([^;]+);", tokens).group(1)
            for layer in shadow.split("), "):
                self.assertNotRegex(layer.strip(), r"^0 0 0 ", f"{folder.name}: a ring in {shadow}")
            button = re.search(r"\.pager-dots button \{([^}]*)\}", css).group(1)
            self.assertIn("border: 0;", button)
            self.assertIn("background: none;", button)
            self.assertNotRegex(re.search(r"\.pager-dots button::before \{([^}]*)\}", css).group(1), r"(?<![\w-])(border|outline)(-\w+)?(?<!-radius):")
            for gone in ("--msn-lead-dot", "--msn-on-photo-dot"):
                self.assertNotIn(gone, tokens + css, folder.name)

    def test_both_rows_of_dots_use_the_shared_style(self):
        for folder in (SITE, ROOT / "extension"):
            self.assertIn('<div class="lead-dots pager-dots" role="group"', (folder / "feed.js").read_text(encoding="utf-8"))
            self.assertIn('<div class="wx-dots pager-dots" role="group"', (folder / "thoi-tiet.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
