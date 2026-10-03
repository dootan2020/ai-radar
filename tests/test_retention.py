"""Tests for 7-day story retention across build snapshots and offline demonstration."""

import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest

from radar import assembly
from radar.items import instant
from radar.retention import retain_stories, RETENTION_SECONDS
from radar.site_payload import page_payload, head_payload


AUDIT_DIR = Path(__file__).resolve().parent.parent / "plans/nhap/audit"
SNAP1_PATH = AUDIT_DIR / "art-11220425807/radar.json"
SNAP2_PATH = AUDIT_DIR / "art-11261861541/radar.json"


def _make_story(story_id, title, url, published_at, coverage_urls=None, **extra):
    cov = []
    for i, c_url in enumerate(coverage_urls or [url]):
        cov.append({
            "id": f"cov-{story_id}-{i}",
            "source": f"source-{i}",
            "publisher": f"publisher-{i}",
            "group": "press",
            "kind": extra.get("kind", "other"),
            "title": title,
            "url": c_url,
            "canonical_url": c_url,
            "published_at": published_at,
            "summary": "summary",
            "observed_at": published_at,
            "metrics": {},
            "media": [],
            "discussion_url": None,
            "time_basis": "published",
        })
    story = {
        "id": story_id,
        "title": title,
        "url": url,
        "summary": "summary",
        "published_at": published_at,
        "kind": extra.get("kind", "other"),
        "time_basis": "published",
        "primary_section": "today",
        "groups": ["press"],
        "coverage": cov,
        "source_count": len(cov),
        "hot_score": None,
        "hot_reason": None,
        "hot_signals": {},
    }
    story.update(extra)
    return story


class RetentionUnitTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
        self.now_str = "2026-10-04T12:00:00Z"

    def test_story_carried_from_previous_past_its_feed(self):
        # Feed has rolled past old_story; fresh stories only contain new_story
        old_pub = "2026-10-02T10:00:00Z"  # ~2 days ago, well within 7 days
        old_story = _make_story("old-1", "OpenAI major announcement", "https://news.example/old", old_pub)
        previous = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": [old_story],
        }

        fresh_story = _make_story("fresh-1", "Fresh breaking news", "https://news.example/fresh", "2026-10-04T10:00:00Z")
        fresh_stories = [fresh_story]

        combined = retain_stories(fresh_stories, previous, self.now)
        combined_ids = [s["id"] for s in combined]

        self.assertIn("fresh-1", combined_ids)
        self.assertIn("old-1", combined_ids)
        carried_story = next(s for s in combined if s["id"] == "old-1")
        self.assertTrue(carried_story.get("carried"))
        # Kept coverage rows and published_at
        self.assertEqual(carried_story["published_at"], old_pub)
        self.assertEqual(len(carried_story["coverage"]), 1)
        self.assertEqual(carried_story["coverage"][0]["id"], "cov-old-1-0")

    def test_story_present_in_published_is_carried_while_baseline_is_not(self):
        old_story = _make_story("pub-only", "Published article", "https://news.example/pub", "2026-10-02T10:00:00Z")
        published = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": [old_story],
        }
        baseline = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": [_make_story("base-only", "Baseline article", "https://news.example/base", "2026-10-02T10:00:00Z")],
        }
        # In retain_stories directly:
        res_pub = retain_stories([], published, self.now)
        self.assertEqual([s["id"] for s in res_pub], ["pub-only"])

        # Through assembly.finish:
        payload = {"generated_at": self.now_str, "sources": [], "updates": [], "hf_releases": [], "live": [], "trending": {"github": [], "huggingface": []}}
        # 1. Baseline only: no stories carried
        res_baseline = assembly.finish(deepcopy(payload), [], [], self.now, previous=baseline, published=None)
        self.assertEqual(res_baseline["stories"], [])

        # 2. Published provided: pub-only carried, base-only NOT carried
        res_both = assembly.finish(deepcopy(payload), [], [], self.now, previous=baseline, published=published)
        self.assertEqual([s["id"] for s in res_both["stories"]], ["pub-only"])
        self.assertTrue(res_both["stories"][0].get("carried"))

    def test_seven_day_cutoff(self):
        # 6 days ago (kept)
        story_6d = _make_story("story-6d", "6 days old", "https://news.example/6d", "2026-09-28T12:00:00Z")
        # Exactly 7 days ago (kept)
        story_7d = _make_story("story-7d", "7 days old", "https://news.example/7d", "2026-09-27T12:00:00Z")
        # 7 days and 1 hour ago (expired, pruned)
        story_7d1h = _make_story("story-7d1h", "7 days 1h old", "https://news.example/7d1h", "2026-09-27T11:00:00Z")
        # 14 days ago (expired, pruned)
        story_14d = _make_story("story-14d", "14 days old", "https://news.example/14d", "2026-09-20T12:00:00Z")

        previous = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": [story_6d, story_7d, story_7d1h, story_14d],
        }

        fresh_stories = []
        combined = retain_stories(fresh_stories, previous, self.now)
        combined_ids = [s["id"] for s in combined]

        self.assertIn("story-6d", combined_ids)
        self.assertIn("story-7d", combined_ids)
        self.assertNotIn("story-7d1h", combined_ids)
        self.assertNotIn("story-14d", combined_ids)

    def test_missing_or_malformed_previous(self):
        fresh = [_make_story("f1", "Fresh", "https://news.example/f", self.now_str)]

        # None (cache miss)
        res_none = retain_stories(fresh, None, self.now)
        self.assertEqual([s["id"] for s in res_none], ["f1"])

        # Empty dict
        res_empty = retain_stories(fresh, {}, self.now)
        self.assertEqual([s["id"] for s in res_empty], ["f1"])

        # Non-dict types
        self.assertEqual([s["id"] for s in retain_stories(fresh, "corrupted string", self.now)], ["f1"])
        self.assertEqual([s["id"] for s in retain_stories(fresh, [1, 2, 3], self.now)], ["f1"])
        self.assertEqual([s["id"] for s in retain_stories(fresh, 42, self.now)], ["f1"])

        # Wrong schema version
        bad_schema = {"schema_version": 1, "stories": [_make_story("old", "Old", "https://old", self.now_str)]}
        self.assertEqual([s["id"] for s in retain_stories(fresh, bad_schema, self.now)], ["f1"])

        # Stories not a list or missing
        self.assertEqual([s["id"] for s in retain_stories(fresh, {"schema_version": 2}, self.now)], ["f1"])
        self.assertEqual([s["id"] for s in retain_stories(fresh, {"schema_version": 2, "stories": "not-list"}, self.now)], ["f1"])

        # Stories containing invalid elements
        mixed_stories = {
            "schema_version": 2,
            "generated_at": self.now_str,
            "stories": [
                None,
                "invalid",
                {},
                {"id": ""},
                {"no_id": True},
                _make_story("valid-old", "Valid Old", "https://old.valid", "2026-10-03T12:00:00Z"),
            ],
        }
        res_mixed = retain_stories(fresh, mixed_stories, self.now)
        self.assertEqual(sorted([s["id"] for s in res_mixed]), ["f1", "valid-old"])

    def test_duplicate_between_feed_and_carried_stories(self):
        # 1. Matching by ID
        fresh_story = _make_story("dup-1", "Fresh headline", "https://news.example/same-url", "2026-10-04T10:00:00Z")
        old_story_same_id = _make_story("dup-1", "Old headline", "https://news.example/same-url", "2026-10-02T10:00:00Z",
                                        title_vi="Bản dịch cũ", summary_vi="Tóm tắt cũ")

        previous = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": [old_story_same_id],
        }

        combined = retain_stories([fresh_story], previous, self.now)
        self.assertEqual(len(combined), 1)
        # Fresh story takes precedence
        self.assertEqual(combined[0]["id"], "dup-1")
        self.assertEqual(combined[0]["title"], "Fresh headline")
        self.assertFalse(combined[0].get("carried", False))
        # Preserved Vietnamese translations from old story
        self.assertEqual(combined[0].get("title_vi"), "Bản dịch cũ")
        self.assertEqual(combined[0].get("summary_vi"), "Tóm tắt cũ")

        # 2. Matching by Story URL
        fresh_by_url = _make_story("fresh-url-id", "Fresh title", "https://news.example/shared-article", "2026-10-04T10:00:00Z")
        old_by_url = _make_story("old-url-id", "Old title", "https://news.example/shared-article?utm_source=rss", "2026-10-02T10:00:00Z")
        previous_by_url = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": [old_by_url],
        }
        combined_url = retain_stories([fresh_by_url], previous_by_url, self.now)
        self.assertEqual(len(combined_url), 1)
        self.assertEqual(combined_url[0]["id"], "fresh-url-id")

        # 3. Matching by Coverage URL
        fresh_cov = _make_story("fresh-cov-id", "Fresh coverage cluster", "https://news.example/story-fresh", "2026-10-04T10:00:00Z",
                                coverage_urls=["https://source.example/original-report", "https://source.example/fresh-take"])
        old_cov = _make_story("old-cov-id", "Old coverage cluster", "https://news.example/story-old", "2026-10-02T10:00:00Z",
                              coverage_urls=["https://source.example/original-report"])
        previous_cov = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": [old_cov],
        }
        combined_cov = retain_stories([fresh_cov], previous_cov, self.now)
        self.assertEqual(len(combined_cov), 1)
        self.assertEqual(combined_cov[0]["id"], "fresh-cov-id")

    def test_pool_cap_enforcement(self):
        fresh = [_make_story(f"fresh-{i}", f"Fresh {i}", f"https://fresh/{i}", "2026-10-04T10:00:00Z") for i in range(5)]
        old_stories = [
            _make_story(f"old-multi-{i}", f"Old Multi {i}", f"https://old/m{i}", "2026-10-02T10:00:00Z",
                        coverage_urls=[f"https://old/m{i}/1", f"https://old/m{i}/2"], source_count=2)
            for i in range(5)
        ] + [
            _make_story(f"old-single-{i}", f"Old Single {i}", f"https://old/s{i}", "2026-10-01T10:00:00Z",
                        source_count=1)
            for i in range(10)
        ]
        previous = {
            "schema_version": 2,
            "generated_at": "2026-10-03T12:00:00Z",
            "stories": old_stories,
        }

        # Cap pool at 10 total stories: 5 fresh + top 5 carried
        combined = retain_stories(fresh, previous, self.now, max_stories=10)
        self.assertEqual(len(combined), 10)
        # All fresh stories kept
        for i in range(5):
            self.assertIn(f"fresh-{i}", [s["id"] for s in combined])
        # Multi-source carried stories prioritized over older single-source stories
        multi_ids = {f"old-multi-{i}" for i in range(5)}
        retained_carried = {s["id"] for s in combined if s.get("carried")}
        self.assertEqual(retained_carried, multi_ids)


