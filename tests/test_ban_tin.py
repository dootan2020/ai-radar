"""Tests for the daily edition reader page (site/ban-tin.html, site/ban-tin.js, site/ban-tin.css).

Covers:
- Normal day (single story and multi-story)
- Empty day (stories: [])
- Missing day (date not in archive)
- Failed fetch (network/server error)
- Static head checks (CSP hash, tight directives, stylesheet & module links)
- Typography and craft rules (no em-dash in UI copy, no banned words)
"""

from pathlib import Path
from html.parser import HTMLParser
import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA_THAT = ROOT / "plans" / "nhap" / "du-lieu-that" / "editions"


def read_text(path):
    return path.read_text(encoding="utf-8")


def csp_directives(html):
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    if not meta:
        raise AssertionError("no CSP meta tag in HTML")
    out = {}
    for part in meta.group(1).split(";"):
        words = part.split()
        if words:
            out[words[0]] = words[1:]
    return out


class BanTinHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_text(SITE / "ban-tin.html")
        cls.head = cls.html.split("</head>")[0]
        cls.csp = csp_directives(cls.html)
        cls.js = read_text(SITE / "ban-tin.js")
        cls.css = read_text(SITE / "ban-tin.css")

    def test_inline_script_matches_sha256_hash_in_csp(self):
        scripts = re.findall(r"<script>([\s\S]*?)</script>", self.html)
        self.assertEqual(len(scripts), 1, "exactly one inline script for theme before paint")
        # One line only for cross-platform hash stability
        self.assertNotIn("\n", scripts[0])
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"'sha256-{digest}'", self.csp["script-src"])
        self.assertNotIn("'unsafe-inline'", self.csp["script-src"])

    def test_csp_policy_is_closed_and_tight(self):
        self.assertEqual(self.csp["default-src"], ["'self'"])
        self.assertEqual(self.csp["object-src"], ["'none'"])
        self.assertEqual(self.csp["base-uri"], ["'self'"])
        self.assertEqual(self.csp["font-src"], ["'self'"])
        self.assertEqual(self.csp["form-action"], ["'none'"])
        self.assertTrue(re.search(r'<meta http-equiv="Content-Security-Policy" content="[^"]+;">', self.html))

    def test_cloudflare_beacon_present(self):
        scripts = re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>", self.html)
        beacons = [(attrs, body) for attrs, body in scripts if "cloudflareinsights.com" in attrs]
        self.assertEqual(len(beacons), 1)
        attrs, _ = beacons[0]
        self.assertIn("type='module'", attrs)
        self.assertIn("src='https://static.cloudflareinsights.com/beacon.min.js'", attrs)

    def test_links_and_preloads_are_ordered_and_present(self):
        self.assertIn('<link rel="stylesheet" href="tokens.css">', self.head)
        self.assertIn('<link rel="stylesheet" href="ban-tin.css">', self.head)
        self.assertIn('<script type="module" src="ban-tin.js"></script>', self.head)
        for mod in ("faces.js", "time-text.js", "words.js", "titles.js"):
            self.assertIn(f'<link rel="modulepreload" href="{mod}">', self.head)

    def test_no_em_dash_in_ban_tin_ui_copy(self):
        # Craft rule: zero em-dashes (—) in user-facing UI text
        self.assertNotIn("—", self.html, "em-dash found in ban-tin.html")
        self.assertNotIn("—", self.js, "em-dash found in ban-tin.js")

    def test_no_banned_ai_slop_words(self):
        banned = ["elevate", "seamless", "unleash", "game-changer", "supercharge", "next-gen"]
        combined = (self.html + " " + self.js).lower()
        for word in banned:
            self.assertNotIn(word, combined, f"banned word '{word}' found in ban-tin files")

    def test_no_default_45_in_ban_tin_js(self):
        self.assertNotIn("|| 45", self.js, "Default fallback || 45 found in ban-tin.js")
        self.assertNotIn("daily-evidence-v2", self.js, "Raw policy ID daily-evidence-v2 found in ban-tin.js")


