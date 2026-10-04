"""Offline tool regressions with explicit fixture provenance.

Constructed Atom/Markdown cases are synthetic. Active-source fixture tests use
authentic browser DOM/code-view captures, separately documented from raw HTTP.
"""

import copy
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import pipeline, tool_updates, youtube
from radar.publication import load_published, prepare_publication
from radar.items import observation
from radar.transport import ResponseText
if __package__:
    from .test_publication import snapshot
else:
    from test_publication import snapshot

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
QUOTE = "Added explicit review of tool permissions before execution."
FIXTURES = Path(__file__).parent / "fixtures" / "tool_updates"


def source(source_id):
    return next(row for row in tool_updates.SOURCES if row["id"] == source_id)


def atom(source_id="claude-code-feed", version="2.1.999", published="2026-10-02T10:00:00Z",
         updated="2026-10-03T10:00:00Z", quote=QUOTE, url=None):
    """Construct synthetic edge cases; no claim about current official markup."""
    spec = source(source_id)
    url = url or spec["release_prefix"] + "v" + version
    dates = "".join(f"<{key}>{value}</{key}>" for key, value in (
        ("published", published), ("updated", updated)) if value is not None)
    return ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            f'<title>{escape(version)}</title><link href="{escape(url, quote=True)}"/>'
            f'{dates}<content type="html">{escape("<p>" + quote + "</p>")}</content>'
            '</entry></feed>')


def parse(body, source_id="claude-code-feed"):
    return tool_updates.parse_source(body, source(source_id), NOW)


def finish(rows):
    records = [dict(id=spec["id"], ok=True, count=0, error=None) for spec in tool_updates.SOURCES]
    return tool_updates.finish(rows, records, NOW)[0]


