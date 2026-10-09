"""Explicitly synthetic RSS/JSON cases for new public-source collectors."""

import json
import unittest

from radar.community import parse_hn, parse_lobsters
from radar.clustering import cluster_items
from radar.discovery import parse_bluesky, parse_github, parse_hf_trending, parse_papers
from radar.v2feeds import parse_feed
from radar.ranking import rank_stories
if __package__:
    from .test_v2_support import NOW, OBSERVED
else:
    from test_v2_support import NOW, OBSERVED

SOURCE = {"id": "synthetic-source", "name": "Synthetic source", "publisher": "synthetic",
          "lab": "", "group": "forum", "kind": "json", "url": "https://feed.example/rss"}


class FreeSocialSourceTests(unittest.TestCase):
    def test_bluesky_author_feed_filters_non_ai_and_preserves_engagement(self):
        from pathlib import Path
        body = (Path(__file__).parent / "fixtures" / "bluesky-author-feed.json").read_text(encoding="utf-8")
        source = SOURCE | {"id": "bluesky-simonwillison", "group": "social",
                           "handle": "simonwillison.net", "filter_ai": True}
        rows = parse_bluesky(body, source, OBSERVED)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://bsky.app/profile/simonwillison.net/post/3lxyz")
        self.assertEqual(rows[0]["metrics"], {"likes": 40, "reposts": 8, "replies": 3})
        self.assertEqual(rows[0]["published_at"], "2026-10-02T11:00:00Z")

    def test_malformed_public_source_payloads_fail_honestly(self):
        with self.assertRaises(ValueError):
            parse_bluesky("{}", SOURCE, OBSERVED)


def hn_row(**changes):
    row = {"objectID": "123", "title": "AI neural reasoning release", "url": "https://lab.example/release",
           "created_at": "2026-10-02T11:00:00Z", "points": 30, "num_comments": 4}
    row.update(changes)
    return row


class CommunityTests(unittest.TestCase):
    def test_hn_retains_actual_counters_and_separates_discussion_from_target(self):
        item = parse_hn(json.dumps({"hits": [hn_row()]}), SOURCE, OBSERVED)[0]
        self.assertEqual(item["url"], "https://lab.example/release")
        self.assertEqual(item["discussion_url"], "https://news.ycombinator.com/item?id=123")
        self.assertEqual(item["metrics"], {"points": 30, "comments": 4})

    def test_hn_self_post_has_safe_thread_link_and_general_news_is_excluded(self):
        rows = [hn_row(url=None), hn_row(objectID="124", title="Gardening a small city balcony")]
        items = parse_hn(json.dumps({"hits": rows}), SOURCE, OBSERVED)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], items[0]["discussion_url"])

    def test_two_hn_endpoints_do_not_count_as_independent_publishers(self):
        body = json.dumps({"hits": [hn_row()]})
        items = []
        for id_ in ["hn-front", "hn-ai"]:
            items.extend(parse_hn(body, SOURCE | {"id": id_, "publisher": "hacker-news"}, OBSERVED))
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_count"], 1)
        self.assertEqual(len(stories[0]["coverage"]), 2)

    def test_hn_distinct_threads_same_target_keep_individual_observation_identity(self):
        items = parse_hn(json.dumps({"hits": [hn_row(objectID="123"), hn_row(objectID="456")]}), SOURCE, OBSERVED)
        self.assertEqual(len({item["id"] for item in items}), 2)
        stories = cluster_items(items, NOW)
        self.assertEqual(len(stories), 1)
        self.assertEqual(len(stories[0]["coverage"]), 2)
        self.assertEqual(stories[0]["source_count"], 1)

    def test_lobsters_distinct_threads_same_target_keep_individual_observation_identity(self):
        rows = [{"title": "AI release", "url": "https://lab.example/release", "tags": ["ai"],
                 "created_at": "2026-10-02T11:00:00Z", "score": 3,
                 "comments_url": "https://lobste.rs/s/" + id_} for id_ in ["abc", "def"]]
        items = parse_lobsters(json.dumps(rows), SOURCE, OBSERVED)
        self.assertEqual(len({item["id"] for item in items}), 2)
        self.assertEqual(len(cluster_items(items, NOW)[0]["coverage"]), 2)

    def test_new_hn_thread_cannot_inherit_old_thread_velocity_for_same_target(self):
        before = parse_hn(json.dumps({"hits": [hn_row(objectID="123", points=1)]}),
                          SOURCE, "2026-10-02T11:00:00Z")
        after = parse_hn(json.dumps({"hits": [hn_row(objectID="456", points=20)]}), SOURCE, OBSERVED)
        previous = {"schema_version": 2, "generated_at": "2026-10-02T11:00:00Z",
                    "stories": cluster_items(before, NOW)}
        story = rank_stories(cluster_items(after, NOW), NOW, previous)[0]
        self.assertIsNone(story["hot_signals"]["velocity_per_hour"])

    def test_hn_missing_malformed_and_nonfinite_metrics_remain_null(self):
        for value in [None, True, -1, "ten", "10", {}, [], float("nan"), float("inf")]:
            with self.subTest(value=value):
                item = parse_hn(json.dumps({"hits": [hn_row(points=value, num_comments=value)]}),
                                SOURCE, OBSERVED)[0]
                self.assertEqual(item["metrics"], {"points": None, "comments": None})
                json.dumps(item, allow_nan=False)

    def test_lobsters_ai_tag_and_zero_measurement_are_preserved(self):
        body = [{"title": "A new reasoning technique", "url": "https://lab.example/paper",
                 "comments_url": "https://lobste.rs/s/example", "tags": ["ai"],
                 "created_at": "2026-10-02T11:00:00Z", "score": 0, "comment_count": None}]
        item = parse_lobsters(json.dumps(body), SOURCE, OBSERVED)[0]
        self.assertEqual(item["metrics"], {"score": 0, "comments": None})
        self.assertEqual(item["discussion_url"], "https://lobste.rs/s/example")

    def test_wrong_json_shapes_fail_instead_of_empty_success(self):
        for parse, invalid in [(parse_hn, []), (parse_lobsters, {}), (parse_papers, {}),
                               (parse_hf_trending, {}), (parse_github, [])]:
            with self.subTest(parser=parse.__name__), self.assertRaises(ValueError):
                parse(json.dumps(invalid), SOURCE, OBSERVED)


