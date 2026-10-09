"""Clustering preserves provenance and refuses ambiguous synthetic stories."""

import json
import unittest
from pathlib import Path

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
    def test_cross_platform_person_sources_count_once(self):
        for sources, expected in (
            (["simon-willison", "bluesky-simonwillison", "x-simonw"], 1),
            (["bluesky-emollick", "x-emollick"], 1),
        ):
            rows = [coverage(source, "https://example.org/shared-event",
                             publisher=("x:@" + source[2:] if source.startswith("x-") else
                                        "bluesky" if source.startswith("bluesky-") else source),
                             title="OpenAI decisions on model release") for source in sources]
            self.assertTrue(all("entity" not in row for row in rows))
            for row in rows:
                if row["source"].startswith("x-"):
                    row["linked_url"] = "https://example.org/shared-event"
            story = cluster_items(rows, NOW)[0]
            self.assertEqual(story["source_count"], expected)

    def test_lab_blog_and_official_x_share_entity_but_independent_sources_do_not(self):
        for lab_source, handle in (
            ("qwen-blog", "alibaba_qwen"),
            ("meta-newsroom", "aiatmeta"),
        ):
            lab = "qwen" if lab_source == "qwen-blog" else "meta"
            rows = [coverage(lab_source, "https://example.org/lab-launch", publisher=lab,
                             title="Qwen launches a model"),
                    coverage("x-" + handle, "https://example.org/post", publisher="x:@" + handle,
                             linked_url="https://example.org/lab-launch", title="Qwen launches a model")]
            story = cluster_items(rows, NOW)[0]
            self.assertEqual(story["source_count"], 1)

        independent = [coverage("source-a"), coverage("source-b"), coverage("source-c")]
        story = cluster_items(independent, NOW)[0]
        self.assertEqual(story["source_count"], 3)

    def test_unrelated_x_posts_do_not_merge_on_entities_or_generic_words(self):
        titles = [
            "Anthropic commits $150 million for scientific research",
            "Claude Startups pauses its application program",
            "Artificial Analysis launches a cyber index",
            "South Korean bank hack comment from an analyst",
            "Claude announces a new feature for users",
            "Claude shares a separate research update",
            "TestingCatalog publishes its daily AI brief",
        ]
        items = [coverage(f"x-account-{index}", f"https://x.com/account{index}/status/{index}",
                          publisher=f"x:@account{index}",
                          group="forum", kind="social", title=title, summary=title)
                 for index, title in enumerate(titles)]
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), len(titles))
        self.assertTrue(all(len(story["coverage"]) == 1 for story in stories))

    def test_x_posts_merge_on_same_link_or_quote_but_not_title_similarity(self):
        linked = [
            coverage("x-a", "https://x.com/a/status/1", publisher="x:@a",
                     kind="social", linked_url="https://news.example/story", title="OpenAI GPT update"),
            coverage("x-b", "https://x.com/b/status/2", publisher="x:@b",
                     kind="social", linked_url="https://news.example/story?utm_source=x", title="Different words"),
        ]
        self.assertEqual(len(cluster_items(linked, NOW)), 1)
        identical = [coverage("x-a", "https://x.com/a/status/5", publisher="x:@a",
                              kind="social", summary="The same exact post"),
                     coverage("x-b", "https://x.com/b/status/6", publisher="x:@b",
                              kind="social", summary=" The same exact post ")]
        self.assertEqual(len(cluster_items(identical, NOW)), 1)

        quoted = [coverage("x-a", "https://x.com/a/status/3", publisher="x:@a",
                           kind="social", title="Shared announcement", summary="Shared announcement",
                           post_id="3"),
                  coverage("x-b", "https://x.com/b/status/4", publisher="x:@b",
                           kind="social", title="A quote of the announcement", quoted_post_id="3")]
        self.assertEqual(len(cluster_items(quoted, NOW)), 1)

    def test_stored_x_coverage_without_publisher_group_counts_as_one_source(self):
        items = [coverage("x-a", "https://x.com/a/status/1", publisher="x:@a",
                          kind="social", title="Same linked announcement"),
                 coverage("x-b", "https://x.com/b/status/2", publisher="x:@b",
                          kind="social", title="Different title", canonical_url="https://press.example/story")]
        items[0]["linked_url"] = "https://press.example/story"
        items[1]["linked_url"] = "https://press.example/story"
        for item in items:
            item.pop("publisher_group", None)
        story = cluster_items(items, NOW)[0]
        self.assertEqual(story["source_count"], 1)

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

    def test_research_paper_does_not_merge_with_non_paper_on_shared_phrase(self):
        paper = coverage("hf-papers", "https://arxiv.org/abs/2610.05750",
                         publisher="huggingface",
                         title="Beyond Semantic Similarity: Performance and Costs of Agentic Retrieval for Complex Tasks")
        blog = coverage("amazon", "https://aws.amazon.com/blogs/agentic-retrieval",
                        publisher="amazon", kind="other",
                        title="Agentic retrieval with LangChain and Amazon Bedrock Knowledge Bases")
        self.assertEqual(len(cluster_items([paper, blog], NOW)), 2)

    def test_research_paper_does_not_merge_with_non_paper_jev_coverage(self):
        news = coverage("hacker-news", "https://news.ycombinator.com/item?id=jev",
                        publisher="hacker-news", kind="other",
                        title="Decision models like Jev don't beat LLM-as-a-judge or traditional classifiers")
        paper = coverage("hf-papers", "https://arxiv.org/abs/2610.02076",
                         publisher="huggingface",
                         title="LLM-as-Jev: LLMs Are Already Jev-Style Decision Models -- When and How to Fine-Tune Them")
        self.assertEqual(len(cluster_items([news, paper], NOW)), 2)

    def test_paper_and_non_paper_with_same_canonical_url_still_merge(self):
        url = "https://example.org/research"
        paper = coverage("huggingface", url, publisher="huggingface", kind="paper", title="Research paper")
        mirror = coverage("press", url + "?utm_source=press", publisher="press", kind="other", title="Press coverage")
        stories = cluster_items([paper, mirror], NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 2)

    def test_reviewed_non_paper_doubtful_clusters_keep_their_existing_matches(self):
        examples = [
            (("wired", "OpenAI Wants Its New Agent to Run Your Life. Mine Said It Loved Me"),
             ("the-verge", "Can you trust Meta’s Muse or OpenAI’s Dots to run your life?")),
            (("hacker-news", "South Korea says AI agents appear to have been used to hack the country's banks"),
             ("semafor", "Companies in Japan, South Korea hit by major cyberattacks")),
        ]
        for index, (left, right) in enumerate(examples):
            with self.subTest(index=index):
                items = [coverage(left[0], f"https://left.example/{index}", publisher=left[0],
                                  title=left[1]),
                         coverage(right[0], f"https://right.example/{index}", publisher=right[0],
                                  title=right[1])]
                self.assertEqual(len(cluster_items(items, NOW)), 1)

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

    def test_real_deepseek_event_and_financing_headlines_stay_separate(self):
        items = [
            coverage("hacker-news", "https://hn.example/deepseek-flash", publisher="hacker-news",
                     title="Why isn't the industry freaking out about DeepSeek 4.1 Flash?",
                     published_at="2026-10-08T00:00:00Z"),
            coverage("bloomberg", "https://bloomberg.example/deepseek-funding", publisher="bloomberg",
                     title="Billions Pour Into OpenAI, DeepSeek Ahead of IPOs",
                     published_at="2026-10-08T00:00:00Z"),
        ]
        self.assertEqual(len(cluster_items(items, NOW)), 2)

    def test_real_build_verbs_and_silicon_valley_titles_stay_separate(self):
        items = [
            coverage("amazon", "https://amazon.example/concierge", publisher="amazon",
                     title="Build a voice travel concierge with Amazon Bedrock AgentCore"),
            coverage("lobsters", "https://lobsters.example/burn", publisher="lobsters",
                     title="Burn 0.22.0: Faster Builds, Smaller Binaries"),
            coverage("bloomberg", "https://bloomberg.example/silicon-island", publisher="bloomberg",
                     title="Malaysia Builds a New Silicon Island to Tap AI Boom"),
        ]
        self.assertEqual(len(cluster_items(items, NOW)), 3)

    def test_reviewed_false_clusters_do_not_survive_as_complete_merges(self):
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads((root / "tests" / "fixtures" / "reviewed-cluster-members.json").read_text(encoding="utf-8"))
        reviewed = fixture["reviewed_clusters"]
        owner = {}
        for index, story in enumerate(cluster_items(fixture["items"], fixture["generated_at"])):
            for item in story["coverage"]:
                owner[(item.get("publisher"), item.get("title"))] = index

        false_clusters = [cluster for cluster in reviewed if cluster["label"] == "FALSE"]
        self.assertEqual(len(false_clusters), 68)
        for cluster in false_clusters:
            keys = [(member["publisher"], member["title"]) for member in cluster["members"]]
            cluster_ids = {owner.get(key) for key in keys}
            with self.subTest(cluster=cluster["cluster_index"], title=cluster["title"]):
                self.assertNotIn(None, cluster_ids)
                self.assertGreater(len(cluster_ids), 1)

        doubtful_decisions = {}
        for cluster in reviewed:
            if cluster["label"] != "DOUBTFUL":
                continue
            keys = [(member["publisher"], member["title"]) for member in cluster["members"]]
            cluster_ids = {owner.get(key) for key in keys}
            doubtful_decisions[cluster["cluster_index"]] = (
                "merge" if None not in cluster_ids and len(cluster_ids) == 1 else "split")
        self.assertEqual(doubtful_decisions, {
            17: "split", 26: "split", 39: "split", 56: "split",
            69: "split", 78: "split", 91: "split", 95: "split",
        })

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
