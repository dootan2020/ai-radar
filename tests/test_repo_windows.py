"""Trending windows (day, week, month), AI-only repositories, generic area rules and the page's orderings."""

from datetime import datetime, timedelta, timezone
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from unittest import mock

from radar import curation, github, pipeline, youtube
from radar.common import vi_error
from radar.curation import CATEGORY_TERMS, classify_category, curate_repos, is_ai_repo, rank_repos

NOW = datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc)


def card(repo, description, gained, phrase, stars=1000, forks=50):
    return f"""<article class="Box-row"><h2 class="h3 lh-condensed"><a href="/{repo}">{repo}</a></h2>
      <p class="col-9">{description}</p>
      <a href="/{repo}/stargazers">{stars:,}</a><a href="/{repo}/forks">{forks:,}</a>
      <span class="d-inline-block float-sm-right">{gained:,} stars {phrase}</span></article>"""


def page(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


DAY = page(card("a/agent-day", "LLM agent toolkit", 300, "today"),
           card("b/rag-kit", "RAG engine for documents with embeddings", 120, "today"),
           card("Effect-TS/effect", "Build production-ready applications in TypeScript", 76, "today"))
WEEK = page(card("c/voice-ai", "Open-source text-to-speech with voice cloning", 9000, "this week"),
            card("a/agent-day", "LLM agent toolkit", 2100, "this week"),
            card("getsentry/sentry", "Developer-first error tracking and performance monitoring", 400, "this week"))
MONTH = page(card("d/video-gen", "AI video generation from text prompts", 31000, "this month", forks=4000),
             card("c/voice-ai", "Open-source text-to-speech with voice cloning", 12000, "this month"),
             card("a/agent-day", "LLM agent toolkit", 5000, "this month"))
RECORDED_DAY = (Path(__file__).parent / "fixtures/github.html").read_text(encoding="utf-8")


def fetcher_for(pages):
    def fetch(url, source_id=None):
        if url in pages:
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return value
        if "raw.githubusercontent.com" in url:
            repo = url.split("raw.githubusercontent.com/")[1].split("/HEAD")[0]
            return f"# {repo}\n\n```bash\npip install {repo.split('/')[1]}\n```\n"
        return None
    return fetch


class TrendingPageTests(unittest.TestCase):
    def test_curation_fetches_week_and_month_after_collection_deadline(self):
        calls = []
        pages = {github.WINDOWS[0][1]: DAY, github.WINDOWS[1][1]: WEEK,
                 github.WINDOWS[2][1]: MONTH}

        def fetch(url, source_id=None):
            calls.append(url)
            return pages.get(url)

        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.json"
            events.write_bytes(b"[]")
            with mock.patch.object(pipeline, "_jobs", return_value=[(github.SOURCE, "github", github.parse_trending)]), \
                 mock.patch.object(youtube, "collect", return_value=([], [])):
                result = pipeline.build_v2(fetch=fetch, now=NOW, timeout=1e-9,
                                           events_path=events, resolve_images=False)

        self.assertEqual(next(row for row in result["sources"] if row["id"] == github.SOURCE["id"])["error"],
                         "Build deadline exceeded")
        self.assertIn(github.WINDOWS[1][1], calls)
        self.assertIn(github.WINDOWS[2][1], calls)
        self.assertNotIn(github.WINDOWS[0][1], calls)
        self.assertEqual(calls.count(github.WINDOWS[1][1]), 1)
        self.assertEqual(calls.count(github.WINDOWS[2][1]), 1)
        self.assertTrue(result["repos_meta"]["windows"]["week"]["measured"])
        self.assertTrue(result["repos_meta"]["windows"]["month"]["measured"])

    def test_deadline_skips_retry_and_daily_refetch_on_failed_pages(self):
        calls = []

        def fetch(url, source_id=None):
            calls.append(url)
            raise HTTPError(url, 504, "Gateway Timeout", {}, None)

        meta = {}
        with mock.patch.object(curation.time, "sleep") as sleep, \
             mock.patch.object(curation, "_previous_repo_snapshots", return_value=[]):
            curate_repos([], [], fetcher=fetch, now=NOW, meta=meta,
                         collection_finished_on_time=False)
        self.assertEqual(calls, [github.WINDOWS[1][1], github.WINDOWS[2][1]])
        sleep.assert_not_called()
        self.assertFalse(meta["windows"]["day"]["measured"])
        self.assertFalse(meta["windows"]["week"]["measured"])
        self.assertFalse(meta["windows"]["month"]["measured"])

    def test_disabled_github_source_does_not_fetch_trending_pages(self):
        source = dict(github.SOURCE, disabled=True, disabled_reason="Unavailable")
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.json"
            events.write_bytes(b"[]")
            with mock.patch.object(pipeline, "_jobs", return_value=[(source, "github", github.parse_trending)]), \
                 mock.patch.object(youtube, "collect", return_value=([], [])):
                result = pipeline.build_v2(fetch=lambda url, **kwargs: self.fail("Unexpected request: " + url),
                                           now=NOW, events_path=events, resolve_images=False)
        self.assertTrue(next(row for row in result["sources"] if row["id"] == source["id"])["disabled"])
        self.assertEqual(result["repos"], [])

    def test_transient_504_recovers_daily_and_weekly_pages(self):
        calls = []
        pages = fetcher_for({github.WINDOWS[0][1]: RECORDED_DAY, github.WINDOWS[1][1]: WEEK,
                             github.WINDOWS[2][1]: MONTH})

        def fetch(url, source_id=None):
            calls.append(url)
            if url in (github.WINDOWS[0][1], github.WINDOWS[1][1]) and calls.count(url) == 1:
                raise HTTPError(url, 504, "Gateway Timeout", {}, None)
            return pages(url, source_id)

        meta = {}
        with mock.patch.object(curation.time, "sleep") as sleep:
            repos = curate_repos([], [], fetcher=fetch, now=NOW, meta=meta)
        self.assertEqual(calls.count(github.WINDOWS[0][1]), 2)
        self.assertEqual(calls.count(github.WINDOWS[1][1]), 2)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(meta["rankings"]["trending"]["day"])
        self.assertTrue(meta["rankings"]["trending"]["week"])
        self.assertEqual(meta["windows"]["day"]["fetched_at"], "2026-10-03T02:00:00Z")
        self.assertTrue(any(row["id"] == "NVIDIA/OpenShell" for row in repos))

    def _published_fixture(self, path, fetched_at):
        meta = {}
        repos = curate_repos(github.parse_trending(DAY), [],
                             fetcher=fetcher_for({github.WINDOWS[1][1]: WEEK, github.WINDOWS[2][1]: MONTH}),
                             now=fetched_at, meta=meta)
        snapshot = {"generated_at": fetched_at.isoformat().replace("+00:00", "Z"),
                    "repos": repos, "repos_meta": meta}
        path.write_text(json.dumps(snapshot), encoding="utf-8", newline="\n")
        return snapshot

    def test_permanent_failure_uses_last_good_lists_and_original_age(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published-snapshot.json"
            prior = self._published_fixture(path, NOW - timedelta(days=1))
            failure = HTTPError(github.WINDOWS[1][1], 504, "Gateway Timeout", {}, None)
            fetch = fetcher_for({github.WINDOWS[0][1]: failure, github.WINDOWS[1][1]: failure,
                                 github.WINDOWS[2][1]: MONTH})
            meta = {}
            with mock.patch.dict(curation.os.environ, {"RADAR_PUBLISHED_SNAPSHOT": str(path)}), \
                 mock.patch.object(curation, "TRENDING_RETRY_SECONDS", 0):
                repos = curate_repos([], [], fetcher=fetch, now=NOW, meta=meta)
            for window in ("day", "week"):
                self.assertEqual(meta["rankings"]["trending"][window],
                                 prior["repos_meta"]["rankings"]["trending"][window])
                self.assertEqual(meta["windows"][window]["fetched_at"], prior["generated_at"])
                self.assertEqual(meta["windows"][window]["age_seconds"], 86400)
                self.assertTrue(meta["windows"][window]["fallback"])
            self.assertTrue(all(any(row["id"] == id_ for row in repos)
                                for id_ in meta["rankings"]["trending"]["week"]))

    def test_stale_daily_fallback_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published-snapshot.json"
            self._published_fixture(path, NOW - timedelta(days=4))
            failure = HTTPError(github.WINDOWS[0][1], 504, "Gateway Timeout", {}, None)
            fetch = fetcher_for({github.WINDOWS[0][1]: failure, github.WINDOWS[1][1]: WEEK,
                                 github.WINDOWS[2][1]: MONTH})
            meta = {}
            with mock.patch.dict(curation.os.environ, {"RADAR_PUBLISHED_SNAPSHOT": str(path)}), \
                 mock.patch.object(curation, "TRENDING_RETRY_SECONDS", 0):
                curate_repos([], [], fetcher=fetch, now=NOW, meta=meta)
            self.assertFalse(meta["windows"]["day"]["measured"])
            self.assertEqual(meta["rankings"]["trending"]["day"], [])

    def test_baseline_recovers_window_when_latest_publication_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "measurement-baseline.json"
            published = Path(directory) / "published-snapshot.json"
            prior = self._published_fixture(baseline, NOW - timedelta(days=2))
            empty = {"generated_at": (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                     "repos": [], "repos_meta": {"windows": {"week": {"measured": False}},
                                                "rankings": {"trending": {"week": []}}}}
            published.write_text(json.dumps(empty), encoding="utf-8", newline="\n")
            failure = HTTPError(github.WINDOWS[1][1], 504, "Gateway Timeout", {}, None)
            fetch = fetcher_for({github.WINDOWS[1][1]: failure, github.WINDOWS[2][1]: MONTH})
            meta = {}
            with mock.patch.dict(curation.os.environ, {"RADAR_PUBLISHED_SNAPSHOT": str(published),
                                                       "RADAR_BASELINE": str(baseline)}), \
                 mock.patch.object(curation, "TRENDING_RETRY_SECONDS", 0):
                curate_repos(github.parse_trending(DAY), [], fetcher=fetch, now=NOW, meta=meta)
            self.assertEqual(meta["rankings"]["trending"]["week"],
                             prior["repos_meta"]["rankings"]["trending"]["week"])
            self.assertEqual(meta["windows"]["week"]["fetched_at"], prior["generated_at"])

    def test_weekly_fallback_expires_by_fetch_time_not_publication_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published-snapshot.json"
            prior = self._published_fixture(path, NOW - timedelta(days=11))
            prior["generated_at"] = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            path.write_text(json.dumps(prior), encoding="utf-8", newline="\n")
            failure = HTTPError(github.WINDOWS[1][1], 504, "Gateway Timeout", {}, None)
            fetch = fetcher_for({github.WINDOWS[1][1]: failure, github.WINDOWS[2][1]: MONTH})
            meta = {}
            with mock.patch.dict(curation.os.environ, {"RADAR_PUBLISHED_SNAPSHOT": str(path)}), \
                 mock.patch.object(curation, "TRENDING_RETRY_SECONDS", 0):
                curate_repos(github.parse_trending(DAY), [], fetcher=fetch, now=NOW, meta=meta)
            self.assertFalse(meta["windows"]["week"]["measured"])
            self.assertEqual(meta["rankings"]["trending"]["week"], [])


    def test_parser_reads_each_windows_own_count_and_forks(self):
        rows = github.parse_trending(MONTH)
        self.assertEqual([r["repo"] for r in rows], ["d/video-gen", "c/voice-ai", "a/agent-day"])
        self.assertEqual(rows[0]["stars_gained"], 31000)
        self.assertEqual(rows[0]["gained_period"], "month")
        self.assertEqual(rows[0]["forks"], 4000)
        self.assertIsNone(rows[0]["stars_today"], "a month count is not a day count")
        self.assertEqual(github.parse_trending(DAY)[0]["stars_today"], 300)

    def test_month_page_is_fetched_and_measured(self):
        meta = {}
        fetch = fetcher_for({github.WINDOWS[1][1]: WEEK, github.WINDOWS[2][1]: MONTH})
        repos = curate_repos(github.parse_trending(DAY), [], fetcher=fetch, now=NOW, meta=meta)
        by_id = {r["id"]: r for r in repos}
        self.assertEqual(by_id["d/video-gen"]["stars_gained"], {"day": None, "week": None, "month": 31000})
        self.assertEqual(by_id["a/agent-day"]["stars_gained"], {"day": 300, "week": 2100, "month": 5000})
        self.assertEqual(by_id["a/agent-day"]["stars_gained_7d"], 2100)
        self.assertEqual(by_id["d/video-gen"]["forks"], 4000)
        self.assertEqual(by_id["d/video-gen"]["forks_source"], "trending_page")
        self.assertTrue(all(meta["windows"][w]["measured"] for w in ("day", "week", "month")))
        self.assertEqual(meta["windows"]["month"]["url"], "https://github.com/trending?since=monthly")

    def test_failed_month_page_leaves_month_unmeasured_and_borrows_nothing(self):
        meta, calls = {}, []
        error = TimeoutError("Source exceeded fetch deadline")
        base = fetcher_for({github.WINDOWS[1][1]: WEEK, github.WINDOWS[2][1]: error})

        def fetch(url, source_id=None):
            calls.append(url)
            return base(url, source_id)

        with mock.patch.object(curation, "TRENDING_RETRY_SECONDS", 0):
            repos = curate_repos(github.parse_trending(DAY), [], fetcher=fetch, now=NOW, meta=meta)
        self.assertEqual(calls.count(github.WINDOWS[2][1]), 3, "a failed page is tried three times")
        self.assertFalse(meta["windows"]["month"]["measured"])
        self.assertIn("theo tháng", meta["windows"]["month"]["error"])
        self.assertTrue(all(r["stars_gained"]["month"] is None for r in repos))
        self.assertEqual(meta["rankings"]["trending"]["month"], [])
        self.assertEqual(meta["rankings"]["usable"]["month"], [])

    def test_page_printing_another_windows_phrase_does_not_measure_this_window(self):
        meta = {}
        fetch = fetcher_for({github.WINDOWS[1][1]: WEEK, github.WINDOWS[2][1]: WEEK})
        curate_repos(github.parse_trending(DAY), [], fetcher=fetch, now=NOW, meta=meta)
        self.assertFalse(meta["windows"]["month"]["measured"])


class AiOnlyTests(unittest.TestCase):
    def test_unrelated_repositories_are_left_out_and_listed(self):
        meta = {}
        fetch = fetcher_for({github.WINDOWS[1][1]: WEEK, github.WINDOWS[2][1]: MONTH})
        repos = curate_repos(github.parse_trending(DAY), [], fetcher=fetch, now=NOW, meta=meta)
        ids = {r["id"] for r in repos}
        self.assertNotIn("Effect-TS/effect", ids)
        self.assertNotIn("getsentry/sentry", ids)
        self.assertEqual(meta["excluded_non_ai"], ["Effect-TS/effect", "getsentry/sentry"])
        self.assertTrue({"a/agent-day", "b/rag-kit", "c/voice-ai", "d/video-gen"} <= ids)

    def test_relevance_reads_name_description_topics_not_a_passing_readme_mention(self):
        self.assertTrue(is_ai_repo("trycua/cua", "Scale computer-use 2.0 with open-source drivers"))
        self.assertTrue(is_ai_repo("x/y", "Toolkit", topics=["llm"]))
        self.assertFalse(is_ai_repo("vercel/next.js", "The React Framework for production apps and sites",
                                    readme_text="Next.js now ships an AI SDK integration."))
        self.assertTrue(is_ai_repo("x/z", "", readme_text="# z\nA local LLM inference server."))


class GenericAreaRuleTests(unittest.TestCase):
    # Names the owner gave as examples (02/10) or tools that once sat in these rules.
    PROPER_NAMES = {"remotion", "hyperframes", "orca", "stablyai", "openhands", "cline", "copilot", "cursor", "devin",
                    "claude", "codex", "tradingagents", "qlib", "freqtrade", "ollama", "llama.cpp", "vllm", "mlx",
                    "unsloth", "llamafactory", "axolotl", "mem0", "docling", "crawl4ai", "firecrawl", "chatterbox",
                    "f5-tts", "whisper", "bark", "playwright", "puppeteer", "ffmpeg", "swe-bench", "heygen"}

    def test_no_area_term_is_a_proper_name(self):
        for area, terms in CATEGORY_TERMS:
            for term in terms:
                with self.subTest(area=area, term=term):
                    self.assertNotIn("/", term, "an owner/repository path is a name, not a rule")
                    self.assertEqual(term, term.lower())
                    plain = re.sub(r"\[- \]|\(\?:|[()?|*.\\]", " ", term)
                    for name in self.PROPER_NAMES:
                        self.assertNotRegex(plain, r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])")

    def test_example_repositories_still_classify_from_what_they_say(self):
        self.assertEqual(classify_category("anyone/new-tool", "Render videos from HTML, built for agents"), "video")
        self.assertEqual(classify_category("anyone/fleet", "ADE for working with a fleet of parallel agents"), "agent-code")
        self.assertEqual(classify_category("anyone/runner", "Run large language models locally"), "local")
        self.assertIsNone(classify_category("remotion-dev/remotion-like", "Weather station firmware"))


class OrderingTests(unittest.TestCase):
    def repo(self, id_, label, day=None, week=None, month=None, stars=0, forks=None, source="github-trending", ai=True):
        return {"id": id_, "label": label, "source": source, "ai_related": ai, "stars": stars, "forks": forks,
                "stars_gained": {"day": day, "week": week, "month": month}}

    def test_each_window_orders_by_its_own_gain_and_labels_do_not_reorder(self):
        repos = [self.repo("r1", "dung-ngay", day=10, week=900, stars=50),
                 self.repo("r2", "nghien-cuu", day=500, week=100, stars=10),
                 self.repo("r3", "xao-nau", day=None, week=3000, month=7000, stars=99, forks=7),
                 self.repo("hf", "dung-ngay", stars=10_000, source="hf"),
                 self.repo("noise", "dung-ngay", day=9999, ai=False),
                 self.repo("unmeasured", None, day=800)]
        rk = rank_repos(repos)
        self.assertEqual(rk["trending"]["day"], ["r2", "r1"], "unmeasured r3 is absent, not ranked by its week count")
        self.assertEqual(rk["trending"]["week"], ["r3", "r1", "r2"])
        self.assertEqual(rk["trending"]["month"], ["r3"])
        self.assertEqual(rk["stars"], ["r3", "r1", "r2"])
        self.assertEqual(rk["forks"], ["r3"])
        self.assertEqual(rk["usable"]["day"], ["r1"])
        self.assertEqual(rk["usable"]["week"], ["r1"])

    def test_ties_fall_back_to_total_stars_then_id(self):
        rk = rank_repos([self.repo("b", "xao-nau", day=5, stars=1), self.repo("a", "xao-nau", day=5, stars=1),
                         self.repo("c", "xao-nau", day=5, stars=9)])
        self.assertEqual(rk["trending"]["day"], ["c", "a", "b"])

    def test_rankings_reach_the_snapshot_meta(self):
        meta = {}
        fetch = fetcher_for({github.WINDOWS[1][1]: WEEK, github.WINDOWS[2][1]: MONTH})
        curate_repos(github.parse_trending(DAY), [], fetcher=fetch, now=NOW, meta=meta)
        self.assertEqual(meta["rankings"]["trending"]["month"][:2], ["d/video-gen", "c/voice-ai"])
        self.assertEqual(meta["rankings"]["trending"]["week"][:2], ["c/voice-ai", "a/agent-day"])
        json.dumps(meta)  # the page reads it as JSON


class ErrorWordingTests(unittest.TestCase):
    def test_reader_sees_vietnamese_and_maintainer_keeps_the_detail(self):
        self.assertEqual(vi_error("HTTPError: HTTP Error 403: Forbidden"), "Nguồn trả mã lỗi HTTP 403")
        self.assertEqual(vi_error("Build deadline exceeded"), "Hết thời hạn dựng bản tin trước khi nguồn trả lời")
        self.assertEqual(vi_error("Disabled: Nguồn tạm tắt."), "Tạm tắt: Nguồn tạm tắt.")
        self.assertEqual(vi_error("RuntimeError: odd"), "Không đọc được nguồn này")
        self.assertIsNone(vi_error(None))


if __name__ == "__main__":
    unittest.main()
