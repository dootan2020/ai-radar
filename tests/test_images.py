"""Unit tests for image resolution order, image verification, and image cache."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from radar.images import (
    ImageCache,
    pattern_image,
    hf_thumbnail_path,
    extract_meta_image,
    resolve_story_image,
    resolve_images_for_stories,
    clear_verification_cache,
)


class ImageResolutionOrderTests(unittest.TestCase):
    def setUp(self):
        clear_verification_cache()

    def test_feed_media_has_first_priority(self):
        # A story with both feed media and a github url
        story = {
            "id": "st-media",
            "url": "https://github.com/owner/repo",
            "coverage": [
                {
                    "source": "ars-ai",
                    "url": "https://arstechnica.com/ai/article",
                    "media": [
                        {"url": "https://example.com/feed-photo.jpg", "type": "image"}
                    ]
                }
            ]
        }
        mock_transport = lambda u: b"\xff\xd8\xff\xe0"  # JPEG bytes
        img = resolve_story_image(story, transport=mock_transport)
        self.assertIsNotNone(img)
        self.assertEqual(img["via"], "feed-media")
        self.assertEqual(img["kind"], "photo")
        self.assertEqual(img["src"], "https://example.com/feed-photo.jpg")

    def test_predictable_addresses_have_second_priority(self):
        # YouTube URL
        story_yt = {
            "id": "st-yt",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "coverage": []
        }
        mock_transport = lambda u: b"\xff\xd8\xff\xe0"
        img_yt = resolve_story_image(story_yt, transport=mock_transport)
        self.assertIsNotNone(img_yt)
        self.assertEqual(img_yt["via"], "youtube")
        self.assertEqual(img_yt["kind"], "photo")
        self.assertEqual(img_yt["src"], "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")

        # GitHub URL
        story_gh = {
            "id": "st-gh",
            "url": "https://github.com/facebookresearch/llama",
            "coverage": []
        }
        img_gh = resolve_story_image(story_gh, transport=mock_transport)
        self.assertIsNotNone(img_gh)
        self.assertEqual(img_gh["via"], "github-social")
        self.assertEqual(img_gh["kind"], "graphic")
        self.assertEqual(img_gh["src"], "https://opengraph.githubassets.com/1/facebookresearch/llama")

        # Hugging Face paper URL
        story_hf = {
            "id": "st-hf",
            "url": "https://huggingface.co/papers/2410.12345",
            "coverage": []
        }
        img_hf = resolve_story_image(story_hf, transport=mock_transport)
        self.assertIsNotNone(img_hf)
        self.assertEqual(img_hf["via"], "hf-thumbnail")
        self.assertEqual(img_hf["kind"], "graphic")
        self.assertEqual(img_hf["src"], "https://cdn-thumbnails.huggingface.co/social-thumbnails/papers/2410.12345.png")

    def test_og_image_from_page_meta_has_third_priority(self):
        story = {
            "id": "st-og",
            "url": "https://blog.example.com/ai-update",
            "coverage": [
                {"source": "custom-blog", "url": "https://blog.example.com/ai-update", "media": []}
            ]
        }
        html_page = """
        <html>
        <head>
          <meta property="og:image" content="https://blog.example.com/hero.png">
        </head>
        <body></body>
        </html>
        """
        def mock_transport(url):
            if "hero.png" in url:
                return b"\x89PNG\r\n\x1a\n"
            return html_page.encode("utf-8")

        img = resolve_story_image(story, transport=mock_transport)
        self.assertIsNotNone(img)
        self.assertEqual(img["via"], "og:image")
        self.assertEqual(img["kind"], "photo")
        self.assertEqual(img["src"], "https://blog.example.com/hero.png")

    def test_discussion_gives_linked_article_via(self):
        story = {
            "id": "st-hn",
            "url": "https://theverge.com/article",
            "coverage": [
                {"source": "hn-front", "url": "https://news.ycombinator.com/item?id=12345"},
                {"source": "the-verge", "url": "https://theverge.com/article"}
            ]
        }
        html_page = '<meta property="og:image" content="https://theverge.com/thumb.jpg">'
        def mock_transport(url):
            if "thumb.jpg" in url:
                return b"\xff\xd8\xff\xe0"
            return html_page.encode("utf-8")

        img = resolve_story_image(story, transport=mock_transport)
        self.assertIsNotNone(img)
        self.assertEqual(img["via"], "linked-article")
        self.assertEqual(img["kind"], "photo")

    def test_no_image_when_unverified_leaves_image_absent(self):
        story = {
            "id": "st-none",
            "url": "https://example.com/unverified-article",
            "coverage": []
        }
        # Returns HTML pointing to og:image, but the image fetch returns text/html, not image bytes
        def mock_transport(url):
            if "hero.png" in url:
                return b"<html>not an image</html>"
            return b'<html><head><meta property="og:image" content="https://example.com/hero.png"></head></html>'

        img = resolve_story_image(story, transport=mock_transport)
        self.assertIsNone(img)


class ImageCacheTests(unittest.TestCase):
    def setUp(self):
        clear_verification_cache()

    def test_cache_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            cache = ImageCache(cache_path=cache_file)
            cache.set("https://example.com/post", {"src": "https://example.com/img.png", "via": "og:image"})
            cache.save()

            self.assertTrue(cache_file.is_file())
            loaded = ImageCache(cache_path=cache_file)
            entry = loaded.get("https://example.com/post")
            self.assertIsNotNone(entry)
            self.assertEqual(entry["src"], "https://example.com/img.png")
            self.assertEqual(entry["via"], "og:image")

    def test_story_image_resolution_hits_cache_without_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            cache = ImageCache(cache_path=cache_file)
            cache.set("https://techcrunch.com/article", {
                "src": "https://techcrunch.com/cached.jpg",
                "via": "og:image"
            })

            story = {
                "id": "st-cache",
                "url": "https://techcrunch.com/article",
                "coverage": [{"source": "techcrunch-ai", "url": "https://techcrunch.com/article"}]
            }
            # No network transport; must resolve purely from cache
            img = resolve_story_image(story, cache=cache)
            self.assertIsNotNone(img)
            self.assertEqual(img["src"], "https://techcrunch.com/cached.jpg")
            self.assertEqual(img["via"], "og:image")
            self.assertEqual(img["kind"], "photo")

    def test_negative_caching_avoids_repeated_failed_lookups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            cache = ImageCache(cache_path=cache_file)
            cache.set("https://example.com/no-image", {"src": None, "via": None, "cached_at": time.time()})

            story = {
                "id": "st-neg",
                "url": "https://example.com/no-image",
                "coverage": []
            }
            calls = []
            def failing_transport(url):
                calls.append(url)
                raise RuntimeError("Should not be called")

            img = resolve_story_image(story, cache=cache, transport=failing_transport)
            self.assertIsNone(img)
            self.assertEqual(len(calls), 0)

    def test_resolve_images_for_stories_annotates_story_objects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            cache = ImageCache(cache_path=cache_file)
            cache.set("https://example.com/with-img", {"src": "https://example.com/img.jpg", "via": "og:image"})
            cache.save()

            stories = [
                {"id": "s1", "url": "https://example.com/with-img", "coverage": []},
                {"id": "s2", "url": "https://example.com/without-img", "coverage": []},
            ]
            resolve_images_for_stories(stories, cache_path=cache_file, transport=lambda u: b"")
            self.assertIn("image", stories[0])
            self.assertEqual(stories[0]["image"]["src"], "https://example.com/img.jpg")
            # Story without image has NO 'image' field (absent, not placeholder)
            self.assertNotIn("image", stories[1])

    def test_image_step_returns_within_deadline_against_slow_server(self):
        # Fake slow server that stalls on connection / read
        def slow_fake_server(*args, **kwargs):
            time.sleep(2.0)
            raise TimeoutError("slow fake server connection")

        stories = [
            {"id": "slow-1", "url": "https://slow-server.com/post-1", "coverage": []},
            {"id": "slow-2", "url": "https://slow-server.com/post-2", "coverage": []},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "image-cache.json"
            start_time = time.monotonic()
            with patch("urllib.request.urlopen", side_effect=slow_fake_server):
                resolve_images_for_stories(stories, cache_path=cache_file, budget_seconds=0.3, timeout=0.1)
            duration = time.monotonic() - start_time
            self.assertLess(duration, 1.2, f"Image step exceeded deadline: took {duration:.2f}s")
            self.assertNotIn("image", stories[0])
            self.assertNotIn("image", stories[1])

    def test_verification_cache_not_polluted_by_transport(self):
        from radar import images
        mock_transport = lambda u: b"\xff\xd8\xff\xe0"
        url = "https://example.com/test-verify-clean.jpg"
        self.assertNotIn(url, images._verified_cache)
        images.verify_image(url, transport=mock_transport)
        self.assertNotIn(url, images._verified_cache)


if __name__ == "__main__":
    unittest.main()
