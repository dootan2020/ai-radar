"""Formal contracts and validators for Halcyon newsroom desks."""

from __future__ import annotations

import re
from typing import Any

from radar.newsroom_decisions import DESK_SUMMARY_SOURCE as WRITER_SOURCE, desk_fields_valid

IMPORTANCE_TIERS = ("top", "notable", "standard")
CONTENT_KINDS = ("event_news", "analysis", "junk")
ANALYSIS_KINDS = ("analysis", "interview", "opinion", "podcast", "survey")
JUNK_KINDS = {
    "non_news_page",
    "vendor_sales",
    "customer_case_study",
    "tutorial",
    "incidental_ai",
    "mis_merged_cluster",
    "stale_content",
}
DECISIONS = ("hold", "publish")
ROUNDS = ("intake", "reporter", "editor", "checker", "chief")

PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bsystem\s+override\b", re.I),
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\b", re.I),
    re.compile(r"\b(?:parsing\s+directive|critical\s+directive|system\s+instruction)\b", re.I),
    re.compile(r"\bset\s+news\s*=\s*(?:true|false)\b", re.I),
    re.compile(r"\bimportance\s*=\s*(?:top|notable|standard)\b", re.I),
    re.compile(r"\breturn\s+claims\s*:\s*\[", re.I),
    re.compile(r"\bclaims\s*:\s*\[\s*\]", re.I),
    re.compile(r"\bdo\s+not\s+(?:extract|list)\s+(?:any\s+)?claims\b", re.I),
    re.compile(r"\byou\s+are\s+instructed\s+to\b", re.I),
    re.compile(r"\b(?:output|return)\s+(?:top-tier|notable)\s+news\b", re.I),
)

RUMOUR_KEYWORDS = re.compile(
    r"\b(?:rumou?r|unverified|secret|alleged|unnamed)\b.*\b(?:deal|partnership|acquisition|buyout|merger)\b"
    r"|\b(?:deal|partnership|acquisition|buyout|merger)\b.*\b(?:rumou?r|unverified|secret|alleged|unnamed)\b",
    re.I,
)


def check_prompt_injection(text: str | None) -> bool:
    """Return True if text contains deterministic prompt injection patterns."""
    if not text or not isinstance(text, str):
        return False
    return any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS)


def is_unverifiable_rumour(story: dict[str, Any]) -> bool:
    """Return True if story appears to be an unverified rumour about a deal/partnership."""
    title = story.get("title") or ""
    summary = story.get("summary") or ""
    combined = f"{title} {summary}"
    return bool(RUMOUR_KEYWORDS.search(combined))


# ============================================================================
# Desk Specifications
# ============================================================================

