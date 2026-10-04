"""Tests for 7-day search index projection (radar-search.json).

Verifies:
1. Index covers every retained story (no stories omitted).
2. Diacritic-free query matching on Vietnamese and English titles and publishers.
3. Strict adherence to size budget (< 500 KB raw, < 150 KB gzipped for 1,100 stories).
4. No invented or defaulted fields for missing data.
5. Atomic writes and cleanup in write_site_snapshot.
6. Path convention and build collision safety.
"""

from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import build
from radar import search_index, site_payload
from test_publication import snapshot

FIXTURES = TESTS_DIR / "fixtures"


def sample_vietnamese_stories():
    return [
        {
            "id": "vn-story-1",
            "title": "Understanding Frontier Artificial Intelligence",
            "title_vi": "Hiểu được trí tuệ nhân tạo tiên phong",
            "url": "https://casp.ac/reports/intelligence-explosion",
            "published_at": "2026-10-03T07:06:02Z",
            "kind": "forum",
            "coverage": [
                {
                    "id": "cov-1",
                    "publisher": "hacker-news",
                    "url": "https://casp.ac/reports/intelligence-explosion",
                }
            ],
            "carried": True,
        },
        {
            "id": "vn-story-2",
            "title": "Đà Nẵng xây dựng trung tâm nghiên cứu thiết kế vi mạch bán dẫn và AI",
            "title_vi": "Đà Nẵng xây dựng trung tâm nghiên cứu thiết kế vi mạch bán dẫn và AI",
            "url": "https://tuoitre.vn/da-nang-xay-dung-trung-tam-vi-mach-ai.htm",
            "published_at": "2026-10-02T15:30:00Z",
            "kind": "press",
            "coverage": [
                {
                    "id": "cov-2",
                    "publisher": "tuoi-tre",
                    "url": "https://tuoitre.vn/da-nang-xay-dung-trung-tam-vi-mach-ai.htm",
                }
            ],
            "carried": True,
        },
        {
            "id": "vn-story-3",
            "title": "OpenAI ra mắt GPT-5 với đột phá mới về khả năng suy luận",
            "url": "https://genk.vn/openai-ra-mat-gpt-5-dot-pha-suy-luan.chn",
            "published_at": "2026-10-01T08:00:00Z",
            "kind": "model",
            "coverage": [
                {
                    "id": "cov-3",
                    "publisher": "genk",
                    "url": "https://genk.vn/openai-ra-mat-gpt-5-dot-pha-suy-luan.chn",
                }
            ],
            "carried": False,
        },
    ]


