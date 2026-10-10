"""Unit tests for Cloudflare Workers AI flux-1-schnell image provider.

Covers:
- No call without env credentials
- Daily cap and persisted ledger
- Circuit breaker: stop for the day on HTTP 429 / quota error
- Once per story generation and static file reuse
- Prompt rules: abstract editorial topic, strictly no brand or person terms
- Label on the page: "Ảnh minh hoạ do AI tạo" for AI cards
"""

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
import contextlib
import io
import unittest
from unittest.mock import patch

from radar.ai_images import (
    AIImageLedger,
    build_ai_prompt,
    generate_ai_illustration,
    probe,
    safe_image_filename,
    sanitize_topic_text,
    BRAND_TERMS,
    PERSON_TERMS,
    MODEL_ID,
    DAILY_NEURON_BUDGET,
    DAILY_CAP,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
    DEFAULT_STEPS,
    compute_neuron_cost,
    story_recency_key,
    ASSUMED_MAX_RUNS_IN_WINDOW,
    GENERATION_WINDOW_UTC_HOUR,
    PER_RUN_NEURON_BUDGET,
    RunBudget,
    generation_window_open,
    read_image_dimensions,
    reset_process_run_budget,
)
from radar.images import resolve_images_for_stories, resolve_story_image, ImageCache


# Valid minimal 1024x1024 JPEG bytes for mock transport
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\xff\xc0\x00\x0b\x08\x04\x00\x04\x00\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"

# Valid minimal 1024x1024 PNG bytes for mock transport
VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x04\x00\x00\x00\x04\x00"
    b"\x08\x02\x00\x00\x00"
    b"\x00\x00\x00\x00"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


# A moment inside the daily generation window (02:00-02:59 UTC) for tests that exercise generation.
IN_WINDOW = datetime(2026, 10, 6, GENERATION_WINDOW_UTC_HOUR, 30, 0, tzinfo=timezone.utc)