DESK_CONTRACTS = {
    "intake": {
        "desk": "intake",
        "description": "Technical filter and prompt injection defense gatekeeper",
        "input_fields": ["id", "title", "url", "published_at"],
        "optional_input_fields": ["summary", "coverage"],
        "output_fields": ["id", "pass", "reason"],
        "rejectable_conditions": [
            "missing title or public canonical URL",
            "missing reliable publication date",
            "publication date is in the future (> 1 day)",
            "original event is over 30 days old without a verified update",
            "no evidence that AI is the main subject",
            "prompt injection detected in title or summary",
        ],
    },
    "reporter": {
        "desk": "reporter",
        "description": "Source resolver and independent evidence gatherer",
        "input_fields": ["id", "title", "published_at", "representative_url", "representative_status", "candidates"],
        "model_reply_fields": ["id", "selected_url", "same_event", "reason"],
        "output_fields": [
            "id", "readable", "selected_url", "source_text", "reason",
            "invalid_response", "representative_status", "provider", "boat",
        ],
        "rejectable_reply_conditions": [
            "model_failure reported",
            "same_event is not a boolean",
            "selected_url is not None and not a string",
            "selected_url is not present among candidate URLs",
        ],
    },
    "editor": {
        "desk": "editor",
        "description": "Event classifier, tier suggester, and claim extractor",
        "input_fields": [
            "id", "title", "summary", "published_at", "original_url",
            "kind", "coverage", "source_url", "source_status", "source_excerpt",
        ],
        "model_reply_fields": [
            "id", "news", "content_kind", "analysis_kind", "junk_kind",
            "reason", "subject", "event_type", "importance", "event_at",
            "claims", "same_event_coverage_ids",
        ],
        "output_fields": [
            "id", "news", "content_kind", "analysis_kind", "reason",
            "invalid_response", "junk_kind", "subject", "event_type",
            "importance", "event_at", "claims", "same_event_coverage_ids",
            "split_coverage_ids", "provider", "boat",
        ],
        "rejectable_reply_conditions": [
            "model_failure reported",
            "news is not a boolean",
            "news is False and junk_kind not in JUNK_KINDS",
            "news is True and content_kind not in {'event_news', 'analysis'}",
            "news is True and content_kind is analysis and analysis_kind not in ANALYSIS_KINDS",
            "news is True and importance not in IMPORTANCE_TIERS",
            "news is True and subject or event_type is not a non-empty string",
            "news is True and same_event_coverage_ids is not a subset of story coverage IDs",
            "news is True and claims is not a valid list of distinct strings (1-520 chars, max 8)",
        ],
    },
    "checker": {
        "desk": "checker",
        "description": "Independent adversarial fact-checker on counter-boat",
        "input_fields": ["id", "title", "claims", "source_url", "cited_paragraphs"],
        "model_reply_fields": ["id", "title_supported", "supported_claims", "reason"],
        "output_fields": [
            "id", "verified", "title_supported", "supported_claims",
            "rejected_claims", "reason", "invalid_response", "provider", "boat",
        ],
        "rejectable_reply_conditions": [
            "model_failure reported",
            "boat matches editor_boat (same-boat violation)",
            "title_supported / verified is not a boolean",
            "supported_claims is not a list",
        ],
    },
    "writer": {
        "desk": "writer",
        "description": "Writer ('Người viết'): 3-4 Vietnamese bullets of one or two sentences (development, "
                       "cause, examples, significance; contract summary-vi-7-bullets) for recent publishable stories, "
                       "each sentence held to the shared number and name checks",
        "input_fields": ["id", "sources", "missing_primary", "linked_primary", "length"],
        "model_reply_fields": ["id", "status", "sheet", "conditions", "title_vi", "paragraphs", "used_source_ids",
                               "limitations"],
        "output_fields": [
            "id", "written", "reason", "invalid_response", "key_points", "editorial_headline_vi",
            "summary_sources", "summary_limitations", "key_points_prompt_version", "dropped_points",
            "provider", "boat",
        ],
        # Audit record of drafted stories: source paragraphs, editor provider when enabled, and
        # rewrite {roles, result} when the checks removed whole paragraphs and the writer redid them once
        # (the request carries the draft's grounded conditions).
        # Kept in the cycle folder, never published; evidence_sheet is the sheet the reply carried.
        # A written row also carries the scoring desk's verdict: score (the block the chief copies, None when
        # unscored), score_state passed/failed/unscored, score_reason, writer_boats (every boat whose words are in
        # the prose), and score_rewrite when a failed story was rewritten once with the scorer's findings.
        "optional_output_fields": ["writer_sources", "writer_source_chars", "editor_provider", "editor_boat",
                                   "rewrite", "evidence_sheet", "sheet_path", "sheet_error", "score", "score_state",
                                   "score_reason", "writer_boats", "score_rewrite"],
        "skip_conditions": [
            "not publishable with a readable source",
            "published outside the writer window (PHONG_BAO_WRITER_WINDOW_HOURS, default 48)",
            "article unreadable or contains prompt injection",
        ],
        "rejectable_reply_conditions": [
            "reply does not match the paragraph shape (3-4 paragraphs with known roles)",
            "status is not ready",
            "the title fails radar.summary_validation's number or name check",
            "conditions is not a list (verbatim source spans of at most 25 words, each with its paragraph ID)",
            "sheet rules (they only trim or improve prose; when they fail after the one rewrite, the draft or "
            "its rewrite is checked as main checked it, without a sheet, and sheet_path records which held): "
            "the evidence sheet {what, why, notable, meaning} is missing, or a box's quote is not a verbatim span "
            "of at most 40 words of its article-body paragraph (never a coverage excerpt), or it names no "
            "speaker, and only why may be empty (a missing or invalid sheet gets one rewrite asking for it); "
            "with an empty why, a sentence or title whose own words (outside quotations and names) state a cause, "
            "motive or purpose (newsroom.CAUSE_VI) is removed unless a cited body paragraph states a reason; a "
            "sheet point whose paragraph (what: development, why: cause, notable: examples, or cause when they "
            "share a paragraph, meaning: significance) has no sentence citing the box's paragraph, or whose "
            "citing sentences hold fewer than half the point's words, gets that paragraph rewritten once",
            "after dropping failing sentences (including a significance sentence that cites no paragraph "
            "holding a listed condition, that is a span found verbatim in that paragraph; naming a speaker "
            "does not replace it) and after one rewrite of the lost paragraphs, which is given the draft's "
            "grounded conditions and may add verbatim ones: any paragraph lost (a development paragraph whose "
            "opening sentence failed counts as lost), fewer than three paragraphs, "
            "development not first, significance not last, or a total outside the story's length window "
            "(newsroom.writer_length, by source size: a least of 90 to 250 units and a most of 230 to 600)",
            "a sentence or the title fails radar.summary_validation.attribution_error: a purpose (nhằm, mục "
            "đích) its cited paragraphs never state, a judgement or cause without the attribution its paragraph "
            "carries, a named speaker its cited paragraphs do not name, or an unnamed group (insiders, experts, "
            "lawmakers) that some cited paragraph does not quote",
        ],
    },
    "scorer": {
        "desk": "scorer",
        "description": "Scoring desk ('Bàn chấm'): reads each written story's Vietnamese headline and paragraphs "
                       "against the source paragraphs the writer used, answers the four reader questions, scores "
                       "each 0-10 and lists hard errors; runs inside the writer stage on a boat that wrote none "
                       "of the prose (phong_bao.scoring)",
        "input_fields": ["id", "sources", "headline_vi", "paragraphs_vi"],
        "model_reply_fields": ["id", "questions", "hard_errors", "findings"],
        "output_fields": ["version", "value", "answers", "hard_errors", "findings", "writer_boats", "scorer_boat",
                          "scorer_provider", "prose_sha256", "scored_at"],
        "rejectable_reply_conditions": [
            "model failure, timeout, budget exhausted, no eligible lane or an admission stop (unscored)",
            "the reply comes from a boat that wrote any of the prose (unscored)",
            "questions is not exactly what/why/notable/meaning, each with source_answer, summary_answer and a "
            "score from 0 to 10 (unscored)",
            "a hard error whose kind is not fact/cause/number/name/role/quote/main_event_missing, or a finding "
            "without question, problem and fix (unscored)",
        ],
        "pass_conditions": [
            "weighted score (what 35%, why 20%, notable 30%, meaning 15%) at least "
            "radar.newsroom_decisions.SCORE_THRESHOLD and no hard error, for the exact headline and paragraphs "
            "shown (prose_sha256)",
        ],
    },
    "chief": {
        "desk": "chief",
        "description": "Chief gatekeeper applying fail-closed publication decisions",
        "input_fields": ["intake", "reporter", "editor", "checker", "now"],
        "output_fields": [
            "id", "decision", "content_kind", "analysis_kind", "round",
            "reason", "importance_tier", "tier_capped", "summary",
            "degradation_reasons", "use_original_title", "source_url",
            "key_points", "same_event_coverage_ids", "split_coverage_ids",
        ],
        "optional_output_fields": [
            "written_by", "editorial_headline_vi", "summary_sources", "summary_limitations",
            "key_points_prompt_version", "score",
        ],
        "hold_conditions": [
            "intake rejected (fail-closed)",
            "editor model failure or invalid schema (fail-closed)",
            "editor determined card is junk",
            "unverifiable rumour without independent readable source",
        ],
    },
}