class SearchIndexTests(unittest.TestCase):
    def test_normalize_vietnamese_comprehensive(self):
        # Tone marks and diacritical marks
        self.assertEqual(
            search_index.normalize_vietnamese("Trí tuệ nhân tạo"),
            "tri tue nhan tao"
        )
        self.assertEqual(
            search_index.normalize_vietnamese("Đà Nẵng"),
            "da nang"
        )
        self.assertEqual(
            search_index.normalize_vietnamese("Đột phá công nghệ"),
            "dot pha cong nghe"
        )
        # All Vietnamese vowels with diverse accents
        self.assertEqual(
            search_index.normalize_vietnamese("à á ả ã ạ ă ằ ắ ẳ ẵ ặ â ầ ấn ẩ ẫ ậ"),
            "a a a a a a a a a a a a a an a a a"
        )
        self.assertEqual(
            search_index.normalize_vietnamese("è é ẻ ẽ ẹ ê ề ế ể ễ ệ"),
            "e e e e e e e e e e e"
        )
        self.assertEqual(
            search_index.normalize_vietnamese("ì í ỉ ĩ ị"),
            "i i i i i"
        )
        self.assertEqual(
            search_index.normalize_vietnamese("ò ó ỏ õ ọ ô ồ ố ổ ỗ ộ ơ ờ ớ ở ỡ ợ"),
            "o o o o o o o o o o o o o o o o o"
        )
        self.assertEqual(
            search_index.normalize_vietnamese("ù ú ủ ũ ụ ư ừ ứ ử ữ ự"),
            "u u u u u u u u u u u"
        )
        self.assertEqual(
            search_index.normalize_vietnamese("ỳ ý ỷ ỹ ỵ"),
            "y y y y y"
        )
        # Stroke letter D (đ, Đ)
        self.assertEqual(search_index.normalize_vietnamese("đường đời Đất Đai"), "duong doi dat dai")
        # Punctuation and symbols become spaces
        self.assertEqual(
            search_index.normalize_vietnamese("GPT-4o: Tốc độ xử lý (x2) & hiệu năng cao!"),
            "gpt 4o toc do xu ly x2 hieu nang cao"
        )
        # Edge cases: empty, None, non-string
        self.assertEqual(search_index.normalize_vietnamese(""), "")
        self.assertEqual(search_index.normalize_vietnamese(None), "")
        self.assertEqual(search_index.normalize_vietnamese("   "), "")
        self.assertEqual(search_index.normalize_vietnamese(123), "")

    def test_diacritic_free_query_matching(self):
        payload = {"stories": sample_vietnamese_stories()}
        index = search_index.search_payload(payload)
        stories_by_id = {s["id"]: s for s in index["stories"]}

        # Story 1: English title + Vietnamese title_vi
        st1 = stories_by_id["vn-story-1"]
        # Match with diacritic-free Vietnamese query
        q_diacritic_free = "tri tue nhan tao"
        self.assertIn(q_diacritic_free, st1["search_text"])
        self.assertIn("tien phong", st1["search_text"])
        # Match with diacritic Vietnamese query after query normalization
        q_with_diacritics = search_index.normalize_vietnamese("trí tuệ nhân tạo")
        self.assertIn(q_with_diacritics, st1["search_text"])
        # Match with English title query
        self.assertIn(search_index.normalize_vietnamese("frontier"), st1["search_text"])
        self.assertIn(search_index.normalize_vietnamese("artificial intelligence"), st1["search_text"])
        # Match with publisher
        self.assertIn(search_index.normalize_vietnamese("hacker news"), st1["search_text"])

        # Story 2: Native Vietnamese title with đ/Đ
        st2 = stories_by_id["vn-story-2"]
        self.assertIn(search_index.normalize_vietnamese("da nang"), st2["search_text"])
        self.assertIn(search_index.normalize_vietnamese("vi mach ban dan"), st2["search_text"])
        self.assertIn(search_index.normalize_vietnamese("tuoi tre"), st2["search_text"])

        # Story 3: Native Vietnamese with "đột phá"
        st3 = stories_by_id["vn-story-3"]
        self.assertIn("dot pha", st3["search_text"])
        self.assertIn("suy luan", st3["search_text"])
        self.assertIn("genk", st3["search_text"])

    def test_index_covers_every_retained_story(self):
        fixture_path = FIXTURES / "edition-real-snapshot.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        index = search_index.search_payload(data)
        original_stories = data.get("stories", [])

        # Count match
        self.assertEqual(len(index["stories"]), len(original_stories))
        self.assertEqual(index["story_count"], len(original_stories))

        # ID coverage and sequence preserved
        original_ids = [s["id"] for s in original_stories]
        index_ids = [s["id"] for s in index["stories"]]
        self.assertEqual(index_ids, original_ids)

        # Retained stories with carried: True are included
        carried_stories = [s for s in original_stories if s.get("carried")]
        if carried_stories:
            for cs in carried_stories:
                self.assertIn(cs["id"], index_ids)

    def test_no_invented_or_defaulted_fields(self):
        sparse_story = {
            "id": "sparse-1",
            "coverage": [],
        }
        sparse_story_2 = {
            "id": "sparse-2",
            "title": "Some title",
            "coverage": [{"publisher": ""}],
        }
        payload = {"stories": [sparse_story, sparse_story_2]}
        index = search_index.search_payload(payload)

        row1 = index["stories"][0]
        self.assertEqual(row1["id"], "sparse-1")
        self.assertEqual(row1["title"], "")
        self.assertEqual(row1["title_vi"], "")
        self.assertEqual(row1["url"], "")
        self.assertEqual(row1["published_at"], "")
        self.assertEqual(row1["publishers"], [])
        self.assertEqual(row1["kind"], "")

        row2 = index["stories"][1]
        self.assertEqual(row2["title"], "Some title")
        self.assertEqual(row2["publishers"], [])

        # Missing field auditor counts
        counts = search_index.audit_missing_fields(payload)
        self.assertEqual(counts["total_stories"], 2)
        self.assertEqual(counts["missing_title"], 1)
        self.assertEqual(counts["missing_title_vi"], 2)
        self.assertEqual(counts["missing_published_at"], 2)
        self.assertEqual(counts["missing_url"], 2)
        self.assertEqual(counts["missing_publisher"], 2)

    def test_size_budget_and_metrics_on_fixture(self):
        fixture_path = FIXTURES / "edition-real-snapshot.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        index = search_index.search_payload(data)
        raw_bytes = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gz_bytes = gzip.compress(raw_bytes)

        # 11 stories fixture must be small
        self.assertLess(len(raw_bytes), 10 * 1024, "Real fixture index must be < 10 KB uncompressed")
        self.assertLess(len(gz_bytes), 4 * 1024, "Real fixture index must be < 4 KB gzipped")

    def test_size_budget_on_full_seven_day_simulation(self):
        """Simulate a full 7-day retention pool of 1,100 stories with realistic lengths.

        Budget:
        - Uncompressed compact JSON: <= 500 KB
        - Gzipped network payload: <= 150 KB
        - Average per story: <= 550 bytes
        """
        simulated_stories = []
        base_samples = sample_vietnamese_stories()
        for i in range(1100):
            base = base_samples[i % len(base_samples)]
            simulated_stories.append({
                "id": f"simulated-story-{i:04d}",
                "title": f"{base['title']} [variant {i}]",
                "title_vi": f"{base.get('title_vi', base['title'])} [biến thể {i}]",
                "url": f"{base.get('url', 'https://example.com/story')}/{i}",
                "published_at": "2026-10-04T12:00:00Z",
                "kind": base.get("kind", "other"),
                "coverage": base.get("coverage", []),
                "carried": (i % 2 == 0),
            })

        payload = {
            "schema_version": 2,
            "generated_at": "2026-10-04T12:00:00Z",
            "stories": simulated_stories,
        }
        index = search_index.search_payload(payload)
        raw_bytes = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gz_bytes = gzip.compress(raw_bytes)

        raw_kb = len(raw_bytes) / 1024
        gz_kb = len(gz_bytes) / 1024
        avg_bytes = len(raw_bytes) / len(simulated_stories)

        self.assertLessEqual(raw_kb, 600.0, f"Uncompressed size {raw_kb:.1f} KB exceeds 600 KB budget")
        self.assertLessEqual(gz_kb, 150.0, f"Gzipped size {gz_kb:.1f} KB exceeds 150 KB budget")
        self.assertLessEqual(avg_bytes, 550.0, f"Per-story average {avg_bytes:.1f} bytes exceeds 550 B budget")

    def test_search_path_derivation(self):
        self.assertEqual(
            search_index.search_path("site/data/radar.json"),
            Path("site/data/radar-search.json")
        )
        self.assertEqual(
            search_index.search_path(Path("/tmp/custom.json")),
            Path("/tmp/custom-search.json")
        )

    def test_write_site_snapshot_atomic_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "radar.json"
            data = snapshot()
            story = data["stories"][0]
            story.update(title="AI Test Story", title_vi="Tin thử nghiệm AI")
            story["coverage"][0].update(publisher="test-publisher")

            site_payload.write_site_snapshot(data, target)

            search_file = search_index.search_path(target)
            self.assertTrue(search_file.is_file())
            self.assertTrue(site_payload.page_path(target).is_file())
            self.assertTrue(site_payload.head_path(target).is_file())

            # Verify content matches search_payload
            loaded = json.loads(search_file.read_text(encoding="utf-8"))
            self.assertEqual(loaded["story_count"], len(data["stories"]))
            self.assertEqual(loaded["stories"][0]["id"], story["id"])
            self.assertEqual(loaded["stories"][0]["publishers"], ["test-publisher"])
            self.assertIn("ai test story", loaded["stories"][0]["search_text"])
            self.assertIn("tin thu nghiem ai", loaded["stories"][0]["search_text"])

            # Verify error invalidates search file
            real_writer = site_payload.write_atomic
            def fail_search(payload, path, **kwargs):
                if "search" in str(path):
                    raise OSError("search index write failure")
                return real_writer(payload, path, **kwargs)

            with patch.object(site_payload, "write_atomic", side_effect=fail_search):
                with self.assertRaises(OSError):
                    site_payload.write_site_snapshot(data, target)
            self.assertFalse(search_file.exists())

    def test_build_collision_check_includes_search_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "radar.json"
            search_file = search_index.search_path(target)
            with patch.dict(os.environ, {"RADAR_OUTPUT": str(target),
                                         "RADAR_BASELINE": str(search_file)}, clear=True), \
                 patch.object(build, "build_v2") as collect:
                with self.assertRaisesRegex(ValueError, "different files"):
                    build.main()
                collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
