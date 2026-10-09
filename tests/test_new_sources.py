"""Unit tests for newly added sources, AI relevance filtering, and Vietnamese translation behavior."""

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from radar import catalog, feeds, items, translate, v2feeds
from radar.common import iso_date
from radar.clustering import titles_match, cluster_items
from radar.editions import nonforum_publishers

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 4, 16, 5, 0, tzinfo=timezone.utc)

NEW_FEED_URLS = {
    "vnexpress-tech": "https://e.vnexpress.net/rss/tech.rss",
    "genk-ai": "https://genk.vn/rss/ai.rss",
    "tuoitre-so": "https://tuoitre.vn/rss/nhip-song-so.rss",
    "thanhnien-cong-nghe": "https://thanhnien.vn/rss/cong-nghe.rss",
    "theregister-ai": "https://www.theregister.com/software/ai_ml/headlines.atom",
    "wired-ai": "https://www.wired.com/feed/tag/ai/latest/rss",
    "404media": "https://www.404media.co/rss/",
    "semafor": "https://www.semafor.com/rss.xml",
    "cnbc-tech": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "bloomberg-tech": "https://feeds.bloomberg.com/technology/news.rss",
    "fedscoop": "https://fedscoop.com/feed/",
    "nextgov-ai": "https://www.nextgov.com/rss/artificial-intelligence/",
    "technode": "https://technode.com/feed/",
    "pandaily": "https://pandaily.com/feed/",
    "scmp-tech": "https://www.scmp.com/rss/36/feed",
    "pandaily": "https://pandaily.com/feed/",
    "scmp-tech": "https://www.scmp.com/rss/36/feed",
    "openai-youtube-feed": "https://www.youtube.com/feeds/videos.xml?channel_id=UCXZCJLdBC09xxGZ6gcdrc6A",
    "anthropic-youtube-feed": "https://www.youtube.com/feeds/videos.xml?channel_id=UCrDwWp7EBBv4NwvScIpBDOA",
    "google-youtube-feed": "https://www.youtube.com/feeds/videos.xml?channel_id=UCK8sQmJBp8GCxrOtXWBpyEA",
    "deepmind-youtube-feed": "https://www.youtube.com/feeds/videos.xml?channel_id=UCP7jMXSY2xbc3KCAE0MHQ-A",
    "nvidia-youtube-feed": "https://www.youtube.com/feeds/videos.xml?channel_id=UCHuiy8bXnmK5nisYHUd1J5g",
    "dwarkesh-video": "https://www.youtube.com/feeds/videos.xml?channel_id=UCXl4i9dYBrFOabk0xGmbkRA",
    "restofworld": "https://restofworld.org/feed/latest/",
    "meta-newsroom": "https://about.fb.com/news/feed/",
    "microsoft-blog": "https://blogs.microsoft.com/feed/",
    "aws-ml-blog": "https://aws.amazon.com/blogs/machine-learning/feed/",
}

FILTERED_SOURCES = {
    "vnexpress-tech", "tuoitre-so", "thanhnien-cong-nghe",
    "404media", "semafor", "cnbc-tech", "bloomberg-tech", "fedscoop",
    "technode", "pandaily", "scmp-tech", "restofworld", "meta-newsroom", "microsoft-blog",
}

UNFILTERED_SOURCES = {
    "genk-ai", "theregister-ai", "wired-ai", "nextgov-ai", "aws-ml-blog",
}


