"""Unit tests for radar/source_scorecard.py using real snapshot slice fixtures."""

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
    parse_iso_datetime,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "scorecard_snapshots"


class TestSourceScorecard(unittest.TestCase):
    def test_parse_iso_datetime(self):
        # Valid ISO strings
        dt1 = parse_iso_datetime("2026-10-02T09:57:17Z")
        self.assertEqual(dt1, datetime(2026, 10, 2, 9, 57, 17, tzinfo=timezone.utc))
        
        dt2 = parse_iso_datetime("2026-10-02T16:57:17+07:00")
        self.assertEqual(dt2, datetime(2026, 10, 2, 9, 57, 17, tzinfo=timezone.utc))

        # None / invalid inputs
        self.assertIsNone(parse_iso_datetime(None))
        self.assertIsNone(parse_iso_datetime(""))
        self.assertIsNone(parse_iso_datetime("not-a-date"))
        self.assertIsNone(parse_iso_datetime(12345))

    def test_categorize_error(self):
        self.assertEqual(categorize_error("Disabled: Reason"), "Disabled")
        self.assertEqual(categorize_error("HTTPError: 403 Forbidden", 403), "HTTP 403")
        self.assertEqual(categorize_error("HTTPError: 404 Not Found", 404), "HTTP 404")
        self.assertEqual(categorize_error("HTTPError: 429 Too Many Requests", 429), "HTTP 429")
        self.assertEqual(categorize_error("HTTPError: 500 Server Error", 500), "HTTP 500")
        self.assertEqual(categorize_error("Build deadline exceeded"), "Timeout / Deadline")
        self.assertEqual(categorize_error("XML parse failed: syntax error"), "Parse Error")
        self.assertEqual(categorize_error(None, None), "None")

    def test_discover_snapshots(self):
        self.assertTrue(FIXTURES_DIR.exists(), f"Fixture directory not found: {FIXTURES_DIR}")
        snapshots = discover_snapshots(FIXTURES_DIR)
        self.assertEqual(len(snapshots), 3)
        # Chronological ordering check
        self.assertEqual(snapshots[0]["name"], "2026-10-04T093532Z")
        self.assertEqual(snapshots[1]["name"], "2026-10-04T094210Z")
        self.assertEqual(snapshots[2]["name"], "2026-10-04T100251Z")

    def test_analyze_snapshots_structure_and_sources(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)

        self.assertIn("summary", scorecard)
        self.assertIn("sources", scorecard)

        summary = scorecard["summary"]
        self.assertEqual(summary["snapshots_count"], 3)
        self.assertGreater(summary["total_sources"], 0)
        self.assertGreater(summary["total_unique_items"], 0)

        sources = scorecard["sources"]
        # Check expected sources from fixture
        self.assertIn("techcrunch-ai", sources)
        self.assertIn("verge-ai", sources)
        self.assertIn("hn-ai", sources)
        self.assertIn("vnexpress-so-hoa", sources)
        self.assertIn("tuoitre-so", sources)
        self.assertIn("google-deepmind", sources)

    def test_reliability_metrics(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)
        sources = scorecard["sources"]

        # vnexpress-so-hoa should fail 100% with HTTP 404
        vnexpress = sources["vnexpress-so-hoa"]
        self.assertEqual(vnexpress["reliability"]["runs_total"], 3)
        self.assertEqual(vnexpress["reliability"]["runs_failed"], 3)
        self.assertEqual(vnexpress["reliability"]["failure_rate"], 1.0)
        self.assertIn("HTTP 404", vnexpress["reliability"]["error_kinds"])

        # google-deepmind should be marked disabled
        deepmind = sources["google-deepmind"]
        self.assertTrue(deepmind["reliability"]["is_disabled"])
        self.assertEqual(deepmind["reliability"]["failure_rate"], 1.0)

        # techcrunch-ai should have 0% failure in fixture
        tc = sources["techcrunch-ai"]
        self.assertEqual(tc["reliability"]["failure_rate"], 0.0)
        self.assertEqual(tc["reliability"]["runs_failed"], 0)

    def test_earliness_metrics_and_thin_flag(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)
        sources = scorecard["sources"]

        # For sources with multi-source stories
        for sid, s in sources.items():
            ear = s["earliness"]
            self.assertIn("multi_stories_count", ear)
            self.assertIn("first_count", ear)
            self.assertIn("thin", ear)
            if ear["multi_stories_count"] < 5:
                self.assertTrue(ear["thin"])
            else:
                self.assertFalse(ear["thin"])

    def test_quality_and_timestamp_issues(self):
        snapshots = discover_snapshots(FIXTURES_DIR)
        scorecard = analyze_snapshots(snapshots)
        sources = scorecard["sources"]

        # tuoitre-so has items with missing timestamps (pub=None)
        tuoitre = sources.get("tuoitre-so")
        if tuoitre and tuoitre["quality"]["total_items"] > 0:
            self.assertGreater(tuoitre["quality"]["missing_timestamp_count"], 0)
            self.assertEqual(tuoitre["quality"]["missing_timestamp_count"], tuoitre["quality"]["total_items"])
            self.assertEqual(tuoitre["quality"]["timestamp_issues_share"], 1.0)

        # techcrunch-ai has high AI relevance
        tc = sources.get("techcrunch-ai")
        if tc and tc["quality"]["total_items"] > 0:
            self.assertGreaterEqual(tc["quality"]["ai_share"], 0.5)

    def test_derive_verdict(self):
        # 100% failure -> CUT
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=1.0, is_disabled=False, item_cnt=0,
            ai_share=0.0, first_rate=None, multi_cnt=0, med_pipe_lag=None,
            ts_issue_share=0.0, rewrite_share=0.0, error_kinds={"HTTP 404": 10}
        )
        self.assertEqual(verdict, "CUT")

        # 100% broken timestamps -> FIX
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=0.0, is_disabled=False, item_cnt=10,
            ai_share=0.9, first_rate=None, multi_cnt=0, med_pipe_lag=None,
            ts_issue_share=1.0, rewrite_share=0.0, error_kinds={}
        )
        self.assertEqual(verdict, "FIX")

        # High earliness + fast pipeline -> PROMOTE
        verdict, rat = derive_verdict(
            runs_tot=10, fail_rate=0.0, is_disabled=False, item_cnt=15,
            ai_share=0.95, first_rate=0.8, multi_cnt=8, med_pipe_lag=1.2,
            ts_issue_share=0.0, rewrite_share=0.0, error_kinds={}
        )
        self.assertEqual(verdict, "PROMOTE")

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

            export_markdown(scorecard, md_path)
            self.assertTrue(md_path.exists())
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("# Bảng điểm Nguồn tin AI Radar", content)
            self.assertIn("techcrunch-ai", content)
            self.assertIn("Master Scorecard", content)


if __name__ == "__main__":
    unittest.main()
