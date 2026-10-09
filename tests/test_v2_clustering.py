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

    def test_cross_publisher_apple_full_disk_access_merges_multiple_outlets(self):
        items = [
            coverage("techcrunch", "https://techcrunch.example/apple-fda", publisher="techcrunch",
                     title="Apple says it’s tightening macOS ‘Full Disk Access’ controls due to new risks from AI agents"),
            coverage("the-verge", "https://theverge.example/apple-disk", publisher="the-verge",
                     title="Apple will limit Mac disk access as AI agents ‘substantially’ increase risk"),
            coverage("ars-technica", "https://arstechnica.example/apple-mac", publisher="ars-technica",
                     title="Apple changes full-disk access permissions to curb abuse from AI agents"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 3)

    def test_cross_publisher_product_variant_launch_merges(self):
        items = [
            coverage("openai", "https://openai.example/sol", publisher="openai", kind="model",
                     title="Introducing GPT-6.1 Sol"),
            coverage("simon-willison", "https://simon.example/sol", publisher="simon-willison", kind="product",
                     title="GPT 6.1 Sol: Near-Astra intelligence for a fifth of the price"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)

    def test_cross_publisher_chegg_penske_antitrust_merges(self):
        items = [
            coverage("ars-technica", "https://arstechnica.example/chegg", publisher="ars-technica",
                     title="Judge dismisses Chegg and Penske antitrust lawsuits targeting Google AI search"),
            coverage("hacker-news", "https://hn.example/chegg", publisher="hacker-news",
                     title="US judge dismisses Chegg, Penske antitrust suits over Google AI Overviews"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)

    def test_cross_publisher_huggingface_hack_lawsuit_merges(self):
        items = [
            coverage("ars-technica", "https://arstechnica.example/hf-hack", publisher="ars-technica",
                     title='"An AI did it" is no defense, says nonprofit suing OpenAI over Hugging Face hack'),
            coverage("hacker-news", "https://hn.example/hf-hack", publisher="hacker-news",
                     title="AI safety advocates sue OpenAI over Hugging Face hack under CA anti-hacking law"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)

    def test_openai_ipo_delay_and_model_cancellation_stay_apart(self):
        items = [
            coverage("ars-technica", "https://arstechnica.example/ipo", publisher="ars-technica",
                     title="OpenAI delays IPO over AI safety concerns"),
            coverage("hacker-news", "https://hn.example/scraps", publisher="hacker-news",
                     title="OpenAI Scraps Release of New AI Model over Safety Concerns"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 2)

    def test_conflicting_model_subvariants_stay_apart(self):
        items = [
            coverage("openai-sol", "https://openai.example/sol", publisher="openai",
                     title="Introducing GPT-6 Sol"),
            coverage("openai-luna", "https://openai.example/luna", publisher="openai",
                     title="Introducing GPT-6 Luna"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 2)

    def test_independent_papers_stay_apart(self):
        items = [
            coverage("paper1", "https://arxiv.org/abs/2609.11111", kind="paper",
                     title="Diffusion Transformers for Video Generation"),
            coverage("paper2", "https://arxiv.org/abs/2609.22222", kind="paper",
                     title="Diffusion Transformers for Video Generation"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 2)

    def test_cross_publisher_meta_muse_gadgets_merges(self):
        items = [
            coverage("the-verge", "https://theverge.example/muse", publisher="the-verge",
                     title="Meta open sources code to let you make Muse AI gadgets"),
            coverage("techcrunch", "https://techcrunch.example/muse", publisher="techcrunch",
                     title="Meta wants your next gadget to be Muse-infused"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)

    def test_real_reflection_beam_coverage_merges_across_three_outlets(self):
        items = [
            coverage("techcrunch", "https://techcrunch.example/reflection-beam", publisher="techcrunch",
                     title="Reflection debuts Beam, an open-weight AI model to rival Chinese models at lower compute cost",
                     published_at="2026-10-05T19:33:53Z"),
            coverage("semafor", "https://semafor.example/reflection-beam", publisher="semafor",
                     title="Reflection AI unveils an open-source Western answer to Chinese labs",
                     published_at="2026-10-05T19:01:43Z"),
            coverage("bloomberg", "https://bloomberg.example/reflection-beam", publisher="bloomberg",
                     title="Nvidia-Backed Reflection Unveils Open AI Model, Taking on China",
                     published_at="2026-10-05T19:00:00Z"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 3)

    def test_real_meta_muse_ipad_headlines_merge(self):
        items = [
            coverage("techcrunch", "https://techcrunch.example/muse-ipad", publisher="techcrunch",
                     title="Meta’s Muse launches on iPad just a month after its mobile debut",
                     published_at="2026-10-07T12:00:00Z"),
            coverage("the-verge", "https://theverge.example/muse-ipad", publisher="the-verge",
                     title="Muse launches on the iPad", published_at="2026-10-07T12:00:00Z"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)

    def test_real_haiku_and_opus_launches_remain_separate(self):
        items = [
            coverage("anthropic-haiku", "https://anthropic.example/haiku", publisher="anthropic",
                     title="Introducing Claude Haiku 5.5", published_at="2026-10-07T12:00:00Z"),
            coverage("anthropic-opus", "https://anthropic.example/opus", publisher="anthropic",
                     title="Introducing Claude Opus 5.5", published_at="2026-10-07T12:00:00Z"),
        ]
        self.assertEqual(len(cluster_items(items, NOW)), 2)

    def test_real_openai_coverage_of_unrelated_events_stays_separate(self):
        items = [
            coverage("ars-technica", "https://ars-technica.example/ipo", publisher="ars-technica",
                     title="OpenAI delays IPO over AI safety concerns", published_at="2026-10-07T12:00:00Z"),
            coverage("the-verge", "https://the-verge.example/funding", publisher="the-verge",
                     title="OpenAI raises new multibillion funding round", published_at="2026-10-07T12:00:00Z"),
        ]
        self.assertEqual(len(cluster_items(items, NOW)), 2)

    def test_entity_with_single_shared_specific_token_stays_apart(self):
        items = [
            coverage("the-verge", "https://theverge.example/emp", publisher="the-verge",
                     title="An OpenAI employee shared thoughts on company culture"),
            coverage("techcrunch", "https://techcrunch.example/fund", publisher="techcrunch",
                     title="OpenAI raises new multibillion funding round"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 2)

    def test_no_entity_shared_common_terms_stays_apart(self):
        items = [
            coverage("the-verge", "https://theverge.example/dc1", publisher="the-verge",
                     title="If a data center is camouflaged in the woods, will anyone hate it?"),
            coverage("techcrunch", "https://techcrunch.example/dc2", publisher="techcrunch",
                     title="Space data centers face launch delays"),
        ]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 2)