class CatalogNewSourcesTests(unittest.TestCase):
    def setUp(self):
        self.sources = {s["id"]: s for s in catalog.sources(NOW)}

    def test_all_17_probed_feeds_are_present_in_catalog(self):
        for id_, expected_url in NEW_FEED_URLS.items():
            with self.subTest(source_id=id_):
                self.assertIn(id_, self.sources)
                src = self.sources[id_]
                self.assertEqual(src["url"], expected_url)
                self.assertEqual(src["parser"], "feed")
                self.assertEqual(src["kind"], "rss")
                self.assertTrue(src.get("first_wave"))
                if id_ == "cnbc-tech":
                    self.assertTrue(src.get("disabled"))
                    self.assertIn("máy dựng của GitHub", src.get("disabled_reason", ""))
                else:
                    self.assertNotIn("disabled", src)
        self.assertTrue(self.sources["ai-news"]["disabled"])
        self.assertEqual(self.sources["ai-news"]["url"], "https://news.smol.ai/rss.xml")

    def test_groups_and_publishers_are_consistent(self):
        press_sources = {
            "vnexpress-tech", "genk-ai", "tuoitre-so",
            "thanhnien-cong-nghe", "theregister-ai", "wired-ai", "404media",
            "semafor", "cnbc-tech", "bloomberg-tech", "fedscoop", "nextgov-ai",
            "technode", "pandaily", "scmp-tech", "restofworld",
        }
        lab_sources = {"meta-newsroom", "microsoft-blog", "aws-ml-blog"}

        for id_ in press_sources:
            with self.subTest(press_id=id_):
                src = self.sources[id_]
                self.assertEqual(src["group"], "press")
                self.assertEqual(src["lab"], "")
                self.assertTrue(src["publisher"])

        for id_ in lab_sources:
            with self.subTest(lab_id=id_):
                src = self.sources[id_]
                self.assertEqual(src["group"], "lab")
                self.assertEqual(src["lab"], src["publisher"])
                self.assertTrue(src["publisher"])

        # Check specific publisher identities
        self.assertEqual(self.sources["vnexpress-tech"]["publisher"], "vnexpress")
        self.assertEqual(self.sources["genk-ai"]["publisher"], "genk")
        self.assertEqual(self.sources["tuoitre-so"]["publisher"], "tuoi-tre")
        self.assertEqual(self.sources["thanhnien-cong-nghe"]["publisher"], "thanh-nien")
        self.assertEqual(self.sources["theregister-ai"]["publisher"], "the-register")
        self.assertEqual(self.sources["wired-ai"]["publisher"], "wired")
        self.assertEqual(self.sources["404media"]["publisher"], "404-media")
        self.assertEqual(self.sources["semafor"]["publisher"], "semafor")
        self.assertEqual(self.sources["cnbc-tech"]["publisher"], "cnbc")
        self.assertEqual(self.sources["bloomberg-tech"]["publisher"], "bloomberg")
        self.assertEqual(self.sources["fedscoop"]["publisher"], "fedscoop")
        self.assertEqual(self.sources["nextgov-ai"]["publisher"], "nextgov")
        self.assertEqual(self.sources["technode"]["publisher"], "technode")
        self.assertEqual(self.sources["pandaily"]["publisher"], "pandaily")
        self.assertEqual(self.sources["scmp-tech"]["publisher"], "scmp")
        self.assertEqual(self.sources["restofworld"]["publisher"], "rest-of-world")
        self.assertEqual(self.sources["meta-newsroom"]["publisher"], "meta")
        self.assertEqual(self.sources["microsoft-blog"]["publisher"], "microsoft")
        self.assertEqual(self.sources["aws-ml-blog"]["publisher"], "amazon")

    def test_filter_ai_configuration(self):
        for id_ in FILTERED_SOURCES:
            with self.subTest(filtered=id_):
                self.assertTrue(self.sources[id_].get("filter_ai"), f"{id_} must have filter_ai=True")
        for id_ in UNFILTERED_SOURCES:
            with self.subTest(unfiltered=id_):
                self.assertFalse(self.sources[id_].get("filter_ai"), f"{id_} must have filter_ai=False")

    def test_bluesky_observations_are_community_sources(self):
        self.assertEqual(self.sources["bluesky-simonwillison"]["group"], "forum")
        self.assertEqual(self.sources["bluesky-emollick"]["group"], "forum")


