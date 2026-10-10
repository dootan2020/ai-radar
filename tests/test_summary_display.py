"""Execute the shared page/modal renderer offline with machine summary content."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node required for offline reader rendering")
class SummaryDisplayTests(unittest.TestCase):
    def test_full_summary_replaces_excerpt_in_page_and_modal_with_trusted_sources(self):
        module = (ROOT / "site" / "story.js").as_uri()
        program = f"""
import {{ renderStoryHTML }} from {json.dumps(module)};
const story = {{id: 'summary-example', title: 'Source title',
  url: 'https://publisher.example/article', published_at: '2026-10-10T00:00:00Z',
  summary: 'Publisher excerpt.', key_points_machine: true,
  key_points_prompt_version: 'summary-vi-5-full',
  summary_sources: [{{name:'Publisher', url:'https://publisher.example/article', role:'outlet'}}, {{name:'HelioLab', url:'https://official.example/report', role:'primary'}}],
  key_points: ['Nội dung <script>bad()</script>.', 'Số liệu từ nguồn.', 'Ý nghĩa của sự kiện.', '**GPU** vẫn giữ nguyên tên.']}};
const options = {{now: Date.parse('2026-10-10T01:00:00Z')}};
console.log(JSON.stringify([
  renderStoryHTML(story, new Map(), {{...options, isPage: true}}),
  renderStoryHTML(story, new Map(), {{...options, isModal: true}}),
  renderStoryHTML({{...story, key_points: []}}, new Map(), {{...options, isPage: true}})
]));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", program], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        page, modal, fallback = json.loads(result.stdout)
        for document in (page, modal):
            self.assertIn('class="story-keypoints-box"', document)
            self.assertNotIn('class="story-summary-box"', document)
            self.assertNotIn('Đọc nhanh', document)
            self.assertNotIn('Đọc đầy đủ', document)
            self.assertNotIn('Ý chính:', document)
            self.assertIn('<strong>GPU</strong>', document)
            self.assertIn('href="https://official.example/report"', document)
            self.assertIn("Tóm tắt bằng AI", document)
            self.assertNotIn("Publisher excerpt.", document)
            self.assertIn('href="https://publisher.example/article"', document)
            self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", document)
            self.assertNotIn("<script>bad()</script>", document)
        self.assertNotIn('class="story-keypoints-box"', fallback)
        self.assertNotIn("Tóm tắt bằng AI", fallback)
        self.assertIn("Publisher excerpt.", fallback)
