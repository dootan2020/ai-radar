import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class VideoScriptContractTestCase(unittest.TestCase):
    def setUp(self):
        self.fixture_path = REPO_ROOT / "video" / "fixtures" / "video-script.json"
        self.sample_0610_path = REPO_ROOT / "video" / "fixtures" / "video-script-0610.json"

    def test_fixture_exists_and_conforms_to_contract(self):
        self.assertTrue(self.fixture_path.is_file(), f"Missing fixture: {self.fixture_path}")
        self.assertTrue(self.sample_0610_path.is_file(), f"Missing 0610 fixture: {self.sample_0610_path}")

        data = json.loads(self.fixture_path.read_text(encoding="utf-8"))

        required_keys = {"date", "generated_at", "prompt_version", "hook", "hint", "stories", "cta"}
        self.assertTrue(required_keys.issubset(data.keys()), f"Missing keys: {required_keys - set(data.keys())}")

        self.assertEqual(data["date"], "2026-10-06")
        self.assertTrue(len(data["hook"]) > 10, "Hook should be non-empty")
        self.assertTrue(len(data["hint"]) > 5, "Hint should be non-empty")
        self.assertTrue(len(data["cta"]) > 10, "CTA should be non-empty")

        stories = data["stories"]
        self.assertEqual(len(stories), 3, "Script must specify exactly 3 stories")

        expected_ids = [
            "a08a24d3f61d4df508c8",  # Nvidia Shield TV (most surprising first)
            "5432f5b94c34f514ec03",  # Apple macOS Full Disk Access
            "90c6c9903271281ae042",  # Amazon $1B data center backlash
        ]

        for idx, item in enumerate(stories):
            self.assertIn("id", item, f"Story {idx} missing id")
            self.assertIn("line", item, f"Story {idx} missing line")
            self.assertTrue(len(item["line"]) > 10, f"Story {idx} line too short")
            self.assertEqual(item["id"], expected_ids[idx], f"Story {idx} order mismatch")

    def test_approved_sample_matches_0610_report(self):
        data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        # Verify content lines match approved sample
        self.assertIn("TV box 7 năm tuổi", data["hook"])
        self.assertIn("45 giây", data["hint"])
        self.assertIn("Nvidia Shield TV Pro", data["stories"][0]["line"])
        self.assertIn("Apple siết quyền truy cập", data["stories"][1]["line"])
        self.assertIn("Amazon chi 1 tỷ đô la", data["stories"][2]["line"])
        self.assertIn("Theo dõi để không bỏ lỡ", data["cta"])

    def test_round5_muted_viewer_script_deliverables(self):
        data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        # 1. Hook stops scroll with specific provocative claim
        self.assertTrue(any(word in data["hook"] for word in ["TV box", "đắt thêm 100 đô la"]))
        # 2. Hint promises time budget
        self.assertIn("45 giây", data["hint"])
        # 3. All 3 stories have distinct non-empty narrative lines for visual presentation
        self.assertEqual(len(data["stories"]), 3)
        for st in data["stories"]:
            self.assertTrue(len(st["line"]) > 20)
        # 4. CTA asks for both following and commenting
        self.assertIn("Theo dõi để không bỏ lỡ", data["cta"])
        self.assertTrue("Bình luận" in data["cta"] or "quan tâm" in data["cta"])

    def test_round6_pacing_and_pause_contract(self):
        render_js = (REPO_ROOT / "video" / "render.js").read_text(encoding="utf-8")
        daily_audio_js = (REPO_ROOT / "video" / "src" / "daily-audio.js").read_text(encoding="utf-8")

        # Verify separatorMs is adjusted for ~1s inter-section pacing
        self.assertIn("separatorMs = 800", daily_audio_js)

        # Verify render.js uses tightened pauseMs (620ms to achieve ~1s measured pause)
        self.assertIn("'620'", render_js)
        self.assertIn("OMNIVOICE_PAUSE_MS", render_js)


if __name__ == "__main__":
    unittest.main()