class RetentionDemonstrationTests(unittest.TestCase):
    @unittest.skipUnless(SNAP1_PATH.is_file() and SNAP2_PATH.is_file(),
                         "Audit demonstration snapshots absent (plans/ is gitignored)")
    def test_offline_demonstration_on_real_audit_snapshots(self):
        """Demonstrate retention using art-11220425807 (snap1) as previous for art-11261861541 (snap2)."""
        with open(SNAP1_PATH, "r", encoding="utf-8") as f:
            snap1 = json.load(f)
        with open(SNAP2_PATH, "r", encoding="utf-8") as f:
            snap2 = json.load(f)

        target_id = "515a9625011c78e10959"

        # Baseline check on raw data
        self.assertIn(target_id, [s["id"] for s in snap1["stories"]])
        self.assertNotIn(target_id, [s["id"] for s in snap2["stories"]])

        # Simulate assembly of snap2 items with snap1 as previous
        now = instant(snap2["generated_at"])
        items = [c for s in snap2["stories"] for c in s.get("coverage", [])]
        events = snap2.get("events", [])
        payload = {k: snap2[k] for k in ("generated_at", "sources", "updates", "hf_releases", "live", "trending")}

        # 1. Build WITHOUT published snapshot (cache miss / published=None)
        build_miss = assembly.finish(deepcopy(payload), deepcopy(items), deepcopy(events), now, previous=None, published=None)
        count_miss = len(build_miss["stories"])
        self.assertNotIn(target_id, [s["id"] for s in build_miss["stories"]])

        # 2. Build WITH snap1 as measurement baseline ONLY (previous=snap1, published=None):
        # Confirms baseline is measurement only and never republished as content
        build_baseline_only = assembly.finish(deepcopy(payload), deepcopy(items), deepcopy(events), now, previous=snap1, published=None)
        self.assertNotIn(target_id, [s["id"] for s in build_baseline_only["stories"]])

        # 3. Build WITH snap1 as published snapshot (published=snap1)
        build_retained = assembly.finish(deepcopy(payload), deepcopy(items), deepcopy(events), now, previous=None, published=snap1)
        count_retained = len(build_retained["stories"])

        # Target story is carried forward!
        self.assertIn(target_id, [s["id"] for s in build_retained["stories"]])
        carried_target = next(s for s in build_retained["stories"] if s["id"] == target_id)
        self.assertTrue(carried_target.get("carried"))
        self.assertEqual(carried_target["published_at"], "2026-09-28T16:43:18Z")
        self.assertEqual(len(carried_target["coverage"]), 1)

        # Measure projection sizes
        raw_miss_bytes = len(json.dumps(build_miss, ensure_ascii=False, indent=2).encode("utf-8"))
        raw_retained_bytes = len(json.dumps(build_retained, ensure_ascii=False, indent=2).encode("utf-8"))

        ui_miss = page_payload(build_miss)
        ui_retained = page_payload(build_retained)
        ui_miss_bytes = len(json.dumps(ui_miss, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        ui_retained_bytes = len(json.dumps(ui_retained, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

        head_miss = head_payload(build_miss)
        head_retained = head_payload(build_retained)
        head_miss_bytes = len(json.dumps(head_miss, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        head_retained_bytes = len(json.dumps(head_retained, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

        print("\n=== OFFLINE DEMONSTRATION METRICS ===")
        print(f"Target story: {target_id} ('{carried_target['title'][:50]}...')")
        print(f"Stories count: before={count_miss} -> after={count_retained} (+{count_retained - count_miss} carried)")
        print(f"radar.json (full indented): {raw_miss_bytes:,} bytes -> {raw_retained_bytes:,} bytes (+{raw_retained_bytes - raw_miss_bytes:,} B, +{(raw_retained_bytes - raw_miss_bytes)/raw_miss_bytes*100:.1f}%)")
        print(f"radar-ui.json (compact): {ui_miss_bytes:,} bytes -> {ui_retained_bytes:,} bytes (+{ui_retained_bytes - ui_miss_bytes:,} B, +{(ui_retained_bytes - ui_miss_bytes)/ui_miss_bytes*100:.1f}%)")
        print(f"radar-head.json (compact): {head_miss_bytes:,} bytes -> {head_retained_bytes:,} bytes (+{head_retained_bytes - head_miss_bytes:,} B, +{(head_retained_bytes - head_miss_bytes)/head_miss_bytes*100:.1f}%)")
        print(f"First-screen board stories count: before={len(head_miss['stories'])} -> after={len(head_retained['stories'])}")


if __name__ == "__main__":
    unittest.main()