# ============================================================================
# Validators
# ============================================================================

def validate_intake_output(row: dict[str, Any]) -> bool:
    """Validate intake desk output against intake contract."""
    if not isinstance(row, dict):
        return False
    if not isinstance(row.get("id"), str) or not row["id"]:
        return False
    if type(row.get("pass")) is not bool:
        return False
    if not isinstance(row.get("reason"), str) or not row["reason"]:
        return False
    return True


def validate_reporter_reply(row: dict[str, Any] | None, candidate_urls: set[str] | None = None) -> bool:
    """Validate reporter model response against contract. Return True if valid, False if rejectable."""
    if not row or not isinstance(row, dict) or row.get("model_failure"):
        return False
    if not isinstance(row.get("id"), str) or not row["id"]:
        return False
    if type(row.get("same_event")) is not bool:
        return False
    selected = row.get("selected_url")
    if selected is not None and not isinstance(selected, str):
        return False
    if selected is not None and candidate_urls is not None and selected not in candidate_urls:
        return False
    return True


def validate_reporter_output(row: dict[str, Any]) -> bool:
    """Validate reporter desk final output dict."""
    if not isinstance(row, dict):
        return False
    required = ["id", "readable", "selected_url", "source_text", "reason", "invalid_response", "representative_status"]
    if any(k not in row for k in required):
        return False
    if type(row["readable"]) is not bool or type(row["invalid_response"]) is not bool:
        return False
    return True


