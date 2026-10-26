"""Importance and real editorial event regressions."""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from radar.clustering import cluster_items, merge_repeated_events, titles_match
from radar.ranking import importance_of
from radar.reader_priority import ordered_stories
from radar.summary_pipeline import fetch_story_article, is_in_ranking_window


DATE = "2026-10-22T12:00:00Z"


def item(title, summary="", url="https://example.org/news", kind="product"):
    return {"title": title, "summary": summary, "url": url, "kind": kind,
            "published_at": DATE, "source": "outlet", "publisher": "outlet", "id": title}


class ImportanceTests(unittest.TestCase):
    def test_independent_reporting_official_origin_and_numbers_raise_weight(self):
        now = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)
        base = item("Company launches an AI agent")
        official = item("Company launches an AI agent with 20% lower cost",
                        url="https://company.example/news")
        official["group"] = "lab"
        one = {"title": base["title"], "kind": "product", "published_at": DATE, "coverage": [base]}
        two = {**one, "coverage": [base, {**official, "publisher": "company"}]}
        first, _, _ = importance_of(one, now)
        second, tier, reason = importance_of(two, now)
        self.assertGreater(second, first)
        self.assertEqual(tier, "top")
        self.assertIn("2 nguồn độc lập", reason)
        self.assertIn("có số liệu", reason)

    def test_queue_uses_importance_before_legacy_hot_and_worth(self):
        stories = [{"id": "low", "published_at": DATE, "importance_weight": 30,
                    "hot_score": 99, "worth_score": 99},
                   {"id": "top", "published_at": DATE, "importance_weight": 70,
                    "hot_score": 0, "worth_score": 0}]
        payload = {"generated_at": "2026-10-22T13:00:00Z", "stories": stories}
        self.assertEqual([s["id"] for s in ordered_stories(payload, [])[0]], ["top", "low"])


class EventPairsTests(unittest.TestCase):
    def test_audit_pairs_merge(self):
        pairs = [
            (item("OpenAI now trains its frontier AI models with no internet access",
                  "OpenAI built an offline testing environment for training."),
             item("Securing our frontier model training environment",
                  "OpenAI strengthened containment for frontier model training, including offline environments.")),
            (item("1Password launches a way for AI agents to log in on your behalf without seeing your password",
                  "Agents log into accounts without private credentials."),
             item("1Password lets AI agents use your passwords without seeing them",
                  "A feature allows AI agents to sign into accounts without seeing passwords.")),
            (item("DeepSeek reportedly raises $15 billion ahead of potential Shanghai IPO",
                  "DeepSeek completed a $15 billion private funding round."),
             item("China's AI leader DeepSeek raises $15B",
                  "DeepSeek increased its financing target ahead of the funding round.")),
            (item("Introducing Claude Duet", "Claude Duet research preview is available by waitlist."),
             item("Claude Duet app is Anthropic’s bet on agents",
                  "Claude Duet is available through waitlist for Pro and Max users.")),
            (item("Introducing Claude Duet", "Claude Duet research preview is available by waitlist."),
             item("Anthropic takes on Muse with Claude Duet, its new AI agent",
                  "Anthropic announced Claude Duet, a research preview.")),
            (item("Claude Duet app is Anthropic’s bet on agents",
                  "Claude Duet is available through waitlist for Pro and Max users."),
             item("Anthropic takes on Muse with Claude Duet, its new AI agent",
                  "Anthropic announced Claude Duet, a research preview.")),
            (item("Recursive launches Flint, a laptop coding model it says was largely built by AI",
                  "Recursive released Flint, a free laptop coding model.",
                  "https://techcrunch.com/recursive-launches-flint-laptop-model"),
             item("This Startup Is All In on Recursive Self-Improvement. Its Latest Model Is Scary Good",
                  "Recursive makes the case for using AI to build AI.",
                  "https://wired.com/recursive-self-improvement-flint-latest-model")),
        ]
        dates = [
            ("2026-10-23T21:11:07Z", "2026-10-23T10:00:00Z"),
            ("2026-10-22T19:07:09Z", "2026-10-22T13:00:00Z"),
            ("2026-10-23T13:51:43Z", "2026-10-22T10:30:40Z"),
            ("2026-10-21T00:00:00Z", "2026-10-22T13:53:26Z"),
            ("2026-10-21T00:00:00Z", "2026-10-21T19:53:20Z"),
            ("2026-10-22T13:53:26Z", "2026-10-21T19:53:20Z"),
            ("2026-10-21T20:27:41Z", "2026-10-21T16:00:00Z"),
        ]
        for (left, right), (left_at, right_at) in zip(pairs, dates):
            left["published_at"], right["published_at"] = left_at, right_at
            right["publisher"] = "second-outlet"
            right["source"] = "second-outlet"
            with self.subTest(left=left["title"], right=right["title"]):
                self.assertTrue(titles_match(left, right))

    def test_same_company_distinct_event_stays_apart(self):
        self.assertFalse(titles_match(
            item("OpenAI launches a new model", "OpenAI releases Model X"),
            item("OpenAI raises $15 billion", "OpenAI closes a funding round")))

    def test_release_articles_merge_and_model_artifact_links(self):
        rows = [
            item("Recursive launches Flint, a laptop coding model it says was largely built by AI",
                 "Recursive released Flint, a free laptop coding model.",
                 "https://techcrunch.com/recursive-launches-flint-laptop-model", "research"),
            item("This Startup Is All In on Recursive Self-Improvement. Its Latest Model Is Scary Good",
                 "Recursive makes the case for using AI to build AI.",
                 "https://wired.com/recursive-self-improvement-flint-latest-model", "other"),
            item("RecursiveSI/flint", "", "https://huggingface.co/RecursiveSI/flint", "model"),
        ]
        for index, row in enumerate(rows):
            row["id"] = str(index)
            row["source"] = row["publisher"] = str(index)
            row["group"] = "repository" if index == 2 else "press"
        stories = merge_repeated_events(cluster_items(rows, datetime(2026, 10, 22, 13, tzinfo=timezone.utc)))
        self.assertEqual(len(stories), 2)
        news = next(story for story in stories if story["kind"] != "model")
        artifact = next(story for story in stories if story["kind"] == "model")
        self.assertEqual(len(news["coverage"]), 2)
        self.assertEqual(artifact["related_story_id"], news["id"])
        self.assertEqual(news["related_artifacts"][0]["story_id"], artifact["id"])


class SummarySourceTests(unittest.TestCase):
    def test_unreadable_representative_uses_independent_coverage(self):
        story = {"url": "https://first.example/story", "coverage": [
            {"url": "https://first.example/story"}, {"url": "https://second.example/story"}]}
        def fetch(candidate, **kwargs):
            if candidate["url"].startswith("https://first"):
                return "", "robots"
            kwargs["details"]["links"] = []
            return "source body", None
        details = {}
        with patch("radar.summary_pipeline.fetch_article_result", side_effect=fetch) as mocked:
            text, reason, url = fetch_story_article(story, {}, details)
        self.assertEqual((text, reason, url), ("source body", None, "https://second.example/story"))
        self.assertEqual(mocked.call_count, 2)

    def test_new_coverage_keeps_old_announcement_in_summary_window(self):
        generated = datetime(2026, 10, 26, 11, tzinfo=timezone.utc)
        story = {"published_at": "2026-10-23T10:00:00Z",
                 "latest_coverage_at": "2026-10-23T21:00:00Z"}
        self.assertTrue(is_in_ranking_window(story, generated, 72))


if __name__ == "__main__":
    unittest.main()
