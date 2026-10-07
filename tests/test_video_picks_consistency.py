"""Cross-language consistency tests for video story selection.

Verifies that Python (radar/video_script.py) and Node.js (video/src/pick-stories.js)
select identical top stories in identical order under the home page rule:
1. Strict Vietnamese title requirement (title_vi non-empty string).
2. Minimum 2 independent news sources.
3. Photo lead prioritization where available.
4. Same-event deduplication (Jaccard similarity threshold).
5. Clean exit without stack traces when fewer than 3 stories qualify.
"""

import json
from pathlib import Path
import subprocess
import sys
import unittest

from radar import video_script

REPO_ROOT = Path(__file__).resolve().parent.parent


class VideoPicksConsistencyTestCase(unittest.TestCase):
    def setUp(self):
        self.fixture_path = REPO_ROOT / "tests" / "fixtures" / "picks-translated-test.json"
        self.insufficient_path = REPO_ROOT / "tests" / "fixtures" / "picks-translated-insufficient.json"
        self.live_snapshot_path = REPO_ROOT / "site" / "data" / "radar-ui.json"
        self.pick_stories_js = REPO_ROOT / "video" / "src" / "pick-stories.js"

    def _run_node_pick_stories(self, fixture_path: Path) -> list[str]:
        cmd = ["node", str(self.pick_stories_js), str(fixture_path), "--json"]
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(proc.stdout)

    def test_picks_consistency_on_translated_fixture(self):
        self.assertTrue(self.fixture_path.is_file(), f"Missing fixture: {self.fixture_path}")

        # 1. Run Python selection
        data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        stories = data.get("stories") or []
        sources = {s["id"]: s for s in data.get("sources") or []}
        py_picks = video_script.choose_picks(stories, sources_map=sources)
        py_ids = [s["id"] for s in py_picks]

        # 2. Run Node.js selection
        js_ids = self._run_node_pick_stories(self.fixture_path)

        # 3. Assertions
        # Untranslated top story (worth 99.0) must NOT be chosen by either side
        self.assertNotIn("story-top-untranslated", py_ids)
        self.assertNotIn("story-top-untranslated", js_ids)

        # Single source story (worth 95.0) must NOT be chosen by either side
        self.assertNotIn("story-single-source", py_ids)
        self.assertNotIn("story-single-source", js_ids)

        # Duplicate event must NOT be chosen by either side
        self.assertNotIn("story-pick-2-dup", py_ids)
        self.assertNotIn("story-pick-2-dup", js_ids)

        # Expected 3 stories in exact order
        expected = ["story-pick-1", "story-pick-2", "story-pick-3"]
        self.assertEqual(py_ids, expected)
        self.assertEqual(js_ids, expected)

        # Python and Node.js selections must be completely identical
        self.assertEqual(py_ids, js_ids)

    def test_picks_consistency_when_insufficient_stories(self):
        self.assertTrue(self.insufficient_path.is_file(), f"Missing fixture: {self.insufficient_path}")

        # 1. Run Python selection
        data = json.loads(self.insufficient_path.read_text(encoding="utf-8"))
        stories = data.get("stories") or []
        sources = {s["id"]: s for s in data.get("sources") or []}
        py_picks = video_script.choose_picks(stories, sources_map=sources)
        py_ids = [s["id"] for s in py_picks]

        # 2. Run Node.js selection
        js_ids = self._run_node_pick_stories(self.insufficient_path)

        # Both must return exactly 2 qualifying stories and exclude the untranslated top story
        self.assertNotIn("story-top-untranslated", py_ids)
        self.assertNotIn("story-top-untranslated", js_ids)

        self.assertEqual(len(py_ids), 2)
        self.assertEqual(len(js_ids), 2)
        self.assertEqual(py_ids, js_ids)

    def test_picks_consistency_on_live_snapshot_if_present(self):
        if not self.live_snapshot_path.is_file():
            self.skipTest(f"Live snapshot not found at {self.live_snapshot_path}")

        data = json.loads(self.live_snapshot_path.read_text(encoding="utf-8"))
        stories = data.get("stories") or []
        sources = {s["id"]: s for s in data.get("sources") or []}

        py_picks = video_script.choose_picks(stories, sources_map=sources)
        py_ids = [s["id"] for s in py_picks]

        js_ids = self._run_node_pick_stories(self.live_snapshot_path)

        # Both sides must pick identical stories in identical order
        self.assertEqual(py_ids, js_ids)
        self.assertEqual(len(py_ids), 3)

        # Ensure untranslated Mistral 4 story is discarded by both
        self.assertNotIn("6f131bbed5e7925d040e", py_ids)
        self.assertNotIn("6f131bbed5e7925d040e", js_ids)

        # Ensure all picked stories have a non-empty Vietnamese title
        stories_map = {s["id"]: s for s in stories}
        for st_id in py_ids:
            st = stories_map[st_id]
            self.assertTrue(bool(st.get("title_vi") and str(st.get("title_vi")).strip()))

    def test_render_exits_cleanly_without_stack_trace_on_insufficient_stories(self):
        render_js = REPO_ROOT / "video" / "render.js"
        cmd = ["node", str(render_js), str(self.insufficient_path)]
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        # Must exit 0 cleanly without throwing unhandled exceptions
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("FATAL", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("Error:", proc.stderr)
        self.assertTrue(
            "Fewer than 3 translated stories qualify" in proc.stdout
            or "Fewer than 3 translated stories qualify" in proc.stderr
        )


if __name__ == "__main__":
    unittest.main()