class DiscoveryTests(unittest.TestCase):
    def test_paper_retains_original_publication_and_real_votes(self):
        body = [{"paper": {"id": "2610.12345", "title": "Synthetic neural paper", "upvotes": 8,
                           "publishedAt": "2026-10-01T10:00:00Z"},
                 "publishedAt": "2026-10-02T10:00:00Z", "numComments": 2}]
        item = parse_papers(json.dumps(body), SOURCE, OBSERVED)[0]
        self.assertEqual(item["published_at"], "2026-10-01T10:00:00Z")
        self.assertEqual(item["metrics"], {"upvotes": 8, "comments": 2})
        self.assertEqual(item["url"], "https://arxiv.org/abs/2610.12345")
        self.assertEqual(item["discussion_url"], "https://huggingface.co/papers/2610.12345")
        self.assertEqual(item["media"], [])

    def test_hf_repository_created_time_is_not_called_a_release(self):
        body = [{"id": "synthetic/model", "createdAt": "2025-01-01T10:00:00Z",
                 "trendingScore": 2.5, "likes": None, "downloads": float("inf")}]
        item = parse_hf_trending(json.dumps(body), SOURCE, OBSERVED)[0]
        self.assertEqual(item["time_basis"], "repository_created")
        self.assertEqual(item["published_at"], "2025-01-01T10:00:00Z")
        self.assertEqual(item["metrics"], {"trending_score": 2.5, "likes": None, "downloads": None})

    def test_github_actual_counts_and_missing_created_at_stay_honest(self):
        body = {"items": [{"full_name": "synthetic/repo", "html_url": "https://github.com/synthetic/repo",
                           "stargazers_count": 42, "forks_count": None}]}
        item = parse_github(json.dumps(body), SOURCE, OBSERVED)[0]
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["metrics"]["stars"], 42)
        self.assertIsNone(item["metrics"]["forks"])


class PodcastFeedTests(unittest.TestCase):
    def parse(self, extra="", **changes):
        source = SOURCE | {"group": "podcast"} | changes
        body = '<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item>' \
               '<title>AI interview</title><link>https://podcast.example/episode</link>' \
               '<pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate>' + extra + '</item></channel></rss>'
        return parse_feed(body, source, OBSERVED)

    def test_actual_enclosure_and_thumbnail_are_preserved(self):
        item = self.parse('<enclosure url="https://cdn.example/audio.mp3" type="audio/mpeg"/>'
                          '<media:thumbnail url="https://cdn.example/cover.jpg"/>')[0]
        self.assertEqual(item["kind"], "podcast")
        self.assertEqual(item["media"], [
            {"url": "https://cdn.example/audio.mp3", "type": "audio", "mime_type": "audio/mpeg"},
            {"url": "https://cdn.example/cover.jpg", "type": "image", "mime_type": None}])

    def test_missing_or_unsafe_media_never_produces_guessed_links(self):
        for extra in ["", '<enclosure url="javascript:alert(1)" type="audio/mpeg"/>']:
            with self.subTest(extra=extra):
                item = self.parse(extra)[0]
                self.assertEqual(item["media"], [])
                self.assertEqual(item["url"], "https://podcast.example/episode")

    def test_atom_enclosure_and_episode_link_do_not_overwrite_each_other(self):
        body = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI interview</title>' \
               '<link rel="alternate" href="https://podcast.example/episode"/>' \
               '<link rel="enclosure" href="https://cdn.example/audio.ogg" type="audio/ogg"/>' \
               '</entry></feed>'
        item = parse_feed(body, SOURCE | {"group": "podcast"}, OBSERVED)[0]
        self.assertEqual(item["url"], "https://podcast.example/episode")
        self.assertEqual(item["media"][0]["url"], "https://cdn.example/audio.ogg")
        self.assertIsNone(item["published_at"])

    def test_v2_feed_ambiguous_dates_remain_unknown_without_invented_utc(self):
        for value in ["2026-10-02", "2026-10-02T11:30:00", "Fri, 02 Oct 2026 11:30:00"]:
            with self.subTest(value=value):
                body = '<rss><channel><item><title>AI interview</title><link>https://podcast.example/episode</link>' \
                       '<pubDate>' + value + '</pubDate></item></channel></rss>'
                item = parse_feed(body, SOURCE, OBSERVED)[0]
                self.assertIsNone(item["published_at"])
                self.assertEqual(item["time_basis"], "unknown")
