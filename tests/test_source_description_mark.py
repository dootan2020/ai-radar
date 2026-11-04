"""A story without a Halcyon summary labels its publisher's description; a desk story does not."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
LABEL = "Mô tả từ nguồn"


@unittest.skipUnless(shutil.which("node"), "Node required for offline reader rendering")
class SourceDescriptionMarkTests(unittest.TestCase):
    def render(self):
        story = (ROOT / "site" / "story.js").as_uri()
        headline = (ROOT / "site" / "editorial-headline.js").as_uri()
        edition = (ROOT / "site" / "ban-tin.js").as_uri()
        program = f"""
import {{ renderStoryHTML }} from {json.dumps(story)};
import {{ sourceDescriptionMark }} from {json.dumps(headline)};
import {{ renderStoryTileHTML }} from {json.dumps(edition)};
const base = {{title: 'Lenovo Kaitian Unveils AI Host', url: 'https://pandaily.example/lenovo',
  published_at: '2026-11-04T01:56:50Z', coverage: [{{source: 'pandaily', publisher: 'pandaily', url: 'https://pandaily.example/lenovo'}}],
  summary: "Lenovo Kaitian's 1.6L AI host pairs a Zhaoxin KX-7000 with a Houmo LQ50 NPU.",
  summary_vi: 'Máy chủ AI 1.6L của Lenovo Kaitian kết hợp một Zhaoxin KX-7000 với một Houmo LQ50 NPU.'}};
const fallback = {{...base, id: 'b0cb80c7ddf2de0b8b38'}};
const desk = {{...base, id: 'desk-story', key_points_source: 'nguoi-viet', key_points_prompt_version: 'summary-vi-6-prose',
  editorial_headline_vi: 'Lenovo ra máy AI chạy mô hình 35B tại chỗ',
  summary_sources: [{{name: 'Pandaily', url: 'https://pandaily.example/lenovo', role: 'outlet'}}],
  key_points: ['Diễn biến chính.', 'Nguyên nhân và ví dụ.', 'Ý nghĩa của sự kiện.']}};
const srcMap = new Map([['pandaily', {{id: 'pandaily', name: 'Pandaily', publisher: 'pandaily'}}]]);
const view = (s, o) => renderStoryHTML(s, srcMap, o);
console.log(JSON.stringify({{
  fallback: {{page: view(fallback, {{isPage: true}}), modal: view(fallback, {{isModal: true}}),
    card: sourceDescriptionMark(fallback), edition: renderStoryTileHTML(fallback)}},
  desk: {{page: view(desk, {{isPage: true}}), modal: view(desk, {{isModal: true}}),
    card: sourceDescriptionMark(desk), edition: renderStoryTileHTML(desk)}},
}}));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", program], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fallback_story_names_the_publishers_description(self):
        out = self.render()["fallback"]
        for surface in ("page", "modal"):
            document = out[surface]
            self.assertIn(f'<h2 class="story-section-h2">{LABEL}</h2>', document)
            self.assertIn("Lời giới thiệu ngắn của Pandaily. Halcyon chưa tóm tắt tin này.", document)
            self.assertIn("Máy chủ AI 1.6L của Lenovo Kaitian", document)
            # The machine translation is named once, by the existing chip, never as "dịch máy" in visible text.
            self.assertIn('>Translated</span>', document)
            self.assertNotIn("Đoạn trích bài viết", document)
            self.assertNotIn("Phòng báo Halcyon tóm tắt", document)
        self.assertEqual(out["card"], f'<span class="src-desc">{LABEL}</span> ')
        self.assertIn(f'<p class="bt-story-summary"><span class="src-desc">{LABEL}</span> Máy chủ AI', out["edition"])

    def test_desk_story_keeps_its_summary_without_the_mark(self):
        out = self.render()["desk"]
        for surface in ("page", "modal"):
            document = out[surface]
            self.assertNotIn(LABEL, document)
            self.assertIn("Phòng báo Halcyon tóm tắt từ Pandaily", document)
            self.assertIn('class="story-prose-text">Diễn biến chính.</p>', document)
        self.assertEqual(out["card"], "")
        self.assertNotIn(LABEL, out["edition"])

    def test_feed_card_and_static_page_use_the_shared_label(self):
        feed = (ROOT / "site" / "feed.js").read_text(encoding="utf-8")
        self.assertIn("<p class=\"card-sum\">${sourceDescriptionMark(st)}${esc(sum)}</p>", feed)
        from radar.story_pages import SOURCE_DESCRIPTION_LABEL
        self.assertEqual(SOURCE_DESCRIPTION_LABEL, LABEL)


if __name__ == "__main__":
    unittest.main()
