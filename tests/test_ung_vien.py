"""The news agency hands the newsroom fresh, readable, unsummarised stories (docs/hop-dong-ung-vien.md)."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from radar import ung_vien
from radar.items import instant

FIXTURES = Path(__file__).parent / "fixtures" / "ung-vien"
SNAPSHOT = FIXTURES / "snapshot.json"
ARTICLES = FIXTURES / "articles.json"
NOW = "2026-10-28T14:21:19Z"
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REASONS = {"already_summarised", "outside_window", "unreadable", "too_short", "duplicate_published", "limit"}
KINDS = {"outlet", "lab", "paper", "regulator", "blog", "other"}
CANDIDATE_FIELDS = {"id", "title", "title_vi", "url", "source", "published_at", "text", "text_chars",
                    "text_source", "text_fetched_at", "coverage", "same_event_published"}


def contract_errors(data):
    """Every way a file breaks hop-dong-ung-vien.md version 1; empty when it conforms."""
    errors = []
    top = {"schema_version", "generated_at", "snapshot_generated_at", "window_hours", "limit", "counts",
           "candidates", "rejected"}
    if set(data) != top:
        return [f"top-level keys {sorted(set(data) ^ top)}"]
    if data["schema_version"] != 1:
        errors.append("schema_version")
    for key in ("generated_at", "snapshot_generated_at"):
        if not isinstance(data[key], str) or not ISO_Z.match(data[key]):
            errors.append(key)
    if not isinstance(data["window_hours"], (int, float)) or not isinstance(data["limit"], int):
        errors.append("window_hours/limit")
    counts = data["counts"]
    if counts != {"in_window": counts.get("in_window"), "candidates": len(data["candidates"]),
                  "rejected": len(data["rejected"])} or not isinstance(counts["in_window"], int):
        errors.append(f"counts {counts}")
    if len(data["candidates"]) > data["limit"]:
        errors.append("over limit")
    dates = [row.get("published_at") for row in data["candidates"]]
    if dates != sorted(dates, reverse=True):
        errors.append("candidates not newest first")
    ids = [row.get("id") for row in data["candidates"] + data["rejected"]]
    if len(ids) != len(set(ids)):
        errors.append("a story appears twice")
    for row in data["candidates"]:
        name = row.get("id")
        if not set(row) - {"text_truncated"} == CANDIDATE_FIELDS:
            errors.append(f"{name} fields {sorted(set(row) ^ CANDIDATE_FIELDS)}")
            continue
        if not (isinstance(row["id"], str) and row["id"] and isinstance(row["title"], str) and row["title"]):
            errors.append(f"{name} id/title")
        if row["title_vi"] is not None and not (isinstance(row["title_vi"], str) and row["title_vi"]):
            errors.append(f"{name} title_vi")
        if not row["url"].startswith("https://"):
            errors.append(f"{name} url")
        source = row["source"]
        if set(source) != {"name", "kind"} or not source["name"] or source["kind"] not in KINDS:
            errors.append(f"{name} source {source}")
        for key in ("published_at", "text_fetched_at"):
            if not ISO_Z.match(row[key]):
                errors.append(f"{name} {key}")
        if not isinstance(row["text"], str) or row["text_chars"] != len(row["text"]) or row["text_chars"] > 24_000:
            errors.append(f"{name} text/text_chars")
        if row["text_source"] not in {"full", "abstract", "partial"}:
            errors.append(f"{name} text_source")
        if row["text_source"] != "abstract" and row["text_chars"] < 600:
            errors.append(f"{name} too short to be a candidate")
        if "text_truncated" in row and row["text_truncated"] is not True:
            errors.append(f"{name} text_truncated")
        if any(set(item) != {"id", "title", "url"} for item in row["coverage"]):
            errors.append(f"{name} coverage")
        if not all(isinstance(item, str) for item in row["same_event_published"]):
            errors.append(f"{name} same_event_published")
    for row in data["rejected"]:
        if set(row) != {"id", "title", "url", "reason", "detail"} or row["reason"] not in REASONS \
                or not isinstance(row["detail"], str):
            errors.append(f"rejected {row}")
    return errors


def fixture_snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def fixture_read():
    return ung_vien.fixture_reader(ARTICLES)


def build(snapshot=None, *, hours=40, limit=30, read=None, **options):
    return ung_vien.build(snapshot or fixture_snapshot(), hours=hours, limit=limit, now=instant(NOW),
                          read=read or fixture_read(), **options)


def by_url(rows, fragment):
    return next(row for row in rows if fragment in row["url"])


class OfflineRunTest(unittest.TestCase):
    def run_main(self, *extra):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "ung-vien.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = ung_vien.main(["--hours", "40", "--limit", "30", "--out", str(out), "--snapshot", str(SNAPSHOT),
                                      "--articles", str(ARTICLES), "--now", NOW, *extra])
            data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        return code, stdout.getvalue(), data

    def test_fixture_run_writes_a_file_that_follows_the_contract(self):
        code, stdout, data = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(contract_errors(data), [])
        counts = data["counts"]
        self.assertEqual(stdout, f"in_window={counts['in_window']} candidates={counts['candidates']} "
                                 f"rejected={counts['rejected']}\n")
        self.assertEqual(data["window_hours"], 40)
        self.assertEqual(data["snapshot_generated_at"], NOW)
        self.assertEqual({row["reason"] for row in data["rejected"]}, {"already_summarised", "unreadable", "too_short"})
        self.assertEqual(counts, {"in_window": 14, "candidates": 8, "rejected": 6})

    def test_validator_rejects_a_broken_file(self):
        _, _, data = self.run_main()
        broken = deepcopy(data)
        broken["candidates"][0]["text_source"] = "teaser"
        del broken["candidates"][1]["coverage"]
        broken["rejected"][0]["reason"] = "boring"
        self.assertEqual(len(contract_errors(broken)), 3)

    def test_unavailable_snapshot_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "ung-vien.json"
            with redirect_stdout(io.StringIO()):
                code = ung_vien.main(["--out", str(out), "--snapshot", str(Path(folder) / "missing.json"),
                                      "--articles", str(ARTICLES)])
            self.assertNotEqual(code, 0)
            self.assertFalse(out.exists())

    def test_keep_rejected_window_lists_old_and_undated_stories(self):
        code, _, data = self.run_main("--keep-rejected-window")
        self.assertEqual(code, 0)
        self.assertEqual(contract_errors(data), [])
        outside = [row for row in data["rejected"] if row["reason"] == "outside_window"]
        self.assertEqual(len(outside), 3)
        self.assertIn("published_at missing", {row["detail"] for row in outside})


class WindowTest(unittest.TestCase):
    def test_window_keeps_only_recent_stories_and_does_not_list_the_rest(self):
        wide, narrow = build(hours=40), build(hours=8)
        self.assertEqual(wide["counts"]["in_window"], 14)
        self.assertEqual(narrow["counts"]["in_window"], 13)  # the arXiv paper is 38 hours old
        self.assertNotIn("outside_window", {row["reason"] for row in narrow["rejected"]})
        listed = {row["id"] for row in narrow["candidates"] + narrow["rejected"]}
        self.assertNotIn("f749bb8136379d77e619", listed)

    def test_future_dates_are_tolerated_for_one_hour_only(self):
        for published_at, inside in (("2026-10-28T15:10:00Z", True), ("2026-10-28T16:30:00Z", False),
                                     ("2026-10-29T10:00:00Z", False), ("2026-11-05T00:00:00Z", False)):
            snapshot = fixture_snapshot()
            snapshot["stories"][2]["published_at"] = published_at
            data = build(snapshot)
            self.assertEqual(data["counts"]["in_window"], 14 if inside else 13, published_at)
            listed = {row["id"] for row in data["candidates"] + data["rejected"]}
            self.assertEqual(snapshot["stories"][2]["id"] in listed, inside, published_at)


class RejectReasonTest(unittest.TestCase):
    def test_already_summarised_names_the_summary(self):
        rows = [row for row in build()["rejected"] if row["reason"] == "already_summarised"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["detail"] for row in rows}, {"key_points x4 (nguoi-viet)"})

    def test_published_decision_counts_as_summarised(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "decisions.json"
            path.write_text(json.dumps({"schema_version": 1, "decisions": [
                {"id": "f749bb8136379d77e619", "decision": "publish"},
                {"id": "5c0e62d42f14a6cede08", "decision": "hold"}]}), encoding="utf-8")
            data = build(decided=ung_vien.published_decision_ids(path))
        row = next(row for row in data["rejected"] if row["id"] == "f749bb8136379d77e619")
        self.assertEqual((row["reason"], row["detail"]), ("already_summarised", "decisions.json publish"))
        self.assertIn("5c0e62d42f14a6cede08", {row["id"] for row in data["candidates"]})

    def test_unreadable_carries_the_reader_reason(self):
        rows = build()["rejected"]
        self.assertEqual(by_url(rows, "kotaku.com")["detail"], "fetch_article_result: robots")
        self.assertEqual(by_url(rows, "bloomberg.com/news/articles/2026-10-28/moore")["detail"],
                         "fetch_article_result: error")
        self.assertEqual({row["reason"] for row in rows if "bloomberg" in row["url"] or "kotaku" in row["url"]},
                         {"unreadable"})

    def test_plain_http_url_is_unreadable_and_not_fetched(self):
        snapshot = fixture_snapshot()
        story = next(s for s in snapshot["stories"] if "404media" in s["url"])
        story["url"] = story["url"].replace("https://", "http://")
        fetched = []

        def read(url):
            fetched.append(url)
            return fixture_read()(url)
        data = build(snapshot, read=read)
        self.assertEqual(contract_errors(data), [])
        row = next(row for row in data["rejected"] if row["id"] == story["id"])
        self.assertEqual((row["reason"], row["detail"]), ("unreadable", "not https"))
        self.assertNotIn(story["url"], fetched)

    def test_too_short_below_six_hundred_characters(self):
        row = by_url(build()["rejected"], "terk-terkowitz")
        self.assertEqual(row["reason"], "too_short")
        self.assertRegex(row["detail"], r"^text_chars \d{3}$")

    def test_reader_too_short_is_too_short(self):
        def read(url):
            if "404media" in url:
                return "", "too_short", datetime.now(timezone.utc)
            return fixture_read()(url)
        row = by_url(build(read=read)["rejected"], "404media")
        self.assertEqual((row["reason"], row["detail"]), ("too_short", "fetch_article_result: too_short (<300 chars)"))

    def test_reader_crash_becomes_an_unreadable_reason(self):
        def explode(story, robots_cache):
            raise RuntimeError("socket closed")
        with patch.object(ung_vien, "fetch_article_result", explode):
            text, reason, fetched_at = ung_vien.network_reader()("https://example.com/a")
        self.assertEqual((text, reason), ("", "error: RuntimeError"))
        self.assertIsNotNone(fetched_at.tzinfo)

    def test_duplicate_of_a_published_story_is_rejected_and_an_update_is_kept(self):
        snapshot = fixture_snapshot()
        published = next(s for s in snapshot["stories"] if s.get("key_points"))
        repeat = deepcopy(published)
        for key in ("key_points", "key_points_source", "key_points_prompt_version", "editorial_headline_vi"):
            repeat.pop(key, None)
        repeat.update(id="aaaaaaaaaaaaaaaaaaa1", aliases=[published["id"]], published_at="2026-10-28T14:00:00Z")
        update = deepcopy(repeat)
        update["id"] = "aaaaaaaaaaaaaaaaaaa2"
        new_article = {"id": "bbbbbbbbbbbbbbbbbbb2", "source": "404media", "publisher": "404-media", "group": "press",
                       "kind": "other", "title": "Follow-up", "url": "https://www.404media.co/meta-ai-training-uk-eu/",
                       "canonical_url": "https://www.404media.co/meta-ai-training-uk-eu",
                       "published_at": "2026-10-28T14:00:00Z"}
        update["url"] = new_article["url"]
        update["coverage"] = update["coverage"] + [new_article]
        snapshot["stories"] += [repeat, update]
        data = build(snapshot)
        self.assertEqual(contract_errors(data), [])
        row = next(row for row in data["rejected"] if row["id"] == repeat["id"])
        self.assertEqual((row["reason"], row["detail"]), ("duplicate_published", "same event as " + published["id"]))
        kept = next(row for row in data["candidates"] if row["id"] == update["id"])
        self.assertEqual(kept["same_event_published"], [published["id"]])
        self.assertEqual([item["id"] for item in kept["coverage"]], [item["id"] for item in published["coverage"]])

    def test_limit_keeps_the_newest_readable_and_skips_fetching_the_rest(self):
        fetched = []

        def read(url):
            fetched.append(url)
            return fixture_read()(url)
        data = build(limit=2, read=read)
        self.assertEqual(contract_errors(data), [])
        self.assertEqual(len(data["candidates"]), 2)
        limited = [row for row in data["rejected"] if row["reason"] == "limit"]
        self.assertTrue(limited)
        self.assertEqual({row["detail"] for row in limited}, {"beyond --limit 2"})
        self.assertTrue(all(row["url"] not in fetched for row in limited))
        newest_limited = max(instant(s["published_at"]) for s in fixture_snapshot()["stories"]
                             if s["id"] in {row["id"] for row in limited})
        self.assertTrue(all(instant(row["published_at"]) >= newest_limited for row in data["candidates"]))


class TextSourceTest(unittest.TestCase):
    def test_paper_is_abstract_outlet_is_full_teaser_is_partial(self):
        rows = build()["candidates"]
        paper = by_url(rows, "arxiv.org")
        self.assertEqual((paper["text_source"], paper["source"]), ("abstract", {"name": "hf-papers", "kind": "paper"}))
        outlet = by_url(rows, "404media")
        self.assertEqual((outlet["text_source"], outlet["source"]), ("full", {"name": "404media", "kind": "outlet"}))
        teaser = by_url(rows, "interconnects.ai")
        self.assertEqual((teaser["text_source"], teaser["source"]["kind"]), ("partial", "blog"))

    def test_audio_player_tail_marks_an_outlet_excerpt_partial(self):
        row = by_url(build()["candidates"], "unitree-reports-70-surge")
        self.assertEqual((row["text_source"], row["source"]["kind"]), ("partial", "outlet"))
        for furniture in ("Select Voice", "AI-generated voice", "Advertisement", "0.9x1.0x", "00:0000:00"):
            self.assertNotIn(furniture, row["text"].split("\n\n"))
        self.assertIn("Unitree Robotics", row["text"])

    def test_long_outlet_text_with_a_player_tail_is_partial_and_without_is_full(self):
        body = "\n".join(["A full paragraph about the model release and what it changes for users."] * 30)

        def read_with(tail):
            return lambda url: (body + tail, None, datetime.now(timezone.utc))
        self.assertEqual(by_url(build(read=read_with("\nSelect Voice\n1x\nAI-generated voice"))["candidates"],
                                "404media")["text_source"], "partial")
        self.assertEqual(by_url(build(read=read_with("\nAD"))["candidates"], "404media")["text_source"], "full")

    def test_short_outlet_text_is_partial(self):
        text = "\n".join(["A complete looking paragraph that is nevertheless short for an outlet."] * 12)
        row = by_url(build(read=lambda url: (text, None, datetime.now(timezone.utc)))["candidates"], "404media")
        self.assertLess(row["text_chars"], 1000)
        self.assertEqual(row["text_source"], "partial")

    def test_complete_outlet_brief_over_one_thousand_characters_is_full(self):
        text = "\n".join(["A complete brief paragraph from an outlet that runs short but has no cut-off."] * 15)
        row = by_url(build(read=lambda url: (text, None, datetime.now(timezone.utc)))["candidates"], "404media")
        self.assertTrue(1000 <= row["text_chars"] < 1500)
        self.assertEqual(row["text_source"], "full")

    def test_page_furniture_is_removed_and_arxiv_keeps_the_abstract(self):
        raw = "Advertisement\nPress Enter to search · Advanced search\nFirst paragraph.\nAD\nSecond paragraph.\nClose Ad"
        self.assertEqual(ung_vien.clean_text(raw), "First paragraph.\n\nSecond paragraph.")
        paper = by_url(build()["candidates"], "arxiv.org")
        self.assertTrue(paper["text"].split("\n\n")[-1].startswith("Abstract:"))
        for furniture in ("Press Enter to search", "arXivLabs", "Bibliographic", "Submission history", "View PDF"):
            self.assertNotIn(furniture, paper["text"])
        self.assertLess(paper["text_chars"], 2200)

    def test_short_abstract_is_still_a_candidate(self):
        def read(url):
            text, reason, at = fixture_read()(url)
            return (text[:450] if "arxiv" in url else text), reason, at
        paper = by_url(build(read=read)["candidates"], "arxiv.org")
        self.assertEqual(paper["text_source"], "abstract")
        self.assertLess(paper["text_chars"], 600)

    def test_long_text_is_cut_at_a_paragraph_and_flagged(self):
        paragraph = "Sentence about the model release. " * 40
        long_text = "\n".join([paragraph.strip()] * 30)

        def read(url):
            return long_text, None, datetime.now(timezone.utc)
        row = by_url(build(read=read)["candidates"], "404media")
        self.assertTrue(row["text_truncated"])
        self.assertLessEqual(row["text_chars"], 24_000)
        self.assertTrue(row["text"].endswith("release."))
        self.assertNotIn("text_truncated", by_url(build()["candidates"], "404media"))

    def test_title_vi_prefers_the_site_translation(self):
        rows = build()["candidates"]
        self.assertIsNone(by_url(rows, "404media")["title_vi"])
        self.assertTrue(by_url(rows, "technologyreview.com")["title_vi"])

    def test_source_kind_rules(self):
        cases = {
            "https://www.ftc.gov/news-events/x": "regulator",
            "https://digital-strategy.ec.europa.eu/en/news/x": "regulator",
            "https://openai.com/index/x": "lab",
            "https://openreview.net/forum?id=x": "paper",
        }
        for url, kind in cases.items():
            story = {"url": url, "coverage": [{"url": url, "source": "s", "group": "forum"}]}
            self.assertEqual(ung_vien.source_of(story)["kind"], kind, url)
        press = {"url": "https://example.com/a", "coverage": [{"url": "https://example.com/a", "source": "ex",
                                                                "group": "press"}]}
        self.assertEqual(ung_vien.source_of(press), {"name": "ex", "kind": "outlet"})


if __name__ == "__main__":
    unittest.main()
