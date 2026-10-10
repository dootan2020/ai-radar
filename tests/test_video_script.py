"""Offline unit and integration tests for video script generation pipeline.

Covers:
- Replicating choosePicks selection (>= 2 news sources, photo lead, same-event dedup, worth sorting)
- Mechanical fact verification:
  - Rejection of ungrounded / invented numbers in story lines
  - Rejection of ungrounded / invented entities in story lines
  - Rejection of ungrounded facts in Hook
  - Line word count limit (<= 25 words)
  - Full acceptance of the approved sample script from 06/10
- Pipeline orchestration:
  - Idempotency (already generated today -> 0 requests, 0 tokens)
  - Time window check (before 05:00 VN time -> skipped)
  - Budget / ledger ceiling exhaustion -> skipped
  - Rejected script -> output file is NOT written
  - Valid script -> atomic write to output path
  - CLI execution and GITHUB_OUTPUT verification
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import summary_budget
from radar import summary_gemini as gemini
from radar import summary_pipeline
from radar import video_script


def make_sample_stories():
    """Create authentic 3-story test dataset matching the 06/10 approved script."""
    st1 = {
        "id": "story-shield",
        "title": "The 7-year-old Nvidia Shield TV is now $100 more expensive due to AI",
        "title_vi": "Nvidia Shield TV 7 năm tuổi bây giờ là 100 đô la đắt hơn do AI",
        "summary": "Nvidia Shield TV Pro, first launched in 2019, now sells for $299.99, up $100 due to demand for AI media processing.",
        "summary_vi": "Nvidia Shield TV Pro, ra mắt lần đầu năm 2019, giờ bán 299,99 đô la, đắt hơn 100 đô la vì AI.",
        "key_points": [
            "Nvidia Shield TV Pro ra mắt từ năm 2019 hiện có giá 299,99 đô la.",
            "Giá thiết bị tăng thêm 100 đô la do nhu cầu tính năng AI."
        ],
        "published_at": "2026-10-06T10:00:00Z",
        "source_count": 2,
        "worth_score": 45.0,
        "image": {"src": "https://example.com/shield.jpg", "kind": "photo"},
        "coverage": [
            {"source": "ars-technica", "publisher": "ars-technica", "title": "The 7-year-old Nvidia Shield TV is now $100 more expensive due to AI", "metrics": {}},
            {"source": "the-verge", "publisher": "the-verge", "title": "Nvidia Shield TV Pro price increases by $100", "metrics": {}}
        ]
    }

    st2 = {
        "id": "story-apple",
        "title": "Apple restricts Full Disk Access permissions on macOS due to AI agents",
        "title_vi": "Apple siết quyền truy cập toàn bộ ổ đĩa trên macOS vì các agent AI",
        "summary": "Apple is tightening Full Disk Access permissions in macOS as AI agents can read user files, messages, mail, and web browsing history.",
        "summary_vi": "Apple siết quyền truy cập toàn bộ ổ đĩa trên macOS. Lý do: các AI agent ngày càng có thể đọc tệp, tin nhắn, thư và lịch sử duyệt web của bạn.",
        "key_points": [
            "Apple thay đổi quyền Full Disk Access trên hệ điều hành macOS.",
            "Quy định mới nhằm ngăn các AI agent tự ý truy cập tệp và tin nhắn cá nhân."
        ],
        "published_at": "2026-10-06T09:00:00Z",
        "source_count": 2,
        "worth_score": 40.0,
        "image": {"src": "https://example.com/apple.jpg", "kind": "photo"},
        "coverage": [
            {"source": "techcrunch", "publisher": "techcrunch", "title": "Apple tightens macOS disk access for AI agents", "metrics": {}},
            {"source": "wired", "publisher": "wired", "title": "macOS changes how apps and agents access files", "metrics": {}}
        ]
    }

    st3 = {
        "id": "story-amazon",
        "title": "Amazon commits $1 billion to ease community pushback over AI data centers",
        "title_vi": "Amazon cam kết 1 tỷ đô la để giảm bớt phản ứng của cộng đồng về các trung tâm dữ liệu AI",
        "summary": "Amazon spent $1 billion to soothe backlash over data centers, but critics say the company is downplaying environmental pollution.",
        "summary_vi": "Amazon chi 1 tỷ đô la để xoa dịu phản ứng về trung tâm dữ liệu, nhưng lại bị chỉ trích là đang làm nhẹ đi chuyện ô nhiễm.",
        "key_points": [
            "Amazon chi 1 tỷ đô la cho các sáng kiến cộng đồng quanh trung tâm dữ liệu.",
            "Các nhà hoạt động chỉ trích động thái này là làm nhẹ đi vấn đề ô nhiễm môi trường."
        ],
        "published_at": "2026-10-06T08:00:00Z",
        "source_count": 2,
        "worth_score": 38.0,
        "image": {"src": "https://example.com/amazon.jpg", "kind": "photo"},
        "coverage": [
            {"source": "bloomberg", "publisher": "bloomberg", "title": "Amazon spends $1 billion on data center community efforts", "metrics": {}},
            {"source": "reuters", "publisher": "reuters", "title": "Amazon pushes $1 billion fund amidst data center criticism", "metrics": {}}
        ]
    }

    return [st1, st2, st3]


def make_approved_sample_script(date_str="2026-10-07"):
    """Approved sample script from plans/reports/kich-ban-mau-0610.md."""
    return {
        "date": date_str,
        "generated_at": f"{date_str}T05:07:00+07:00",
        "prompt_version": video_script.PROMPT_VERSION,
        "hook": "AI vừa khiến một chiếc TV box 7 năm tuổi đắt thêm 100 đô la. Và đó chưa phải tin lạ nhất hôm nay.",
        "hint": "Ba tin AI đáng chú ý nhất, trong 45 giây.",
        "stories": [
            {
                "id": "story-shield",
                "line": "Nvidia Shield TV Pro, ra mắt từ 2019, giờ bán 299,99 đô la, đắt hơn 100 đô la vì AI."
            },
            {
                "id": "story-apple",
                "line": "Apple siết quyền truy cập toàn bộ ổ đĩa trên macOS. Lý do: các AI agent ngày càng có thể đọc tệp, tin nhắn, thư và lịch sử duyệt web của bạn."
            },
            {
                "id": "story-amazon",
                "line": "Amazon chi 1 tỷ đô la để xoa dịu phản ứng về trung tâm dữ liệu, nhưng lại bị chỉ trích là đang làm nhẹ đi chuyện ô nhiễm."
            }
        ],
        "cta": "Mỗi sáng ai-radar chọn 3 tin AI đáng đọc nhất. Theo dõi kênh để cập nhật tin AI nóng nhất. Bạn quan tâm tin nào nhất? Bình luận cho mình biết nhé."
    }


class VideoScriptSelectionTests(unittest.TestCase):
    def setUp(self):
        self.stories = make_sample_stories()

    def test_choose_picks_selects_three_stories_with_two_news_sources(self):
        now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        picks = video_script.choose_picks(self.stories, now_dt=now)
        self.assertEqual(len(picks), 3)
        self.assertEqual({s["id"] for s in picks}, {"story-shield", "story-apple", "story-amazon"})

    def test_choose_picks_discards_single_source_and_hn_only_stories(self):
        now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        single_source = {
            "id": "story-single",
            "title": "Single source story",
            "published_at": "2026-10-06T11:00:00Z",
            "worth_score": 90.0,
            "coverage": [
                {"source": "press-a", "publisher": "press-a", "metrics": {}}
            ]
        }
        hn_story = {
            "id": "story-hn",
            "title": "HN only story",
            "published_at": "2026-10-06T11:00:00Z",
            "worth_score": 90.0,
            "coverage": [
                {"source": "hn-ai", "publisher": "hacker-news", "metrics": {"points": 500}},
                {"source": "press-b", "publisher": "press-b", "metrics": {}}
            ]
        }
        test_set = [single_source, hn_story] + self.stories
        picks = video_script.choose_picks(test_set, now_dt=now)
        # single_source has 1 news source, hn_story has 1 news source (hn-ai is excluded)
        self.assertEqual({s["id"] for s in picks}, {"story-shield", "story-apple", "story-amazon"})

    def test_choose_picks_dedupes_same_event(self):
        now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        duplicate_shield = {
            "id": "story-shield-duplicate",
            "title": "The Nvidia Shield TV 7-year-old console now costs $100 more due to AI",
            "title_vi": "Nvidia Shield TV đắt thêm 100 đô la do AI",
            "published_at": "2026-10-06T09:30:00Z",
            "worth_score": 44.0,
            "coverage": [
                {"source": "cnet", "publisher": "cnet", "metrics": {}},
                {"source": "gizmodo", "publisher": "gizmodo", "metrics": {}}
            ]
        }
        fourth_story = {
            "id": "story-fourth",
            "title": "DeepSeek unveils novel architecture for mathematical reasoning",
            "title_vi": "DeepSeek công bố kiến trúc mới cho suy luận toán học",
            "published_at": "2026-10-06T07:00:00Z",
            "worth_score": 35.0,
            "coverage": [
                {"source": "venturebeat", "publisher": "venturebeat", "metrics": {}},
                {"source": "mit", "publisher": "mit-tech-review", "metrics": {}}
            ]
        }
        stories = [self.stories[0], duplicate_shield, self.stories[1], fourth_story]
        picks = video_script.choose_picks(stories, now_dt=now)
        # Duplicate shield should be skipped in favor of the fourth story
        pick_ids = [s["id"] for s in picks]
        self.assertIn("story-shield", pick_ids)
        self.assertNotIn("story-shield-duplicate", pick_ids)
        self.assertIn("story-fourth", pick_ids)

    def test_choose_picks_discards_untranslated_story(self):
        now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        untranslated = {
            "id": "story-untranslated-top",
            "title": "Introducing Mistral Large 4 with massive breakthrough",
            "title_vi": None,
            "published_at": "2026-10-06T11:30:00Z",
            "worth_score": 99.0,
            "image": {"src": "https://example.com/mistral.jpg", "kind": "photo"},
            "coverage": [
                {"source": "techcrunch", "publisher": "techcrunch", "metrics": {}},
                {"source": "wired", "publisher": "wired", "metrics": {}}
            ]
        }
        stories = [untranslated] + self.stories
        picks = video_script.choose_picks(stories, now_dt=now)
        pick_ids = [s["id"] for s in picks]
        self.assertNotIn("story-untranslated-top", pick_ids)
        self.assertEqual(len(picks), 3)
        self.assertEqual({s["id"] for s in picks}, {"story-shield", "story-apple", "story-amazon"})

    def test_choose_picks_returns_fewer_than_three_when_insufficient_translated(self):
        now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        two_stories = [self.stories[0], self.stories[1]]
        picks = video_script.choose_picks(two_stories, now_dt=now)
        self.assertEqual(len(picks), 2)


class VideoScriptVerificationTests(unittest.TestCase):
    def setUp(self):
        self.stories = make_sample_stories()
        self.stories_map = {s["id"]: s for s in self.stories}

    def test_approved_sample_script_passes_verification(self):
        script = make_approved_sample_script()
        valid, reason = video_script.validate_video_script(script, self.stories_map, expected_date="2026-10-07")
        self.assertTrue(valid, f"Approved script was rejected: {reason}")
        self.assertIsNone(reason)

    def test_reject_invented_number_in_story_line(self):
        """Boundary check: an invented number not found in source data must cause script rejection."""
        script = make_approved_sample_script()
        # Story 1 originally has 100 and 299,99. Introduce invented number 500:
        script["stories"][0]["line"] = "Nvidia Shield TV Pro, ra mắt từ 2019, giờ bán 299,99 đô la, đắt hơn 500 đô la vì AI."
        valid, reason = video_script.validate_video_script(script, self.stories_map)
        self.assertFalse(valid)
        self.assertIn("invented_number", reason)
        self.assertIn("500", reason)

    def test_reject_invented_entity_in_story_line(self):
        """Boundary check: an invented proper noun/entity must cause script rejection."""
        script = make_approved_sample_script()
        # Story 2 is about Apple. Replace Apple with Microsoft:
        script["stories"][1]["line"] = "Microsoft siết quyền truy cập toàn bộ ổ đĩa trên macOS cho các AI agent."
        valid, reason = video_script.validate_video_script(script, self.stories_map)
        self.assertFalse(valid)
        self.assertIn("invented_entity", reason)
        self.assertIn("microsoft", reason.lower())

    def test_reject_invented_number_in_hook(self):
        """An invented number in Hook not present in any story must cause rejection."""
        script = make_approved_sample_script()
        script["hook"] = "AI vừa khiến một chiếc TV box 7 năm tuổi đắt thêm 888 đô la. Và đó chưa phải tin lạ nhất hôm nay."
        valid, reason = video_script.validate_video_script(script, self.stories_map)
        self.assertFalse(valid)
        self.assertIn("invented_number in hook", reason)
        self.assertIn("888", reason)

    def test_reject_invented_entity_in_hook(self):
        """An ungrounded company/product in Hook must cause rejection."""
        script = make_approved_sample_script()
        script["hook"] = "Sony vừa khiến một chiếc TV box 7 năm tuổi đắt thêm 100 đô la. Và đó chưa phải tin lạ nhất hôm nay."
        valid, reason = video_script.validate_video_script(script, self.stories_map)
        self.assertFalse(valid)
        self.assertIn("invented_entity in hook", reason)
        self.assertIn("sony", reason.lower())

    def test_reject_story_line_too_long(self):
        """Each story line must be under 25 words."""
        script = make_approved_sample_script()
        # Add extra words so line exceeds 35 words
        script["stories"][0]["line"] = "Nvidia Shield TV Pro, ra mắt từ 2019, giờ bán 299,99 đô la, đắt hơn 100 đô la vì AI do nhu cầu tăng cao chưa từng thấy trong lịch sử thị trường công nghệ tiêu dùng toàn cầu hiện nay."
        valid, reason = video_script.validate_video_script(script, self.stories_map)
        self.assertFalse(valid)
        self.assertIn("line_too_long", reason)

    def test_reject_mismatched_story_ids(self):
        script = make_approved_sample_script()
        script["stories"][0]["id"] = "unknown-id"
        valid, reason = video_script.validate_video_script(script, self.stories_map)
        self.assertFalse(valid)
        self.assertIn("stories_id_mismatch", reason)

    def test_reject_date_mismatch(self):
        script = make_approved_sample_script(date_str="2026-10-06")
        valid, reason = video_script.validate_video_script(script, self.stories_map, expected_date="2026-10-07")
        self.assertFalse(valid)
        self.assertIn("date_mismatch", reason)


class VideoScriptPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

        self.input_file = self.tmp_path / "radar-ui.json"
        self.output_file = self.tmp_path / "video-script.json"
        self.ledger_file = self.tmp_path / "summary-gemini-ledger.json"
        summary_budget.init_ledger(self.ledger_file)

        self.stories = make_sample_stories()
        self.payload = {"schema_version": 2, "stories": self.stories, "sources": []}
        self.input_file.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")

        # Disable network
        self.network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

        # Isolate environment from ambient GitHub Actions ref
        self.env_patch = patch.dict(os.environ, {"GITHUB_REF": "", "GITHUB_REF_NAME": ""})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def fake_gemini_transport(self, body, key, timeout):
        """Stub model response delivering the approved script."""
        script = make_approved_sample_script()
        response_json = {
            "hook": script["hook"],
            "hint": script["hint"],
            "stories": script["stories"],
            "cta": script["cta"]
        }
        return {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": json.dumps(response_json, ensure_ascii=False)}]}
            }],
            "usageMetadata": {
                "promptTokenCount": 500,
                "candidatesTokenCount": 200,
                "totalTokenCount": 700
            }
        }

    def test_successful_generation_writes_file_and_updates_ledger(self):
        now = datetime(2026, 10, 7, 5, 7, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["script_written"])
        self.assertTrue(self.output_file.is_file())

        written = json.loads(self.output_file.read_text(encoding="utf-8"))
        self.assertEqual(written["date"], "2026-10-07")
        self.assertEqual(len(written["stories"]), 3)

        # Check ledger recorded the 700 tokens
        ledger_data = json.loads(self.ledger_file.read_text(encoding="utf-8"))
        self.assertEqual(len(ledger_data["attempts"]), 1)
        self.assertEqual(ledger_data["attempts"][0]["tokens"], 700)

    def test_today_script_survives_changed_or_missing_picks_without_request(self):
        script = make_approved_sample_script(date_str="2026-10-07")
        self.output_file.write_text(json.dumps(script), encoding="utf-8")
        self.input_file.write_text(json.dumps({"stories": []}), encoding="utf-8")
        result = video_script.generate_video_script(
            input_path=self.input_file, output_path=self.output_file, ledger_path=self.ledger_file,
            now_val=datetime(2026, 10, 7, 5, 30, tzinfo=video_script.VIETNAM),
            transport_fn=lambda *args: self.fail("must not call API"))
        self.assertEqual(result["status"], "already_generated")
        self.assertEqual(json.loads(self.output_file.read_text(encoding="utf-8")), script)

    def test_idempotency_does_not_spend_tokens_if_already_generated_today(self):
        # Pre-populate output file with today's script
        today_script = make_approved_sample_script(date_str="2026-10-07")
        self.output_file.write_text(json.dumps(today_script, ensure_ascii=False), encoding="utf-8")

        now = datetime(2026, 10, 7, 5, 37, 0, tzinfo=video_script.VIETNAM)
        calls = []
        def tracking_transport(*args, **kwargs):
            calls.append(args)
            return self.fake_gemini_transport(*args, **kwargs)

        res = video_script.generate_video_script(
            input_path=self.input_file,
            output_path=self.output_file,
            ledger_path=self.ledger_file,
            now_val=now,
            transport_fn=tracking_transport
        )

        self.assertEqual(res["status"], "already_generated")
        self.assertFalse(res["script_written"])
        self.assertEqual(len(calls), 0)

    def test_outside_window_skips_before_five_am_vn_time(self):
        # 04:37 VN time
        now = datetime(2026, 10, 7, 4, 37, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "outside_window")
        self.assertFalse(res["script_written"])
        self.assertFalse(self.output_file.exists())

    def test_force_flag_bypasses_window_check(self):
        # 04:37 VN time with force=True
        now = datetime(2026, 10, 7, 4, 37, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                force=True,
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["script_written"])
        self.assertTrue(self.output_file.is_file())

    def test_outside_window_skips_after_six_am_vn_time(self):
        # 06:15 VN time
        now = datetime(2026, 10, 7, 6, 15, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "outside_window")
        self.assertFalse(res["script_written"])
        self.assertFalse(self.output_file.exists())

    def test_non_main_ref_bypasses_window_and_generates_script(self):
        # 14:00 VN time on non-main ref (coordinator live run on branch before merge)
        now = datetime(2026, 10, 7, 14, 0, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                ref="refs/heads/feat/video-script",
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["script_written"])
        self.assertTrue(self.output_file.is_file())

    def test_non_main_ref_preserves_once_per_day_idempotency(self):
        # 14:00 VN time on non-main ref, but script for today already exists
        today_script = make_approved_sample_script(date_str="2026-10-07")
        self.output_file.write_text(json.dumps(today_script, ensure_ascii=False), encoding="utf-8")

        now = datetime(2026, 10, 7, 14, 30, 0, tzinfo=video_script.VIETNAM)
        calls = []
        def tracking_transport(*args, **kwargs):
            calls.append(args)
            return self.fake_gemini_transport(*args, **kwargs)

        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                ref="refs/heads/feat/video-script",
                now_val=now,
                transport_fn=tracking_transport
            )

        self.assertEqual(res["status"], "already_generated")
        self.assertFalse(res["script_written"])
        self.assertEqual(len(calls), 0)

    def test_non_main_ref_preserves_shared_ledger_budget_exhaustion(self):
        # 14:00 VN time on non-main ref, but daily request ceiling (12) reached
        now = datetime(2026, 10, 7, 14, 0, 0, tzinfo=video_script.VIETNAM)
        now_ts = now.timestamp()
        for i in range(12):
            summary_budget.reserve(self.ledger_file, estimated_tokens=1000, now=now_ts - 3600 + i * 10, last_story_id=f"story-{i}")

        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                ref="refs/heads/feat/video-script",
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "budget_exhausted")
        self.assertFalse(res["script_written"])

    def test_main_ref_strictly_enforces_window_check(self):
        # 14:00 VN time with explicit main ref
        now = datetime(2026, 10, 7, 14, 0, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                ref="refs/heads/main",
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "outside_window")
        self.assertFalse(res["script_written"])

    def test_cli_accepts_ref_argument_and_bypasses_window(self):
        github_output_file = self.tmp_path / "github_output"
        github_output_file.touch()
        now_str = "2026-10-07T14:00:00+07:00"

        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
            "GITHUB_OUTPUT": str(github_output_file)
        }
        with patch.dict(os.environ, env), patch("radar.summary_gemini.transport", side_effect=self.fake_gemini_transport):
            code = video_script.main([
                "--input", str(self.input_file),
                "--output", str(self.output_file),
                "--ledger", str(self.ledger_file),
                "--ref", "refs/heads/feat/video-script",
                "--now", now_str
            ])
            self.assertEqual(code, 0)

        self.assertTrue(self.output_file.is_file())
        output_content = github_output_file.read_text(encoding="utf-8")
        self.assertIn("video_script_written=true", output_content)
        self.assertIn("video_script_ledger_written=true", output_content)

    def test_rejected_script_is_never_written_to_public_path(self):
        """Boundary: When model hallucinating ungrounded fact, script is rejected and NOT written."""
        def hallucinating_transport(body, key, timeout):
            script = make_approved_sample_script()
            # Model hallucinated 999 dollars
            script["stories"][0]["line"] = "Nvidia Shield TV Pro tăng giá thêm 999 đô la do trí tuệ nhân tạo."
            response_json = {
                "hook": script["hook"],
                "hint": script["hint"],
                "stories": script["stories"],
                "cta": script["cta"]
            }
            return {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": json.dumps(response_json, ensure_ascii=False)}]}
                }],
                "usageMetadata": {"totalTokenCount": 650}
            }

        now = datetime(2026, 10, 7, 5, 7, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=hallucinating_transport
            )

        self.assertEqual(res["status"], "rejected")
        self.assertIn("invented_number", res["detail"])
        self.assertFalse(res["script_written"])
        self.assertFalse(self.output_file.exists())

    def test_budget_exhaustion_prevents_api_call(self):
        # Fill ledger to 12 attempts
        now = datetime(2026, 10, 7, 5, 7, 0, tzinfo=video_script.VIETNAM)
        now_ts = now.timestamp()
        attempts = [{"time": now_ts - 100 * i, "tokens": 1000} for i in range(12)]
        self.ledger_file.write_text(json.dumps({"version": 1, "attempts": attempts}), encoding="utf-8")

        calls = []
        def tracking_transport(*args, **kwargs):
            calls.append(args)
            return self.fake_gemini_transport(*args, **kwargs)

        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=tracking_transport
            )

        self.assertEqual(res["status"], "budget_exhausted")
        self.assertFalse(res["script_written"])
        self.assertEqual(len(calls), 0)

    def test_cli_execution_with_github_output(self):
        github_output_file = self.tmp_path / "github_output.txt"
        now_str = "2026-10-07T05:07:00+07:00"
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
            "GITHUB_OUTPUT": str(github_output_file)
        }
        with patch.dict(os.environ, env), patch("radar.summary_gemini.transport", side_effect=self.fake_gemini_transport):
            code = video_script.main([
                "--input", str(self.input_file),
                "--output", str(self.output_file),
                "--ledger", str(self.ledger_file),
                "--force",
                "--now", now_str
            ])
            self.assertEqual(code, 0)

        self.assertTrue(self.output_file.is_file())
        output_content = github_output_file.read_text(encoding="utf-8")
        self.assertIn("video_script_written=true", output_content)
        self.assertIn("video_script_ledger_written=true", output_content)

    def test_rejection_unlinks_existing_today_file(self):
        # Suppose a corrupted or unverified file for today was present
        today_invalid = {"date": "2026-10-07", "partial": True}
        self.output_file.write_text(json.dumps(today_invalid), encoding="utf-8")

        def rejecting_transport(body, key, timeout):
            script = make_approved_sample_script()
            script["stories"][0]["line"] = "Nvidia Shield TV Pro có giá 9999 đô la do AI."
            return {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": json.dumps(script, ensure_ascii=False)}]}
                }],
                "usageMetadata": {"totalTokenCount": 500}
            }

        now = datetime(2026, 10, 7, 5, 7, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=rejecting_transport
            )

        self.assertEqual(res["status"], "rejected")
        self.assertFalse(self.output_file.exists())

    def test_missing_api_key_skips_cleanly(self):
        now = datetime(2026, 10, 7, 5, 7, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["detail"], "missing_api_key")
        self.assertFalse(self.output_file.exists())

    def test_unconfirmed_free_tier_skips_cleanly(self):
        now = datetime(2026, 10, 7, 5, 7, 0, tzinfo=video_script.VIETNAM)
        env = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "0"
        }
        with patch.dict(os.environ, env):
            res = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.output_file,
                ledger_path=self.ledger_file,
                now_val=now,
                transport_fn=self.fake_gemini_transport
            )

        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["detail"], "free_tier_unconfirmed")
        self.assertFalse(self.output_file.exists())

    def test_choose_picks_from_real_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "edition-real-snapshot.json"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        stories = data.get("stories") or []
        sources = {s["id"]: s for s in data.get("sources") or []}
        now = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
        picks = video_script.choose_picks(stories, sources_map=sources, now_dt=now)
        # Verify all chosen stories have at least 2 news sources
        for st in picks:
            news_covs = video_script.news_coverage_of(st, sources)
            self.assertGreaterEqual(len(news_covs), 2)


class TestVideoScriptBudgetReserve(unittest.TestCase):
    """Test suite for protecting the video script's share of shared free-tier budget."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.ledger_file = self.tmp_path / "summary-gemini-ledger.json"
        self.script_file = self.tmp_path / "video-script.json"
        summary_budget.init_ledger(self.ledger_file)
        self.input_file = self.tmp_path / "radar-ui.json"
        payload = {
            "stories": make_sample_stories(),
            "sources": [{"id": "ars-technica"}, {"id": "the-verge"}, {"id": "techcrunch"}, {"id": "wired"}, {"id": "bloomberg"}, {"id": "reuters"}]
        }
        self.input_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_is_script_reserve_active_conditions(self):
        now_early = datetime(2026, 10, 7, 2, 0, 0, tzinfo=video_script.VIETNAM)
        now_in_window = datetime(2026, 10, 7, 5, 30, 0, tzinfo=video_script.VIETNAM)
        now_after_window = datetime(2026, 10, 7, 6, 15, 0, tzinfo=video_script.VIETNAM)

        # Before script runs and before window ends -> reserve is active
        self.assertTrue(summary_budget.is_script_reserve_active(now_early, script_path=self.script_file, ledger_path=self.ledger_file))
        self.assertTrue(summary_budget.is_script_reserve_active(now_in_window, script_path=self.script_file, ledger_path=self.ledger_file))

        # After script is written today -> reserve is released
        sample = make_approved_sample_script("2026-10-07")
        self.script_file.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
        self.assertFalse(summary_budget.is_script_reserve_active(now_in_window, script_path=self.script_file, ledger_path=self.ledger_file))
        self.assertFalse(summary_budget.is_script_reserve_active(now_early, script_path=self.script_file, ledger_path=self.ledger_file))

        # If script file is removed but ledger records script completion -> reserve is released
        self.script_file.unlink()
        summary_budget.mark_script_completed(self.ledger_file, "2026-10-07")
        self.assertFalse(summary_budget.is_script_reserve_active(now_in_window, script_path=self.script_file, ledger_path=self.ledger_file))

        # Reset ledger and remove script: after window passes (>= 06:00 VN) -> reserve is released
        self.ledger_file.write_text(json.dumps({"version": 1, "attempts": []}), encoding="utf-8")
        self.assertFalse(summary_budget.is_script_reserve_active(now_after_window, script_path=self.script_file, ledger_path=self.ledger_file))

    def test_summaries_stop_short_of_script_request_share_before_script_ran_today(self):
        now_dt = datetime(2026, 10, 7, 3, 0, 0, tzinfo=video_script.VIETNAM)
        now_ts = now_dt.timestamp()

        # Fill ledger with 11 attempts (11 / 12 requests)
        for i in range(11):
            summary_budget.reserve(self.ledger_file, estimated_tokens=500, now=now_ts - 3600 + i * 10, last_story_id=f"story-{i}")

        # Summary check (reserve_for_script=True): 11 >= (12 - 1) -> blocked with daily_limit
        cap_err = summary_budget.capacity_error(self.ledger_file, now=now_ts, reserve_for_script=True)
        self.assertEqual(cap_err, "daily_limit")
        res_err = summary_budget.reserve(self.ledger_file, estimated_tokens=500, now=now_ts, reserve_for_script=True)
        self.assertEqual(res_err, "daily_limit")

        # Video script check (reserve_for_script=False): 11 < 12 -> allowed to reserve slot 12
        cap_script = summary_budget.capacity_error(self.ledger_file, now=now_ts, reserve_for_script=False)
        self.assertIsNone(cap_script)
        res_script = summary_budget.reserve(self.ledger_file, estimated_tokens=1500, now=now_ts, reserve_for_script=False)
        self.assertIsNone(res_script)

    def test_summaries_stop_short_of_script_token_share_before_script_ran_today(self):
        now_dt = datetime(2026, 10, 7, 4, 0, 0, tzinfo=video_script.VIETNAM)
        now_ts = now_dt.timestamp()

        # Reserve 23,000 tokens across attempts (out of 25,000 ceiling; reserve threshold is 23,500)
        summary_budget.reserve(self.ledger_file, estimated_tokens=23000, now=now_ts - 600, last_story_id="bulk-stories")

        # Summary estimating 1,000 tokens: 23,000 + 1,000 = 24,000 > 23,500 -> blocked
        cap_err = summary_budget.capacity_error(self.ledger_file, estimated_tokens=1000, now=now_ts, reserve_for_script=True)
        self.assertEqual(cap_err, "daily_token_limit")
        res_err = summary_budget.reserve(self.ledger_file, estimated_tokens=1000, now=now_ts, reserve_for_script=True)
        self.assertEqual(res_err, "daily_token_limit")

        # Video script estimating 1,500 tokens against 25,000 ceiling: 23,000 + 1,500 = 24,500 <= 25,000 -> allowed
        cap_script = summary_budget.capacity_error(self.ledger_file, estimated_tokens=1500, now=now_ts, reserve_for_script=False)
        self.assertIsNone(cap_script)
        res_script = summary_budget.reserve(self.ledger_file, estimated_tokens=1500, now=now_ts, reserve_for_script=False)
        self.assertIsNone(res_script)

    def test_summaries_may_use_share_after_script_is_written_today(self):
        now_dt = datetime(2026, 10, 7, 5, 20, 0, tzinfo=video_script.VIETNAM)
        now_ts = now_dt.timestamp()

        # 11 attempts in ledger
        for i in range(11):
            summary_budget.reserve(self.ledger_file, estimated_tokens=500, now=now_ts - 3600 + i * 10, last_story_id=f"story-{i}")

        # Write script for today
        sample = make_approved_sample_script("2026-10-07")
        self.script_file.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")

        # Reserve is no longer active
        is_active = summary_budget.is_script_reserve_active(now_ts, script_path=self.script_file, ledger_path=self.ledger_file)
        self.assertFalse(is_active)

        # Summaries are allowed to use slot 12
        cap_err = summary_budget.capacity_error(self.ledger_file, now=now_ts, reserve_for_script=is_active)
        self.assertIsNone(cap_err)
        res_err = summary_budget.reserve(self.ledger_file, estimated_tokens=500, now=now_ts, reserve_for_script=is_active)
        self.assertIsNone(res_err)

    def test_summaries_may_use_share_after_window_passes(self):
        now_dt = datetime(2026, 10, 7, 6, 15, 0, tzinfo=video_script.VIETNAM)
        now_ts = now_dt.timestamp()

        # 11 attempts in ledger, no script written
        for i in range(11):
            summary_budget.reserve(self.ledger_file, estimated_tokens=500, now=now_ts - 3600 + i * 10, last_story_id=f"story-{i}")

        # Reserve is inactive because window passed
        is_active = summary_budget.is_script_reserve_active(now_ts, script_path=self.script_file, ledger_path=self.ledger_file)
        self.assertFalse(is_active)

        # Summaries are allowed to use slot 12
        cap_err = summary_budget.capacity_error(self.ledger_file, now=now_ts, reserve_for_script=is_active)
        self.assertIsNone(cap_err)
        res_err = summary_budget.reserve(self.ledger_file, estimated_tokens=500, now=now_ts, reserve_for_script=is_active)
        self.assertIsNone(res_err)

    def test_pipeline_summarize_stops_short_before_script_and_unblocks_after(self):
        now_dt = datetime(2026, 10, 7, 3, 0, 0, tzinfo=video_script.VIETNAM)
        now_ts = now_dt.timestamp()

        # 11 attempts in ledger
        for i in range(11):
            summary_budget.reserve(self.ledger_file, estimated_tokens=500, now=now_ts - 3600 + i * 10, last_story_id=f"story-{i}")

        story = {
            "id": "story-test",
            "title": "A new AI breakthrough announced",
            "coverage": [{"publisher": "reuters", "title": "A new AI breakthrough announced", "url": "https://example.com/ai"}]
        }
        payload = {"stories": [story], "ranking": {"window_hours": 72}}
        cache = {}

        calls = []
        def fake_transport(batch, cfg, transport_fn, remaining):
            calls.append(batch)
            return {s["id"]: ["Điểm một", "Điểm hai", "Điểm ba"] for s in batch}, 500, None, True

        # Summarize step before script runs: stops short with daily_limit
        stats, _ = summary_pipeline.summarize_payload(
            payload,
            cache,
            config=gemini.Config(api_key="test-key", confirmed=True),
            article_fetch_fn=lambda s, **kw: "Đoạn văn bài báo dài hơn ba trăm ký tự để đủ chuẩn tóm tắt nội dung bài viết và kiểm thử hạn mức quota.",
            ledger_path=self.ledger_file,
            script_path=self.script_file,
            now=lambda: now_ts
        )
        self.assertEqual(stats["status"], "failed")
        self.assertEqual(stats["error"], "daily_limit")
        self.assertEqual(len(calls), 0)

        # At 05:07 VN time: video script generates successfully
        now_script = datetime(2026, 10, 7, 5, 7, 0, tzinfo=video_script.VIETNAM)
        def fake_script_transport(body, key, timeout):
            return {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": json.dumps(make_approved_sample_script("2026-10-07"), ensure_ascii=False)}]}
                }],
                "usageMetadata": {"totalTokenCount": 700}
            }

        env = {"GEMINI_API_KEY": "test-key", "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"}
        with patch.dict(os.environ, env):
            res_script = video_script.generate_video_script(
                input_path=self.input_file,
                output_path=self.script_file,
                ledger_path=self.ledger_file,
                now_val=now_script,
                transport_fn=fake_script_transport
            )
        self.assertEqual(res_script["status"], "success")
        self.assertTrue(self.script_file.is_file())

        # Now is_script_reserve_active returns False
        self.assertFalse(summary_budget.is_script_reserve_active(now_script.timestamp(), script_path=self.script_file, ledger_path=self.ledger_file))

    def test_cli_reads_github_ref_from_env_without_cli_arg(self):
        now_str = "2026-10-07T03:00:00+07:00"

        # On a non-main branch in env: bypasses window check
        env_branch = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
            "GITHUB_REF": "refs/heads/feat/video-script"
        }
        with patch.dict(os.environ, env_branch), patch("radar.summary_gemini.transport", side_effect=lambda body, k, t: {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(make_approved_sample_script("2026-10-07"), ensure_ascii=False)}]}}],
            "usageMetadata": {"totalTokenCount": 700}
        }):
            code = video_script.main([
                "--input", str(self.input_file),
                "--output", str(self.script_file),
                "--ledger", str(self.ledger_file),
                "--now", now_str
            ])
            self.assertEqual(code, 0)
        self.assertTrue(self.script_file.is_file())
        self.script_file.unlink()

        # On main branch in env: outside window check skips
        env_main = {
            "GEMINI_API_KEY": "test-key",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
            "GITHUB_REF": "refs/heads/main"
        }
        with patch.dict(os.environ, env_main):
            code = video_script.main([
                "--input", str(self.input_file),
                "--output", str(self.script_file),
                "--ledger", str(self.ledger_file),
                "--now", now_str
            ])
            self.assertEqual(code, 0)
        self.assertFalse(self.script_file.exists())


if __name__ == "__main__":
    unittest.main()