class RelevanceFilterTests(unittest.TestCase):
    def setUp(self):
        fixture_path = FIXTURES / "new_sources_headlines.json"
        self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_vietnamese_ai_headlines_pass_filter(self):
        for item in self.fixture["vietnamese_ai"]:
            with self.subTest(title=item["title"]):
                self.assertTrue(
                    items.relevant(item["title"], item.get("summary", "")),
                    f"Headline should be relevant: {item['title']}"
                )

    def test_vietnamese_non_ai_headlines_dropped_by_filter(self):
        for item in self.fixture["vietnamese_non_ai"]:
            with self.subTest(title=item["title"]):
                self.assertFalse(
                    items.relevant(item["title"], item.get("summary", "")),
                    f"Headline should NOT be relevant: {item['title']}"
                )

    def test_english_ai_headlines_pass_filter(self):
        for item in self.fixture["english_ai"]:
            with self.subTest(title=item["title"]):
                self.assertTrue(
                    items.relevant(item["title"], item.get("summary", "")),
                    f"Headline should be relevant: {item['title']}"
                )

    def test_english_non_ai_headlines_dropped_by_filter(self):
        for item in self.fixture["english_non_ai"]:
            with self.subTest(title=item["title"]):
                self.assertFalse(
                    items.relevant(item["title"], item.get("summary", "")),
                    f"Headline should NOT be relevant: {item['title']}"
                )

    def test_vietnamese_word_ai_does_not_trigger_false_positive(self):
        # In Vietnamese, 'ai' means 'who' or 'anyone', and 'Ai Cập' is Egypt.
        # Only exact uppercase 'AI' with word boundaries should trigger relevance.
        self.assertFalse(items.relevant("Ai là người chế tạo điện thoại thông minh đầu tiên?"))
        self.assertFalse(items.relevant("Không ai nghĩ giá vàng có thể đạt kỷ lục cao như hôm nay"))
        self.assertFalse(items.relevant("Khảo cổ học tại Ai Cập phát hiện lăng mộ mới"))
        self.assertFalse(items.relevant("Ai cũng cần nắm rõ luật an toàn giao thông"))
        self.assertTrue(items.relevant("Ứng dụng AI giúp tối ưu hóa sản xuất nông nghiệp"))
        self.assertTrue(items.relevant("Doanh nghiệp Việt đón làn sóng AI mới"))

    def test_newly_added_vietnamese_terms_and_entities(self):
        cases = [
            ("Chatbot chăm sóc khách hàng tự động", True),
            ("Thủ đoạn lừa đảo tinh vi bằng video deepfake", True),
            ("Nghiên cứu mới về thị giác máy tính tại VinAI", True),
            ("Phát triển trợ lý ảo cho dịch vụ công trực tuyến", True),
            ("Ứng dụng mạng nơ-ron sâu trong xử lý hình ảnh", True),
            ("Tranh luận quốc tế về kịch bản xuất hiện siêu trí tuệ", True),
            ("Zhipu AI mở mã nguồn mô hình lý luận mới", True),
            ("Mistral ra mắt phiên bản mô hình ngôn ngữ mới", True),
            ("Công cụ tạo video Sora của OpenAI", True),
            ("Elon Musk cập nhật năng lực chatbot Grok", True),
            ("ElevenLabs cung cấp công cụ lồng tiếng bằng giọng nói tổng hợp", True),
            ("Startup GenAI huy động thành công 50 triệu USD", True),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(items.relevant(title), expected)


class FeedParsingAndFilterIntegrationTests(unittest.TestCase):
    def test_filtered_rss_drops_offtopic_and_retains_ai_items(self):
        source = {
            "id": "vnexpress-so-hoa",
            "name": "VnExpress Số hóa",
            "publisher": "vnexpress",
            "group": "press",
            "kind": "rss",
            "url": "https://vnexpress.net/rss/so-hoa.rss",
            "filter_ai": True,
        }
        xml = """<rss version="2.0">
        <channel>
          <title>Số hóa - VnExpress</title>
          <link>https://vnexpress.net/so-hoa</link>
          <item>
            <title>Trí tuệ nhân tạo hỗ trợ bác sĩ chẩn đoán hình ảnh</title>
            <link>https://vnexpress.net/ai-ho-tro-bac-si-1234.html</link>
            <description><![CDATA[<a href="..."><img src="thumb.jpg"/></a>Mô hình học máy phân tích phim chụp X-quang chính xác hơn.]]></description>
            <pubDate>Sun, 04 Oct 2026 10:00:00 +0700</pubDate>
          </item>
          <item>
            <title>Đánh giá chi tiết camera iPhone 16 Pro Max</title>
            <link>https://vnexpress.net/danh-gia-camera-iphone-16-5678.html</link>
            <description><![CDATA[Trải nghiệm khả năng chụp thiếu sáng và quay phim 4K.]]></description>
            <pubDate>Sun, 04 Oct 2026 09:00:00 +0700</pubDate>
          </item>
        </channel>
        </rss>"""
        parsed = v2feeds.parse_feed(xml, source, NOW.isoformat())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Trí tuệ nhân tạo hỗ trợ bác sĩ chẩn đoán hình ảnh")
        self.assertEqual(parsed[0]["url"], "https://vnexpress.net/ai-ho-tro-bac-si-1234.html")
        self.assertEqual(parsed[0]["publisher"], "vnexpress")
        self.assertEqual(parsed[0]["group"], "press")
        self.assertEqual(parsed[0]["published_at"], "2026-10-04T03:00:00Z")

    def test_unfiltered_atom_feed_parses_all_entries(self):
        source = {
            "id": "theregister-ai",
            "name": "The Register AI/ML",
            "publisher": "the-register",
            "group": "press",
            "kind": "rss",
            "url": "https://www.theregister.com/software/ai_ml/headlines.atom",
            "filter_ai": False,
        }
        atom = """<feed xmlns="http://www.w3.org/2005/Atom">
          <title>The Register - AI / ML</title>
          <entry>
            <title>OpenAI frontier training stopped over security concerns</title>
            <link rel="alternate" type="text/html" href="https://www.theregister.com/2026/10/02/openai_halt/"/>
            <updated>2026-10-02T14:30:00Z</updated>
            <summary>Safety evaluations found sandbox escape risks.</summary>
          </entry>
        </feed>"""
        parsed = v2feeds.parse_feed(atom, source, NOW.isoformat())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "OpenAI frontier training stopped over security concerns")
        self.assertEqual(parsed[0]["url"], "https://www.theregister.com/2026/10/02/openai_halt/")
        self.assertEqual(parsed[0]["publisher"], "the-register")
        self.assertEqual(parsed[0]["published_at"], "2026-10-02T14:30:00Z")

    def test_feed_timestamp_parsing_exact_shapes_and_utc_normalization(self):
        # 1. GenK real pubDate: two-digit +07 offset means hours, normalized to UTC
        genk_date = "Mon, 05 Oct 2026 11:07:00 +07"
        self.assertEqual(iso_date(genk_date), "2026-10-05T04:07:00Z")

        # 2. Tuoi Tre (source tuoitre-so): 10/2/2026 9:25:00 AM (month/day/year, 12-hour clock, no zone)
        # Without declared timezone, naive timestamp is NOT guessed as UTC+7 everywhere (returns None)
        tuoitre_date = "10/2/2026 9:25:00 AM"
        self.assertIsNone(iso_date(tuoitre_date))
        # With declared UTC+7 in source definition, parsed as UTC+7 -> UTC 02:25:00Z
        self.assertEqual(iso_date(tuoitre_date, default_tz="+07:00"), "2026-10-02T02:25:00Z")

        # 3. VnExpress: Mon, 05 Oct 2026 11:00:00 +0700 parses correctly today
        vnexpress_date = "Mon, 05 Oct 2026 11:00:00 +0700"
        self.assertEqual(iso_date(vnexpress_date), "2026-10-05T04:00:00Z")

        # 4. Thanh Nien: Mon, 05 Oct 26 14:10:00 +0700 parses correctly today
        thanhnien_date = "Mon, 05 Oct 26 14:10:00 +0700"
        self.assertEqual(iso_date(thanhnien_date), "2026-10-05T07:10:00Z")

    def test_genk_and_tuoitre_feed_parsing_with_source_definitions(self):
        sources = {s["id"]: s for s in catalog.sources(NOW)}
        # GenK feed parsing with real +07 offset
        genk_source = sources["genk-ai"]
        genk_xml = """<rss version="2.0">
        <channel>
          <title>GenK - Tin tức công nghệ</title>
          <link>https://genk.vn</link>
          <item>
            <title>Kịch bản AI đe dọa tồn vong loài người</title>
            <link>https://genk.vn/kich-ban-ai-de-doa-ton-vong-loai-nguoi-165261005110748938.chn</link>
            <description><![CDATA[Các chuyên gia cảnh báo về kịch bản rủi ro nghiêm trọng từ trí tuệ nhân tạo.]]></description>
            <pubDate>Mon, 05 Oct 2026 11:07:00 +07</pubDate>
          </item>
        </channel>
        </rss>"""
        v2_genk = v2feeds.parse_feed(genk_xml, genk_source, NOW.isoformat())
        self.assertEqual(len(v2_genk), 1)
        self.assertEqual(v2_genk[0]["published_at"], "2026-10-05T04:07:00Z")

        feeds_genk = feeds.parse_feed(genk_xml, genk_source)
        self.assertEqual(len(feeds_genk), 1)
        self.assertEqual(feeds_genk[0]["published_at"], "2026-10-05T04:07:00Z")

        # Tuoi Tre feed parsing with declared UTC+7 in source definition
        tuoitre_source = sources["tuoitre-so"]
        self.assertEqual(tuoitre_source.get("default_tz"), "+07:00")
        tuoitre_xml = """<rss version="2.0">
        <channel>
          <title>Tuổi Trẻ Online - Nhịp sống số</title>
          <link>https://tuoitre.vn</link>
          <item>
            <title>Sau Úc, phát hiện tác nhân AI tìm cách xâm nhập hệ thống Canada</title>
            <link>https://tuoitre.vn/sau-uc-phat-hien-tac-nhan-ai-tim-cach-xam-nhap-he-thong-chinh-phu-canada-100261002091032857.htm</link>
            <description><![CDATA[Canada cho biết chưa có dấu hiệu hệ thống bị xâm phạm.]]></description>
            <pubDate>10/2/2026 9:25:00 AM</pubDate>
          </item>
        </channel>
        </rss>"""
        v2_tuoitre = v2feeds.parse_feed(tuoitre_xml, tuoitre_source, NOW.isoformat())
        self.assertEqual(len(v2_tuoitre), 1)
        self.assertEqual(v2_tuoitre[0]["published_at"], "2026-10-02T02:25:00Z")

        feeds_tuoitre = feeds.parse_feed(tuoitre_xml, tuoitre_source)
        self.assertEqual(len(feeds_tuoitre), 1)
        self.assertEqual(feeds_tuoitre[0]["published_at"], "2026-10-02T02:25:00Z")

        # Undeclared source without timezone: naive timestamp stays unknown (None)
        undeclared_source = {"id": "undeclared-source", "name": "Other", "publisher": "other", "url": "https://example.org/rss", "kind": "rss"}
        v2_undeclared = v2feeds.parse_feed(tuoitre_xml, undeclared_source, NOW.isoformat())
        self.assertIsNone(v2_undeclared[0]["published_at"])


