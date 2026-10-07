"""Test that video story count and home page header count never diverge."""

import json
from pathlib import Path
import re
import subprocess
import unittest

from radar.items import instant
from radar.summary_pipeline import is_in_ranking_window

REPO_ROOT = Path(__file__).resolve().parent.parent


class FeedVideoCountSyncTestCase(unittest.TestCase):
    def setUp(self):
        self.divergence_fixture_path = REPO_ROOT / "tests" / "fixtures" / "feed-count-divergence-fixture.json"
        self.live_snapshot_path = REPO_ROOT / "site" / "data" / "radar-ui.json"
        self.pick_stories_js = REPO_ROOT / "video" / "src" / "pick-stories.js"
        self.render_js = REPO_ROOT / "video" / "render.js"

    def _compute_home_page_count(self, snapshot: dict) -> tuple[int, int]:
        """Replicate site/feed.js count logic in Python."""
        ranking = snapshot.get("ranking")
        win_h = ranking.get("window_hours") if isinstance(ranking, dict) else None
        try:
            window_hours = float(win_h) if win_h is not None and float(win_h) > 0 else 72.0
        except (ValueError, TypeError):
            window_hours = 72.0

        gen_dt = instant(snapshot.get("generated_at"))
        all_stories = [
            s for s in snapshot.get("stories") or []
            if isinstance(s, dict) and is_in_ranking_window(s, gen_dt, window_hours)
        ]
        return len(all_stories), int(window_hours)

    def _run_node_stats(self, fixture_path: Path) -> dict:
        cmd = ["node", str(self.pick_stories_js), str(fixture_path), "--stats"]
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(proc.stdout)

    def _run_node_dry_run(self, fixture_path: Path) -> str:
        cmd = ["node", str(self.render_js), "--dry-run", str(fixture_path)]
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return proc.stdout

    def test_divergence_fixture_proves_video_and_home_page_match(self):
        self.assertTrue(self.divergence_fixture_path.is_file(), f"Missing {self.divergence_fixture_path}")
        data = json.loads(self.divergence_fixture_path.read_text(encoding="utf-8"))

        raw_count = len(data.get("stories") or [])
        home_count, home_window = self._compute_home_page_count(data)

        # Confirm the fixture actually has out-of-window stories
        self.assertEqual(raw_count, 8, "Fixture must contain 8 total stories")
        self.assertEqual(home_count, 4, "Home page rule must count exactly 4 stories in window")
        self.assertEqual(home_window, 72)
        self.assertNotEqual(
            raw_count,
            home_count,
            "Fixture must demonstrate divergence between raw snapshot count and home page count"
        )

        # 1. Video pick-stories --stats output
        stats = self._run_node_stats(self.divergence_fixture_path)
        video_count = stats.get("storyCount")
        video_window = stats.get("windowHours")

        self.assertEqual(
            video_count,
            home_count,
            f"Video count ({video_count}) diverged from home page count ({home_count})"
        )
        self.assertEqual(video_window, home_window)

        # 2. Video render --dry-run narration check
        dry_run_output = self._run_node_dry_run(self.divergence_fixture_path)
        match = re.search(r"Trong (\d+) giờ qua, ai-radar theo dõi (\d+) tin AI", dry_run_output)
        self.assertIsNotNone(match, f"Narration missing honest window count: {dry_run_output}")

        spoken_window = int(match.group(1))
        spoken_count = int(match.group(2))
        self.assertEqual(spoken_count, home_count, f"Spoken count ({spoken_count}) diverged from home count ({home_count})")
        self.assertEqual(spoken_window, home_window)
        self.assertNotIn("Hôm nay ai-radar theo dõi", dry_run_output, "Narration must not claim Hôm nay when window is 72h")

    def test_live_snapshot_video_count_matches_home_page_count(self):
        if not self.live_snapshot_path.is_file():
            self.skipTest(f"Live snapshot not found at {self.live_snapshot_path}")

        data = json.loads(self.live_snapshot_path.read_text(encoding="utf-8"))
        raw_count = len(data.get("stories") or [])
        home_count, home_window = self._compute_home_page_count(data)

        # Live snapshot has ~1500 total stories, but active window has ~323-325
        self.assertNotEqual(
            raw_count,
            home_count,
            "Live snapshot must have historical stories outside 72h window"
        )

        stats = self._run_node_stats(self.live_snapshot_path)
        self.assertEqual(
            stats.get("storyCount"),
            home_count,
            f"Video count ({stats.get('storyCount')}) must match home page count ({home_count})"
        )
        self.assertEqual(stats.get("windowHours"), home_window)

        dry_run_output = self._run_node_dry_run(self.live_snapshot_path)
        self.assertIn(f"Trong {home_window} giờ qua, ai-radar theo dõi {home_count} tin AI", dry_run_output)


if __name__ == "__main__":
    unittest.main()