def validate_editor_reply(
    row: dict[str, Any] | None,
    coverage_ids: set[str] | None = None,
    *,
    require_importance: bool = True,
) -> bool:
    """Validate editor model response against contract. Return True if valid, False if rejectable."""
    if not row or not isinstance(row, dict) or row.get("model_failure"):
        return False
    if not isinstance(row.get("id"), str) or not row["id"]:
        return False
    news = row.get("news")
    if type(news) is not bool:
        return False
    if news is False:
        junk_kind = row.get("junk_kind")
        return isinstance(junk_kind, str) and junk_kind in JUNK_KINDS

    # news is True
    content_kind = row.get("content_kind", "event_news")
    if content_kind not in CONTENT_KINDS[:2]:
        return False
    if content_kind == "analysis" and row.get("analysis_kind") not in ANALYSIS_KINDS:
        return False
    if require_importance and row.get("importance") not in IMPORTANCE_TIERS:
        return False
    subject = row.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        return False
    event_type = row.get("event_type")
    if not isinstance(event_type, str) or not event_type.strip():
        return False
    same = row.get("same_event_coverage_ids")
    if not isinstance(same, list) or not all(isinstance(v, str) for v in same):
        return False
    if coverage_ids is not None and not set(same).issubset(coverage_ids):
        return False
    claims = row.get("claims")
    if not isinstance(claims, list) or len(claims) > 8:
        return False
    if not all(isinstance(c, str) and 0 < len(c.strip()) <= 520 for c in claims):
        return False
    if len({c.casefold().strip() for c in claims}) != len(claims):
        return False
    if row.get("event_at") is not None and not isinstance(row["event_at"], str):
        return False
    return True


def validate_editor_output(row: dict[str, Any]) -> bool:
    """Validate editor desk final output dict."""
    if not isinstance(row, dict):
        return False
    required = [
        "id", "news", "content_kind", "analysis_kind", "reason",
        "invalid_response", "junk_kind", "subject", "event_type",
        "importance", "event_at", "claims", "same_event_coverage_ids",
        "split_coverage_ids", "provider", "boat",
    ]
    if any(k not in row for k in required):
        return False
    if type(row["news"]) is not bool or type(row["invalid_response"]) is not bool:
        return False
    return True


def validate_checker_reply(row: dict[str, Any] | None, editor_boat: str | None = None) -> bool:
    """Validate checker model response against contract. Return True if valid, False if rejectable."""
    if not row or not isinstance(row, dict) or row.get("model_failure"):
        return False
    if not isinstance(row.get("id"), str) or not row["id"]:
        return False
    if editor_boat is not None and row.get("boat") == editor_boat:
        return False
    title_supported = row.get("title_supported", row.get("verified"))
    if type(title_supported) is not bool:
        return False
    if not isinstance(row.get("supported_claims"), list):
        return False
    return True


def validate_checker_output(row: dict[str, Any]) -> bool:
    """Validate checker desk final output dict."""
    if not isinstance(row, dict):
        return False
    required = [
        "id", "verified", "title_supported", "supported_claims",
        "rejected_claims", "reason", "invalid_response", "provider", "boat",
    ]
    if any(k not in row for k in required):
        return False
    if type(row["verified"]) is not bool or type(row["title_supported"]) is not bool:
        return False
    return True



def _written_fields_valid(row: dict[str, Any]) -> bool:
    sources = row.get("summary_sources")
    return (desk_fields_valid(row) and bool(sources)
            and all(isinstance(s, dict) and isinstance(s.get("url"), str)
                    and s["url"].startswith(("https://", "http://")) for s in sources))


def validate_writer_output(row: dict[str, Any] | None) -> bool:
    """Validate writer desk final output; a written row must carry a complete public summary."""
    if not isinstance(row, dict):
        return False
    required = DESK_CONTRACTS["writer"]["output_fields"]
    if any(k not in row for k in required):
        return False
    if type(row["written"]) is not bool or type(row["invalid_response"]) is not bool:
        return False
    if not isinstance(row["dropped_points"], list):
        return False
    if row["written"]:
        return _written_fields_valid(row)
    return row["key_points"] == []


def validate_chief_output(row: dict[str, Any]) -> bool:
    """Validate chief desk final output record against chief contract."""
    if not isinstance(row, dict):
        return False
    required = [
        "id", "decision", "content_kind", "analysis_kind", "round",
        "reason", "importance_tier", "tier_capped", "summary",
        "degradation_reasons", "use_original_title", "source_url",
        "key_points", "same_event_coverage_ids", "split_coverage_ids",
    ]
    if any(k not in row for k in required):
        return False
    if row["decision"] not in DECISIONS:
        return False
    if row["round"] not in ROUNDS:
        return False
    if row["importance_tier"] not in IMPORTANCE_TIERS:
        return False
    if type(row["tier_capped"]) is not bool or type(row["use_original_title"]) is not bool:
        return False
    if not isinstance(row["degradation_reasons"], list) or not isinstance(row["key_points"], list):
        return False
    written_by = row.get("written_by")
    if written_by is not None:
        if written_by != WRITER_SOURCE or row["decision"] != "publish" or row["summary"] != "written":
            return False
        if row.get("score") is not None and not isinstance(row["score"], dict):
            return False
        return _written_fields_valid(row)
    return True