class VietnameseLanguageAndTranslationTests(unittest.TestCase):
    def test_already_vietnamese_titles_do_not_need_translation(self):
        vietnamese_titles = [
            "Chuyên gia Việt bàn giải pháp ứng dụng trí tuệ nhân tạo trong y tế",
            "Cảnh báo thủ đoạn lừa đảo bằng video deepfake giả mạo",
            "VinAI giới thiệu công nghệ thị giác máy tính thế hệ mới",
            "Việt Nam đẩy mạnh xây dựng mô hình ngôn ngữ lớn mã nguồn mở",
            "Trợ lý ảo AI giúp giải đáp thắc mắc người dân nhanh chóng",
        ]
        for title in vietnamese_titles:
            with self.subTest(title=title):
                self.assertFalse(
                    translate.needs_translation(title),
                    f"Title already in Vietnamese should not need translation: {title}"
                )

    def test_english_titles_need_translation(self):
        english_titles = [
            "OpenAI says planned GPT-6.1 is too insecure to release",
            "White House readies executive order on artificial intelligence safety",
            "US arrests tech executive accused of smuggling Nvidia AI chips into China",
        ]
        for title in english_titles:
            with self.subTest(title=title):
                self.assertTrue(
                    translate.needs_translation(title),
                    f"English title should need translation: {title}"
                )

    def test_apply_keeps_already_vietnamese_title_without_invoking_model(self):
        story = {
            "id": "abc123def456",
            "title": "Trí tuệ nhân tạo đang thay đổi ngành tài chính Việt Nam",
            "url": "https://vnexpress.net/ai-tai-chinh",
            "summary": "Nhiều ngân hàng bắt đầu ứng dụng học máy tự động.",
            "source_count": 1,
            "published_at": "2026-10-04T10:00:00Z",
            "coverage": [{
                "id": "cov1",
                "source": "vnexpress-so-hoa",
                "publisher": "vnexpress",
                "title": "Trí tuệ nhân tạo đang thay đổi ngành tài chính Việt Nam",
                "url": "https://vnexpress.net/ai-tai-chinh",
                "published_at": "2026-10-04T10:00:00Z",
            }]
        }
        payload = {"stories": [story], "sections": {"today": ["abc123def456"]}}
        cache = {}
        counts, rejected = translate.apply(payload, cache)

        self.assertEqual(counts["kept_original"], 3)  # story title, story summary, coverage title
        self.assertEqual(counts["translated"], 0)
        self.assertEqual(counts["pending"], 0)
        self.assertEqual(counts["rejected"], 0)
        self.assertNotIn("title_vi", story)
        self.assertEqual(story["title"], "Trí tuệ nhân tạo đang thay đổi ngành tài chính Việt Nam")


