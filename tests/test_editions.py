"""Offline edition policy tests from attributed real captured rows.

Tests that alter dates or signals model boundary cases, not live observations.
"""

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from radar.editions import build_edition

FIXTURE = Path(__file__).parent / "fixtures" / "edition-real-snapshot.json"
NOW = datetime(2026, 10, 3, 9, 18, 1, tzinfo=timezone.utc)
ASTA = "e81b1dea7ce0fb42c978"
APPLE = "b3857f26daabd24cdab2"
SAD = "7c35e1148c5e7af2378a"


def real_snapshot():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def subset(payload, identities):
    """Keep a valid source/story graph when exercising a slow day."""
    result = copy.deepcopy(payload)
    result["stories"] = [row for row in result["stories"] if row["id"] in identities]
    for key, ids in result["sections"].items():
        result["sections"][key] = [id_ for id_ in ids if id_ in identities]
    return result


class EditionSelectionTests(unittest.TestCase):
    def test_real_snapshot_excludes_uncorroborated_forum_and_single_publisher(self):
        payload = real_snapshot()
        original = copy.deepcopy(payload)
        edition = build_edition(payload, NOW)
        self.assertEqual([row["id"] for row in edition["stories"]], [ASTA])
        self.assertEqual(edition["date"], "2026-10-03")
        self.assertEqual(edition["timezone"], "Asia/Ho_Chi_Minh")
        self.assertEqual(edition["cutoff_at"], "2026-10-02T23:00:00Z")
        self.assertEqual(edition["window_start_at"], "2026-10-01T23:00:00Z")
        self.assertEqual(payload, original)
        for row in edition["stories"]:
            self.assertTrue(row["selection"]["reasons"])
            self.assertTrue(all(reason["code"] and reason["text"] for reason in row["selection"]["reasons"]))

    def test_existing_translations_and_source_text_are_copied_without_prose(self):
        payload = real_snapshot()
        by_id = {row["id"]: row for row in payload["stories"]}
        for row in build_edition(payload, NOW)["stories"]:
            original = by_id[row["id"]]
            for field in ("title", "title_vi", "url", "published_at"):
                self.assertEqual(row[field], original[field])
            for field in ("summary", "summary_vi", "editorial", "analysis", "why_it_matters"):
                self.assertNotIn(field, row)
            evidence = {item["id"]: item for item in original["coverage"]}
            for item in row["coverage"]:
                for field in ("id", "source", "publisher", "title", "title_vi", "url"):
                    self.assertEqual(item[field], evidence[item["id"]][field])

    def test_missing_translation_does_not_trigger_invented_text(self):
        payload = subset(real_snapshot(), {ASTA})
        payload["stories"][0].pop("title_vi")
        for item in payload["stories"][0]["coverage"]:
            item.pop("title_vi")
        row = build_edition(payload, NOW)["stories"][0]
        self.assertNotIn("title_vi", row)
        self.assertTrue(all("title_vi" not in item for item in row["coverage"]))

    def test_slow_day_keeps_one_or_zero_without_padding(self):
        for identities in ({ASTA}, {ASTA, APPLE}, {"b6aee1da4c9da9519c63"}):
            with self.subTest(identities=identities):
                edition = build_edition(subset(real_snapshot(), identities), NOW)
                expected = identities & {ASTA}
                self.assertEqual({row["id"] for row in edition["stories"]}, expected)

    def test_empty_snapshot_selection_stays_empty(self):
        self.assertEqual(build_edition(subset(real_snapshot(), set()), NOW)["stories"], [])

    def test_no_previous_day_backfill_before_morning_cut(self):
        for now in ("2026-10-02T17:00:00+00:00",
                    "2026-10-02T22:59:59+00:00"):
            with self.subTest(now=now):
                # Shift only collection time for a controlled clock-boundary scenario.
                payload = real_snapshot()
                payload["generated_at"] = now
                self.assertIsNone(build_edition(payload, datetime.fromisoformat(now)))

    def test_exact_cut_uses_vietnam_date_and_half_open_window(self):
        payload = subset(real_snapshot(), {ASTA})
        now = datetime(2026, 10, 2, 23, tzinfo=timezone.utc)
        payload["generated_at"] = now.isoformat()
        for published_at, included in (("2026-10-01T22:59:59Z", False),
                                       ("2026-10-01T23:00:00Z", True),
                                       ("2026-10-02T22:59:59Z", True),
                                       ("2026-10-02T23:00:00Z", False)):
            with self.subTest(published_at=published_at):
                payload["stories"][0]["published_at"] = published_at
                for item in payload["stories"][0]["coverage"]:
                    item["published_at"] = published_at
                edition = build_edition(payload, now)
                self.assertEqual(edition["date"], "2026-10-03")
                self.assertEqual(bool(edition["stories"]), included)

    def test_missing_invalid_future_or_stale_dates_never_gain_freshness(self):
        for value in (None, "", "not-a-date", "2026-10-02", "2026-10-02T15:00:00",
                      "2026-10-04T00:00:00Z", "2026-09-29T12:00:00Z"):
            with self.subTest(value=value):
                payload = subset(real_snapshot(), {ASTA})
                payload["stories"][0]["published_at"] = value
                self.assertEqual(build_edition(payload, NOW)["stories"], [])

    def test_nonpublication_dates_and_scheduled_events_are_not_news(self):
        for field, value in (("time_basis", None), ("time_basis", "unknown"),
                             ("time_basis", "repository_created"), ("time_basis", "scheduled"),
                             ("kind", "event"), ("status", "upcoming")):
            with self.subTest(field=field, value=value):
                payload = subset(real_snapshot(), {ASTA})
                payload["stories"][0][field] = value
                self.assertEqual(build_edition(payload, NOW)["stories"], [])

    def test_pre_cut_collection_cannot_freeze_an_incomplete_morning(self):
        payload = real_snapshot()
        payload["generated_at"] = "2026-10-02T22:59:00Z"
        self.assertIsNone(build_edition(payload, datetime(2026, 10, 2, 23, 1, tzinfo=timezone.utc)))

    def test_failed_source_cannot_inflate_independent_coverage(self):
        payload = subset(real_snapshot(), {APPLE})
        # Controlled forum-to-press change establishes qualifying independent coverage.
        next(row for row in payload["stories"][0]["coverage"] if row["group"] == "forum")["group"] = "press"
        self.assertEqual(len(build_edition(payload, NOW)["stories"]), 1)
        for source in payload["sources"]:
            if source["id"] == "hn-ai":
                source["ok"] = False
        self.assertEqual(build_edition(payload, NOW)["stories"], [])

    def test_mirror_publishers_and_inflated_source_count_do_not_qualify(self):
        payload = subset(real_snapshot(), {APPLE})
        row = payload["stories"][0]
        next(item for item in row["coverage"] if item["group"] == "forum")["group"] = "press"
        self.assertEqual(len(build_edition(payload, NOW)["stories"]), 1)
        row["coverage"][1]["publisher"] = row["coverage"][0]["publisher"]
        row["source_count"] = 99
        self.assertEqual(build_edition(payload, NOW)["stories"], [])

    def test_real_personal_post_and_single_publisher_are_excluded_individually(self):
        for identity in (SAD, APPLE):
            with self.subTest(identity=identity):
                self.assertEqual(build_edition(subset(real_snapshot(), {identity}), NOW)["stories"], [])

    def test_attention_requires_real_positive_measured_evidence(self):
        baseline = subset(real_snapshot(), {SAD})
        baseline["stories"][0]["hot_signals"]["engagement_percentile"] = .97
        self.assertEqual(len(build_edition(baseline, NOW)["stories"]), 1)
        for field, value in (("measurement", None), ("engagement_percentile", None),
                             ("engagement_percentile", 0.7999)):
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(baseline)
                payload["stories"][0]["hot_signals"][field] = value
                self.assertEqual(build_edition(payload, NOW)["stories"], [])
        for value in (0, -1, None):
            with self.subTest(measurement=value):
                payload = copy.deepcopy(baseline)
                payload["stories"][0]["hot_signals"]["measurement"]["value"] = value
                self.assertEqual(build_edition(payload, NOW)["stories"], [])

    def test_forum_exception_cannot_borrow_comments_from_another_measurement(self):
        baseline = subset(real_snapshot(), {SAD})
        story = baseline["stories"][0]
        story["hot_signals"]["engagement_percentile"] = .97
        self.assertEqual(len(build_edition(baseline, NOW)["stories"]), 1)
        story["coverage"][0]["metrics"]["comments"] = 99
        extra = copy.deepcopy(story["coverage"][0])
        extra["id"] += "-controlled-other-observation"
        extra["metrics"]["points"] += 1
        extra["metrics"]["comments"] = 100
        story["coverage"].append(extra)
        self.assertEqual(build_edition(baseline, NOW)["stories"], [])

    def test_forum_only_attention_needs_both_exception_thresholds(self):
        # Controlled signal mutations on the captured personal essay, not new observations.
        for percentile, comments, selected in ((.9699, 224, False), (.97, 99, False),
                                               (.97, 100, True), (1, 100, True),
                                               (1.01, 100, False), (.99, None, False)):
            with self.subTest(percentile=percentile, comments=comments):
                payload = subset(real_snapshot(), {SAD})
                story = payload["stories"][0]
                story["hot_signals"]["engagement_percentile"] = percentile
                story["coverage"][0]["metrics"]["comments"] = comments
                self.assertEqual(bool(build_edition(payload, NOW)["stories"]), selected)

    def test_corroborated_attention_has_exact_threshold_and_nonforum_count(self):
        # Apple already has real press + HN coverage; alter only its percentile.
        for percentile, included in ((.7999, False), (.8, True)):
            payload = subset(real_snapshot(), {APPLE})
            payload["stories"][0]["hot_signals"]["engagement_percentile"] = percentile
            stories = build_edition(payload, NOW)["stories"]
            self.assertEqual(bool(stories), included)
            if included:
                self.assertEqual(stories[0]["source_count"], 1)
                self.assertEqual(stories[0]["selection"]["signals"]["publishers"], ["techcrunch"])
                self.assertEqual([r["code"] for r in stories[0]["selection"]["reasons"]], ["measured_attention"])

    def test_ineligible_nonforum_rows_cannot_corroborate_attention(self):
        for mutation in ("failed", "disabled", "stale", "future", "nonpublication", "event", "upcoming"):
            with self.subTest(mutation=mutation):
                payload = subset(real_snapshot(), {APPLE})
                story = payload["stories"][0]
                story["hot_signals"]["engagement_percentile"] = .8
                press = next(row for row in story["coverage"] if row["group"] != "forum")
                source = next(row for row in payload["sources"] if row["id"] == press["source"])
                if mutation == "failed":
                    source["ok"] = False
                elif mutation == "disabled":
                    source["disabled"] = True
                else:
                    field, value = {"stale": ("published_at", "2026-10-01T22:59:59Z"),
                                    "future": ("published_at", "2026-10-02T23:00:00Z"),
                                    "nonpublication": ("time_basis", "repository_created"),
                                    "event": ("kind", "event"), "upcoming": ("status", "upcoming")}[mutation]
                    press[field] = value
                self.assertEqual(build_edition(payload, NOW)["stories"], [])

    def test_forum_exception_has_one_slot_and_sorts_after_other_evidence(self):
        payload = real_snapshot()
        # Shift real forum rows into the window and raise their actual metric to model a busy day.
        forums = [s for s in payload["stories"] if s["kind"] == "forum"]
        payload = subset(payload, {ASTA, APPLE} | {s["id"] for s in forums})
        for story in payload["stories"]:
            if story["kind"] != "forum":
                continue
            story["published_at"] = "2026-10-02T12:00:00Z"
            story["hot_signals"]["engagement_percentile"] = .99
            story["hot_score"] = 999
            for row in story["coverage"]:
                row["published_at"] = story["published_at"]
                row["metrics"]["comments"] = 100
        apple = next(s for s in payload["stories"] if s["id"] == APPLE)
        apple["hot_signals"]["engagement_percentile"] = .8
        first = build_edition(payload, NOW)["stories"]
        self.assertEqual(len(first), 3)
        self.assertEqual([s["id"] for s in first[:2]], [ASTA, APPLE])
        self.assertEqual(first[2]["source_count"], 0)
        payload["stories"].reverse()
        self.assertEqual(first, build_edition(payload, NOW)["stories"])
        # Removing all forum rows leaves a genuine two-pick day, without padding.
        payload["stories"] = [s for s in payload["stories"] if s["kind"] != "forum"]
        self.assertEqual(len(build_edition(payload, NOW)["stories"]), 2)

    def test_launch_needs_primary_lab_evidence_and_launch_action(self):
        for update in ({"group": "press", "lab": ""}, {"title": "AstaBrief model research notes"}):
            with self.subTest(update=update):
                payload = subset(real_snapshot(), {ASTA})
                payload["stories"][0]["coverage"][0].update(update)
                if "title" in update:
                    payload["stories"][0]["title"] = update["title"]
                self.assertEqual(build_edition(payload, NOW)["stories"], [])

    def test_at_most_five_unique_stories_and_input_order_does_not_change_result(self):
        payload = real_snapshot()
        # Controlled signal/date mutations on real rows create an overfull day.
        for row in payload["stories"]:
            row["published_at"] = "2026-10-02T12:00:00Z"
            for item in row["coverage"]:
                item["published_at"] = row["published_at"]
            row["hot_signals"]["engagement_percentile"] = 0.9
            row["hot_signals"]["measurement"] = dict(
                source=row["coverage"][0]["source"], metric="points", value=100,
                observed_at=payload["generated_at"])
            row["coverage"][0]["metrics"]["points"] = 100
        payload["stories"].append(copy.deepcopy(payload["stories"][0]))
        first = build_edition(payload, NOW)["stories"]
        payload["stories"].reverse()
        self.assertEqual(first, build_edition(payload, NOW)["stories"])
        self.assertEqual(len(first), 5)
        self.assertEqual(len({row["id"] for row in first}), 5)


if __name__ == "__main__":
    unittest.main()
