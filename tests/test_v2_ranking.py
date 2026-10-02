"""Synthetic ranking cases distinguish observations from missing evidence."""

import json
import unittest

from radar.clustering import cluster_items
from radar.ranking import hot_eligible, rank_stories
from test_v2_support import NOW, coverage


def hn_items(values, observed_at="2026-10-02T12:00:00Z"):
    return [coverage("hn", f"https://example.org/{index}", title=f"Article {index}",
                     publisher="hacker-news", group="forum", kind="forum",
                     metrics={"points": value}, observed_at=observed_at)
            for index, value in enumerate(values)]


def rank(items, previous=None):
    return rank_stories(cluster_items(items, NOW), NOW, previous=previous)


def baseline(values, observed_at="2026-10-02T11:00:00Z"):
    return {"schema_version": 2, "generated_at": observed_at,
            "stories": cluster_items(hn_items(values, observed_at), NOW)}


class RankingTests(unittest.TestCase):
    def test_age_alone_and_duplicate_publisher_are_not_popularity(self):
        for items in [[coverage()], [coverage(publisher="lab"),
                                   coverage("mirror", publisher="lab")]]:
            with self.subTest(count=len(items)):
                story = rank(items)[0]
                self.assertIsNone(story["hot_score"])
                self.assertIsNone(story["hot_reason"])

    def test_independent_spread_can_score_without_invented_engagement(self):
        story = rank([coverage(), coverage("press-b")])[0]
        self.assertGreater(story["hot_score"], 0)
        self.assertLessEqual(story["hot_score"], 100)
        self.assertIn("2", story["hot_reason"])
        self.assertIn("nguồn", story["hot_reason"])
        self.assertIsNone(story["hot_signals"]["engagement_percentile"])
        self.assertIsNone(story["hot_signals"]["velocity_per_hour"])

    def test_unknown_future_and_stale_times_never_score(self):
        for timestamp in [None, "2026-10-02T13:00:00Z", "2026-09-28T12:00:00Z"]:
            with self.subTest(timestamp=timestamp):
                story = rank([coverage(published_at=timestamp),
                              coverage("b", published_at=timestamp)])[0]
                self.assertIsNone(story["hot_score"])

    def test_one_counter_cannot_establish_a_percentile(self):
        story = rank(hn_items([120]))[0]
        self.assertIsNone(story["hot_signals"]["engagement_percentile"])
        self.assertIsNone(story["hot_score"])

    def test_scores_follow_measured_counts_and_reason_names_actual_value(self):
        stories = rank(hn_items([2, 20, 120]))
        by_value = {story["coverage"][0]["metrics"]["points"]: story for story in stories}
        self.assertGreater(by_value[120]["hot_score"], by_value[20]["hot_score"])
        self.assertGreater(by_value[20]["hot_score"], by_value[2]["hot_score"])
        self.assertIn("120", by_value[120]["hot_reason"])
        self.assertEqual(by_value[120]["hot_signals"]["measurement"]["value"], 120)
        for story in stories:
            self.assertIsNone(story["hot_signals"]["velocity_per_hour"])

    def test_all_tied_counts_receive_identical_average_percentile(self):
        stories = rank(hn_items([12, 12, 12]))
        self.assertEqual({story["hot_signals"]["engagement_percentile"] for story in stories}, {0.5})
        self.assertEqual(len({story["hot_score"] for story in stories}), 1)
        self.assertTrue(all(not hot_eligible(story) for story in stories))

    def test_hot_list_requires_strong_positive_measurement_or_independent_spread(self):
        self.assertFalse(any(hot_eligible(story) for story in rank(hn_items([0, 0]))))
        eligible = [story for story in rank(hn_items([0, 5, 100])) if hot_eligible(story)]
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["coverage"][0]["metrics"]["points"], 100)
        self.assertTrue(hot_eligible(rank([coverage(), coverage("press-b")])[0]))

    def test_invalid_counters_do_not_create_rank_or_nonfinite_json(self):
        for value in [None, True, -1, "not-a-number", float("nan"), float("inf"), -float("inf")]:
            with self.subTest(value=value):
                stories = rank(hn_items([value, value]))
                self.assertTrue(all(story["hot_score"] is None for story in stories))
                for story in stories:
                    json.dumps(story["hot_signals"], allow_nan=False)

    def test_measured_zero_velocity_is_distinct_from_absent_baseline(self):
        stories = rank(hn_items([10, 20]), baseline([10, 20]))
        self.assertEqual({story["hot_signals"]["velocity_per_hour"] for story in stories}, {0})
        self.assertTrue(all(story["hot_signals"]["velocity_percentile"] is not None for story in stories))

    def test_velocity_uses_same_item_measurement_and_elapsed_hours(self):
        stories = rank(hn_items([20, 40]), baseline([10, 20], "2026-10-02T10:00:00Z"))
        by_value = {story["coverage"][0]["metrics"]["points"]: story for story in stories}
        self.assertEqual(by_value[20]["hot_signals"]["velocity_per_hour"], 5)
        self.assertEqual(by_value[40]["hot_signals"]["velocity_per_hour"], 10)

    def test_counter_reset_or_invalid_snapshot_interval_keeps_velocity_unknown(self):
        cases = [baseline([20, 40]), baseline([1, 2], "2026-10-02T12:00:00Z"),
                 baseline([1, 2], "2026-10-02T13:00:00Z"),
                 baseline([1, 2], "2026-09-29T11:00:00Z")]
        for previous in cases:
            with self.subTest(previous=previous["generated_at"]):
                stories = rank(hn_items([10, 20]), previous)
                self.assertTrue(all(story["hot_signals"]["velocity_per_hour"] is None for story in stories))

    def test_previous_other_source_cannot_be_used_as_velocity_baseline(self):
        previous = baseline([1, 2])
        for story in previous["stories"]:
            for item in story["coverage"]:
                item["source"] = "different-source"
        self.assertTrue(all(story["hot_signals"]["velocity_per_hour"] is None
                            for story in rank(hn_items([10, 20]), previous)))

    def test_reason_uses_selected_source_percentile_not_largest_foreign_counter(self):
        items = hn_items([10, 100])
        items.extend([coverage("hf", items[1]["url"], title=items[1]["title"], metrics={"upvotes": 1000}),
                      coverage("hf", "https://example.org/paper-peer", title="Another paper",
                               metrics={"upvotes": 2000})])
        story = next(story for story in rank(items) if len(story["coverage"]) == 2)
        selected = story["hot_signals"]["measurement"]
        self.assertEqual((selected["source"], selected["metric"], selected["value"]), ("hn", "points", 100))
        self.assertIn("hn", story["hot_reason"])
        self.assertNotIn("1000", story["hot_reason"])

    def test_malformed_optional_baseline_does_not_break_current_ranking(self):
        for changes in [{"stories": None}, {"stories": [None, {"coverage": None}]},
                        {"generated_at": "invalid"}]:
            previous = baseline([1, 2]) | changes
            with self.subTest(changes=changes):
                stories = rank(hn_items([10, 20]), previous)
                self.assertEqual(len(stories), 2)
                self.assertTrue(all(story["hot_signals"]["velocity_per_hour"] is None for story in stories))

    def test_legacy_schema_cannot_supply_velocity_even_with_matching_rows(self):
        previous = baseline([1, 2]) | {"schema_version": 1}
        stories = rank(hn_items([10, 20]), previous)
        self.assertTrue(all(story["hot_signals"]["velocity_per_hour"] is None for story in stories))

    def test_huge_optional_baseline_counter_is_unknown_not_a_build_failure(self):
        stories = rank(hn_items([10, 20]), baseline([10 ** 400, 10 ** 400]))
        self.assertEqual(len(stories), 2)
        self.assertTrue(all(story["hot_signals"]["velocity_per_hour"] is None for story in stories))
