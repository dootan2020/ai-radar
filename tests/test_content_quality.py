"""Offline content-policy contracts; synthetic pixels are not a precision sample."""

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

from radar import assembly, image_quality, images, site_payload, translate, x_collector
from radar.headlines import annotate_headlines, compact_headline

ROOT = Path(__file__).parent
PIXELS = (ROOT / "fixtures" / "continuous-tone.png").read_bytes()
HAS_PILLOW = importlib.util.find_spec("PIL") is not None


class HeadlineTests(unittest.TestCase):
    def test_extracts_complete_sentence_without_rewriting_claims(self):
        sentence = "OpenAI releases GPT-5.2 for developers today."
        self.assertEqual(compact_headline(sentence + " More details follow." * 15), sentence)

    def test_word_boundary_limit_and_short_title(self):
        self.assertEqual(compact_headline("GPT-5.2 launch"), "GPT-5.2 launch")
        value = compact_headline("Mô hình AI mới " * 30)
        self.assertLessEqual(len(value), 140)
        self.assertTrue(value.endswith("…"))
        self.assertIn(value[:-1], "Mô hình AI mới " * 30)
        self.assertEqual(len(compact_headline("x" * 200)), 140)
        self.assertLessEqual(len(compact_headline("Word " * 27 + "word. More details.")), 140)

    def test_originals_translation_and_worth_are_unchanged(self):
        story = {"title": "AI report " * 30, "title_vi": "Báo cáo AI " * 30,
                 "summary": "A different subject.", "worth_score": 45,
                 "worth_why": "Two sources", "coverage": [{"title": "Another AI report " * 20}]}
        before = deepcopy(story)
        annotate_headlines(story)
        for key in ("title", "title_vi", "summary", "worth_score", "worth_why"):
            self.assertEqual(story[key], before[key])
        self.assertLessEqual(len(story["headline_vi"]), 140)
        self.assertLessEqual(len(story["coverage"][0]["headline"]), 140)
        first = deepcopy(story)
        annotate_headlines(story)
        self.assertEqual(story, first)

    def test_writer_refreshes_reader_headlines_without_mutating_evidence(self):
        story = {"id": "s", "title": "An AI report " * 20, "coverage": []}
        data = {"stories": [story], "sections": {"today": ["s"]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "radar.json"
            site_payload.write_site_snapshot(data, path)
            story["title_vi"] = "Báo cáo về trí tuệ nhân tạo " * 15
            site_payload.write_site_snapshot(data, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)
            self.assertNotIn("headline", story)
            for file in (site_payload.page_path(path), site_payload.head_path(path)):
                written = json.loads(file.read_text(encoding="utf-8"))["stories"][0]
                self.assertEqual(written["title_vi"], story["title_vi"])
                self.assertEqual(written["headline_vi"], compact_headline(story["title_vi"]))

    def test_translation_cli_refreshes_full_snapshot_after_translator_returns(self):
        title_vi = "Báo cáo nghiên cứu AI mới " * 20
        def translated(payload, *args, **kwargs):
            payload["stories"][0]["title_vi"] = title_vi
            return {"status": "ok"}, False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "radar.json"
            path.write_text(json.dumps({"stories": [{"id": "s", "title": "AI research " * 20,
                                                    "headline_vi": "Stale", "coverage": []}]}), encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True), patch("radar.translation_pipeline.translate_payload", side_effect=translated):
                translate.main(["--input", str(path), "--cache", str(root / "translations.json")])
            story = json.loads(path.read_text(encoding="utf-8"))["stories"][0]
            self.assertEqual(story["title_vi"], title_vi)
            self.assertEqual(story["headline_vi"], compact_headline(title_vi))


class ReplyTests(unittest.TestCase):
    def test_parser_rejects_replies_even_if_search_filter_leaks(self):
        account = {"id": "1", "handle": "writer", "name": "Writer", "entity": "writer"}
        base = {"id": "1234", "author_id": "1", "text": "AI release is available today"}
        posts = [dict(base, referenced_tweets=[{"type": "replied_to", "id": "100"}]),
                 dict(base, in_reply_to_user_id="2"), dict(base, text="@reader AI release is available today"),
                 dict(base, id="1235", referenced_tweets=[{"type": "quoted", "id": "100"}]),
                 dict(base, id="1236", text="AI news from @writer today")]
        parsed = x_collector.parse_search(json.dumps({"data": posts}), [account], datetime.now(timezone.utc))
        self.assertEqual([item["post_id"] for item in parsed], ["1235", "1236"])
        self.assertEqual(parsed[0]["quoted_post_id"], "100")

    def test_retained_reply_removed_but_other_coverage_survives(self):
        reply = {"id": "reply", "source": "x-writer", "title": "@someone AI response", "url": "https://x.com/writer/status/123"}
        article = {"id": "article", "source": "press", "publisher": "press", "title": "AI news",
                   "title_vi": "Tin AI", "url": "https://press.example/news"}
        mixed = {"id": "stable", "title": reply["title"], "title_vi": "@someone Trả lời",
                 "url": reply["url"], "coverage": [reply, article], "source_count": 2,
                 "image": {"src": "old.jpg"}, "aliases": ["old"]}
        before = deepcopy(mixed)
        result = x_collector.without_reply_stories([mixed, dict(mixed, coverage=[reply])])
        self.assertEqual(mixed, before)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "stable")
        self.assertEqual(result[0]["title_vi"], "Tin AI")
        self.assertEqual(result[0]["source_count"], 1)
        self.assertNotIn("image", result[0])
        self.assertEqual(result[0]["aliases"], ["old"])

    def test_non_x_mentions_are_not_removed(self):
        story = {"title": "@decorator in Python AI", "coverage": [
            {"source": "press", "title": "@decorator in Python AI"}]}
        self.assertEqual(x_collector.without_reply_stories([story]), [story])

    def test_assembly_filters_fresh_and_carried_replies_before_ranking_and_sections(self):
        from tests.test_v2_support import NOW, coverage
        from radar.clustering import cluster_items
        reply = coverage("x-writer", "https://x.com/writer/status/123", title="@reader AI response")
        article = coverage("press", "https://press.example/article")
        old = {"schema_version": 2, "generated_at": NOW.isoformat(), "stories": cluster_items([reply], NOW)}
        old_before = deepcopy(old)
        with patch.dict("os.environ", {}, clear=True):
            result = assembly.finish({"sources": [], "trending": {}}, [reply, article], [], NOW, {},
                                     published=old, resolve_images=False)
        self.assertEqual(old, old_before)
        self.assertEqual(len(result["stories"]), 1)
        self.assertEqual(result["stories"][0]["coverage"][0]["source"], "press")
        self.assertIn("worth_score", result["stories"][0])
        ids = {s["id"] for s in result["stories"]}
        self.assertTrue(all(set(section) <= ids for section in result["sections"].values()))


class ImagePolicyTests(unittest.TestCase):
    def test_known_cards_and_encoded_logo_names_are_rejected_without_network(self):
        for src in ("https://opengraph.githubassets.com/1/owner/repo",
                    "https://cdn-thumbnails.huggingface.co/social-thumbnails/models/org/model.png",
                    "https://news.ycombinator.com/y18.svg",
                    "https://publisher.com/brand%2Dlogo.png",
                    "https://publisher.com/Screenshot-2026-10-01.png"):
            with self.subTest(src=src):
                self.assertFalse(images.assess_image({"src": src}, allow_network=False)["keep"])

    def test_old_seed_and_carried_images_cannot_bypass_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = {"src": "https://publisher.com/image.jpg", "via": "og:image", "verified": True}
            cache = images.ImageCache(root / "cache.json", root / "seed.json")
            cache.set("https://publisher.com/post", image)
            story = {"id": "s", "url": "https://publisher.com/post", "image": image, "coverage": []}
            self.assertIsNone(images.resolve_story_image(story, cache=cache, allow_network=False))
            with patch.dict("os.environ", {}, clear=True):
                images.resolve_images_for_stories([story], cache_path=root / "cache.json", seed_path=root / "seed.json",
                    transport=lambda _: b"not an image", ledger_path=root / "ledger.json", site_root=root,
                    now=datetime(2026, 10, 10, 10, tzinfo=timezone.utc))
            self.assertNotIn("image", story)

    def test_rejected_card_uses_cached_ai_without_a_request(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = images.ImageCache(Path(directory) / "cache.json", Path(directory) / "seed.json")
            cache.set("ai:s", {"src": "assets/ai/s.jpg", "via": "ai"})
            story = {"id": "s", "image": {"src": "https://opengraph.githubassets.com/1/o/r", "via": "github-social"}}
            result = images.resolve_story_image(story, cache=cache, allow_network=False)
            self.assertEqual(result["via"], "ai")

    def test_missing_decoder_fails_closed(self):
        with patch.dict("sys.modules", {"PIL": None}):
            self.assertEqual(image_quality.classify_pixels(PIXELS)["reason"], "decoder-unavailable")

    @unittest.skipUnless(HAS_PILLOW, "Pillow is required for pixel screening")
    def test_decode_flat_logo_text_layout_and_continuous_tone(self):
        from PIL import Image, ImageDraw, ImageFont
        self.assertTrue(image_quality.classify_pixels(PIXELS)["keep"])
        image = Image.new("RGB", (640, 360), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((200, 100, 440, 260), fill="orange")
        output = BytesIO()
        image.save(output, format="PNG")
        self.assertEqual(image_quality.classify_pixels(output.getvalue())["reason"], "flat-logo-or-text-layout")
        # Text over a continuous-tone background exercises glyph rows, not the flat-color gate.
        image = Image.open(BytesIO(PIXELS)).resize((800, 450))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=24)
        for y in range(20, 420, 40):
            draw.text((15, y), "AI NEWS Headline and repeated text on a banner", font=font, fill="white", stroke_width=1)
        output = BytesIO()
        image.save(output, format="PNG")
        self.assertEqual(image_quality.classify_pixels(output.getvalue())["reason"], "aligned-text-layout")

    @unittest.skipUnless(HAS_PILLOW, "Pillow is required for pixel screening")
    def test_quality_cache_is_versioned_and_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = images.ImageCache(root / "cache.json", root / "seed.json")
            candidate = {"src": "https://publisher.com/photo.png", "via": "feed-media"}
            result = images.assess_image(candidate, cache=cache, transport=lambda _: PIXELS)
            self.assertTrue(result["keep"])
            self.assertTrue(images.assess_image(candidate, cache=cache, allow_network=False)["keep"])
            cache.quality[candidate["src"]]["version"] = 0
            self.assertFalse(images.assess_image(candidate, cache=cache, allow_network=False)["keep"])
            cache.quality[candidate["src"]].update(version=image_quality.QUALITY_VERSION, checked_at=time.time() - images.NEGATIVE_TTL - 1)
            self.assertFalse(images.assess_image(candidate, cache=cache, allow_network=False)["keep"])

    @unittest.skipUnless(HAS_PILLOW, "Pillow is required for pixel screening")
    def test_subject_on_plain_background_and_small_tag_are_retained(self):
        for name in ("tonal-subject.png", "tagged-subject.png", "aligned-texture.png"):
            with self.subTest(fixture=name):
                result = image_quality.classify_pixels((ROOT / "fixtures" / name).read_bytes())
                self.assertTrue(result["keep"], result)

    @unittest.skipUnless(HAS_PILLOW, "Pillow is required for pixel screening")
    def test_text_cards_on_gradients_and_short_stacked_headlines_are_withheld(self):
        for name in ("gradient-text-card.png", "stacked-headline.png"):
            with self.subTest(fixture=name):
                result = image_quality.classify_pixels((ROOT / "fixtures" / name).read_bytes())
                self.assertFalse(result["keep"], result)
                self.assertEqual(result["reason"], "aligned-text-layout")

    @unittest.skipUnless(HAS_PILLOW, "Pillow is required for pixel screening")
    def test_thumbnail_panorama_and_camera_sized_subject_are_measured(self):
        from PIL import Image
        with Image.open(ROOT / "fixtures" / "tonal-subject.png") as subject:
            for size in ((128, 128), (1200, 200), (20000, 64), (5500, 3624)):
                with self.subTest(size=size):
                    output = BytesIO()
                    subject.resize(size).save(output, format="JPEG", quality=85)
                    result = image_quality.classify_pixels(output.getvalue())
                    self.assertTrue(result["keep"], result)

    @unittest.skipUnless(HAS_PILLOW, "Pillow is required for pixel screening")
    def test_invalid_truncated_and_resource_exhausting_images_are_withheld(self):
        raw = (ROOT / "fixtures" / "tonal-subject.png").read_bytes()
        for payload in (b"", b"not an image", raw[:100], b"x" * (image_quality.MAX_IMAGE_BYTES + 1)):
            self.assertFalse(image_quality.classify_pixels(payload)["keep"])
        # A valid PNG header declaring 81 megapixels must be refused before
        # allocating its raster, even when its compressed payload is small.
        header = bytearray(raw)
        header[16:24] = struct.pack(">II", 9000, 9000)
        header[29:33] = struct.pack(">I", zlib.crc32(header[12:29]))
        self.assertEqual(image_quality.classify_pixels(header)["reason"], "pixel-safety-limit")

    @unittest.skipUnless(HAS_PILLOW, "Pillow is required for pixel screening")
    def test_previous_policy_rejection_is_reinspected_before_retaining_source(self):
        raw = (ROOT / "fixtures" / "tagged-subject.png").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = images.ImageCache(root / "cache.json", root / "seed.json")
            candidate = {"src": "https://publisher.com/portrait.png", "via": "feed-media"}
            cache.quality[candidate["src"]] = dict(version=1, keep=False,
                reason="flat-logo-or-text-layout", checked_at=time.time())
            result = images.assess_image(candidate, cache=cache, transport=lambda _: raw)
            self.assertTrue(result["keep"])
            self.assertEqual(result["version"], image_quality.QUALITY_VERSION)
            self.assertTrue(images.assess_image(candidate, cache=cache, allow_network=False)["keep"])