class InsideWindowTestCase(unittest.TestCase):
    """Runs the test with the UTC clock inside the generation window and a fresh per-run budget."""

    def setUp(self):
        patcher = patch("radar.ai_images._utc_now", return_value=IN_WINDOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        reset_process_run_budget()
        self.addCleanup(reset_process_run_budget)


class AIImagesNoCallWithoutEnvTests(InsideWindowTestCase):
    def test_no_call_without_env_in_generate_ai_illustration(self):
        """No network call and returns None when environment variables are missing."""
        story = {"id": "st-no-env", "title": "New research in neural network scaling", "kind": "paper"}
        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            ledger_path = Path(tmpdir) / "ledger.json"

            with patch.dict(os.environ, {}, clear=True):
                # Ensure neither CLOUDFLARE_ACCOUNT_ID nor CLOUDFLARE_AI_API_TOKEN is set
                self.assertIsNone(os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
                self.assertIsNone(os.environ.get("CLOUDFLARE_AI_API_TOKEN"))

                res = generate_ai_illustration(
                    story,
                    site_root=site_dir,
                    ledger_path=ledger_path,
                    transport=None,
                )
                self.assertIsNone(res)
                self.assertFalse((site_dir / "assets" / "ai" / "st-no-env.jpg").exists())

    def test_no_call_without_env_in_pipeline_resolution(self):
        """Stories without images stay without images when env credentials are absent."""
        stories = [
            {"id": "st-plain", "title": "A story with no source image", "coverage": []}
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"

            with patch.dict(os.environ, {}, clear=True):
                resolve_images_for_stories(
                    stories,
                    cache_path=cache_file,
                    ledger_path=ledger_file,
                    site_root=site_dir,
                    transport=lambda u: b"",  # offline mock for source fetcher
                    ai_transport=None,
                )
                self.assertNotIn("image", stories[0])


class AIImageNeuronBudgetAndLedgerTests(InsideWindowTestCase):
    def test_compute_neuron_cost_formula(self):
        """Neuron cost matches Cloudflare flux-1-schnell pricing per 512x512 tile and step."""
        # 1 tile (512x512), 4 steps: 1 * 4.80 + 1 * 4 * 9.60 = 43.20 neurons
        self.assertEqual(compute_neuron_cost(width=512, height=512, steps=4), 43.20)

        # 4 tiles (1024x1024), 4 steps: 4 * 4.80 + 4 * 4 * 9.60 = 172.80 neurons
        self.assertEqual(compute_neuron_cost(width=1024, height=1024, steps=4), 172.80)

        # 4 tiles (1024x576 in 2x2 grid), 4 steps: 172.80 neurons
        self.assertEqual(compute_neuron_cost(width=1024, height=576, steps=4), 172.80)

        # 2 tiles (768x512 in 2x1 grid), 4 steps: 2 * 43.20 = 86.40 neurons
        self.assertEqual(compute_neuron_cost(width=768, height=512, steps=4), 86.40)

    def test_default_daily_budget_is_at_most_8000(self):
        """Default daily budget is at most 8,000 neurons (under 10,000 free allocation)."""
        self.assertLessEqual(DAILY_NEURON_BUDGET, 8000.0)
        self.assertEqual(DAILY_NEURON_BUDGET, 8000.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = AIImageLedger(ledger_path=Path(tmpdir) / "ai-ledger.json")
            self.assertEqual(ledger.daily_budget, 8000.0)
            self.assertEqual(ledger.daily_cap, 8000.0)

    def test_ledger_stops_before_cost_passes_8000_neurons(self):
        """The ledger stops BEFORE the computed cost would pass 8,000 neurons in a UTC day."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"
            ledger = AIImageLedger(ledger_path=ledger_file, daily_budget=8000.0)

            cost_per_img = compute_neuron_cost(width=1024, height=1024, steps=4)
            self.assertEqual(cost_per_img, 172.80)

            now = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)

            # 46 images * 172.8 = 7,948.80 neurons <= 8,000 neurons
            for i in range(1, 47):
                story_id = f"story-{i}"
                can_gen, _ = ledger.can_generate(story_id, cost=cost_per_img, now=now)
                self.assertTrue(can_gen, f"Story {i} should be allowed within 8,000 neuron budget")
                ledger.record_generation(story_id, cost=cost_per_img, now=now)

            day = ledger.get_day(now)
            self.assertEqual(day["count"], 46)
            self.assertAlmostEqual(day["neurons_spent"], 7948.80, places=2)
            self.assertLessEqual(day["neurons_spent"], 8000.0)

            # Story 47: 7,948.80 + 172.80 = 8,121.60 > 8,000 neurons.
            # Must be REFUSED before crossing 8,000!
            can_gen_47, reason = ledger.can_generate("story-47", cost=cost_per_img, now=now)
            self.assertFalse(can_gen_47, "Story 47 must be refused as it would exceed 8,000 neurons")
            self.assertIn("daily_budget", reason)

            # Total spent remains strictly under or equal to 8,000 neurons
            self.assertLessEqual(ledger.get_day(now)["neurons_spent"], 8000.0)
            self.assertTrue(ledger.get_day(now)["stopped"])

            # Verify generate_ai_illustration returns None and makes zero network calls for story 47
            calls = []
            mock_transport = lambda u, h, d: (calls.append(u) or (200, "image/jpeg", VALID_JPEG_BYTES))
            res = generate_ai_illustration(
                {"id": "story-47", "title": "AI research"},
                site_root=site_dir,
                ledger=ledger,
                account_id="acc",
                api_token="tok",
                transport=mock_transport,
                now=now,
            )
            self.assertIsNone(res)
            self.assertEqual(len(calls), 0, "No network call should be made after budget is reached")
            self.assertLessEqual(ledger.get_day(now)["neurons_spent"], 8000.0)

    def test_budget_resets_on_new_utc_day(self):
        """The neuron budget resets on a new UTC day."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            ledger = AIImageLedger(ledger_path=ledger_file, daily_budget=8000.0)

            day1 = datetime(2026, 10, 5, 23, 30, 0, tzinfo=timezone.utc)
            cost_per_img = compute_neuron_cost(1024, 1024, 4)

            # Exhaust Day 1 budget (46 images)
            for i in range(1, 47):
                ledger.record_generation(f"day1-{i}", cost=cost_per_img, now=day1)

            # Day 1 is stopped
            self.assertTrue(ledger.get_day(day1)["stopped"])
            can_gen_day1, _ = ledger.can_generate("day1-overflow", cost=cost_per_img, now=day1)
            self.assertFalse(can_gen_day1)

            # Day 2 begins at 00:00:01 UTC
            day2 = datetime(2026, 10, 6, 0, 0, 1, tzinfo=timezone.utc)
            day2_record = ledger.get_day(day2)
            self.assertEqual(day2_record["neurons_spent"], 0.0)
            self.assertEqual(day2_record["count"], 0)
            self.assertFalse(day2_record["stopped"])

            # Day 2 can generate fresh stories
            can_gen_day2, reason = ledger.can_generate("day2-first", cost=cost_per_img, now=day2)
            self.assertTrue(can_gen_day2, f"Generation must be allowed on new UTC day: {reason}")


class AIImageDimensionsAndSchemaTests(InsideWindowTestCase):
    def test_request_body_has_no_width_or_height(self):
        """The REST API request body sends only prompt and steps; no width or height."""
        story = {"id": "st-schema-check", "title": "Advanced deep learning reasoning", "kind": "model"}
        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            ledger_file = Path(tmpdir) / "ai-ledger.json"

            sent_payloads = []

            def mock_transport(url, headers, data):
                sent_payloads.append(json.loads(data.decode("utf-8")))
                b64 = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")
                return 200, "application/json", json.dumps({"result": {"image": b64}}).encode("utf-8")

            res = generate_ai_illustration(
                story,
                site_root=site_dir,
                ledger_path=ledger_file,
                account_id="acc-test",
                api_token="tok-test",
                transport=mock_transport,
            )
            self.assertIsNotNone(res)
            self.assertEqual(len(sent_payloads), 1)

            payload = sent_payloads[0]
            # Must NOT contain width or height
            self.assertNotIn("width", payload)
            self.assertNotIn("height", payload)
            # Must contain prompt and steps
            self.assertIn("prompt", payload)
            self.assertIn("steps", payload)
            self.assertEqual(payload["steps"], 4)

    def test_dimensions_read_from_jpeg(self):
        """Image dimensions are read from JPEG bytes and real cost is recorded in the ledger."""
        # Test direct dimensions extraction
        w, h = read_image_dimensions(VALID_JPEG_BYTES)
        self.assertEqual((w, h), (1024, 1024))

        # Test 512x512 JPEG: SOF0 has height=512 (0x0200), width=512 (0x0200)
        jpeg_512 = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00"
            b"\xff\xc0\x00\x0b\x08\x02\x00\x02\x00\x01\x01\x11\x00"
            b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        )
        w512, h512 = read_image_dimensions(jpeg_512)
        self.assertEqual((w512, h512), (512, 512))

        story = {"id": "st-jpeg-dims", "title": "Neural architecture", "kind": "model"}
        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            ledger_file = Path(tmpdir) / "ai-ledger.json"

            def mock_transport(url, headers, data):
                b64 = base64.b64encode(jpeg_512).decode("ascii")
                return 200, "application/json", json.dumps({"result": {"image": b64}}).encode("utf-8")

            outcome = {}
            res = generate_ai_illustration(
                story,
                site_root=site_dir,
                ledger_path=ledger_file,
                account_id="acc-test",
                api_token="tok-test",
                transport=mock_transport,
                outcome=outcome,
            )
            self.assertIsNotNone(res)
            self.assertEqual(outcome.get("width"), 512)
            self.assertEqual(outcome.get("height"), 512)
            # 512x512 at 4 steps is 1 tile: 4.80 + 4 * 9.60 = 43.20 neurons
            self.assertAlmostEqual(outcome.get("cost"), 43.20, places=2)
            ledger = AIImageLedger(ledger_path=ledger_file)
            self.assertAlmostEqual(ledger.get_day()["neurons_spent"], 43.20, places=2)

    def test_dimensions_read_from_png(self):
        """Image dimensions are read from PNG bytes and real cost is recorded in the ledger."""
        w, h = read_image_dimensions(VALID_PNG_BYTES)
        self.assertEqual((w, h), (1024, 1024))

        # 512x512 PNG
        png_512 = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x02\x00\x00\x00\x02\x00"
            b"\x08\x02\x00\x00\x00"
            b"\x00\x00\x00\x00"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        w512, h512 = read_image_dimensions(png_512)
        self.assertEqual((w512, h512), (512, 512))

        story = {"id": "st-png-dims", "title": "Scientific discovery", "kind": "paper"}
        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            ledger_file = Path(tmpdir) / "ai-ledger.json"

            def mock_transport(url, headers, data):
                return 200, "image/png", png_512

            outcome = {}
            res = generate_ai_illustration(
                story,
                site_root=site_dir,
                ledger_path=ledger_file,
                account_id="acc-test",
                api_token="tok-test",
                transport=mock_transport,
                outcome=outcome,
            )
            self.assertIsNotNone(res)
            self.assertEqual(outcome.get("width"), 512)
            self.assertEqual(outcome.get("height"), 512)
            self.assertAlmostEqual(outcome.get("cost"), 43.20, places=2)
            ledger = AIImageLedger(ledger_path=ledger_file)
            self.assertAlmostEqual(ledger.get_day()["neurons_spent"], 43.20, places=2)

    def test_oversize_response_records_real_cost_and_stops_day(self):
        """A response larger than the assumed size records its real cost and stops the day."""
        # 1536 x 1024 JPEG: 3x2 tiles = 6 tiles; cost = 6 * 4.80 + 6 * 4 * 9.60 = 259.20 neurons
        # Assumed upper bound: 1024 x 1024 at 4 steps = 172.80 neurons
        oversize_jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00"
            b"\xff\xc0\x00\x0b\x08\x04\x00\x06\x00\x01\x01\x11\x00"
            b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        )
        w, h = read_image_dimensions(oversize_jpeg)
        self.assertEqual((w, h), (1536, 1024))

        story1 = {"id": "st-oversize-1", "title": "Large model vision", "kind": "model"}
        story2 = {"id": "st-oversize-2", "title": "Next story attempted today", "kind": "paper"}

        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            ledger_file = Path(tmpdir) / "ai-ledger.json"

            def mock_transport(url, headers, data):
                b64 = base64.b64encode(oversize_jpeg).decode("ascii")
                return 200, "application/json", json.dumps({"result": {"image": b64}}).encode("utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                res1 = generate_ai_illustration(
                    story1,
                    site_root=site_dir,
                    ledger_path=ledger_file,
                    account_id="acc-test",
                    api_token="tok-test",
                    transport=mock_transport,
                )
            printed = buf.getvalue()

            self.assertIsNotNone(res1)
            # Printed reason why generation is stopped
            self.assertIn("AI image generation stopped for day", printed)
            self.assertIn("1536x1024", printed)
            self.assertIn("259.2 neurons", printed)

            # Ledger recorded real cost (259.20) and marked day stopped
            ledger = AIImageLedger(ledger_path=ledger_file)
            day = ledger.get_day()
            self.assertAlmostEqual(day["neurons_spent"], 259.20, places=2)
            self.assertTrue(day["stopped"])
            self.assertIn("exceeding assumed bound", day["stop_reason"])

            # Subsequent generation on the same day is refused
            res2 = generate_ai_illustration(
                story2,
                site_root=site_dir,
                ledger=ledger,
                account_id="acc-test",
                api_token="tok-test",
                transport=mock_transport,
            )
            self.assertIsNone(res2)


class AIImageNewestFirstTests(InsideWindowTestCase):
    def test_story_recency_key_ordering(self):
        """Newer timestamps produce larger sort keys for descending ordering."""
        st_old = {"id": "old", "published_at": "2026-10-01T10:00:00Z"}
        st_mid = {"id": "mid", "published_at": "2026-10-03T10:00:00Z"}
        st_new = {"id": "new", "published_at": "2026-10-05T10:00:00Z"}

        self.assertGreater(story_recency_key(st_new), story_recency_key(st_mid))
        self.assertGreater(story_recency_key(st_mid), story_recency_key(st_old))

    def test_pipeline_serves_newest_stories_first(self):
        """When budget is constrained, newest stories are served first."""
        stories = [
            {"id": "st-old", "title": "Old story", "published_at": "2026-10-01T10:00:00Z", "coverage": []},
            {"id": "st-new", "title": "New story", "published_at": "2026-10-05T10:00:00Z", "coverage": []},
            {"id": "st-mid", "title": "Mid story", "published_at": "2026-10-03T10:00:00Z", "coverage": []},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"

            # Set budget to allow exactly ONE image (budget=200 neurons, each image is 172.8 neurons)
            ledger = AIImageLedger(ledger_path=ledger_file, daily_budget=200.0)
            ledger.save()

            called_stories = []
            b64_img = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")

            def mock_ai_transport(url, headers, data):
                called_stories.append(url)
                return 200, "application/json", json.dumps({"result": {"image": b64_img}}).encode("utf-8")

            resolve_images_for_stories(
                stories,
                cache_path=cache_file,
                ledger_path=ledger_file,
                site_root=site_dir,
                transport=lambda u: b"",
                ai_transport=mock_ai_transport,
            )

            # Exactly one image was generated under the budget
            self.assertEqual(len(called_stories), 1)

            by_id = {s["id"]: s for s in stories}
            # The newest story (st-new) MUST be the one that received the image!
            self.assertIn("image", by_id["st-new"], "Newest story must be served first")
            self.assertEqual(by_id["st-new"]["image"]["via"], "ai")

            # Older stories (st-mid and st-old) stay without image (falling back to cover)
            self.assertNotIn("image", by_id["st-mid"], "Mid story should not receive image due to budget")
            self.assertNotIn("image", by_id["st-old"], "Old story should not receive image due to budget")


class AIImageStopOn429Tests(InsideWindowTestCase):
    def test_stop_on_429_activates_circuit_breaker(self):
        """When Cloudflare API returns 429, the provider halts for the day and falls back to cover."""
        story = {"id": "st-429", "title": "Large model training methodology", "kind": "paper"}
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"
            ledger = AIImageLedger(ledger_path=ledger_file)

            calls = []

            def mock_429_transport(url, headers, data):
                calls.append((url, headers, data))
                return 429, "application/json", b'{"success":false,"errors":[{"message":"Rate limit exceeded"}]}'

            res = generate_ai_illustration(
                story,
                site_root=site_dir,
                ledger=ledger,
                account_id="acc-123",
                api_token="tok-abc",
                transport=mock_429_transport,
            )
            # Generation failed
            self.assertIsNone(res)
            self.assertEqual(len(calls), 1)

            # Ledger now records stopped status for today
            day = ledger.get_day()
            self.assertTrue(day["stopped"])
            self.assertIn("429", day["stop_reason"])

            # Subsequent call on the same day is short-circuited with 0 calls
            story2 = {"id": "st-429-second", "title": "Another paper", "kind": "paper"}
            res2 = generate_ai_illustration(
                story2,
                site_root=site_dir,
                ledger=ledger,
                account_id="acc-123",
                api_token="tok-abc",
                transport=mock_429_transport,
            )
            self.assertIsNone(res2)
            self.assertEqual(len(calls), 1)  # No second call was made!


class AIImageOncePerStoryTests(InsideWindowTestCase):
    def test_once_per_story_caches_and_reuses_image(self):
        """Each story is generated at most once; subsequent runs reuse the disk file with zero calls."""
        story = {"id": "st-once-1", "title": "Quantum algorithms and error correction", "kind": "paper"}
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"
            cache_file = Path(tmpdir) / "image-cache.json"

            calls = []
            b64_img = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")

            def mock_success_transport(url, headers, data):
                calls.append(url)
                resp = json.dumps({"result": {"image": b64_img}, "success": True}).encode("utf-8")
                return 200, "application/json", resp

            ledger = AIImageLedger(ledger_path=ledger_file)
            cache = ImageCache(cache_path=cache_file)

            # Run 1: Generates image
            res1 = generate_ai_illustration(
                story,
                site_root=site_dir,
                ledger=ledger,
                account_id="acc-123",
                api_token="tok-abc",
                transport=mock_success_transport,
            )
            self.assertIsNotNone(res1)
            self.assertEqual(res1["via"], "ai")
            self.assertEqual(res1["kind"], "photo")
            self.assertEqual(res1["src"], "assets/ai/st-once-1.jpg")
            self.assertEqual(len(calls), 1)
            self.assertEqual(ledger.get_day()["count"], 1)

            # File exists on disk
            img_file = site_dir / "assets" / "ai" / "st-once-1.jpg"
            self.assertTrue(img_file.is_file())
            self.assertEqual(img_file.read_bytes(), VALID_JPEG_BYTES)

            # Run 2: Reuses the disk file without calling the API
            res2 = generate_ai_illustration(
                story,
                site_root=site_dir,
                ledger=ledger,
                account_id="acc-123",
                api_token="tok-abc",
                transport=mock_success_transport,
            )
            self.assertIsNotNone(res2)
            self.assertEqual(res2["src"], "assets/ai/st-once-1.jpg")
            self.assertEqual(len(calls), 1)  # Still 1 call, zero new network requests!
            self.assertEqual(ledger.get_day()["count"], 1)  # Count did not increment again


class AIImagePromptRulesTests(unittest.TestCase):
    def test_prompt_has_no_brand_or_person_terms(self):
        """Prompt filters out all brand names, product terms, and prominent person names."""
        test_titles = [
            "OpenAI CEO Sam Altman announces GPT-5 partnership with Microsoft and Apple",
            "Elon Musk reveals xAI Grok 3 infrastructure details on Twitter",
            "Google DeepMind Demis Hassabis and Yann LeCun discuss Meta Llama 4",
            "NVIDIA Jensen Huang shows new GPU cluster for Anthropic Claude 3.5 Sonnet",
            "Hugging Face and GitHub collaborate with DeepSeek and Mistral AI",
        ]

        forbidden_terms = [
            "Sam Altman", "Altman", "Elon Musk", "Musk", "Demis Hassabis", "Yann LeCun", "Jensen Huang",
            "OpenAI", "ChatGPT", "GPT-5", "Microsoft", "Apple", "xAI", "Grok", "Google", "DeepMind",
            "Meta", "Llama", "NVIDIA", "Anthropic", "Claude", "Hugging Face", "GitHub", "DeepSeek",
            "Mistral", "Twitter",
        ]

        for title in test_titles:
            prompt = build_ai_prompt(title, kind="model")

            # Check that prompt begins with abstract editorial illustration
            self.assertTrue(prompt.startswith("Abstract editorial digital illustration"))

            # Check negative prompt guardrails
            self.assertIn("No people", prompt)
            self.assertIn("no human faces", prompt)
            self.assertIn("no text", prompt)
            self.assertIn("no logos", prompt)
            self.assertIn("no brand marks", prompt)

            # Check that no forbidden brand or person term appears (word boundary check)
            for forbidden in forbidden_terms:
                pattern = r"\b" + re.escape(forbidden.lower()) + r"\b"
                self.assertIsNone(
                    re.search(pattern, prompt.lower()),
                    f"Forbidden term '{forbidden}' found in prompt: '{prompt}'"
                )

    def test_clean_topic_extraction(self):
        """Sanitizer extracts meaningful abstract topic from messy titles."""
        topic = sanitize_topic_text("OpenAI GPT-4o voice latency benchmark report")
        self.assertNotIn("openai", topic.lower())
        self.assertNotIn("gpt", topic.lower())
        self.assertTrue(any(w in topic for w in ["voice", "latency", "benchmark"]))


class AIImagePageLabelTests(unittest.TestCase):
    def test_the_label_on_the_page(self):
        """The page shows a small 'Ảnh minh hoạ do AI tạo' label on AI cards."""
        feed_js_path = Path(__file__).resolve().parent.parent / "site" / "feed.js"
        feed_css_path = Path(__file__).resolve().parent.parent / "site" / "feed.css"

        self.assertTrue(feed_js_path.is_file())
        self.assertTrue(feed_css_path.is_file())

        feed_js = feed_js_path.read_text(encoding="utf-8")
        feed_css = feed_css_path.read_text(encoding="utf-8")

        # Check that feed.js defines the exact label text
        self.assertIn("Ảnh minh hoạ do AI tạo", feed_js)
        self.assertIn("ai-badge", feed_js)

        # Check that feed.js handles via === 'ai'
        self.assertIn("img.via === 'ai'", feed_js)

        # Check that feed.css defines the .ai-badge style
        self.assertIn(".ai-badge", feed_css)
        self.assertIn("backdrop-filter", feed_css)


class AIImagePipelineIntegrationTests(InsideWindowTestCase):
    def test_pipeline_illustrates_rejected_preview_card_and_missing_image(self):
        """Rejected repository previews enter the same budgeted fallback as missing images."""
        stories = [
            {
                "id": "st-with-source",
                "url": "https://github.com/facebookresearch/llama",
                "coverage": [],
            },
            {
                "id": "st-without-source",
                "url": "https://example.com/no-source-image",
                "coverage": [],
                "title": "Novel algorithmic discovery in transformer architecture",
                "kind": "model",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"

            calls = []
            b64_img = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")

            def mock_ai_transport(url, headers, data):
                calls.append(url)
                return 200, "application/json", json.dumps({"result": {"image": b64_img}}).encode("utf-8")

            # Source mock transport validates github-social image bytes
            def mock_source_transport(url):
                if "opengraph.githubassets.com" in url:
                    return b"\xff\xd8\xff\xe0"
                return b""

            resolve_images_for_stories(
                stories,
                cache_path=cache_file,
                ledger_path=ledger_file,
                site_root=site_dir,
                transport=mock_source_transport,
                ai_transport=mock_ai_transport,
            )

            # The repository preview is available but unsuitable as an editorial lead.
            self.assertIn("image", stories[0])
            self.assertEqual(stories[0]["image"]["via"], "ai")

            # Story 2 resolved via AI illustration
            self.assertIn("image", stories[1])
            self.assertEqual(stories[1]["image"]["via"], "ai")
            self.assertEqual(stories[1]["image"]["src"], "assets/ai/st-without-source.jpg")
            self.assertEqual(len(calls), 2)

            # File is stored on disk under site/assets/ai/
            generated_file = site_dir / "assets" / "ai" / "st-without-source.jpg"
            self.assertTrue(generated_file.is_file())
            self.assertEqual(generated_file.read_bytes(), VALID_JPEG_BYTES)

            # Run 2: Re-run with the same cache and disk
            stories_rerun = [
                {
                    "id": "st-without-source",
                    "url": "https://example.com/no-source-image",
                    "coverage": [],
                    "title": "Novel algorithmic discovery in transformer architecture",
                    "kind": "model",
                }
            ]
            resolve_images_for_stories(
                stories_rerun,
                cache_path=cache_file,
                ledger_path=ledger_file,
                site_root=site_dir,
                transport=mock_source_transport,
                ai_transport=mock_ai_transport,
            )
            # Reused without calling AI transport again
            self.assertIn("image", stories_rerun[0])
            self.assertEqual(stories_rerun[0]["image"]["via"], "ai")
            self.assertEqual(len(calls), 2)

    def test_pipeline_ai_stops_when_ledger_capped(self):
        """When ledger daily cap is hit, stories without source images fall back to cover (no image)."""
        stories = [
            {"id": "st-capped", "title": "Some paper", "kind": "paper", "coverage": []}
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"

            # Pre-cap the ledger
            ledger = AIImageLedger(ledger_path=ledger_file, daily_cap=1)
            ledger.record_generation("pre-existing-story")
            self.assertTrue(ledger.get_day()["stopped"])

            resolve_images_for_stories(
                stories,
                cache_path=cache_file,
                ledger_path=ledger_file,
                site_root=site_dir,
                transport=lambda u: b"",
                ai_transport=lambda u, h, d: (200, "application/json", b"{}"),
            )
            # No image attached; card falls back to cover
            self.assertNotIn("image", stories[0])

    def test_pipeline_ai_stops_on_429(self):
        """When AI transport returns 429, pipeline stops AI generation and subsequent stories stay without image."""
        stories = [
            {"id": "st-fail-429", "title": "Paper 1", "kind": "paper", "coverage": []},
            {"id": "st-skip-after-429", "title": "Paper 2", "kind": "paper", "coverage": []},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            site_dir = Path(tmpdir) / "site"

            calls = []

            def mock_ai_429(u, h, d):
                calls.append(u)
                return 429, "application/json", b'{"error": "rate limit"}'

            resolve_images_for_stories(
                stories,
                cache_path=cache_file,
                ledger_path=ledger_file,
                site_root=site_dir,
                transport=lambda u: b"",
                ai_transport=mock_ai_429,
            )
            # Both stories fall back to cover (no image)
            self.assertNotIn("image", stories[0])
            self.assertNotIn("image", stories[1])
            # Only 1 call was made because 429 stopped the provider for the day
            self.assertEqual(len(calls), 1)


def _jpeg_transport(calls, status=200):
    """Offline transport that records each request; status != 200 simulates failed requests."""
    b64 = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")

    def transport(url, headers, data):
        calls.append(url)
        if status != 200:
            return status, "application/json", b'{"errors":[{"message":"server error"}]}'
        return 200, "application/json", json.dumps({"result": {"image": b64}}).encode("utf-8")

    return transport


def _simulate_run(tmpdir, tag, run_now, stories=40, status=200, daily_budget=None):
    """One workflow run that lost everything: empty ledger, empty image cache, fresh process budget.

    Returns the neurons requested by that run (requests sent * cost of one image).
    """
    calls = []
    ledger_kwargs = {} if daily_budget is None else {"daily_budget": daily_budget}
    ledger = AIImageLedger(ledger_path=Path(tmpdir) / f"{tag}-ledger.json", **ledger_kwargs)
    site_dir = Path(tmpdir) / f"{tag}-site"
    run_budget = RunBudget()
    transport = _jpeg_transport(calls, status=status)
    for i in range(stories):
        generate_ai_illustration(
            {"id": f"story-{i}", "title": "Advanced reasoning methods", "kind": "paper"},
            site_root=site_dir,
            ledger=ledger,
            account_id="acc",
            api_token="tok",
            transport=transport,
            now=run_now,
            run_budget=run_budget,
        )
    return len(calls) * compute_neuron_cost()


class AIImageGenerationWindowTests(InsideWindowTestCase):
    def test_window_and_budget_are_named_constants_that_fit_the_daily_budget(self):
        self.assertIsInstance(GENERATION_WINDOW_UTC_HOUR, int)
        self.assertTrue(0 <= GENERATION_WINDOW_UTC_HOUR <= 23)
        self.assertLessEqual(PER_RUN_NEURON_BUDGET * ASSUMED_MAX_RUNS_IN_WINDOW, DAILY_NEURON_BUDGET)

    def test_window_is_one_utc_hour_and_honours_time_zones(self):
        self.assertTrue(generation_window_open(IN_WINDOW))
        self.assertTrue(generation_window_open(IN_WINDOW.replace(minute=0, second=0)))
        self.assertTrue(generation_window_open(IN_WINDOW.replace(minute=59, second=59)))
        self.assertFalse(generation_window_open(IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR - 1, minute=59, second=59)))
        self.assertFalse(generation_window_open(IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 1, minute=0, second=0)))
        # 09:30 at UTC+7 is 02:30 UTC (inside); 02:30 at UTC+7 is 19:30 UTC the day before (outside)
        plus7 = timezone(timedelta(hours=7))
        self.assertTrue(generation_window_open(datetime(2026, 10, 6, 9, 30, tzinfo=plus7)))
        self.assertFalse(generation_window_open(datetime(2026, 10, 6, 2, 30, tzinfo=plus7)))

    def test_no_generation_outside_the_window(self):
        """Every other hour of the day, and the second either side of the window, sends nothing."""
        moments = [IN_WINDOW.replace(hour=h, minute=30) for h in range(24) if h != GENERATION_WINDOW_UTC_HOUR]
        moments += [
            IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR - 1, minute=59, second=59),
            IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 1, minute=0, second=0),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, moment in enumerate(moments):
                calls = []
                ledger = AIImageLedger(ledger_path=Path(tmpdir) / f"ledger-{index}.json")
                site_dir = Path(tmpdir) / f"site-{index}"
                res = generate_ai_illustration(
                    {"id": f"out-{index}", "title": "Some paper", "kind": "paper"},
                    site_root=site_dir,
                    ledger=ledger,
                    account_id="acc",
                    api_token="tok",
                    transport=_jpeg_transport(calls),
                    now=moment,
                    run_budget=RunBudget(),
                )
                self.assertIsNone(res, f"generated outside the window at {moment.isoformat()}")
                self.assertEqual(calls, [], f"request sent outside the window at {moment.isoformat()}")
                self.assertFalse((site_dir / "assets" / "ai").exists())
                # a closed window must not poison the day record with a 'stopped' flag
                self.assertFalse(ledger.get_day(moment)["stopped"])

    def test_no_generation_outside_the_window_when_now_is_the_real_clock(self):
        """The default (now=None) path reads the clock seam; outside the hour nothing is sent."""
        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 5)
        calls = []
        with tempfile.TemporaryDirectory() as tmpdir, patch("radar.ai_images._utc_now", return_value=outside):
            res = generate_ai_illustration(
                {"id": "st-clock", "title": "Some paper", "kind": "paper"},
                site_root=Path(tmpdir) / "site",
                ledger_path=Path(tmpdir) / "ledger.json",
                account_id="acc",
                api_token="tok",
                transport=_jpeg_transport(calls),
            )
        self.assertIsNone(res)
        self.assertEqual(calls, [])

    def test_pipeline_sends_nothing_outside_the_window(self):
        stories = [{"id": f"st-pipe-{i}", "title": "A paper", "kind": "paper", "coverage": []} for i in range(5)]
        calls = []
        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 5)
        with tempfile.TemporaryDirectory() as tmpdir, patch("radar.ai_images._utc_now", return_value=outside):
            resolve_images_for_stories(
                stories,
                cache_path=Path(tmpdir) / "image-cache.json",
                ledger_path=Path(tmpdir) / "ledger.json",
                site_root=Path(tmpdir) / "site",
                transport=lambda u: b"",
                ai_transport=_jpeg_transport(calls),
            )
        self.assertEqual(calls, [])
        self.assertTrue(all("image" not in st for st in stories))

    def test_reusing_an_existing_image_is_free_outside_the_window(self):
        """Already-generated files keep being served at any hour with zero requests."""
        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 5)
        calls = []
        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            (site_dir / "assets" / "ai").mkdir(parents=True)
            (site_dir / "assets" / "ai" / "st-have.jpg").write_bytes(VALID_JPEG_BYTES)
            res = generate_ai_illustration(
                {"id": "st-have", "title": "Some paper", "kind": "paper"},
                site_root=site_dir,
                ledger_path=Path(tmpdir) / "ledger.json",
                transport=_jpeg_transport(calls),
                now=outside,
                run_budget=RunBudget(),
            )
        self.assertEqual(res["src"], "assets/ai/st-have.jpg")
        self.assertEqual(calls, [])


class AIImagePerRunBudgetTests(InsideWindowTestCase):
    def test_per_run_spend_stops_at_the_per_run_budget_even_when_the_ledger_would_allow_more(self):
        cost = compute_neuron_cost()
        expected_images = int(PER_RUN_NEURON_BUDGET // cost)
        self.assertGreaterEqual(expected_images, 1)
        calls = []
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = AIImageLedger(ledger_path=Path(tmpdir) / "ledger.json", daily_budget=1_000_000.0)
            run_budget = RunBudget()
            produced = 0
            for i in range(50):
                res = generate_ai_illustration(
                    {"id": f"st-run-{i}", "title": "A paper", "kind": "paper"},
                    site_root=Path(tmpdir) / "site",
                    ledger=ledger,
                    account_id="acc",
                    api_token="tok",
                    transport=_jpeg_transport(calls),
                    now=IN_WINDOW,
                    run_budget=run_budget,
                )
                produced += 1 if res else 0
        self.assertEqual(len(calls), expected_images)
        self.assertEqual(produced, expected_images)
        self.assertLessEqual(run_budget.spent, PER_RUN_NEURON_BUDGET)
        self.assertLessEqual(len(calls) * cost, PER_RUN_NEURON_BUDGET)

    def test_failed_requests_still_count_against_the_run(self):
        """A response we cannot use may still be billed, so it spends the run's budget too."""
        cost = compute_neuron_cost()
        with tempfile.TemporaryDirectory() as tmpdir:
            neurons = _simulate_run(tmpdir, "failing", IN_WINDOW, status=500, daily_budget=1_000_000.0)
        self.assertLessEqual(neurons, PER_RUN_NEURON_BUDGET)
        self.assertEqual(neurons, int(PER_RUN_NEURON_BUDGET // cost) * cost)

    def test_run_budget_refuses_without_reserving_when_the_next_request_does_not_fit(self):
        budget = RunBudget(budget=300.0)
        self.assertTrue(budget.try_reserve(172.8))
        self.assertFalse(budget.try_reserve(172.8))
        self.assertEqual(budget.spent, 172.8)
        self.assertTrue(budget.try_reserve(100.0))

    def test_default_budget_is_shared_by_the_whole_process(self):
        """The pipeline passes no budget: two passes in one run still share one per-run budget."""
        cost = compute_neuron_cost()
        expected_images = int(PER_RUN_NEURON_BUDGET // cost)
        calls = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for batch in range(2):
                stories = [
                    {"id": f"st-shared-{batch}-{i}", "title": "A paper", "kind": "paper", "coverage": []}
                    for i in range(10)
                ]
                resolve_images_for_stories(
                    stories,
                    cache_path=Path(tmpdir) / "image-cache.json",
                    ledger_path=Path(tmpdir) / "ledger.json",
                    site_root=Path(tmpdir) / "site",
                    transport=lambda u: b"",
                    ai_transport=_jpeg_transport(calls),
                )
        self.assertEqual(len(calls), expected_images)


class AIImageLostLedgerDailyBoundTests(InsideWindowTestCase):
    """The day stays at or under 8,000 neurons when the ledger and image cache are lost on every run."""

    @staticmethod
    def _starts_in_one_utc_day():
        """Every scheduled start: GitHub cron 7,37 and the scheduler/ cron */20 (:00,:20,:40)."""
        day = datetime(2026, 10, 6, tzinfo=timezone.utc)
        return [
            day + timedelta(hours=hour, minutes=minute)
            for hour in range(24)
            for minute in (0, 7, 20, 37, 40)
        ]

    def _extra_runs_in_window(self):
        """Runs beyond the schedule that can generate in the window.

        1 scheduled start delayed in from the previous hour, 1 run started before the
        window and still running into it (the concurrency group serialises runs, so one),
        and 3 manual dispatches or re-runs.
        """
        base = datetime(2026, 10, 6, GENERATION_WINDOW_UTC_HOUR, tzinfo=timezone.utc)
        delayed = base + timedelta(minutes=6)
        straddler = base + timedelta(minutes=5)
        manual = [base + timedelta(minutes=m) for m in (10, 25, 55)]
        return [delayed, straddler] + manual

    def test_runs_that_can_generate_in_one_day_never_exceed_the_assumed_run_count(self):
        window_moments = [
            m for m in self._starts_in_one_utc_day() + self._extra_runs_in_window()
            if generation_window_open(m)
        ]
        self.assertEqual(len(window_moments), ASSUMED_MAX_RUNS_IN_WINDOW)

    def test_empty_ledger_on_every_run_stays_at_or_under_8000_neurons_per_utc_day(self):
        moments = self._starts_in_one_utc_day() + self._extra_runs_in_window()
        total = 0.0
        spending_runs = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, moment in enumerate(moments):
                spent = _simulate_run(tmpdir, f"run-{index}", moment)
                self.assertLessEqual(spent, PER_RUN_NEURON_BUDGET)
                total += spent
                spending_runs += 1 if spent else 0
        self.assertLessEqual(round(total, 4), DAILY_NEURON_BUDGET)
        self.assertGreater(total, 0.0, "the window must still allow generation")
        self.assertEqual(spending_runs, ASSUMED_MAX_RUNS_IN_WINDOW)

    def test_one_run_more_than_assumed_still_fits_the_daily_budget(self):
        """Margin: whole images (691.20 per run) leave room beyond the assumed run count."""
        moments = self._starts_in_one_utc_day() + self._extra_runs_in_window()
        moments.append(datetime(2026, 10, 6, GENERATION_WINDOW_UTC_HOUR, 50, tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as tmpdir:
            total = sum(_simulate_run(tmpdir, f"run-{i}", m) for i, m in enumerate(moments))
        self.assertLessEqual(round(total, 4), DAILY_NEURON_BUDGET)

    def test_failing_requests_on_every_run_stay_within_the_daily_bound(self):
        moments = self._starts_in_one_utc_day() + self._extra_runs_in_window()
        with tempfile.TemporaryDirectory() as tmpdir:
            total = sum(
                _simulate_run(tmpdir, f"run-{i}", m, status=500, daily_budget=1_000_000.0)
                for i, m in enumerate(moments)
            )
        self.assertLessEqual(round(total, 4), DAILY_NEURON_BUDGET)


class AIImageSummaryLoggingTests(InsideWindowTestCase):
    def test_summary_line_for_success(self):
        """Build summary line reports window open, considered, generated count, reused, and skipped."""
        stories = [
            {"id": "st-log-success", "title": "Model scaling advances", "kind": "model", "coverage": []}
        ]
        calls = []
        b64_img = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")

        def mock_ai(url, headers, data):
            calls.append(url)
            return 200, "application/json", json.dumps({"result": {"image": b64_img}}).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            cache_file = Path(tmpdir) / "cache.json"
            ledger_file = Path(tmpdir) / "ledger.json"

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                resolve_images_for_stories(
                    stories,
                    cache_path=cache_file,
                    ledger_path=ledger_file,
                    site_root=site_dir,
                    transport=lambda u: b"",
                    ai_transport=mock_ai,
                    now=IN_WINDOW,
                )
            output = buf.getvalue()

            self.assertIn("AI images: window open, 1 considered, 1 generated, 0 reused, 0 skipped", output)
            self.assertEqual(len(calls), 1)

    def test_summary_line_for_4xx_response(self):
        """Build summary line reports HTTP status and error message on 4xx failure."""
        stories = [
            {"id": "st-log-4xx", "title": "Paper on neural search", "kind": "paper", "coverage": []}
        ]
        calls = []

        def mock_ai_401(url, headers, data):
            calls.append(url)
            err_json = {"success": False, "errors": [{"code": 1000, "message": "Authentication error"}]}
            return 401, "application/json", json.dumps(err_json).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            cache_file = Path(tmpdir) / "cache.json"
            ledger_file = Path(tmpdir) / "ledger.json"

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                resolve_images_for_stories(
                    stories,
                    cache_path=cache_file,
                    ledger_path=ledger_file,
                    site_root=site_dir,
                    transport=lambda u: b"",
                    ai_transport=mock_ai_401,
                    now=IN_WINDOW,
                )
            output = buf.getvalue()

            self.assertIn("AI images: window open, 1 considered, 0 generated, 0 reused, 1 skipped", output)
            self.assertIn("HTTP 401: code 1000: Authentication error", output)
            self.assertEqual(len(calls), 1)

    def test_summary_line_for_closed_window(self):
        """Build summary line reports window closed and skips without making network requests."""
        stories = [
            {"id": "st-log-closed", "title": "Closed window story", "kind": "model", "coverage": []}
        ]
        calls = []
        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 5)

        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            cache_file = Path(tmpdir) / "cache.json"
            ledger_file = Path(tmpdir) / "ledger.json"

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                resolve_images_for_stories(
                    stories,
                    cache_path=cache_file,
                    ledger_path=ledger_file,
                    site_root=site_dir,
                    transport=lambda u: b"",
                    ai_transport=lambda u, h, d: calls.append(u),
                    now=outside,
                )
            output = buf.getvalue()

            self.assertIn("AI images: window closed, 1 considered, 0 generated, 0 reused, 1 skipped (window closed)", output)
            self.assertEqual(len(calls), 0)

    def test_summary_line_reused_from_disk(self):
        """Build summary line correctly counts images reused from disk."""
        stories = [
            {"id": "st-reused", "title": "Reused story", "kind": "model", "coverage": []}
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            site_dir = Path(tmpdir) / "site"
            ai_dir = site_dir / "assets" / "ai"
            ai_dir.mkdir(parents=True)
            (ai_dir / "st-reused.jpg").write_bytes(VALID_JPEG_BYTES)

            cache_file = Path(tmpdir) / "cache.json"
            ledger_file = Path(tmpdir) / "ledger.json"

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                resolve_images_for_stories(
                    stories,
                    cache_path=cache_file,
                    ledger_path=ledger_file,
                    site_root=site_dir,
                    transport=lambda u: b"",
                    ai_transport=None,
                    now=IN_WINDOW,
                )
            output = buf.getvalue()

            self.assertIn("AI images: window open, 1 considered, 0 generated, 1 reused, 0 skipped", output)


class AIImageProbeTests(unittest.TestCase):
    def test_probe_makes_one_request_and_no_more(self):
        """Probe makes exactly one request outside the window and prints status, bytes, cost."""
        calls = []
        b64_img = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")

        def mock_ai(url, headers, data):
            calls.append((url, headers, data))
            return 200, "application/json", json.dumps({"result": {"image": b64_img}}).encode("utf-8")

        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 6)
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = probe(
                    ledger_path=ledger_file,
                    account_id="acc-test-123",
                    api_token="tok-test-456",
                    transport=mock_ai,
                    now=outside,
                )
            output = buf.getvalue()

            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("AI image probe: HTTP 200", output)
            self.assertIn("1024x1024", output)
            self.assertIn(f"{len(VALID_JPEG_BYTES)} bytes received", output)
            self.assertIn("172.8 neurons spent", output)

            # Ledger recorded the spend
            ledger = AIImageLedger(ledger_path=ledger_file)
            self.assertAlmostEqual(ledger.get_day(outside)["neurons_spent"], 172.80, places=2)
            self.assertEqual(ledger.get_day(outside)["count"], 1)

    def test_probe_prints_measured_dimensions_for_png(self):
        """Probe prints measured dimensions when response is PNG."""
        calls = []

        def mock_ai(url, headers, data):
            calls.append((url, headers, data))
            return 200, "image/png", VALID_PNG_BYTES

        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 6)
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = probe(
                    ledger_path=ledger_file,
                    account_id="acc-test-123",
                    api_token="tok-test-456",
                    transport=mock_ai,
                    now=outside,
                )
            output = buf.getvalue()

            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("AI image probe: HTTP 200, 1024x1024", output)
            self.assertIn(f"{len(VALID_PNG_BYTES)} bytes received", output)
            self.assertIn("172.8 neurons spent", output)

    def test_probe_refuses_when_ledger_day_is_stopped(self):
        """Probe refuses without calling API when ledger day is marked stopped."""
        calls = []
        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 6)
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            ledger = AIImageLedger(ledger_path=ledger_file)
            ledger.record_stop("HTTP 429 Too Many Requests (rate limit or daily quota)", now=outside)

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = probe(
                    ledger_path=ledger_file,
                    account_id="acc-test-123",
                    api_token="tok-test-456",
                    transport=lambda u, h, d: calls.append(u),
                    now=outside,
                )
            output = buf.getvalue()

            self.assertEqual(code, 1)
            self.assertEqual(len(calls), 0)
            self.assertIn("AI image probe: refused (stopped_for_day: HTTP 429 Too Many Requests", output)
            self.assertIn("0 bytes received, 0.0 neurons spent", output)

    def test_probe_refuses_when_ledger_day_is_over_budget(self):
        """Probe refuses without calling API when ledger day has exhausted 8,000 neurons."""
        calls = []
        outside = IN_WINDOW.replace(hour=GENERATION_WINDOW_UTC_HOUR + 6)
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            ledger = AIImageLedger(ledger_path=ledger_file, daily_budget=8000.0)
            # Pre-spend budget
            day = ledger.get_day(outside)
            day["neurons_spent"] = 7950.0  # +172.8 would exceed 8000.0
            ledger.save()

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = probe(
                    ledger_path=ledger_file,
                    account_id="acc-test-123",
                    api_token="tok-test-456",
                    transport=lambda u, h, d: calls.append(u),
                    now=outside,
                )
            output = buf.getvalue()

            self.assertEqual(code, 1)
            self.assertEqual(len(calls), 0)
            self.assertIn("AI image probe: refused (daily_budget_exceeded)", output)
            self.assertIn("0 bytes received, 0.0 neurons spent", output)

    def test_no_secret_appears_in_any_printed_output(self):
        """Tokens, account IDs, and sensitive URLs are never printed in logs or probe output."""
        sensitive_acc = "cf-sensitive-acc-id-998877"
        sensitive_tok = "cf-sensitive-secret-token-112233"

        calls = []
        def mock_error_transport(url, headers, data):
            calls.append(url)
            # Response containing account ID and token in payload / URL
            body = (
                f'{{"success": false, "errors": [{{"code": 1000, "message": "Failed on {sensitive_acc}"}}], '
                f'"auth": "{sensitive_tok}"}}'
            ).encode("utf-8")
            return 401, "application/json", body

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = probe(
                    ledger_path=ledger_file,
                    account_id=sensitive_acc,
                    api_token=sensitive_tok,
                    transport=mock_error_transport,
                )
            output = buf.getvalue()

            self.assertEqual(code, 1)
            self.assertNotIn(sensitive_acc, output)
            self.assertNotIn(sensitive_tok, output)
            self.assertIn("[REDACTED]", output)

    def test_missing_credentials_prints_variable_names_only(self):
        """When credentials are absent, only the environment variable names are printed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "ai-ledger.json"
            buf = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(buf):
                code = probe(ledger_path=ledger_file, transport=None)
            output = buf.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("CLOUDFLARE_ACCOUNT_ID", output)
            self.assertIn("CLOUDFLARE_AI_API_TOKEN", output)
            self.assertIn("refused (missing CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AI_API_TOKEN)", output)


if __name__ == "__main__":
    unittest.main()

