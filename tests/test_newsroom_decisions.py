"""Reader publication decisions and exact silent-newsroom fallback."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar.newsroom_decisions import apply_decisions, load_decisions
from radar import site_payload
from tests.test_publication import snapshot


def reader_fixture():
    data = snapshot()
    data["stories"][0].update(summary="Old summary", summary_vi="Bản tóm tắt cũ",
                              importance_tier="top", importance_weight=3,
                              published_at=data["generated_at"])
    return data


class DecisionProjectionTests(unittest.TestCase):
    def test_fresh_decisions_hide_holds_but_preserve_tiers_unless_capping_is_enabled(self):
        payload = reader_fixture()
        story = payload["stories"][0]
        story.update(importance_tier="top", importance_weight=90, importance_reason="top story")
        held = deepcopy(story)
        held["id"] = "held"
        payload["stories"] = [story, held]
        decisions = {"decisions": [
            {"id": story["id"], "decision": "publish", "content_kind": "analysis",
             "importance_tier": "standard"},
            {"id": "held", "decision": "hold"},
        ]}

        with patch.dict("os.environ", {"RADAR_NEWSROOM_CAP_TIERS": ""}):
            default_result = apply_decisions(payload, decisions)
        self.assertEqual([row["id"] for row in default_result["stories"]], [story["id"]])
        self.assertEqual(default_result["stories"][0], story)

        with patch.dict("os.environ", {"RADAR_NEWSROOM_CAP_TIERS": "true"}):
            capped = apply_decisions(payload, decisions)
        self.assertEqual(capped["stories"][0]["importance_tier"], "standard")
        self.assertEqual(capped["stories"][0]["importance_weight"], 29.99)

    def test_fresh_file_filters_every_reader_projection_and_keeps_vietnamese(self):
        payload = reader_fixture()
        original = deepcopy(payload["stories"][0])
        approved = deepcopy(original)
        approved["id"] = "approved"
        approved.update(key_points=["Điểm đã dịch"], key_points_machine=True,
                        key_points_source="machine", editorial_headline_vi="Tiêu đề biên tập")
        held = deepcopy(original)
        held["id"] = "held"
        unknown = deepcopy(original)
        unknown["id"] = "unknown"
        payload["stories"] = [approved, held, unknown]
        payload["sections"] = {"today": ["approved", "held", "unknown"]}
        decisions = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                     "decisions": [
                         {"id": "approved", "decision": "publish", "content_kind": "analysis",
                          "importance_tier": "standard", "summary": "claims",
                          "key_points": ["First checked fact.", "Second checked fact."]},
                         {"id": "held", "decision": "hold"}]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            choice = base / "decisions.json"
            choice.write_bytes(json.dumps(decisions).encode())
            target = base / "radar.json"
            with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice),
                                            "RADAR_NEWSROOM_CAP_TIERS": "true"}):
                site_payload.write_site_snapshot(payload, target)
            full = json.loads(target.read_bytes())
            self.assertEqual([story["id"] for story in full["stories"]], ["approved", "unknown"])
            story = full["stories"][0]
            self.assertEqual(story["importance_tier"], "standard")
            for key in ("summary", "summary_vi", "key_points", "key_points_machine",
                        "key_points_source", "editorial_headline_vi"):
                self.assertEqual(story[key], approved[key])
            self.assertEqual(full["stories"][1], unknown)
            self.assertEqual(full["sections"]["today"], ["approved", "unknown"])
            self.assertEqual(len(json.loads(site_payload.intake_path(target).read_bytes())["stories"]), 3)
            with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice),
                                            "RADAR_NEWSROOM_CAP_TIERS": "true"}):
                site_payload.write_site_snapshot(full, target)
            self.assertEqual(len(json.loads(site_payload.intake_path(target).read_bytes())["stories"]), 3)
            for path in (site_payload.page_path(target), site_payload.window_path(target),
                         site_payload.head_path(target), site_payload.search_path(target)):
                reader = json.loads(path.read_bytes())
                self.assertEqual([row["id"] for row in reader["stories"]], ["approved", "unknown"])

    def test_missing_and_stale_decisions_write_identical_payload(self):
        payload = reader_fixture()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            choice = base / "decisions.json"
            fresh = {"schema_version": 1, "generated_at":
                     (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat(),
                     "decisions": [{"id": payload["stories"][0]["id"], "decision": "hold"}]}
            choice.write_bytes(json.dumps(fresh).encode())
            with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(base / "missing.json")}):
                site_payload.write_site_snapshot(payload, base / "without" / "radar.json")
            with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice)}):
                site_payload.write_site_snapshot(payload, base / "stale" / "radar.json")
            for filename in ("radar.json", "radar-ui.json", "radar-window.json", "radar-head.json", "radar-search.json"):
                self.assertEqual((base / "without" / filename).read_bytes(), (base / "stale" / filename).read_bytes())
            self.assertIsNone(load_decisions(choice))
            self.assertEqual(load_decisions(choice, max_age_hours=24), fresh)
            self.assertEqual(apply_decisions(payload, None), payload)
            choice.write_bytes(b'{"schema_version":1,"generated_at":null,"decisions":[]}')
            self.assertIsNone(load_decisions(choice))


if __name__ == "__main__":
    unittest.main()
