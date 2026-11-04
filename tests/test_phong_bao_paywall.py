"""A paywalled or login-only story with no readable alternative is held (captain, 2026-11-05)."""

import importlib.util
import io
import json
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from phong_bao.newsroom import _chief
from phong_bao.paywall import HOLD_REASON, held_for_paywall

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hold_paywalled", ROOT / "scripts" / "hold-paywalled-decisions.py")
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)

NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)
BLOOMBERG = "https://www.bloomberg.com/news/articles/2026-11-02/marvell-reaches-115-billion-deal-for-lumentum-holdings"
TECHCRUNCH = "https://techcrunch.com/2026/11/02/in-one-of-the-largest-deals-in-tech-history-marvell-buys-lumentum-for-115b/"


def chief(url, readable, status, selected=None):
    story = {"id": "s", "title": "Marvell Reaches $115 Billion Deal for Lumentum Holdings", "url": url,
             "published_at": "2026-11-02T12:15:00Z"}
    reporter = {"s": {"readable": readable, "selected_url": selected, "source_text": "text" if readable else "",
                      "representative_status": status}}
    editor = {"s": {"news": True, "importance": "notable", "reason": "deal", "content_kind": "event_news",
                    "analysis_kind": None, "event_at": "2026-11-02T12:15:00Z", "claims": [],
                    "same_event_coverage_ids": [], "split_coverage_ids": []}}
    checker = {"s": {"supported_claims": [], "title_supported": readable}}
    return _chief([story], {"s": {"pass": True, "reason": "eligible"}}, reporter, editor, checker, NOW)[0]


class PaywallHoldTests(unittest.TestCase):
    def test_paywalled_story_without_alternative_is_held(self):
        row = chief(BLOOMBERG, False, "error:http_403")
        self.assertEqual((row["decision"], row["round"], row["reason"]), ("hold", "chief", HOLD_REASON))

    def test_same_story_with_a_readable_alternative_is_published(self):
        row = chief(BLOOMBERG, True, "error:http_403", selected=TECHCRUNCH)
        self.assertEqual(row["decision"], "publish")
        self.assertEqual(row["source_url"], TECHCRUNCH)

    def test_bot_wall_robots_and_js_pages_keep_todays_behaviour(self):
        for url, status in (("https://openai.com/index/example", "error:http_403"),
                            ("https://www.cnbc.com/2026/11/02/example.html", "robots:unavailable_403"),
                            ("https://x.com/someone/status/1", "robots:disallow"),
                            ("https://longcat.ai/blog/example", "too_short:0 chars")):
            with self.subTest(url=url):
                self.assertEqual(chief(url, False, status)["decision"], "publish")

    def test_fetch_paywall_reason_holds_any_publisher(self):
        self.assertEqual(chief("https://example.com/article", False, "paywall:phrase 'subscribe to read'")["decision"], "hold")

    def test_only_scmp_plus_counts_as_paywalled_at_scmp(self):
        self.assertTrue(held_for_paywall("https://www.scmp.com/plus/tech/article/1/x", False, "too_short:0 chars"))
        self.assertFalse(held_for_paywall("https://www.scmp.com/tech/article/1/x", False, "error:http_403"))

    def test_own_article_readable_is_never_held(self):
        self.assertFalse(held_for_paywall(BLOOMBERG, False, "readable"))


class ExistingDecisionsScriptTests(unittest.TestCase):
    def fixture(self):
        def row(sid, url, degradations, decision="publish"):
            return {"id": sid, "decision": decision, "content_kind": "event_news", "analysis_kind": None,
                    "round": "chief", "reason": "; ".join(degradations) or "news and claims checked",
                    "importance_tier": "standard", "tier_capped": True, "summary": "none",
                    "degradation_reasons": degradations, "use_original_title": True, "source_url": url,
                    "key_points": [], "same_event_coverage_ids": [], "split_coverage_ids": []}
        lost = ["no readable same-event source", "original title not source-checked", "too few verified claims for summary"]
        return {"schema_version": 1, "generated_at": "2026-11-04T17:10:33+00:00", "input_generated_at": None,
                "decisions": [row("bbg", BLOOMBERG, lost),
                              row("bbg-recovered", TECHCRUNCH, ["checker rejected claims"]),
                              row("openai", "https://openai.com/index/example", lost),
                              row("held", "https://www.ft.com/content/x", lost, decision="hold")]}

    def run_script(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(SCRIPT.main([str(a) for a in args]), 0)
        return out.getvalue()

    def test_dry_run_lists_rows_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            path.write_text(json.dumps(self.fixture()), encoding="utf-8")
            before = path.read_bytes()
            output = self.run_script(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["decisions.json"])
        self.assertIn("bbg\tbloomberg.com\t", output)
        self.assertIn("1 of 3 publish rows would be held", output)

    def test_apply_writes_a_new_file_with_those_rows_held(self):
        with tempfile.TemporaryDirectory() as directory:
            path, out = Path(directory) / "decisions.json", Path(directory) / "held.json"
            path.write_text(json.dumps(self.fixture()), encoding="utf-8")
            before = path.read_bytes()
            self.run_script(path, "--apply", out)
            self.assertEqual(path.read_bytes(), before)
            rows = {row["id"]: row for row in json.loads(out.read_text(encoding="utf-8"))["decisions"]}
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()), unittest.mock.patch("sys.stderr", io.StringIO()):
                    SCRIPT.main([str(path), "--apply", str(path)])
        self.assertEqual((rows["bbg"]["decision"], rows["bbg"]["reason"]), ("hold", HOLD_REASON))
        self.assertEqual(rows["bbg-recovered"]["decision"], "publish")
        self.assertEqual(rows["openai"]["decision"], "publish")

    def test_apply_never_overwrites_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path, other = Path(directory) / "decisions.json", Path(directory) / "other-snapshot.json"
            path.write_text(json.dumps(self.fixture()), encoding="utf-8")
            other.write_text('{"schema_version": 1, "decisions": []}', encoding="utf-8")
            before = other.read_bytes()
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                    unittest.mock.patch("sys.stderr", io.StringIO()):
                SCRIPT.main([str(path), "--apply", str(other)])
            self.assertEqual(other.read_bytes(), before)
            # A file created between the check and the write is refused by the exclusive create.
            late = Path(directory) / "late.json"
            real_exists = Path.exists
            with unittest.mock.patch.object(Path, "exists", lambda p: False if p == late else real_exists(p)):
                late.write_text("keep", encoding="utf-8")
                with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                        unittest.mock.patch("sys.stderr", io.StringIO()):
                    SCRIPT.main([str(path), "--apply", str(late)])
            self.assertEqual(late.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
