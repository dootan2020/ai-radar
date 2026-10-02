"""Clustering preserves provenance and refuses ambiguous synthetic stories."""

import unittest

from radar.clustering import canonical_url, cluster_items
if __package__:
    from .test_v2_support import NOW, coverage
else:
    from test_v2_support import NOW, coverage


class CanonicalUrlTests(unittest.TestCase):
    def test_tracking_fragment_default_port_and_host_normalize(self):
        self.assertEqual(
            canonical_url("HTTPS://Example.ORG:443/Story/?utm_source=mail&fbclid=x#part"),
            canonical_url("https://example.org/Story"))

    def test_semantic_queries_and_path_case_are_not_discarded(self):
        for first, second in [
            ("https://news.ycombinator.com/item?id=12", "https://news.ycombinator.com/item?id=13"),
            ("https://example.org/post?version=1", "https://example.org/post?version=2"),
            ("https://example.org/Model", "https://example.org/model"),
        ]:
            with self.subTest(first=first):
                self.assertNotEqual(canonical_url(first), canonical_url(second))

    def test_arxiv_pdf_abs_share_identity_but_versions_remain_distinct(self):
        self.assertEqual(canonical_url("https://arxiv.org/pdf/2609.12345v2.pdf"),
                         canonical_url("https://arxiv.org/abs/2609.12345v2"))
        self.assertNotEqual(canonical_url("https://arxiv.org/abs/2609.12345v2"),
                            canonical_url("https://arxiv.org/abs/2609.12345v3"))

    def test_unsafe_and_malformed_urls_are_rejected(self):
        for url in [None, "", "javascript:alert(1)", "file:///tmp/a", "https://user:pass@example.org/a"]:
            with self.subTest(url=url):
                self.assertIsNone(canonical_url(url))


class ClusterTests(unittest.TestCase):
    def test_duplicate_publisher_feeds_preserve_coverage_without_spread_inflation(self):
        items = [coverage("anthropic-news", publisher="anthropic"),
                 coverage("anthropic-mirror", publisher="anthropic"),
                 coverage("press", publisher="independent-press")]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)
        self.assertEqual({row["source"] for row in stories[0]["coverage"]},
                         {row["source"] for row in items})

    def test_normalized_url_merges_even_with_different_titles(self):
        items = [coverage(), coverage("b", "https://example.org/article?utm_source=x#top",
                                      title="A completely different headline")]
        self.assertEqual(len(cluster_items(items, NOW)), 1)

    def test_cross_url_strong_title_match_keeps_both_original_links(self):
        items = [coverage(), coverage("b", "https://press.example/article")]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual({item["url"] for item in stories[0]["coverage"]},
                         {item["url"] for item in items})

    def test_conflicting_versions_do_not_merge_despite_shared_words(self):
        items = [coverage(title="Introducing Orion 5.1 neural reasoning architecture released today"),
                 coverage("b", "https://other.example/story",
                          title="Introducing Orion 5.2 neural reasoning architecture released today")]
        self.assertEqual(len(cluster_items(items, NOW)), 2)

    def test_recap_and_keynote_for_same_named_dated_event_share_a_story(self):
        # Titles observed in checked-in snapshot; URLs/dates are synthetic.
        items = [coverage(title="DevDay 2026 Recap"),
                 coverage("video", "https://video.example/keynote", kind="video",
                          title="OpenAI DevDay 2026 Keynote (FULL)")]
        self.assertEqual(len(cluster_items(items, NOW)), 1)

    def test_same_named_event_in_different_years_remains_separate(self):
        items = [coverage(title="DevDay 2026 Recap"),
                 coverage("video", "https://video.example/keynote", kind="video",
                          title="OpenAI DevDay 2025 Keynote (FULL)")]
        self.assertEqual(len(cluster_items(items, NOW)), 2)

    def test_unknown_or_far_apart_dates_do_not_establish_cross_url_matches(self):
        for timestamp in [None, "2026-09-28T11:00:00Z"]:
            with self.subTest(timestamp=timestamp):
                items = [coverage(), coverage("b", "https://other.example/story", published_at=timestamp)]
                self.assertEqual(len(cluster_items(items, NOW)), 2)

    def test_short_generic_headline_does_not_establish_cross_url_identity(self):
        items = [coverage(title="AI model"),
                 coverage("b", "https://other.example/story", title="AI model")]
        self.assertEqual(len(cluster_items(items, NOW)), 2)

    def test_pairwise_matching_prevents_transitive_bridge_cluster(self):
        titles = ["alpha beta gamma delta epsilon zeta theta lambda",
                  "alpha beta gamma delta epsilon zeta theta sigma",
                  "alpha beta gamma delta epsilon zeta omega sigma"]
        items = [coverage(str(index), f"https://example.org/{index}", title=title)
                 for index, title in enumerate(titles)]
        stories = cluster_items(items, NOW, threshold=0.75)
        self.assertGreater(len(stories), 1)
        self.assertEqual(sum(len(story["coverage"]) for story in stories), 3)

    def test_metrics_and_observation_time_do_not_change_story_identity(self):
        before = cluster_items([coverage(metrics={"points": 10})], NOW)[0]
        after = cluster_items([coverage(metrics={"points": 500},
                                        observed_at="2026-10-02T13:00:00Z")], NOW)[0]
        self.assertEqual(before["id"], after["id"])

    def test_different_arxiv_versions_do_not_remerge_by_identical_titles(self):
        items = [coverage(url="https://arxiv.org/abs/2610.12345v2"),
                 coverage("b", "https://arxiv.org/pdf/2610.12345v3.pdf")]
        self.assertEqual(len(cluster_items(items, NOW)), 2)
