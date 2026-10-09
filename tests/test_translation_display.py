"""Offline checks for how the page shows machine-translated titles and the lead's source list.

site/titles.js is a pure ES module, so Node runs it without a DOM. The wiring in site/app.js is
checked by reading the source, as tests/test_bento_review_fixes.py does.
"""

from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

HARNESS = """
import {{ shown, origLine, uniqCoverage }} from {titles};
const esc = s => String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
const names = {{'ars-ai': 'Ars Technica AI', 'hn-ai': 'Hacker News', 'hn-front': 'Hacker News', 'lob': 'Lobsters'}};
const nameOf = id => names[id] || id;
const out = {{}};
out.shown = [
  shown('Introducing Claude Sonnet 5', 'Ra mắt Claude Sonnet 5'),
  shown('Introducing Claude Sonnet 5', undefined),
  shown('Introducing Claude Sonnet 5', '   '),
  shown('Grok 4 Fast', 'Grok 4 Fast'),
];
out.orig = [
  origLine('A <b>bold</b> title', 'Một tiêu đề', esc),
  origLine('Untranslated title', null, esc),
  origLine('Same', 'Same', esc),
  origLine('Lead title', 'Tiêu đề chính', esc, 'orig lead-orig'),
];
// The Stratego story of 03/10: two Hacker News feeds carry the same discussion.
const stratego = [
  {{source: 'ars-ai', publisher: 'ars-technica', url: 'https://arstechnica.com/x', metrics: {{}}}},
  {{source: 'hn-ai', publisher: 'hacker-news', url: 'https://arstechnica.com/x', discussion_url: 'https://news.ycombinator.com/item?id=1', metrics: {{points: 65, comments: 15}}}},
  {{source: 'hn-front', publisher: 'hacker-news', url: 'https://arstechnica.com/x', discussion_url: 'https://news.ycombinator.com/item?id=1', metrics: {{points: 65, comments: 15}}}},
];
out.stratego = uniqCoverage(stratego, nameOf).map(c => c.source);
out.richer = uniqCoverage([
  {{source: 'hn-front', publisher: 'hacker-news', metrics: {{}}}},
  {{source: 'lob', publisher: 'lobsters', metrics: {{score: 3}}}},
  {{source: 'hn-ai', publisher: 'hacker-news', metrics: {{points: 9, comments: 2}}}},
], nameOf).map(c => c.source);
out.noPublisher = uniqCoverage([{{source: 'hn-ai'}}, {{source: 'hn-front'}}, null], nameOf).map(c => c.source);
out.empty = uniqCoverage(undefined, nameOf);
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class TranslationDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness.write_text(HARNESS.format(titles=json.dumps((SITE / "titles.js").as_uri())),
                               encoding="utf-8", newline="\n")
            result = subprocess.run(["node", str(harness)], cwd=ROOT, capture_output=True,
                                    text=True, encoding="utf-8", timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout)
        cls.app = (SITE / "app.js").read_text(encoding="utf-8")
        cls.feed_js = (SITE / "feed.js").read_text(encoding="utf-8")
        cls.feed_css = (SITE / "feed.css").read_text(encoding="utf-8")

    def test_vietnamese_reads_first_and_original_is_the_fallback(self):
        self.assertEqual(self.out["shown"], ["Ra mắt Claude Sonnet 5", "Introducing Claude Sonnet 5",
                                             "Introducing Claude Sonnet 5", "Grok 4 Fast"])

    def test_original_line_is_labelled_and_escaped(self):
        labelled, untranslated, same, lead = self.out["orig"]
        # The chip reads "Translated" (owner, 03/10 17:49) and is hidden from screen readers, which hear the
        # Vietnamese sentence beside it.
        self.assertEqual(labelled, '<span class="orig" lang="en"><span class="mt" aria-hidden="true" '
                                   'title="Bản dịch máy; dòng này là tiêu đề gốc">Translated</span>'
                                   '<span class="sr" lang="vi">Bản dịch máy. Tiêu đề gốc: </span>'
                                   'A &lt;b&gt;bold&lt;/b&gt; title</span>')
        self.assertEqual(untranslated, "")
        self.assertEqual(same, "")
        self.assertIn('class="orig lead-orig"', lead)

    def test_lead_never_lists_a_source_twice(self):
        self.assertEqual(self.out["stratego"], ["ars-ai", "hn-ai"])
        self.assertEqual(self.out["richer"], ["hn-ai", "lob"], "the entry with numbers wins, order kept")
        self.assertEqual(self.out["noPublisher"], ["hn-ai"], "without a publisher, the source name decides")
        self.assertEqual(self.out["empty"], [])

    def test_lead_and_sheet_use_the_deduplicated_list(self):
        self.assertIn('aria-label="Các nguồn đưa chuyện này">${covOf(st).map(', self.app)
        self.assertIn("const cov = [...covOf(st)].sort(", self.app)
        self.assertNotIn("(st.coverage || []).map(c => `<li>", self.app)

    def test_every_headline_slot_reads_the_translation(self):
        self.assertIn("import { shown as viShown, headlineShown, origLine, uniqCoverage } from './titles.js';", self.app)
        # Rows, hot list, lead, videos, sheet and coverage links all go through tt(); none print the raw title.
        self.assertGreaterEqual(self.app.count("${tt("), 10)
        for raw in ("${esc(String(st.title))}</span>", "${esc(String(s.title))}</span>", "${esc(String(c.title))}</a>",
                    "<h2>${esc(String(st.title))}</h2>", "<strong>${esc(String(L0.title))}</strong>"):
            self.assertNotIn(raw, self.app)
        self.assertIn("viShown(r.description, r.description_vi)", self.app)

    def test_headlines_and_screened_images_across_reader_surfaces(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "verify-feed-content.mjs")],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_card_source_marks_do_not_overlap(self):
        self.assertIn('.cov-btn .av-stack { gap: var(--space-4); }', self.feed_css)
        self.assertIn('.cov-btn .av-stack-item + .av-stack-item { margin-left: 0; }', self.feed_css)

    def test_footer_names_the_model_and_its_licence(self):
        self.assertIn("NLLB-200 (giấy phép CC-BY-NC 4.0", self.app)
        self.assertIn("t.error_vi", self.app)

    def test_feed_machine_translation_chip_reads_translated(self):
        # Owner decision (03/10 17:49): chip reads "Translated", not "dịch máy",
        # hidden from screen readers which hear the Vietnamese sentence beside it.
        self.assertIn('>Translated</span>', self.feed_js)
        self.assertNotIn('>dịch máy</span>', self.feed_js)
        self.assertIn('<span class="mt" aria-hidden="true" title="Bản dịch máy; dòng này là tiêu đề gốc">Translated</span>', self.feed_js)
        self.assertIn('<span class="sr" lang="vi">Bản dịch máy. Tiêu đề gốc: </span>', self.feed_js)

    def test_feed_chip_style_uses_google_translate_colors_everywhere(self):
        # The chip uses Google Translate colors (--color-mt-bg, --color-mt-ink) everywhere,
        # without being overridden on photo cards.
        self.assertIn("var(--color-mt-bg)", self.feed_css)
        self.assertIn("var(--color-mt-ink)", self.feed_css)
        self.assertNotIn(".card-photo .mt", self.feed_css)

    def test_feed_footer_names_translated_label(self):
        self.assertIn('kèm nhãn “Translated”.', self.feed_js)
        self.assertNotIn('kèm nhãn “dịch máy”.', self.feed_js)


if __name__ == "__main__":
    unittest.main()
