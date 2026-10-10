"""Reader-facing priority order for bounded language spending."""
import unittest
from radar.reader_priority import ordered_stories


class ReaderPriorityTests(unittest.TestCase):
    def test_editor_hot_featured_then_archive_with_expired_pins_ignored(self):
        def story(sid, worth, date="2026-10-10T00:00:00Z"):
            return {"id": sid, "title": sid, "worth_score": worth, "published_at": date, "hot_score": 30 if sid == "hot" else 0}
        payload = {"generated_at": "2026-10-10T01:00:00Z",
                   "stories": [story("archive", 100, "2026-10-01T00:00:00Z"),
                               story("featured", 90), story("hot", 30), story("pinned", 10)],
                   "sections": {"hot": ["hot"]}}
        ordered, active = ordered_stories(payload, [{"id": "archive"}, {"id": "pinned"},
                                                    {"id": "featured", "until": "2026-10-09T00:00:00Z"}])
        self.assertEqual([s["id"] for s in ordered], ["pinned", "hot", "featured", "archive"])
        self.assertEqual(len(active), 3)

    def test_only_five_hot_leaders_jump_ahead_of_other_worth_ranked_stories(self):
        stories = [{"id": str(i), "title": str(i), "hot_score": i, "worth_score": 20 - i,
                    "published_at": "2026-10-10T00:00:00Z"} for i in range(1, 8)]
        ordered, _ = ordered_stories({"stories": stories, "generated_at": "2026-10-10T01:00:00Z",
                                      "sections": {"hot": [s["id"] for s in stories]}}, [])
        self.assertEqual([s["id"] for s in ordered], ["7", "6", "5", "4", "3", "1", "2"])

    def test_a_measured_but_ordinary_story_does_not_jump_ahead_as_hot(self):
        stories = [{"id": "ordinary", "title": "ordinary", "hot_score": 50, "worth_score": 1,
                    "published_at": "2026-10-10T00:00:00Z"},
                   {"id": "worthy", "title": "worthy", "hot_score": 0, "worth_score": 9,
                    "published_at": "2026-10-10T00:00:00Z"}]
        payload = {"stories": stories, "generated_at": "2026-10-10T01:00:00Z", "sections": {"hot": []}}
        ordered, _ = ordered_stories(payload, [])
        self.assertEqual([s["id"] for s in ordered], ["worthy", "ordinary"])
        # Without sections, the story's own signals decide, the same test sections.hot uses.
        stories[0]["hot_signals"] = {"source_count": 1, "engagement_percentile": 0.9, "measurement": {"value": 5}}
        ordered, _ = ordered_stories({"stories": stories, "generated_at": "2026-10-10T01:00:00Z"}, [])
        self.assertEqual([s["id"] for s in ordered], ["ordinary", "worthy"])

    def test_promoted_story_without_vietnamese_title_is_still_first_for_spending(self):
        import json
        from pathlib import Path
        payload = json.loads((Path(__file__).parent / "fixtures" / "picks-translated-test.json").read_text(encoding="utf-8"))
        for story in payload["stories"]:
            story.pop("title_vi", None)
            for coverage in story.get("coverage", []):
                coverage.pop("title_vi", None)
        ordered, _ = ordered_stories(payload, [])
        self.assertEqual([s["id"] for s in ordered[:3]],
                         ["story-top-untranslated", "story-pick-1", "story-pick-2"])
        # The higher-worth single-source rumor does not displace a promoted pick.
        self.assertNotIn("story-single-source", [s["id"] for s in ordered[:3]])
