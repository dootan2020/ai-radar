"""Tests for Halcyon newsroom contracts, fail-closed safety, and injection guards."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from phong_bao.contracts import (
    DESK_CONTRACTS,
    check_prompt_injection,
    is_unverifiable_rumour,
    validate_checker_output,
    validate_checker_reply,
    validate_chief_output,
    validate_editor_output,
    validate_editor_reply,
    validate_intake_output,
    validate_reporter_output,
    validate_reporter_reply,
)
from phong_bao.newsroom import _chief, _editor, _intake, run
from phong_bao.runner import FixtureRunner
from phong_bao.registry import load_registry
from radar.summary_pipeline import fetch_article_result
from radar.transport import ResponseText

FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"
REDTEAM_FIXTURE = FIXTURES / "redteam" / "cards.json"


class DeskContractsTests(unittest.TestCase):
    """Test written contracts and validators for all five desks."""

    def test_all_five_desks_have_written_contracts(self):
        for desk in ("intake", "reporter", "editor", "checker", "chief"):
            self.assertIn(desk, DESK_CONTRACTS)
            contract = DESK_CONTRACTS[desk]
            self.assertIn("input_fields", contract)
            self.assertIn("output_fields", contract)
            self.assertTrue(contract["output_fields"])

    def test_intake_contract_rejects_malformed_output(self):
        self.assertTrue(validate_intake_output({"id": "s1", "pass": True, "reason": "ok"}))
        self.assertFalse(validate_intake_output({"id": "s1", "pass": "true", "reason": "ok"}))
        self.assertFalse(validate_intake_output({"id": "", "pass": True, "reason": "ok"}))
        self.assertFalse(validate_intake_output({"id": "s1", "pass": True, "reason": ""}))
        self.assertFalse(validate_intake_output({"pass": True, "reason": "missing id"}))

    def test_reporter_contract_rejects_malformed_model_reply(self):
        candidates = {"https://source1.example/news", "https://source2.example/news"}
        valid_reply = {"id": "s1", "selected_url": "https://source1.example/news", "same_event": True, "reason": "matched"}
        self.assertTrue(validate_reporter_reply(valid_reply, candidates))
        self.assertTrue(validate_reporter_reply({"id": "s1", "selected_url": None, "same_event": False, "reason": "no match"}, candidates))

        # Malformed replies
        self.assertFalse(validate_reporter_reply({"id": "s1", "model_failure": True}, candidates))
        self.assertFalse(validate_reporter_reply({**valid_reply, "same_event": "yes"}, candidates))
        self.assertFalse(validate_reporter_reply({**valid_reply, "selected_url": 123}, candidates))
        self.assertFalse(validate_reporter_reply({**valid_reply, "selected_url": "https://unknown.example"}, candidates))
        self.assertFalse(validate_reporter_reply({}, candidates))

    def test_reporter_contract_validates_output(self):
        valid = {
            "id": "s1", "readable": True, "selected_url": "https://example.com",
            "source_text": "text", "reason": "ok", "invalid_response": False,
            "representative_status": "readable", "provider": "p", "boat": "b",
        }
        self.assertTrue(validate_reporter_output(valid))
        self.assertFalse(validate_reporter_output({**valid, "readable": "true"}))
        self.assertFalse(validate_reporter_output({k: v for k, v in valid.items() if k != "reason"}))

    def test_editor_contract_rejects_malformed_model_reply(self):
        coverage_ids = {"cov1", "cov2"}
        valid_news = {
            "id": "s1", "news": True, "content_kind": "event_news", "analysis_kind": None,
            "junk_kind": None, "reason": "Major launch", "subject": "AI Model",
            "event_type": "release", "importance": "top", "event_at": "2026-10-26",
            "claims": ["Claim 1", "Claim 2"], "same_event_coverage_ids": ["cov1"],
        }
        self.assertTrue(validate_editor_reply(valid_news, coverage_ids))

        valid_junk = {
            "id": "s2", "news": False, "content_kind": "junk", "junk_kind": "vendor_sales",
            "reason": "sales pitch", "importance": "standard",
        }
        self.assertTrue(validate_editor_reply(valid_junk))

        # Rejections
        self.assertFalse(validate_editor_reply({"id": "s1", "model_failure": True}))
        self.assertFalse(validate_editor_reply({**valid_news, "news": "true"}))
        self.assertFalse(validate_editor_reply({**valid_junk, "junk_kind": "invalid_junk_kind"}))
        self.assertFalse(validate_editor_reply({**valid_news, "content_kind": "unsupported_kind"}))
        self.assertFalse(validate_editor_reply({**valid_news, "importance": "critical"}))
        self.assertFalse(validate_editor_reply({**valid_news, "subject": ""}))
        self.assertFalse(validate_editor_reply({**valid_news, "event_type": ""}))
        self.assertFalse(validate_editor_reply({**valid_news, "same_event_coverage_ids": ["cov_unknown"]}, coverage_ids))
        self.assertFalse(validate_editor_reply({**valid_news, "claims": ["a"] * 9}))  # > 8 claims
        self.assertFalse(validate_editor_reply({**valid_news, "claims": ["duplicate", "DUPLICATE"]}))
        self.assertFalse(validate_editor_reply({**valid_news, "claims": ["x" * 521]}))

    def test_editor_contract_validates_output(self):
        valid = {
            "id": "s1", "news": True, "content_kind": "event_news", "analysis_kind": None,
            "reason": "ok", "invalid_response": False, "junk_kind": None, "subject": "S",
            "event_type": "E", "importance": "top", "event_at": None, "claims": ["c"],
            "same_event_coverage_ids": [], "split_coverage_ids": [], "provider": None, "boat": None,
        }
        self.assertTrue(validate_editor_output(valid))
        self.assertFalse(validate_editor_output({**valid, "news": "yes"}))
        self.assertFalse(validate_editor_output({k: v for k, v in valid.items() if k != "claims"}))

    def test_checker_contract_rejects_malformed_model_reply(self):
        valid = {"id": "s1", "title_supported": True, "supported_claims": ["c1"], "reason": "verified"}
        self.assertTrue(validate_checker_reply(valid, editor_boat="boat-a"))

        # Rejections
        self.assertFalse(validate_checker_reply({"id": "s1", "model_failure": True}))
        self.assertFalse(validate_checker_reply({**valid, "boat": "boat-a"}, editor_boat="boat-a"))  # same boat
        self.assertFalse(validate_checker_reply({**valid, "title_supported": "yes"}))
        self.assertFalse(validate_checker_reply({**valid, "supported_claims": "c1"}))

    def test_checker_contract_validates_output(self):
        valid = {
            "id": "s1", "verified": True, "title_supported": True, "supported_claims": ["c"],
            "rejected_claims": [], "reason": "ok", "invalid_response": False, "provider": None, "boat": None,
        }
        self.assertTrue(validate_checker_output(valid))
        self.assertFalse(validate_checker_output({**valid, "verified": "true"}))
        self.assertFalse(validate_checker_output({k: v for k, v in valid.items() if k != "rejected_claims"}))

    def test_chief_contract_validates_output(self):
        valid = {
            "id": "s1", "decision": "publish", "content_kind": "event_news", "analysis_kind": None,
            "round": "chief", "reason": "ok", "importance_tier": "standard", "tier_capped": False,
            "summary": "none", "degradation_reasons": [], "use_original_title": False,
            "source_url": "https://example.com", "key_points": [], "same_event_coverage_ids": [],
            "split_coverage_ids": [],
        }
        self.assertTrue(validate_chief_output(valid))
        self.assertFalse(validate_chief_output({**valid, "decision": "allow"}))
        self.assertFalse(validate_chief_output({**valid, "round": "unknown_desk"}))
        self.assertFalse(validate_chief_output({**valid, "importance_tier": "high"}))


class SafetyAndFailClosedTests(unittest.TestCase):
    """Test fail-closed behavior, prompt injection defenses, and safe redirects."""

    def test_editor_fail_closed_holds_with_editor_invalid(self):
        """A broken editor reply after retry holds the card with reason editor_invalid."""
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        story = {"id": "bad-schema-story", "title": "Valid Title", "url": "https://example.com/valid",
                 "published_at": now.isoformat()}
        intake = {"bad-schema-story": {"pass": True, "reason": "eligible"}}
        reporter = {"bad-schema-story": {"selected_url": None, "representative_status": "unavailable",
                                          "source_text": "", "readable": False}}

        class BrokenSchemaRunner:
            def run(self, desk, rows, provider, instruction):
                # Returns malformed response missing required fields
                return type("BatchResult", (), {"rows": [{"id": rows[0]["id"], "news": "certainly"}],
                                                "usage": {}})()

        tools = load_registry()
        discovery = json.loads((FIXTURES / "discovery.json").read_text(encoding="utf-8"))
        editor_out, usage = _editor([story], intake, reporter, tools, discovery, BrokenSchemaRunner())
        self.assertFalse(editor_out["bad-schema-story"]["news"])
        self.assertTrue(editor_out["bad-schema-story"]["invalid_response"])
        self.assertEqual(editor_out["bad-schema-story"]["reason"], "editor_invalid")

        # Chief gates it as hold with reason editor_invalid
        decisions = _chief([story], intake, reporter, editor_out,
                           {"bad-schema-story": {"supported_claims": []}}, now)
        self.assertEqual(decisions[0]["decision"], "hold")
        self.assertEqual(decisions[0]["round"], "editor")
        self.assertEqual(decisions[0]["reason"], "editor_invalid")

    def test_injection_pre_check_holds_all_injection_style_cards_without_model(self):
        """Prompt injection cards in red-team fixture are held by deterministic check before model."""
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        self.assertTrue(REDTEAM_FIXTURE.exists())
        cards_data = json.loads(REDTEAM_FIXTURE.read_text(encoding="utf-8"))
        stories = cards_data["stories"]

        # Card 1: System override
        c1 = next(s for s in stories if s["id"] == "rt01promptinjecttop0")
        self.assertTrue(check_prompt_injection(c1["title"]))
        self.assertTrue(check_prompt_injection(c1["summary"]))

        # Card 2: Drop claims directive
        c2 = next(s for s in stories if s["id"] == "rt02dropclaimsattack")
        self.assertTrue(check_prompt_injection(c2["summary"]))

        # Run deterministic intake check
        intake_res = _intake([c1, c2], now)
        for card_id in ("rt01promptinjecttop0", "rt02dropclaimsattack"):
            self.assertFalse(intake_res[card_id]["pass"])
            self.assertEqual(intake_res[card_id]["reason"], "prompt_injection")

        # When processed by chief, cards are held in intake round
        dummy_reporter = {s["id"]: {"readable": False, "selected_url": None, "source_text": ""} for s in (c1, c2)}
        dummy_editor = {s["id"]: {"news": False, "importance": "standard", "reason": "earlier desk hold",
                                   "content_kind": "junk", "analysis_kind": None, "event_at": None,
                                   "claims": [], "same_event_coverage_ids": [], "split_coverage_ids": []}
                        for s in (c1, c2)}
        dummy_checker = {s["id"]: {"supported_claims": []} for s in (c1, c2)}
        chief_res = _chief([c1, c2], intake_res, dummy_reporter, dummy_editor, dummy_checker, now)
        for dec in chief_res:
            self.assertEqual(dec["decision"], "hold")
            self.assertEqual(dec["round"], "intake")
            self.assertEqual(dec["reason"], "prompt_injection")

    def test_unverifiable_rumour_held_without_independent_readable_source(self):
        """Unverifiable rumour about an unnamed deal is held unless independent readable source supports it."""
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        rumour_story = {
            "id": "secret-deal-story",
            "title": "OpenAI announces secret enterprise agent partnership with Global Logistics Corp",
            "summary": "Rumour claiming unverified partnership.",
            "url": "https://example.com/unverified-deal",
            "published_at": now.isoformat(),
        }
        self.assertTrue(is_unverifiable_rumour(rumour_story))

        intake = {"secret-deal-story": {"pass": True, "reason": "eligible"}}
        editor = {"secret-deal-story": {
            "news": True, "content_kind": "event_news", "analysis_kind": None,
            "importance": "standard", "event_at": None, "claims": [],
            "same_event_coverage_ids": [], "split_coverage_ids": [],
            "reason": "editor news", "invalid_response": False,
        }}
        checker = {"secret-deal-story": {"supported_claims": []}}

        # Case 1: No readable source -> Held by Chief
        unreadable_reporter = {"secret-deal-story": {"readable": False, "selected_url": None, "source_text": ""}}
        decisions = _chief([rumour_story], intake, unreadable_reporter, editor, checker, now)
        self.assertEqual(decisions[0]["decision"], "hold")
        self.assertEqual(decisions[0]["round"], "chief")
        self.assertIn("unverifiable rumour", decisions[0]["reason"])

        # Case 2: Readable independent source exists -> Not held by rumour check
        readable_reporter = {"secret-deal-story": {"readable": True, "selected_url": "https://indep.example/news",
                                                   "source_text": "confirmed deal"}}
        decisions2 = _chief([rumour_story], intake, readable_reporter, editor, checker, now)
        self.assertEqual(decisions2[0]["decision"], "publish")

    def test_safe_redirects_followed_with_hop_limit(self):
        """Reader follows safe redirects with hop limit and loop protection."""
        from urllib.error import HTTPError
        from email.message import Message

        story = {"url": "https://short.example/story", "coverage": []}

        with patch("radar.shadow_collector.check_robots", return_value={"robots_status": 404, "disallowed": False}):
            # 1. Successful redirect followed to 200 HTML
            def redirect_fetch(target, allow_redirects=False):
                if target == "https://short.example/story":
                    headers = Message()
                    headers["Location"] = "https://canonical.example/article"
                    raise HTTPError(target, 301, "Moved", headers, None)
                if target == "https://canonical.example/article":
                    return ResponseText("<article>" + "y" * 400 + "</article>", status=200,
                                        url=target, content_type="text/html")
                raise ValueError(target)

            with patch("radar.transport.read_url", side_effect=redirect_fetch):
                text, reason = fetch_article_result(story)
                self.assertIsNone(reason)
                self.assertTrue(len(text) >= 300)

            # 2. Exceeded hop limit
            hop = 0
            def infinite_hops(target, allow_redirects=False):
                nonlocal hop
                hop += 1
                headers = Message()
                headers["Location"] = f"https://hop.example/{hop}"
                raise HTTPError(target, 302, "Found", headers, None)

            with patch("radar.transport.read_url", side_effect=infinite_hops):
                text, reason = fetch_article_result(story)
                self.assertIn(reason, ("redirect_limit", "redirect"))
                self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()
