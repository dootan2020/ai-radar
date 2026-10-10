"""Synthetic editorial cases; no publisher copy is used as a fixture."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import unicodedata
import unittest
from xml.sax.saxutils import escape

from radar import assembly, catalog
from radar.clustering import cluster_items
from radar.items import observation, relevant
from radar.press_relevance import accepts_feed_item, filter_published_stories, press_subject_reason
from radar.v2feeds import parse_feed

NOW = datetime(2026, 10, 10, 14, tzinfo=timezone.utc)
PASSING = [
    ("Hạn mức chuyển tiền mới có quy định liên quan đến AI", "Ngân hàng thay đổi thủ tục xác nhận giao dịch."),
    ("Bank transfer limits change under rules related to AI", "Customers must verify large payments. AI detects fraud in the background."),
    ("Payment requirements get an AI-related update", "Customers must provide identity documents."),
    ("Lịch nghỉ lễ của thành phố được công bố", "Cơ quan công bố lịch làm việc. Thông báo cũng nhắc đến AI."),
    ("City announces its holiday schedule", "Offices close for two days. The notice also mentions AI."),
    ("City publishes new parking prices", "The rate rises next month."),
    ("City festival announcement briefly mentions AI", "The notice lists the opening times."),
    ("Thông báo lịch hội chợ có nhắc đến AI", "Ban tổ chức công bố giờ mở cửa."),
]
GENUINE = [
    ("Ngân hàng triển khai AI phát hiện giao dịch gian lận", "Mô hình giảm báo động sai."),
    ("AI changes bank transfer verification rules", "The model explains rejected payments."),
    ("Bank transfer rules address deepfake attacks related to AI", "Banks test detection models."),
    ("New rules related to AI", "Lawmakers require model safety evaluations."),
    ("AI-related bank account data breach exposes training records", "Researchers investigate the model."),
    ("Quy định mới liên quan đến AI trong y tế", "Bệnh viện kiểm định mô hình trước khi sử dụng."),
    ("Nhóm nghiên cứu ra mắt mô hình ngôn ngữ tiếng Việt", "Mã nguồn đã được công bố."),
    ("OpenAI releases a smaller reasoning model", "Developers can test it today."),
    ("Hospital trials new diagnostic assistant", "A machine learning system flags missed lesions."),
    ("Những công cụ mới cho bác sĩ", "Trí tuệ nhân tạo hỗ trợ đọc ảnh y khoa."),
    ("Researchers audit discriminatory hiring", "The experiment measures disparities in candidate rankings. AI models reproduce the disparities."),
    ("Neural research explains new inference technique", "The article also mentions AI policy."),
    ("Aster launches on tablets", ""),
    ("Aster launches on tablets", "The assistant creates short films from text prompts."),
    ("New safety evaluations arrive", "The report also mentions AI and compares ChatGPT with Claude."),
]


def source(id_="genk-ai", **extra):
    return dict(id=id_, group="press", publisher=id_, filter_ai=False,
                url="https://press.example/feed") | extra


def item(title, summary, id_="genk-ai", url="https://press.example/story", **extra):
    return observation(source(id_, **extra), title, url, NOW, NOW, summary=summary)


class PressSubjectTests(unittest.TestCase):
    def test_passing_mentions_and_unrelated_copy_are_rejected_in_both_languages(self):
        for title, summary in PASSING:
            with self.subTest(title=title):
                self.assertFalse(accepts_feed_item(source(), title, summary))

    def test_real_ai_stories_survive_including_banking_policy_and_summary_only_evidence(self):
        for title, summary in GENUINE:
            with self.subTest(title=title):
                self.assertTrue(accepts_feed_item(source(), title, summary))

    def test_all_press_catalog_sources_use_subject_rule_regardless_of_keyword_flag(self):
        for src in catalog.sources(NOW):
            if src["group"] != "press":
                continue
            with self.subTest(source=src["id"]):
                self.assertFalse(accepts_feed_item(src, *PASSING[0]))
                self.assertTrue(accepts_feed_item(src, *GENUINE[0]))

    def test_keywords_and_nonpress_contracts_are_unchanged(self):
        self.assertTrue(relevant(*PASSING[0]))
        for group in ("lab", "forum", "newsletter", "repository", "podcast"):
            self.assertTrue(accepts_feed_item(source(group=group), *PASSING[0]))
        self.assertFalse(accepts_feed_item(source(group="lab", filter_ai=True), "Gardening", ""))

    def test_unicode_and_html_are_normalized(self):
        title, summary = PASSING[0]
        self.assertFalse(accepts_feed_item(source(), unicodedata.normalize("NFD", title), summary))
        self.assertFalse(accepts_feed_item(source(), "<b>" + title + "</b>", summary))

    def test_rss_atom_and_playlist_admission_use_same_rule(self):
        for title, summary in (PASSING[0], GENUINE[0]):
            expected = 0 if (title, summary) in PASSING else 1
            fields = f"<title>{escape(title)}</title><link>https://press.example/story</link><description>{escape(summary)}</description>"
            bodies = ["<rss><channel><item>" + fields + "</item></channel></rss>",
                      "<feed><entry>" + fields + "</entry></feed>",
                      json.dumps({"items": [{"snippet": {"title": title, "description": summary},
                                             "contentDetails": {"videoId": "synthetic"}}]})]
            for body in bodies:
                self.assertEqual(len(parse_feed(body, source(), NOW)), expected)

    def test_sparse_copy_is_explicitly_uncertain(self):
        self.assertEqual(press_subject_reason("Aster launches on tablets"), "keep-insufficient-copy")
        self.assertTrue(accepts_feed_item(source(), "Aster launches on tablets"))
        self.assertFalse(accepts_feed_item(source(filter_ai=True), "Aster launches on tablets"))

    def test_assembly_removes_fresh_and_carried_noise_without_mutating_snapshot(self):
        bad = item(*PASSING[0])
        good = item(*GENUINE[0], url="https://press.example/ai")
        published = dict(schema_version=2, generated_at=NOW.isoformat(),
                         stories=cluster_items([bad, good], NOW))
        before = deepcopy(published)
        payload = dict(updates=[], hf_releases=[], live=[], sources=[], trending={})
        result = assembly.finish(payload, [bad], [], NOW, None, published=published, resolve_images=False)
        self.assertEqual([s["url"] for s in result["stories"]], [good["url"]])
        self.assertTrue(result["stories"][0]["carried"])
        self.assertEqual(published, before)
        self.assertEqual(result["sections"]["today"], [result["stories"][0]["id"]])

    def test_mixed_retained_story_keeps_real_coverage_and_discards_rejected_enrichment(self):
        bad = item(*PASSING[0])
        good = item(*GENUINE[0], id_="techcrunch-ai")
        old = cluster_items([bad, good], NOW)[0]
        old.update(image={"src": "https://press.example/old.jpg"}, title_vi="Old translation",
                   headline="Old headline", key_points=["Old generated summary"])
        before = deepcopy(old)
        cleaned = filter_published_stories([old], NOW)[0]
        self.assertEqual(cleaned["title"], good["title"])
        self.assertEqual(cleaned["coverage"], [good])
        self.assertEqual(cleaned["source_count"], 1)
        for field in ("image", "title_vi", "headline", "key_points"):
            self.assertNotIn(field, cleaned)
        self.assertEqual(old, before)

    def test_source_id_fallback_handles_retained_coverage_without_group(self):
        bad = item(*PASSING[0])
        bad.pop("group")
        self.assertEqual(filter_published_stories(cluster_items([bad], NOW), NOW), [])

    def test_removed_primary_url_remains_an_alias_of_surviving_story(self):
        bad = item(*PASSING[0])
        good = item(*GENUINE[0], url="https://press.example/genuine")
        old = cluster_items([bad], NOW)[0]
        # A historical cluster can contain observations no longer admitted.
        old["coverage"].append(good)
        cleaned = filter_published_stories([old], NOW)[0]
        self.assertEqual(cleaned["url"], good["url"])
        self.assertNotEqual(cleaned["id"], old["id"])
        self.assertIn(old["id"], cleaned["aliases"])


if __name__ == "__main__":
    unittest.main()
