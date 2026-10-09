"""Offline contract tests for the X API collector."""

import json
from datetime import datetime
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from radar import x_collector
from radar import x_paid_budget
from radar import assembly
from radar.clustering import cluster_items
from radar.ranking import rank_stories
from tests.test_v2_support import OBSERVED, coverage


ACCOUNTS = [
    {"id": "1001", "handle": "leader_ai", "name": "AI Leader", "role": "leader"},
    {"id": "1002", "handle": "product_ai", "name": "Product Lead", "role": "product"},
]


class XCollectorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = (Path(__file__).parent / "fixtures" / "x-search-recent.json").read_text(encoding="utf-8")

    def test_groups_queries_server_side_filter_and_obey_recent_search_limits(self):
        rows = [{"id": str(i), "handle": "person_" + str(i), "name": "Person", "role": "researcher"}
                for i in range(21)]
        chunks = x_collector.groups(rows)
        self.assertEqual([len(chunk) for chunk in chunks], [10, 10, 1])
        url = x_collector.search_url(chunks[0], since_id="123")
        query = parse_qs(urlsplit(url).query)
        self.assertLessEqual(len(query["query"][0]), 512)
        self.assertIn("from:person_0", query["query"][0])
        self.assertIn("OR", query["query"][0])
        self.assertIn("-is:retweet", query["query"][0])
        self.assertIn("-is:reply", query["query"][0])
        self.assertIn("GPT", query["query"][0])
        self.assertEqual(query["max_results"], ["10"])
        self.assertEqual(query["since_id"], ["123"])
        self.assertNotIn("pagination_token", query)

    def test_fixture_retains_per_post_author_and_original_x_link(self):
        items = x_collector.parse_search(self.fixture, ACCOUNTS, OBSERVED)
        self.assertEqual(len(items), 1)
        post = items[0]
        self.assertEqual(post["author_handle"], "leader_ai")
        self.assertEqual(post["author_name"], "AI Leader")
        self.assertEqual(post["url"], "https://x.com/leader_ai/status/1900000000000000001")
        self.assertEqual(post["group"], "forum")
        self.assertEqual(post["kind"], "social")
        self.assertEqual(post["publisher"], "x:@leader_ai")
        self.assertEqual(post["publisher_group"], "x")
        self.assertEqual(post["summary"], post["title"])

    def test_headline_removes_links_and_cuts_at_a_word_boundary(self):
        post = {"author_id": "1001", "id": "1900000000000000004",
                "created_at": "2026-10-09T10:00:00Z",
                "text": "GPT " + "important " * 20 + "https://t.co/link"}
        text = json.dumps({"data": [post]})
        item = x_collector.parse_search(text, ACCOUNTS, OBSERVED)[0]
        self.assertLessEqual(len(item["title"]), 121)
        self.assertNotIn("https://", item["title"])
        self.assertTrue(item["title"].endswith("…"))
        self.assertIn("https://t.co/link", item["summary"])

    def test_response_state_uses_numeric_max_and_pagination_token(self):
        self.assertEqual(x_collector.response_state(self.fixture),
                         ("1900000000000000003", "fixture-next-page"))

    def test_malformed_responses_fail_honestly(self):
        for invalid in ["{", "[]", json.dumps({"data": {}})]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                x_collector.parse_search(invalid, ACCOUNTS, OBSERVED)

    def test_roster_requires_unique_live_lookup_ids_and_supported_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "accounts.json"
            path.write_text(json.dumps({"version": 1, "accounts": ACCOUNTS}), encoding="utf-8")
            self.assertEqual(x_collector.load_accounts(path), ACCOUNTS)
            invalid = {"version": 1, "accounts": ACCOUNTS + [ACCOUNTS[0]]}
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ValueError):
                x_collector.load_accounts(path)

    def test_x_coverage_can_cluster_with_matching_press_coverage(self):
        post = x_collector.parse_search(self.fixture, ACCOUNTS, OBSERVED)[0]
        press = coverage(source="press", url="https://news.example/gpt-release",
                         title=post["title"], publisher="press", published_at=post["published_at"])
        stories = cluster_items([post, press], datetime.fromisoformat(OBSERVED.replace("Z", "+00:00")))
        self.assertEqual(len(stories), 1)
        self.assertEqual({item["source"] for item in stories[0]["coverage"]},
                         {post["source"], "press"})

    def test_x_accounts_share_one_publisher_identity(self):
        items = [coverage(source="x-" + account["handle"], publisher="x:@" + account["handle"],
                          publisher_group="x", group="forum", kind="social",
                          url="https://x.com/shared/story", title="GPT announces important feature")
                 for account in ACCOUNTS]
        stories = cluster_items(items, datetime.fromisoformat(OBSERVED.replace("Z", "+00:00")))
        self.assertEqual({item["publisher"] for item in stories[0]["coverage"]},
                         {"x:@leader_ai", "x:@product_ai"})
        self.assertEqual(stories[0]["source_count"], 1)
        rank_stories(stories, datetime.fromisoformat(OBSERVED.replace("Z", "+00:00")))
        self.assertEqual(stories[0]["hot_signals"]["source_count"], 1)
        self.assertIsNone(stories[0]["hot_signals"]["spread"])

    def test_collect_reserves_before_request_settles_returned_posts_and_keeps_page_cursor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            ledger = root / "ledger.json"
            now = datetime.fromisoformat(OBSERVED.replace("Z", "+00:00"))
            self.assertIsNone(x_paid_budget.prepare(ledger, paid=False, remote=str(remote), now=now.timestamp()))
            self.assertIsNone(x_paid_budget.prepare(ledger, paid=True, remote=str(remote), now=now.timestamp(),
                                                     run_key="501-1"))
            received = []

            def transport(url, token):
                received.append((url, token))
                return self.fixture

            posts, records = x_collector.collect(
                ACCOUNTS, ledger, now=now, transport=transport,
                env={"RADAR_X_ENABLED": "1", "X_BEARER_TOKEN": "fixture-only"})
            local = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0][1], "fixture-only")
            self.assertEqual(len(posts), 1)
            self.assertEqual({record["id"] for record in records}, {"x-leader_ai", "x-product_ai"})
            self.assertEqual(sum(row["micros"] for row in local["reservations"]), 15_000)
            cursor = next(iter(local["cursors"].values()))
            self.assertIsNone(cursor["since_id"])
            self.assertEqual(cursor["next_token"], "fixture-next-page")

    def test_collection_is_inert_without_flag_or_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing-ledger.json"
            posts, records = x_collector.collect(ACCOUNTS, path, now=datetime.fromisoformat(OBSERVED.replace("Z", "+00:00")),
                                                  transport=lambda *_: self.fail("unexpected X request"), env={})
            self.assertEqual(posts, [])
            self.assertEqual({record["id"] for record in records}, {"x-leader_ai", "x-product_ai"})
            self.assertTrue(all(record["disabled"] for record in records))

    def test_disabled_x_outcomes_cannot_reject_retained_coverage(self):
        from radar.publication import rejection_reason
        from tests.test_publication import snapshot as publication_snapshot

        now = datetime.fromisoformat(OBSERVED.replace("Z", "+00:00"))
        roster = x_collector.load_accounts(Path(__file__).resolve().parent.parent / "data/x-accounts.json")
        first = roster[0]
        cases = ("daily cap", "HTTP 500", "ledger unavailable")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                ledger = Path(temporary) / "ledger.json"
                remote = Path(temporary) / "remote.git"
                if case != "ledger unavailable":
                    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
                    self.assertIsNone(x_paid_budget.prepare(ledger, paid=False, remote=str(remote), now=now.timestamp()))
                    self.assertIsNone(x_paid_budget.prepare(ledger, paid=True, remote=str(remote), now=now.timestamp(),
                                                             run_key="601-1"))
                transport = lambda *_: self.fixture
                with patch.dict("os.environ", {}, clear=True):
                    if case == "daily cap":
                        reserve = x_paid_budget.reserve
                        calls = 0

                        def capped(*args, **kwargs):
                            nonlocal calls
                            calls += 1
                            return reserve(*args, **kwargs) if calls == 1 else ("x_daily_cap", None)

                        with patch.object(x_paid_budget, "reserve", side_effect=capped):
                            _, records = x_collector.collect(roster, ledger, now=now, transport=transport,
                                                             env={"RADAR_X_ENABLED": "1", "X_BEARER_TOKEN": "fixture-only"})
                        self.assertGreater(calls, 1)
                    elif case == "HTTP 500":
                        def fail_http(*_):
                            raise HTTPError("https://api.x.com/2/tweets/search/recent", 500, "failed", {}, None)
                        _, records = x_collector.collect(roster, ledger, now=now, transport=fail_http,
                                                         env={"RADAR_X_ENABLED": "1", "X_BEARER_TOKEN": "fixture-only"})
                    else:
                        _, records = x_collector.collect(roster, ledger, now=now,
                                                         transport=lambda *_: self.fail("unavailable ledger must not call X"),
                                                         env={"RADAR_X_ENABLED": "1", "X_BEARER_TOKEN": "fixture-only"})

                by_id = {record["id"]: record for record in records}
                self.assertTrue({"x-" + row["handle"].casefold() for row in roster}.issubset(by_id))
                account_rows = [by_id["x-" + row["handle"].casefold()] for row in roster]
                if case == "daily cap":
                    active_rows = [row for row in account_rows if not row.get("disabled", False)]
                    self.assertEqual(len(active_rows), 10)
                    self.assertTrue(all(row.get("disabled") for row in account_rows if row not in active_rows))
                else:
                    self.assertTrue(all(row.get("disabled") for row in account_rows))
                if case != "daily cap":
                    self.assertTrue(by_id["x-collector"]["disabled"])
                payload = publication_snapshot(at=now)
                payload["generated_at"] = now.isoformat()
                payload["sources"].extend(records)
                x_item = coverage(source="x-" + first["handle"].casefold(),
                                  url=f"https://x.com/{first['handle']}/status/1900000000000000009",
                                  publisher="x:@" + first["handle"], group="forum", kind="social",
                                  title="Synthetic retained AI post", published_at=now.isoformat(),
                                  observed_at=now.isoformat())
                payload["stories"][0]["coverage"].append(x_item)
                payload["stories"][0]["source_count"] = 2
                self.assertIsNone(rejection_reason(payload)[0])

    def test_daily_reconciliation_removes_missing_posts_and_fails_closed_after_24_hours(self):
        now = datetime.fromisoformat("2026-10-09T12:00:00+00:00")
        active = {"RADAR_X_ENABLED": "1", "X_BEARER_TOKEN": "fixture-only"}
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.json"
            remote = Path(temporary) / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            self.assertIsNone(x_paid_budget.prepare(ledger, paid=False, remote=str(remote), now=now.timestamp()))
            self.assertIsNone(x_paid_budget.prepare(ledger, paid=True, remote=str(remote), now=now.timestamp(),
                                                    run_key="502-1"))
            published = {"stories": [{"coverage": [
                {"url": "https://x.com/leader_ai/status/1900000000000000001",
                 "published_at": "2026-10-09T11:00:00Z"},
                {"url": "https://x.com/leader_ai/status/1900000000000000002",
                 "published_at": "2026-10-09T11:00:00Z"}]}]}
            current = json.loads(json.dumps(published["stories"]))
            result = x_collector.reconcile_published(
                current, published, ledger, now=now,
                transport=lambda url, token: json.dumps({"data": [{"id": "1900000000000000001"}]}), env=active)
            self.assertEqual(len(result[0]["coverage"]), 1)
            self.assertEqual(json.loads(ledger.read_text(encoding="utf-8"))["reconciled_day"], "2026-10-09")

            old = {"coverage": [{"url": "https://x.com/leader_ai/status/1900000000000000003",
                                  "published_at": "2026-10-07T11:00:00Z"}]}
            local = json.loads(ledger.read_text(encoding="utf-8"))
            local["reconciled_day"] = "2026-10-08"
            ledger.write_text(json.dumps(local), encoding="utf-8")
            failed = x_collector.reconcile_published(
                [old], {"stories": [old]}, ledger, now=now,
                transport=lambda *_: (_ for _ in ()).throw(TimeoutError()), env=active)
            self.assertEqual(failed, [])

    def test_daily_reconciliation_keeps_x_posts_collected_in_the_current_run(self):
        now = datetime.fromisoformat("2026-10-09T12:00:00+00:00")
        active = {"RADAR_X_ENABLED": "1", "X_BEARER_TOKEN": "fixture-only"}
        current_post = {"url": "https://x.com/leader_ai/status/1900000000000000004",
                        "published_at": "2026-10-09T11:30:00Z"}
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.json"
            remote = Path(temporary) / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            self.assertIsNone(x_paid_budget.prepare(ledger, paid=False, remote=str(remote), now=now.timestamp()))
            self.assertIsNone(x_paid_budget.prepare(ledger, paid=True, remote=str(remote), now=now.timestamp(),
                                                    run_key="503-1"))
            result = x_collector.reconcile_published(
                [{"coverage": [current_post]}], {"stories": []}, ledger, now=now,
                transport=lambda *_: self.fail("there are no published IDs to reconcile"), env=active)
        self.assertEqual(result[0]["coverage"], [current_post])

    def test_reconciliation_fallback_runs_without_flag_or_token(self):
        now = datetime.fromisoformat("2026-10-09T12:00:00+00:00")
        old = {"coverage": [{"url": "https://x.com/leader_ai/status/1900000000000000005",
                              "published_at": "2026-10-07T11:00:00Z"}]}
        with tempfile.TemporaryDirectory() as temporary:
            result = x_collector.reconcile_published(
                [old], {"stories": [old]}, Path(temporary) / "missing.json", now=now,
                transport=lambda *_: self.fail("fallback must not make a network request"), env={})
        self.assertEqual(result, [])

    def test_assembly_always_runs_reconciliation_when_x_is_disabled(self):
        with patch("radar.clustering.cluster_items", return_value=[]), \
                patch("radar.retention.retain_stories", return_value=[]), \
                patch("radar.ranking.rank_stories", return_value=[]), \
                patch("radar.curation.curate_repos", return_value=[]), \
                patch.object(x_collector, "reconcile_published", side_effect=lambda stories, *_args, **_kwargs: stories) as reconcile:
            with patch.dict("os.environ", {}, clear=True):
                assembly.finish({}, [], [], datetime.fromisoformat(OBSERVED.replace("Z", "+00:00")), {},
                                published={"stories": []}, resolve_images=False)
        reconcile.assert_called_once()

    def test_missing_reconciliation_ledger_expires_old_x_coverage(self):
        now = datetime.fromisoformat("2026-10-09T12:00:00+00:00")
        old = {"coverage": [{"url": "https://x.com/leader_ai/status/1900000000000000003",
                              "published_at": "2026-10-07T11:00:00Z"}]}
        with tempfile.TemporaryDirectory() as temporary:
            result = x_collector.reconcile_published(
                [old], {"stories": [old]}, Path(temporary) / "missing.json", now=now,
                transport=lambda *_: self.fail("must not call X without a usable ledger"),
                env={"RADAR_X_ENABLED": "1", "X_BEARER_TOKEN": "fixture-only"})
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