class ClusteringBehaviorTests(unittest.TestCase):
    def test_vietnamese_sources_can_cluster_together_on_same_event(self):
        date = "2026-10-04T08:00:00Z"
        item_vnexpress = {
            "id": "vne-1",
            "source": "vnexpress-tech",
            "publisher": "vnexpress",
            "group": "press",
            "title": "OpenAI công bố thỏa thuận hợp tác nghiên cứu an toàn với các trường đại học",
            "url": "https://vnexpress.net/openai-hop-tac-an-toan",
            "canonical_url": "https://vnexpress.net/openai-hop-tac-an-toan",
            "published_at": date,
            "kind": "model",
            "time_basis": "published",
        }
        item_tuoitre = {
            "id": "tt-1",
            "source": "tuoitre-so",
            "publisher": "tuoi-tre",
            "group": "press",
            "title": "OpenAI công bố thỏa thuận hợp tác an toàn cùng các trường đại học lớn",
            "url": "https://tuoitre.vn/openai-hop-tac-dai-hoc",
            "canonical_url": "https://tuoitre.vn/openai-hop-tac-dai-hoc",
            "published_at": date,
            "kind": "model",
            "time_basis": "published",
        }
        self.assertTrue(titles_match(item_vnexpress, item_tuoitre))
        stories = cluster_items([item_vnexpress, item_tuoitre], NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)
        self.assertEqual(nonforum_publishers(stories[0]["coverage"]), ["tuoi-tre", "vnexpress"])

    def test_vietnamese_and_english_general_headlines_do_not_falsely_merge(self):
        # As documented in the architecture, cross-lingual headlines lack shared specific words
        # and do not falsely merge across languages.
        item_vn = {
            "id": "vn-1",
            "source": "tuoitre-so",
            "publisher": "tuoi-tre",
            "group": "press",
            "title": "Chính phủ Mỹ điều tra nguy cơ an ninh từ các hệ thống trí tuệ nhân tạo",
            "url": "https://tuoitre.vn/my-dieu-tra-ai",
            "canonical_url": "https://tuoitre.vn/my-dieu-tra-ai",
            "published_at": "2026-10-04T08:00:00Z",
        }
        item_en = {
            "id": "en-1",
            "source": "wired-ai",
            "publisher": "wired",
            "group": "press",
            "title": "FTC launches inquiry into major AI foundation model partnerships",
            "url": "https://wired.com/ftc-ai-inquiry",
            "canonical_url": "https://wired.com/ftc-ai-inquiry",
            "published_at": "2026-10-04T08:00:00Z",
        }
        self.assertFalse(titles_match(item_vn, item_en))
        stories = cluster_items([item_vn, item_en], NOW)
        self.assertEqual(len(stories), 2)


if __name__ == "__main__":
    unittest.main()
