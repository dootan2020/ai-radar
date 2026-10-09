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
                self.assertEqual(
                    written["headline_vi"],
                    "Báo cáo về trí tuệ nhân tạo Báo cáo về trí tuệ nhân tạo Báo cáo về trí tuệ nhân tạo Báo cáo về trí tuệ nhân tạo Báo cáo về trí tuệ nhân…",
                )

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
            self.assertEqual(
                story["headline_vi"],
                "Báo cáo nghiên cứu AI mới Báo cáo nghiên cứu AI mới Báo cáo nghiên cứu AI mới Báo cáo nghiên cứu AI mới Báo cáo nghiên cứu AI mới Báo cáo…",
            )

    def test_sentence_cut_rejects_english_and_vietnamese_abbreviations(self):
        # 1. English acronym with interior dots (U.S.)
        self.assertEqual(
            compact_headline("Leading Artificial Intelligence Researchers Urge the U.S. Congress to Mandate Federal Safety Standards for Frontier Artificial Intelligence Models"),
            "Leading Artificial Intelligence Researchers Urge the U.S. Congress to Mandate Federal Safety Standards for Frontier Artificial…",
        )
        # 2. English number abbreviation (No. 1)
        self.assertEqual(
            compact_headline("Artificial Analysis Confirms DeepSeek Reaches No. 1 on Global Open-Source LLM Benchmark Rankings Across Multiple Key Reasoning Evaluations Worldwide"),
            "Artificial Analysis Confirms DeepSeek Reaches No. 1 on Global Open-Source LLM Benchmark Rankings Across Multiple Key Reasoning Evaluations…",
        )
        # 3. Vietnamese academic title (TS.)
        self.assertEqual(
            compact_headline("Báo cáo nghiên cứu mới nhất của TS. Nguyễn Văn A và các cộng sự tại Viện Trí tuệ Nhân tạo Quốc gia đã làm sáng tỏ nhiều vấn đề quan trọng trong năm nay"),
            "Báo cáo nghiên cứu mới nhất của TS. Nguyễn Văn A và các cộng sự tại Viện Trí tuệ Nhân tạo Quốc gia đã làm sáng tỏ nhiều vấn đề quan trọng…",
        )
        # 4. Vietnamese city abbreviation (TP.)
        self.assertEqual(
            compact_headline("Hội nghị thượng đỉnh quốc tế về đạo đức AI tại TP. Hồ Chí Minh đã chính thức thông qua tuyên bố chung về các nguyên tắc phát triển công nghệ có trách nhiệm xã hội"),
            "Hội nghị thượng đỉnh quốc tế về đạo đức AI tại TP. Hồ Chí Minh đã chính thức thông qua tuyên bố chung về các nguyên tắc phát triển công…",
        )
        # 5. Vietnamese academic title (ThS.)
        self.assertEqual(
            compact_headline("Công trình nghiên cứu đột phá của ThS. Trần Thị B đã mang lại nhiều giải pháp mới cho việc tối ưu hóa mô hình ngôn ngữ lớn trên thiết bị biên di động"),
            "Công trình nghiên cứu đột phá của ThS. Trần Thị B đã mang lại nhiều giải pháp mới cho việc tối ưu hóa mô hình ngôn ngữ lớn trên thiết bị…",
        )
        # 6. Vietnamese academic title (PGS.)
        self.assertEqual(
            compact_headline("Báo cáo khoa học mới nhất từ nhóm nghiên cứu do PGS. Lê Văn C dẫn đầu đã công bố giải thuật huấn luyện mới giúp giảm chi phí điện toán xuống một nửa"),
            "Báo cáo khoa học mới nhất từ nhóm nghiên cứu do PGS. Lê Văn C dẫn đầu đã công bố giải thuật huấn luyện mới giúp giảm chi phí điện toán…",
        )
        # 7. English corporate suffix (Inc.)
        self.assertEqual(
            compact_headline("Executive leadership members at Anthropic, Inc. yesterday approved a new sweeping governance framework designed to oversee frontier safety testing"),
            "Executive leadership members at Anthropic, Inc. yesterday approved a new sweeping governance framework designed to oversee frontier safety…",
        )
        # 8. English corporate suffix (Corp.)
        self.assertEqual(
            compact_headline("Senior enterprise strategy directors at Microsoft Corp. announced a strategic investment into next-generation optical computing infrastructure today"),
            "Senior enterprise strategy directors at Microsoft Corp. announced a strategic investment into next-generation optical computing…",
        )
        # 9. English generational suffix (Jr.)
        self.assertEqual(
            compact_headline("Distinguished keynote address delivered by Martin Luther King Jr. Institute fellows outlines the societal implications of autonomous AI agents"),
            "Distinguished keynote address delivered by Martin Luther King Jr. Institute fellows outlines the societal implications of autonomous AI…",
        )
        # 10. Single initial (F.)
        self.assertEqual(
            compact_headline("A comprehensive new research study by scholar John F. Kennedy School fellow demonstrates novel alignment vulnerabilities in autonomous models"),
            "A comprehensive new research study by scholar John F. Kennedy School fellow demonstrates novel alignment vulnerabilities in autonomous…",
        )
        # 11. Version number (v2.)
        self.assertEqual(
            compact_headline("The artificial intelligence engineering team at Meta released Llama v2. with enhanced reasoning capabilities and wider context windows for users"),
            "The artificial intelligence engineering team at Meta released Llama v2. with enhanced reasoning capabilities and wider context windows for…",
        )

    def test_sentence_cut_after_abbreviation_extracts_full_first_sentence(self):
        title = "Leading Artificial Intelligence Researchers Urge the U.S. Congress to Mandate Federal Safety Standards. The landmark proposal was formally presented by researchers in Washington today."
        self.assertEqual(
            compact_headline(title),
            "Leading Artificial Intelligence Researchers Urge the U.S. Congress to Mandate Federal Safety Standards.",
        )

    def test_fallback_never_splits_grapheme_cluster_or_url(self):
        # Multi-codepoint emoji flag (VN flag = 2 codepoints)
        flag_headline = compact_headline("🇻🇳" * 75)
        self.assertEqual(flag_headline, ("🇻🇳" * 69) + "…")
        self.assertNotIn("🇻…", flag_headline)
        self.assertLessEqual(len(flag_headline), 140)

        # Standalone long URL (single long token) keeps origin domain
        long_url = "https://example.com/very/long/path/without/spaces/that/exceeds/one/hundred/and/forty/characters/in/total/length/completely/and/further/still/beyond/endpoint"
        self.assertEqual(compact_headline(long_url), "https://example.com…")

        # Text followed by a URL crossing limit drops the partial URL cleanly
        text_with_url = "Here is the latest paper on frontier artificial intelligence models and safety standards across jurisdictions: https://arxiv.org/abs/2607.088499999999999999999999999"
        self.assertEqual(
            compact_headline(text_with_url),
            "Here is the latest paper on frontier artificial intelligence models and safety standards across jurisdictions…",
        )

    def test_real_titles_from_radar_ui_payload(self):
        # 1. Complete first sentence (ID: c51707869e438becf5aa, EN)
        self.assertEqual(
            compact_headline("Sabi says it can already predict a person's next three to four keystrokes from brain signals, before anything is typed. Up next on its roadmap are thought-to-prompt and intent-to-action, where an AI agent carries out what the wearer means to do. A waitlist for the cap is open"),
            "Sabi says it can already predict a person's next three to four keystrokes from brain signals, before anything is typed.",
        )
        # 2. Complete first sentence in Vietnamese (ID: c51707869e438becf5aa, VI)
        self.assertEqual(
            compact_headline("Sabi cho biết họ đã có thể dự đoán 3 đến 4 lần nhấn phím tiếp theo của một người từ tín hiệu não, trước khi bất kỳ thứ gì được gõ ra. Kế tiếp trên lộ trình của họ là từ ý nghĩ thành lời nhắc và từ ý định thành hành động, nơi một agent AI thực hiện những gì người đeo dự định làm. Danh sách chờ nhận mũ hiện đã mở"),
            "Sabi cho biết họ đã có thể dự đoán 3 đến 4 lần nhấn phím tiếp theo của một người từ tín hiệu não, trước khi bất kỳ thứ gì được gõ ra.",
        )
        # 3. Quoted sentence with trailing quote (ID: c04d7ead62c78c3b5855, EN)
        self.assertEqual(
            compact_headline('"The invention of the boat reduced the importance of swimming, but enabled the discovery of new lands." Beautiful analogy from @ylecun about the opportunities and changes with AI, in mathematics and in science more broadly.'),
            '"The invention of the boat reduced the importance of swimming, but enabled the discovery of new lands."',
        )
        # 4. Fallback word cut preserving decimal version numbers (ID: faac871e12b6f555c9f0, EN)
        self.assertEqual(
            compact_headline("From The Lancet: in an urgent care setting, the advice of the obsolete Gemini 2.5 Pro & Gemini 2.5 Flash (without access to patient medical records) were rated of similar quality to doctors by other physicians. There was no safety issues spotted. Models have gotten significantly better since."),
            "From The Lancet: in an urgent care setting, the advice of the obsolete Gemini 2.5 Pro & Gemini 2.5 Flash (without access to patient…",
        )
        # 5. Complete first sentence under limit (ID: 22f25599af2d94e866ab, EN)
        self.assertEqual(
            compact_headline("To help secure systems like power grids and water systems, we’re launching a new Critical Infrastructure Defense Program. We’ll bring frontier Claude models, on-site engineers, and our latest research to these operators’ security, manufacturing and technology providers."),
            "To help secure systems like power grids and water systems, we’re launching a new Critical Infrastructure Defense Program.",
        )
        # 6. Fallback word cut omitting trailing URL (ID: 2da07dc90d4ec1b166c7, EN)
        self.assertEqual(
            compact_headline('Note that their press release from when he pleaded guilty back on March 19th used "North Carolina Man Pleads Guilty To Music Streaming Fraud Aided By Artificial Intelligence" because of course it did https://t.co/iJktn2sq2a'),
            'Note that their press release from when he pleaded guilty back on March 19th used "North Carolina Man Pleads Guilty To Music Streaming…',
        )
        # 7. Fallback word cut for exclamation mark sentence (ID: 1b6e4a4351e95749721c, EN)
        self.assertEqual(
            compact_headline("Excited to announce that all super intelligence organizations have now jointly agreed to the ultimate in AI/SI safety: Moving all testing to Delta Airlines flights, where accessing the Internet is utterly impossible!"),
            "Excited to announce that all super intelligence organizations have now jointly agreed to the ultimate in AI/SI safety: Moving all testing…",
        )


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