class SyntheticToolParserTests(unittest.TestCase):
    def test_atom_source_matrix_preserves_exact_entry_and_quote_attribution(self):
        for spec in tool_updates.SOURCES:
            if spec["parser"] != "atom":
                continue
            with self.subTest(source=spec["id"]):
                url = spec["release_prefix"] + "v2.1.999"
                rows = parse(atom(spec["id"]), spec["id"])
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual((row["url"], row["version"]), (url, "2.1.999"))
                self.assertEqual(row["published_at"], "2026-10-02T10:00:00Z")
                self.assertEqual(row["updated_at"], "2026-10-03T10:00:00Z")
                self.assertEqual(row["sources"], [spec["id"]])
                self.assertEqual(row["highlights"][0]["text"], QUOTE)
                self.assertEqual(row["highlights"][0]["url"], url)
                self.assertEqual(row["highlights"][0]["source"], spec["id"])
                self.assertEqual(row["highlights"][0]["source_name"], spec["name"])

    def test_modified_date_cannot_reage_an_old_release(self):
        rows = parse(atom(published="2026-08-01T10:00:00Z"))
        self.assertEqual(rows[0]["published_at"], "2026-08-01T10:00:00Z")
        self.assertEqual(finish(rows), [])

    def test_updated_only_keeps_publication_unknown(self):
        row = parse(atom(published=None))[0]
        self.assertIsNone(row["published_at"])
        self.assertIsNone(row["published_date"])
        self.assertEqual(row["updated_at"], "2026-10-03T10:00:00Z")
        self.assertEqual(row["time_basis"], "updated")

    def test_rolling_window_boundary_excludes_old_and_future_instants(self):
        for stamp, expected in (("2026-09-26T12:00:00Z", 1), ("2026-09-26T11:59:59Z", 0),
                                ("2026-10-03T12:00:00Z", 1), ("2026-10-03T12:00:01Z", 0)):
            with self.subTest(stamp=stamp):
                self.assertEqual(len(finish(parse(atom(published=stamp)))), expected)

    def test_atom_date_only_never_invents_midnight(self):
        row = parse(atom(published="2026-10-02", updated=None))[0]
        self.assertIsNone(row["published_at"])
        self.assertEqual(row["published_date"], "2026-10-02")
        self.assertEqual(row["time_precision"], "date")
        self.assertEqual(len(finish([row])), 1)

    def test_unknown_and_timezone_free_times_cannot_prove_freshness(self):
        for value in (None, "not-a-date", "2026-10-02T10:00:00"):
            with self.subTest(value=value):
                row = parse(atom(published=value, updated=None))[0]
                self.assertIsNone(row["published_at"])
                self.assertEqual(row["time_precision"], "unknown")
                self.assertEqual(finish([row]), [])

    def test_prerelease_variants_are_not_stable_updates(self):
        for version in ("2.1.999-alpha.1", "2.1.999-beta.2", "2.1.999-rc1", "2.1.999-preview", "2.1.999-nightly"):
            with self.subTest(version=version):
                self.assertEqual(finish(parse(atom(version=version))), [])
        self.assertEqual(len(finish(parse(atom()))), 1)

    def test_version_join_combines_claude_atom_and_undated_changelog(self):
        markdown = "# Changelog\n\n## 2.1.999\n- " + QUOTE + "\n- Fixed repeated reconnect attempts after a timeout.\n\n## 2.1.998\n- Older unrelated changes remain undated.\n"
        changelog = parse(markdown, "claude-code-changelog")
        self.assertEqual(finish(changelog), [])
        rows = finish(parse(atom()) + changelog)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], "2.1.999")
        self.assertEqual(set(rows[0]["sources"]), {"claude-code-feed", "claude-code-changelog"})
        self.assertEqual(rows[0]["url"], "https://github.com/anthropics/claude-code/releases/tag/v2.1.999")
        md_quote = next(item for item in rows[0]["highlights"] if item["text"].startswith("Fixed repeated"))
        self.assertEqual(md_quote["source"], "claude-code-changelog")
        self.assertEqual(md_quote["url"], "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md#21999")

    def test_different_versions_have_distinct_ids_and_order_does_not_change_dedupe(self):
        rows = parse(atom()) + parse(atom(version="2.1.998"))
        result = finish(rows + rows)
        self.assertEqual(len(result), 2)
        self.assertEqual(len({row["id"] for row in result}), 2)
        self.assertEqual(result, finish(list(reversed(rows))))

    def test_selection_is_bounded_attributed_and_does_not_mutate_parser_rows(self):
        quote = "Fixed repeated reconnect attempts after an unavailable endpoint."
        markdown = ("# Changelog\n## 2.1.999\n- " + quote + "\n"
                    "- Added a new review command for repository changes.\n"
                    "- Security: prevent unintended reads outside the selected workspace.\n"
                    "- Improved the terminal status display during downloads.\n")
        parsed = parse(atom()) + parse(markdown, "claude-code-changelog")
        before = copy.deepcopy(parsed)
        result = finish(parsed)[0]
        self.assertEqual(parsed, before)
        self.assertEqual(len(result["highlights"]), 3)
        self.assertTrue(result["highlights"][0]["text"].startswith("Security:"))
        self.assertEqual(len({row["text"] for row in result["highlights"]}), 3)
        evidence = {(quote["text"], quote["source"], quote["url"])
                    for row in parsed for quote in row["highlights"]}
        self.assertTrue(all((quote["text"], quote["source"], quote["url"]) in evidence
                            for quote in result["highlights"]))

    def test_late_security_bullet_is_not_lost_before_highlight_ranking(self):
        notes = [f"Fixed ordinary display behavior in terminal number {index}." for index in range(15)]
        security = "Security: prevent cross-workspace access without an explicit grant."
        markdown = "# Changelog\n## 2.1.999\n" + "\n".join("- " + note for note in notes + [security])
        rows = finish(parse(atom()) + parse(markdown, "claude-code-changelog"))
        self.assertEqual(rows[0]["highlights"][0]["text"], security)

    def test_pull_request_index_does_not_displace_release_prose(self):
        index = "#49763 Security: merge internal changelog bookkeeping"
        markdown = "# Changelog\n## 2.1.999\n- " + index + "\n- " + QUOTE + "\n"
        rows = finish(parse(atom()) + parse(markdown, "claude-code-changelog"))
        self.assertFalse(any(quote["text"].startswith("#49763") for quote in rows[0]["highlights"]))

    def test_equivalent_bullet_and_markdown_formatting_yields_one_exact_quote(self):
        plain = "Added review mode to inspect changes before a tool runs."
        feed = parse(atom(quote="• " + plain))
        markdown = parse("# Changelog\n## 2.1.999\n- Added `review` mode to inspect changes before a tool runs.\n",
                         "claude-code-changelog")
        rows = finish(feed + markdown)
        self.assertEqual(len(rows[0]["highlights"]), 1)
        self.assertIn(rows[0]["highlights"][0]["text"],
                      {"• " + plain, "Added `review` mode to inspect changes before a tool runs."})

    def test_long_unbroken_quote_stays_a_bounded_exact_prefix_and_can_publish(self):
        original = "a" * 300
        row = finish(parse(atom(quote=original)))[0]
        quote = row["highlights"][0]
        self.assertLessEqual(len(quote["text"]), 240)
        self.assertTrue(original.startswith(quote["text"]))
        self.assertTrue(quote["truncated"])
        candidate, status = prepare_publication(snapshot() | {"tool_updates": [row]}, None, NOW)
        self.assertTrue(status["published"], status)
        self.assertEqual(candidate["tool_updates"], [row])

    def test_empty_atom_is_success_but_malformed_or_wrong_identity_is_failure(self):
        self.assertEqual(parse('<feed xmlns="http://www.w3.org/2005/Atom"/>'), [])
        for body in ("", "<feed", "<html>Challenge</html>",
                     atom(url="https://example.org/unrelated")):
            with self.subTest(body=body[:40]), self.assertRaises((ValueError, SyntaxError)):
                parse(body)

    def test_markdown_empty_and_unversioned_responses_are_not_successful_empty(self):
        for body in ("", "# Changelog\nService unavailable", "<html>Challenge</html>"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse(body, "claude-code-changelog")

    def test_html_without_recognized_entries_is_not_a_healthy_empty_source(self):
        with self.assertRaises(ValueError):
            parse("<html><h1>Codex changelog</h1></html>", "codex-changelog")


class ToolPipelineIsolationTests(unittest.TestCase):
    def test_finish_failure_preserves_news_and_explicit_failure_metadata(self):
        spec = dict(id="news", name="Synthetic news", kind="rss", group="lab", lab="openai",
                    url="https://example.org/feed")
        item = observation(spec, "OpenAI adds new capabilities", "https://example.org/news",
                           "2026-10-03T10:00:00Z", NOW)
        jobs = [(spec, "coverage", lambda text: [item])]
        with patch.object(pipeline, "_jobs", return_value=jobs), \
                patch.object(youtube, "collect", return_value=([], [])), \
                patch.object(tool_updates, "finish", side_effect=ValueError("broken grouping")):
            result = pipeline.build_v2(fetch=lambda url, **kwargs: "", now=NOW)
        self.assertEqual(result["tool_updates"], [])
        self.assertFalse(result["tool_updates_meta"]["ok"])
        self.assertIn("broken grouping", result["tool_updates_meta"]["error"])
        self.assertEqual(result["updates"][0]["title"], item["title"])
        self.assertEqual(result["stories"][0]["title"], item["title"])
        candidate, status = prepare_publication(result, None, NOW)
        self.assertTrue(status["published"], status)

    def test_partial_codex_failure_counts_reach_source_and_tool_metadata(self):
        jobs = [job for job in pipeline._jobs(True, NOW) if job[0]["id"] == "codex-changelog"]
        body = (FIXTURES / "codex-changelog-dom.html").read_text(encoding="utf-8")
        broken = '<li data-product="codex" id="broken"><h3>Missing article</h3></li>'
        with patch.object(pipeline, "_jobs", return_value=jobs), \
                patch.object(youtube, "collect", return_value=([], [])):
            result = pipeline.build_v2(fetch=lambda url, **kwargs: broken + body, now=NOW)
        record = next(row for row in result["sources"] if row["id"] == "codex-changelog")
        self.assertTrue(record["ok"])
        self.assertEqual(record["dropped_entries"], 1)
        self.assertEqual(record["count"], len(parse(body, "codex-changelog")))
        self.assertIn("Skipped 1", record["diagnostics"][0])
        self.assertEqual(result["tool_updates_meta"]["dropped_entries"], {"codex-changelog": 1})
        self.assertEqual(len(result["tool_updates"]), 4)

    def test_failed_tool_endpoint_preserves_success_and_http_evidence(self):
        ids = {"claude-code-feed", "codex-changelog"}
        jobs = [job for job in pipeline._jobs(True, NOW) if job[0]["id"] in ids]
        self.assertEqual({job[0]["id"] for job in jobs}, ids)

        def fetch(url, **kwargs):
            if url == source("codex-changelog")["url"]:
                raise TimeoutError("synthetic endpoint timeout")
            return ResponseText(atom(), status=200, url=url)

        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.json"
            events.write_bytes(b"[]")
            with patch.object(pipeline, "_jobs", return_value=jobs), \
                    patch.object(youtube, "collect", return_value=([], [])):
                result = pipeline.build_v2(fetch=fetch, now=NOW, events_path=events)
        records = {row["id"]: row for row in result["sources"]}
        self.assertTrue(records["claude-code-feed"]["ok"])
        self.assertEqual(records["claude-code-feed"]["http_status"], 200)
        self.assertFalse(records["codex-changelog"]["ok"])
        self.assertIn("timeout", records["codex-changelog"]["error"])
        self.assertEqual(len(result["tool_updates"]), 1)
        self.assertEqual(result["tool_updates"][0]["sources"], ["claude-code-feed"])
        self.assertEqual(result["updates"], [])
        json.dumps(result, allow_nan=False)


class CapturedCodexDomTests(unittest.TestCase):
    def test_malformed_codex_entry_does_not_erase_valid_entries(self):
        body = (FIXTURES / "codex-changelog-dom.html").read_text(encoding="utf-8")
        broken = '<li data-product="codex" id="broken"><h3>Missing article and date</h3></li>'
        rows = parse(broken + body, "codex-changelog")
        self.assertEqual(rows, parse(body, "codex-changelog"))
        self.assertEqual(rows.dropped_entries, 1)

    def test_all_malformed_codex_entries_fail_the_source(self):
        with self.assertRaises(ValueError):
            parse('<li data-product="codex" id="broken"><h3>Missing article</h3></li>', "codex-changelog")

    def test_valueless_codex_topics_do_not_erase_valid_entries(self):
        body = (FIXTURES / "codex-changelog-dom.html").read_text(encoding="utf-8")
        broken = ('<li data-product="codex" data-codex-topics id="broken">'
                  '<h3>Malformed metadata</h3><time>2026-10-01</time>'
                  '<article><p>' + QUOTE + '</p></article></li>')
        rows = parse(broken + body, "codex-changelog")
        self.assertEqual(rows, parse(body, "codex-changelog"))
        self.assertEqual(rows.dropped_entries, 1)

    def test_authentic_dom_retains_release_date_url_and_verbatim_words(self):
        body = (FIXTURES / "codex-changelog-dom.html").read_text(encoding="utf-8")
        rows = parse(body, "codex-changelog")
        row = next(row for row in rows if row["version"] == "0.160.0")
        self.assertEqual(row["product"], "codex-cli")
        self.assertEqual(row["url"], "https://github.com/openai/codex/releases/tag/rust-v0.160.0")
        self.assertEqual(row["published_date"], "2026-10-01")
        self.assertIsNone(row["published_at"])
        self.assertEqual(row["time_precision"], "date")
        quote = next(item for item in row["highlights"] if item["text"].startswith("Browse older tasks"))
        self.assertEqual(quote["text"], 'Browse older tasks in the agent command center with a keyboard-accessible “Show more” action. (#49106)')
        self.assertEqual(quote["source"], "codex-changelog")
        self.assertEqual(quote["url"], "https://learn.chatgpt.com/docs/changelog#github-release-401312540")

    def test_repeated_official_dom_keeps_one_release_identity(self):
        body = (FIXTURES / "codex-changelog-dom.html").read_text(encoding="utf-8")
        rows = parse(body, "codex-changelog")
        merged = [row for row in finish(rows + rows) if row["version"] == "0.160.0"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["sources"], ["codex-changelog"])


class CapturedClaudeSourceTests(unittest.TestCase):
    def test_every_active_source_has_an_authentic_parser_fixture(self):
        fixture_by_source = {"claude-code-feed": "claude-code-feed-dom.xml",
                             "claude-code-changelog": "claude-code-changelog-dom.md",
                             "codex-changelog": "codex-changelog-dom.html"}
        self.assertEqual({spec["id"] for spec in tool_updates.SOURCES}, set(fixture_by_source))
        for source_id, filename in fixture_by_source.items():
            with self.subTest(source=source_id):
                self.assertTrue(parse((FIXTURES / filename).read_text(encoding="utf-8"), source_id))

    def test_official_feed_keeps_updated_only_provenance_and_real_entry_identity(self):
        body = (FIXTURES / "claude-code-feed-dom.xml").read_text(encoding="utf-8")
        rows = parse(body, "claude-code-feed")
        self.assertEqual([row["version"] for row in rows], ["2.1.288", "2.1.287", "2.1.286"])
        row = rows[0]
        self.assertEqual(row["url"], "https://github.com/anthropics/claude-code/releases/tag/v2.1.288")
        self.assertEqual(row["updated_at"], "2026-10-02T20:19:38Z")
        self.assertEqual(row["time_basis"], "updated")
        self.assertIsNone(row["published_at"])
        self.assertIsNone(row["published_date"])
        self.assertIn("Added $.ui.selection() for mods:", row["highlights"][0]["text"])
        self.assertEqual(row["highlights"][0]["source"], "claude-code-feed")
        self.assertEqual(row["highlights"][0]["url"], row["url"])

    def test_real_atom_markdown_pair_deduplicates_and_undated_old_section_stays_out(self):
        feed = parse((FIXTURES / "claude-code-feed-dom.xml").read_text(encoding="utf-8"), "claude-code-feed")
        markdown = parse((FIXTURES / "claude-code-changelog-dom.md").read_text(encoding="utf-8"), "claude-code-changelog")
        self.assertEqual({row["version"] for row in markdown}, {"2.1.288", "2.1.287", "2.1.224"})
        self.assertTrue(all(row["published_at"] is None and row["updated_at"] is None for row in markdown))
        rows = finish(feed + markdown)
        # Authentic feed has modification dates only; Markdown adds no original
        # publication evidence. Neither source proves a release happened this week.
        self.assertEqual(rows, [])


class ToolPublicationTests(unittest.TestCase):
    def test_failed_tools_cannot_change_exact_two_thirds_news_quorum(self):
        payload = snapshot(good=28)
        records = [dict(id=spec["id"], ok=False, count=0, url=spec["url"],
                        group="tool", error="offline") for spec in tool_updates.SOURCES]
        payload["sources"].extend(records)
        payload["tool_updates"], payload["tool_updates_meta"] = tool_updates.finish([], records, NOW)
        candidate, status = prepare_publication(payload, None, NOW)
        self.assertTrue(status["published"], status)
        self.assertEqual(status["active_remote_sources"], 42)
        self.assertEqual(status["successful_remote_sources"], 28)
        self.assertEqual(candidate["sources"], payload["sources"])
        self.assertEqual(candidate["tool_updates_meta"], payload["tool_updates_meta"])
        payload["sources"][27]["ok"] = False
        self.assertFalse(prepare_publication(payload, None, NOW)[1]["published"])

    def test_updated_only_old_entry_is_not_a_new_release(self):
        rows = parse(atom(version="0.1.0", published=None))
        self.assertEqual(finish(rows), [])
        candidate, status = prepare_publication(snapshot() | {"tool_updates": rows}, None, NOW)
        self.assertTrue(status["published"], status)
        self.assertEqual(candidate["tool_updates"], [])
        self.assertEqual(status["dropped_projection_rows"]["tool_updates"], 1)

    def test_markdown_complex_headings_cannot_publish_a_guessed_anchor(self):
        for heading in ("## 2.1.999 - 2026-10-02", "## [2.1.999](https://example.org/tag)",
                        "## 2.1.999\n- Earlier notes for this version.\n## 2.1.999",
                        "# 2.1.999\n## 2.1.999", "### 21999\n## 2.1.999",
                        "```markdown\n## 2.1.999\n```", "2.1.999\n===\n## 2.1.999",
                        "<!--\n## 2.1.999\n-->", "21999\n=\n\n## 2.1.999",
                        "<div>\n## 2.1.999\n</div>", "> # 21999\n\n## 2.1.999",
                        "- # 21999\n\n## 2.1.999", "- Nested:\n    # 21999\n\n## 2.1.999",
                        "<?xml\n## 2.1.999\n?>", "<![CDATA[\n## 2.1.999\n]]>"):
            with self.subTest(heading=heading):
                rows = finish(parse(atom()) + parse(heading + "\n- " + QUOTE, "claude-code-changelog"))
                self.assertEqual(rows[0]["sources"], ["claude-code-feed"])
        row = finish(parse(atom()) + parse("## 2.1.999\n- Fixed a different official release detail.",
                                          "claude-code-changelog"))[0]
        quote = next(quote for quote in row["highlights"] if quote["source"] == "claude-code-changelog")
        quote["url"] += "-wrong"
        candidate, status = prepare_publication(snapshot() | {"tool_updates": [row]}, None, NOW)
        self.assertEqual(candidate["tool_updates"], [])

    def valid(self):
        return finish(parse(atom()))[0]

    def test_optional_projection_preserves_legacy_and_accepts_attributed_rows(self):
        old = snapshot()
        candidate, status = prepare_publication(old, None, NOW)
        self.assertTrue(status["published"], status)
        self.assertNotIn("tool_updates", candidate)
        self.assertNotIn("tool_updates", status["dropped_projection_rows"])
        new = old | {"tool_updates": [self.valid()]}
        candidate, status = prepare_publication(new, None, NOW)
        self.assertTrue(status["published"], status)
        self.assertEqual(candidate["tool_updates"], new["tool_updates"])
        self.assertEqual(status["dropped_projection_rows"]["tool_updates"], 0)

    def test_malformed_rows_are_filtered_with_counts_without_mutating_collection(self):
        valid = self.valid()
        invalid = [None, {}, valid | {"url": "javascript:bad"}, valid | {"product": ""},
                   valid | {"published_at": "garbage"}, valid | {"published_date": "2026-02-30"},
                   valid | {"updated_at": "not-a-time"}, valid | {"published_date": "2026-09-01"},
                   valid | {"channel": "prerelease"}, valid | {"sources": []},
                   valid | {"sources": ["unrecognized-source"]}, valid | {"sources": valid["sources"] * 2},
                   valid | {"highlights": []}, valid | {"highlights": valid["highlights"] * 4},
                   valid | {"highlights": [dict(text=QUOTE, source="unknown", source_name="Unknown", url=valid["url"])]},
                   valid | {"highlights": [dict(text=QUOTE, source=valid["sources"][0], source_name="Official", url="javascript:bad")]},
                   valid | {"time_precision": "date"}, valid | {"extra": float("nan")}]
        for row in invalid:
            with self.subTest(row=row):
                payload = snapshot() | {"tool_updates": [valid, row]}
                before = copy.deepcopy(payload)
                candidate, status = prepare_publication(payload, None, NOW)
                self.assertTrue(status["published"], status)
                self.assertEqual(candidate["tool_updates"], [valid])
                self.assertEqual(status["dropped_projection_rows"]["tool_updates"], 1)
                self.assertEqual(payload, before)

    def test_broken_tool_container_rejects_the_whole_snapshot(self):
        for rows in (None, {}, "broken"):
            with self.subTest(rows=rows):
                _, status = prepare_publication(snapshot() | {"tool_updates": rows}, None, NOW)
                self.assertFalse(status["published"])

    def test_invalid_metadata_rejects_instead_of_advertising_a_false_window(self):
        _, meta = tool_updates.finish([], [], NOW)
        for invalid in (None, [], meta | {"window_days": True}, meta | {"window_days": 30},
                        meta | {"window_start": "2026-10-03"}, meta | {"window_end": meta["window_start"]},
                        meta | {"excluded": {"unknown_date": -1}}, meta | {"products": {}}):
            with self.subTest(meta=invalid):
                _, status = prepare_publication(snapshot() | {"tool_updates": [], "tool_updates_meta": invalid}, None, NOW)
                self.assertFalse(status["published"])

    def test_prior_publication_load_does_not_silently_sanitize_bad_tool_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published.json"
            path.write_bytes(json.dumps(snapshot() | {"tool_updates": [self.valid()]}).encode())
            self.assertIsNotNone(load_published(path, NOW))
            path.write_bytes(json.dumps(snapshot() | {"tool_updates": [None]}).encode())
            before = path.read_bytes()
            self.assertIsNone(load_published(path, NOW))
            self.assertEqual(path.read_bytes(), before)