HARNESS_CODE = """
import {{
  formatFullDateVi,
  formatShortDateVi,
  formatEditionTimeVi,
  getStorySummary,
  findEditionByDate,
  getAdjacentEditions,
  renderStoryTileHTML,
  renderEmptyStateHTML,
  renderMissingStateHTML,
  renderErrorStateHTML,
  renderEndSectionHTML
}} from {ban_tin_js};

import fs from 'node:fs';

const out = {{}};

// 1. Dữ liệu thật từ plans/nhap/du-lieu-that/editions/
const realIndex = JSON.parse(fs.readFileSync({real_index_path}, 'utf-8'));
const realEdition = JSON.parse(fs.readFileSync({real_day_path}, 'utf-8'));

// Test date formatters
out.fullDate = formatFullDateVi('2026-10-03');
out.shortDate = formatShortDateVi('2026-10-03');
out.editionTime = formatEditionTimeVi(realEdition);

// Test normal day single story
const singleStory = realEdition.stories[0];
out.singleTileHtml = renderStoryTileHTML(singleStory, true);
out.singleSummary = getStorySummary(singleStory);
out.endSectionToday = renderEndSectionHTML(realEdition.date, true, realIndex.editions);

// Test multi-story edition with summary
const multiEdition = JSON.parse(JSON.stringify(realEdition));
const secondStory = JSON.parse(JSON.stringify(singleStory));
secondStory.id = 'second-story-123';
secondStory.title = 'Anthropic releases Claude 5';
secondStory.title_vi = 'Anthropic ra mắt Claude 5';
secondStory.summary = 'Mô hình mới tập trung vào khả năng lập trình và suy luận logic sâu.';
secondStory.source_count = 3;
secondStory.selection = {{
  reasons: [
    {{ code: 'primary_release', text: 'Tiêu đề nguồn gốc có dấu hiệu công bố model hoặc sản phẩm' }},
    {{ code: 'publisher_coverage', text: '3 định danh nhà xuất bản cùng đưa tin' }}
  ],
  signals: {{
    publishers: ['anthropic', 'techcrunch', 'the-verge'],
    age_hours_at_cutoff: 4.5,
    hot_score: 95.2,
    engagement_percentile: 0.98
  }}
}};
multiEdition.stories.push(secondStory);
out.secondTileHtml = renderStoryTileHTML(secondStory, false);
out.secondSummary = getStorySummary(secondStory);

// Test empty day with measured health
const emptyEdition = JSON.parse(JSON.stringify(realEdition));
emptyEdition.stories = [];
out.emptyStateHtml = renderEmptyStateHTML(emptyEdition);

// Test empty day WITHOUT source_health (honest handling, no defaulted 45)
const emptyNoHealth = JSON.parse(JSON.stringify(realEdition));
emptyNoHealth.stories = [];
delete emptyNoHealth.source_health;
out.emptyStateNoHealthHtml = renderEmptyStateHTML(emptyNoHealth);

// Test missing day
out.missingStateHtml = renderMissingStateHTML('2026-09-15', realIndex.latest.date);

// Test failed fetch
out.errorStateHtml = renderErrorStateHTML('Network timeout');

// Test adjacent editions navigation
const mockIndex = {{
  schema_version: 1,
  latest: {{ date: '2026-10-03', path: '2026-10-03.json' }},
  editions: [
    {{ date: '2026-10-03', path: '2026-10-03.json' }},
    {{ date: '2026-10-02', path: '2026-10-02.json' }},
    {{ date: '2026-10-01', path: '2026-10-01.json' }}
  ]
}};

out.adjLatest = getAdjacentEditions(mockIndex, '2026-10-03');
out.adjMiddle = getAdjacentEditions(mockIndex, '2026-10-02');
out.adjOldest = getAdjacentEditions(mockIndex, '2026-10-01');
out.adjMissing = getAdjacentEditions(mockIndex, '2026-09-01');

process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class BanTinRenderLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real_day_path = DATA_THAT / "2026-10-03.json"
        real_index_path = DATA_THAT / "index.json"
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness_src = HARNESS_CODE.format(
                ban_tin_js=json.dumps((SITE / "ban-tin.js").as_uri()),
                real_index_path=json.dumps(str(real_index_path)),
                real_day_path=json.dumps(str(real_day_path)),
            )
            harness.write_text(harness_src, encoding="utf-8", newline="\n")
            result = subprocess.run(
                ["node", str(harness)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
        if result.returncode != 0:
            raise AssertionError("Harness execution failed:\n" + result.stdout + result.stderr)
        cls.out = json.loads(result.stdout)

    def test_date_formatting_vietnamese(self):
        self.assertEqual(self.out["fullDate"], "Thứ Bảy, ngày 3 tháng 10 năm 2026")
        self.assertEqual(self.out["shortDate"], "03/10/2026")

    def test_edition_creation_and_cutoff_time(self):
        # 14:45:47Z is 21:45 in Asia/Ho_Chi_Minh; 23:00:00Z is 06:00
        self.assertEqual(self.out["editionTime"], "Xuất bản lúc 21:45 · Dữ liệu chốt 06:00 (giờ Việt Nam)")

    def test_normal_day_single_story_rendering(self):
        tile = self.out["singleTileHtml"]
        # Vietnamese title rendered first
        self.assertIn("AstaBrief nguồn mở, mô hình tạo báo cáo nhanh trong Asta", tile)
        # Original title marked as translated
        self.assertIn('class="mt" aria-hidden="true" title="Bản dịch máy; dòng này là tiêu đề gốc">Translated</span>', tile)
        self.assertIn("Open-sourcing AstaBrief, the fast report-generation model in Asta", tile)
        # Display name resolved from sources catalog
        self.assertIn("Hugging Face Blog", tile)
        self.assertNotIn('<span class="bt-source-name">huggingface-blog</span>', tile)
        # Verified logo present
        self.assertIn("avatars.githubusercontent.com/huggingface", tile)
        # Selection reason present
        self.assertIn("Tiêu đề nguồn gốc có dấu hiệu công bố model hoặc sản phẩm", tile)
        # Real numbers present
        self.assertIn("nhà xuất bản", tile)
        # No confusing pipeline arithmetic
        self.assertNotIn("giờ trước giờ chốt", tile)
        # Link to original
        self.assertIn('href="https://huggingface.co/blog/allenai/astabrief"', tile)
        self.assertIn('target="_blank"', tile)
        self.assertIn('rel="noopener noreferrer"', tile)
        # Single story has no invented summary
        self.assertIsNone(self.out["singleSummary"])
        self.assertNotIn("bt-story-summary", tile)

    def test_normal_day_multi_story_with_summary(self):
        tile = self.out["secondTileHtml"]
        self.assertIn("Anthropic ra mắt Claude 5", tile)
        self.assertIn("bt-story-summary", tile)
        self.assertEqual(self.out["secondSummary"], "Mô hình mới tập trung vào khả năng lập trình và suy luận logic sâu.")
        self.assertIn("3 định danh nhà xuất bản cùng đưa tin", tile)
        self.assertIn("95", tile)  # hot score
        self.assertIn("98%", tile)  # engagement percentile

    def test_empty_day_honest_state(self):
        empty_html = self.out["emptyStateHtml"]
        self.assertIn("Hôm nay không có tin nào đạt tiêu chuẩn biên tập", empty_html)
        self.assertIn("Không chèn tin bù lấp chỗ", empty_html)
        self.assertIn("45 nguồn", empty_html)

        # When source_health is missing, no default 45 is shown
        no_health_html = self.out["emptyStateNoHealthHtml"]
        self.assertIn("Hôm nay không có tin nào đạt tiêu chuẩn biên tập", no_health_html)
        self.assertIn("Không chèn tin bù lấp chỗ", no_health_html)
        self.assertNotIn("45", no_health_html, "Invented 45 shown when source_health is missing")
        self.assertIn("Đã rà soát các nguồn tin độc lập", no_health_html)

    def test_missing_day_honest_state(self):
        missing_html = self.out["missingStateHtml"]
        self.assertIn("Không tìm thấy bản tin ngày 15/09/2026", missing_html)
        self.assertIn("Về bản tin mới nhất (03/10/2026)", missing_html)

    def test_failed_fetch_error_state(self):
        error_html = self.out["errorStateHtml"]
        self.assertIn("Không thể tải bản tin", error_html)
        self.assertIn("bt-retry-btn", error_html)
        self.assertIn("Thử tải lại", error_html)

    def test_end_section_today(self):
        end_html = self.out["endSectionToday"]
        self.assertIn("Hết bản tin hôm nay", end_html)
        self.assertIn("Bạn đã xem trọn vẹn điểm tin AI sáng nay", end_html)
        self.assertIn("Về đầu trang", end_html)

    def test_adjacent_editions_navigation(self):
        # At latest edition: next is None, prev is yesterday
        self.assertIsNone(self.out["adjLatest"]["next"])
        self.assertEqual(self.out["adjLatest"]["prev"]["date"], "2026-10-02")

        # In middle: next is newer (2026-10-03), prev is older (2026-10-01)
        self.assertEqual(self.out["adjMiddle"]["next"]["date"], "2026-10-03")
        self.assertEqual(self.out["adjMiddle"]["prev"]["date"], "2026-10-01")

        # At oldest: prev is None, next is newer (2026-10-02)
        self.assertIsNone(self.out["adjOldest"]["prev"])
        self.assertEqual(self.out["adjOldest"]["next"]["date"], "2026-10-02")

        # Missing date
        self.assertIsNone(self.out["adjMissing"]["prev"])
        self.assertIsNone(self.out["adjMissing"]["next"])


if __name__ == "__main__":
    unittest.main()
