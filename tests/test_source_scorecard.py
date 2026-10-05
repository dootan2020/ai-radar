"""Unit tests for radar/source_scorecard.py using minimal slice fixtures."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from radar.source_scorecard import (
    analyze_snapshots,
    categorize_error,
    derive_verdict,
    discover_snapshots,
    export_json,
    export_markdown,
    find_duplicate_feeds,
    is_date_only,
    parse_iso_datetime,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "scorecard_snapshots"


class TestSourceScorecard(unittest.TestCase):
    def test_parse_iso_datetime(self):
        dt1 = parse_iso_datetime("2026-10-02T09:57:17Z")
        self.assertEqual(dt1, datetime(2026, 10, 2, 9, 57, 17, tzinfo=timezone.utc))

        dt2 = parse_iso_datetime("2026-10-02T16:57:17+07:00")
        self.assertEqual(dt2, datetime(2026, 10, 2, 9, 57, 17, tzinfo=timezone.utc))

        self.assertIsNone(parse_iso_datetime(None))
        self.assertIsNone(parse_iso_datetime(""))
        self.assertIsNone(parse_iso_datetime("invalid-date"))
        self.assertIsNone(parse_iso_datetime(12345))

    def test_is_date_only(self):
        # Midnight UTC / date-only formats
        dt_midnight = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_date_only("2026-10-02T00:00:00Z", dt_midnight))
        self.assertTrue(is_date_only("2026-10-02", dt_midnight))

        # Non-midnight times
        dt_time = datetime(2026, 10, 2, 9, 30, 0, tzinfo=timezone.utc)
        self.assertFalse(is_date_only("2026-10-02T09:30:00Z", dt_time))
        self.assertFalse(is_date_only(None, None))

    def test_categorize_error_and_disabled_vs_failing(self):
        # Rule 4: Differentiate Disabled vs Failing 404
        self.assertEqual(
            categorize_error("Disabled: Substack podcast feed returned HTTP 403", is_disabled=True),
            "Disabled (Substack 403)"
        )
        self.assertEqual(
            categorize_error("Disabled: Nguồn CNBC trả mã HTTP 403", is_disabled=True),
            "Disabled (CNBC 403)"
        )
        self.assertEqual(
            categorize_error("Disabled: RSS endpoint returned HTTP 200 with invalid XML", is_disabled=True),
            "Disabled (Invalid XML)"
        )
        self.assertEqual(
            categorize_error("HTTPError: HTTP Error 404: Not Found", http_status=404, is_disabled=False),
            "HTTP 404 (Address Changed)"
        )
        self.assertEqual(categorize_error("HTTPError: 403 Forbidden", 403), "HTTP 403")
        self.assertEqual(categorize_error("HTTPError: 429 Too Many Requests", 429), "HTTP 429")
        self.assertEqual(categorize_error("Build deadline exceeded"), "Timeout / Deadline")
        self.assertEqual(categorize_error(None, None), "None")

    def test_discover_snapshots(self):
        self.assertTrue(FIXTURES_DIR.exists(), f"Fixture directory not found: {FIXTURES_DIR}")
        snapshots = discover_snapshots(FIXTURES_DIR)
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(snapshots[0]["name"], "2026-10-04T093532Z")
        self.assertEqual(snapshots[1]["name"], "2026-10-04T094210Z")
        self.assertEqual(snapshots[2]["name"], "2026-10-04T100251Z")

    def test_rule_1_pipeline_lag_excludes_items_before_or_in_first_snapshot(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)
        sources = scorecard["sources"]

        tc = sources["techcrunch-ai"]
        # In fixture, techcrunch has:
        # - Item 0: in first snapshot (published at 08:00, before first snapshot) -> EXCLUDED from lag
        # - Item 1: in snapshot 2 (published at 09:36, seen at 09:42 -> lag = 0.10h) -> INCLUDED
        # - Item 2: in snapshot 3 (published at 09:50, seen at 10:02 -> lag = 0.20h) -> INCLUDED
        pl = tc["pipeline_lag"]
        self.assertEqual(pl["items_measured"], 2)
        self.assertAlmostEqual(pl["median_hours"], 0.15, places=2)
        self.assertAlmostEqual(pl["min_hours"], 0.10, places=2)
        self.assertAlmostEqual(pl["max_hours"], 0.20, places=2)

    def test_rule_2_earliness_and_duplicate_feeds(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)
        sources = scorecard["sources"]
        summary = scorecard["summary"]

        # In fixture:
        # story-anthropic-dup has anthropic-news and anthropic-gftdon (both publisher="anthropic")
        # Because both have the same publisher, this is NOT a multi-publisher story!
        # Multi-publisher stories require len(publishers) >= 2.
        # Only story-multi-pub-1 (techcrunch vs verge) and story-multi-pub-2 (hn vs techcrunch) are multi-publisher.
        self.assertEqual(summary["multi_publisher_stories_count"], 2)

        # Anthropic feeds must NOT have multi-publisher counts from racing themselves
        self.assertEqual(sources["anthropic-news"]["earliness"]["multi_stories_count"], 0)
        self.assertEqual(sources["anthropic-gftdon"]["earliness"]["multi_stories_count"], 0)

        # TechCrunch participates in 2 multi-publisher stories
        tc_ear = sources["techcrunch-ai"]["earliness"]
        self.assertEqual(tc_ear["multi_stories_count"], 2)
        # TechCrunch was first in story 1 (09:36 vs 09:40 for verge)
        # and second in story 2 (09:50 vs 09:45 for hn)
        self.assertEqual(tc_ear["first_count"], 1)

        # Duplicate feeds check: Anthropic feeds should be identified as duplicates
        dup_pairs = [(d["source_1"], d["source_2"]) for d in summary["duplicate_feeds"]]
        self.assertIn(("anthropic-gftdon", "anthropic-news"), dup_pairs)

    def test_rule_3_timestamp_separation_missing_future_date_only_archive(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)
        sources = scorecard["sources"]

        # Missing timestamp: tuoitre-so has null published_at
        tuoitre = sources["tuoitre-so"]
        self.assertEqual(tuoitre["quality"]["missing_timestamp_count"], 1)
        self.assertEqual(tuoitre["quality"]["future_timestamp_count"], 0)

        # Future timestamp: genk-ai has published_at = 16:00 when snapshot is 09:42
        genk = sources["genk-ai"]
        self.assertEqual(genk["quality"]["future_timestamp_count"], 1)
        self.assertEqual(genk["quality"]["missing_timestamp_count"], 0)

        # Date-only timestamp: anthropic-news has 00:00:00Z
        anth = sources["anthropic-news"]
        self.assertGreater(anth["quality"]["date_only_timestamp_count"], 0)

        # Archive item: archive-source has item from August (> 30 days old)
        # Archive items must NOT be counted as timestamp errors!
        arch = sources["archive-source"]
        self.assertEqual(arch["quality"]["archive_items_count"], 1)
        self.assertEqual(arch["quality"]["timestamp_issues_count"], 0)

    def test_rule_4_reliability_and_tech_status(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)
        sources = scorecard["sources"]

        # vnexpress-so-hoa: Failing 100% with HTTP 404 (Address Changed)
        vnexpress = sources["vnexpress-so-hoa"]
        self.assertEqual(vnexpress["reliability"]["tech_status"], "FAILING")
        self.assertEqual(vnexpress["reliability"]["failure_rate"], 1.0)
        self.assertIn("HTTP 404 (Address Changed)", vnexpress["reliability"]["error_kinds"])

        # google-deepmind: Disabled (Invalid XML)
        deepmind = sources["google-deepmind"]
        self.assertEqual(deepmind["reliability"]["tech_status"], "DISABLED")
        self.assertTrue(deepmind["reliability"]["is_disabled"])
        self.assertIn("Disabled (Invalid XML)", deepmind["reliability"]["error_kinds"])

        # import-ai: Disabled (Substack 403)
        import_ai = sources["import-ai"]
        self.assertEqual(import_ai["reliability"]["tech_status"], "DISABLED")
        self.assertIn("Disabled (Substack 403)", import_ai["reliability"]["error_kinds"])

    def test_derive_verdict_and_evidence_threshold(self):
        # Disabled -> CUT
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=1.0, is_disabled=True, disabled_reason="Substack 403"
        )
        self.assertEqual(verdict, "CUT")
        self.assertIn("vô hiệu hóa", rat)

        # Failing 404 -> CUT with address changed rationale
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=1.0, is_disabled=False,
            error_kinds={"HTTP 404 (Address Changed)": 10}
        )
        self.assertEqual(verdict, "CUT")
        self.assertIn("404", rat)

        # High earliness with enough samples (N_multi >= 5) -> PROMOTE
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=0.0, is_disabled=False, item_cnt=15,
            ai_share=0.95, first_rate=0.8, multi_cnt=8, med_pipe_lag=1.2
        )
        self.assertEqual(verdict, "PROMOTE")

        # Stable with enough samples (N_multi >= 5) -> KEEP
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=0.0, is_disabled=False, item_cnt=15,
            ai_share=0.95, first_rate=0.4, multi_cnt=6, med_pipe_lag=5.0
        )
        self.assertEqual(verdict, "KEEP")

        # Rule: when a source has too few independent clusters (N_multi < 5),
        # say "not enough evidence yet" rather than KEEP or CUT
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=0.0, is_disabled=False, item_cnt=8,
            ai_share=0.9, first_rate=0.5, multi_cnt=2, med_pipe_lag=2.0
        )
        self.assertEqual(verdict, "NOT_ENOUGH_EVIDENCE")
        self.assertIn("not enough evidence yet", rat)

    def test_export_json_and_markdown(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "scorecard.json"
            md_path = Path(tmpdir) / "scorecard.md"

            export_json(scorecard, json_path)
            self.assertTrue(json_path.exists())
            with open(json_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["summary"]["snapshots_count"], 3)
            self.assertEqual(loaded["summary"]["multi_publisher_stories_count"], 2)

            export_markdown(scorecard, md_path)
            self.assertTrue(md_path.exists())
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("# Bảng điểm Nguồn tin AI Radar (Source Scorecard) - Round 2", content)
            self.assertIn("Duplicate Feeds", content)
            self.assertIn("Disabled vs Failing", content)


if __name__ == "__main__":
    unittest.main()
