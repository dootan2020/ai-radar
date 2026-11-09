"""Readers see only stories whose newsroom prose the scoring desk passed; everything else fails closed."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import radar.newsroom_decisions as newsroom_decisions
from radar.newsroom_decisions import (DESK_PROMPT_VERSION, QUESTION_FLOOR, SCORE_THRESHOLD, SCORER_VERSION,
                                      apply_decisions,
                                      load_decisions, prose_digest, score_passed, weighted_score)
from radar import site_payload, story_pages
from tests.test_publication import snapshot

ROOT = Path(__file__).resolve().parents[1]
READER_FILES = ("radar.json", "radar-ui.json", "radar-window.json", "radar-head.json", "radar-search.json")
PASSING = {"what": 9, "why": 9, "notable": 8, "meaning": 8}  # 8.55
JUST_UNDER = {"what": 8, "why": 8, "notable": 8, "meaning": 7}  # 7.85


def reader_fixture():
    data = snapshot()
    data["stories"][0].update(summary="Old summary", summary_vi="Bản tóm tắt cũ",
                              importance_tier="top", importance_weight=3,
                              published_at=data["generated_at"])
    return data


def desk_row(sid, **extra):
    """A publish decision carrying desk prose, before any verdict."""
    row = {"id": sid, "decision": "publish", "content_kind": "event_news", "importance_tier": "standard",
           "summary": "written", "written_by": "nguoi-viet",
           "key_points": [f"Đoạn {index} của tin {sid}, viết bằng tiếng Việt." for index in range(1, 4)],
           "editorial_headline_vi": f"Tiêu đề biên tập của tin {sid}",
           "summary_sources": [{"id": "outlet", "role": "outlet", "name": "Desk Source",
                                "url": "https://desk.example/story"}],
           "summary_limitations": [], "key_points_prompt_version": DESK_PROMPT_VERSION}
    row.update(extra)
    return row


def scored(row, answers=PASSING, *, hard_errors=(), writer="agy", scorer="codex"):
    """The row with a scoring desk verdict on its exact headline and paragraphs."""
    row = deepcopy(row)
    row["score"] = {"version": SCORER_VERSION, "value": weighted_score(answers), "answers": dict(answers),
                    "hard_errors": list(hard_errors), "findings": [], "writer_boats": [writer],
                    "scorer_boat": scorer, "scorer_provider": scorer,
                    "prose_sha256": prose_digest(row["editorial_headline_vi"], row["key_points"]),
                    "scored_at": "2026-11-06T09:00:00+00:00"}
    return row


def payload_with(ids):
    payload = reader_fixture()
    template = payload["stories"][0]
    payload["stories"] = [{**deepcopy(template), "id": sid} for sid in ids]
    payload["sections"] = {"today": list(ids), "hot": list(reversed(ids))}
    return payload


def decisions_file(directory, rows, *, age=timedelta(0)):
    path = Path(directory) / "decisions.json"
    path.write_text(json.dumps({"schema_version": 1,
                                "generated_at": (datetime.now(timezone.utc) - age).isoformat(),
                                "decisions": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def reader_ids(target):
    """Story IDs in every reader file, and every section ID of the files that carry sections."""
    found = {}
    for name in READER_FILES:
        data = json.loads((target.parent / name).read_bytes())
        found[name] = [story["id"] for story in data["stories"]]
        for section, ids in (data.get("sections") or {}).items():
            found[f"{name}:{section}"] = list(ids)
    return found


def story_page_kinds(site):
    """Each /tin/<id>/ page: "story" for a story page; redirect pages listed by the story ID they point to."""
    kinds = {"redirects": set()}
    for page in (Path(site) / "tin").iterdir():
        text = (page / "index.html").read_text(encoding="utf-8")
        if 'http-equiv="refresh"' in text:
            kinds["redirects"].add(text.split('rel="canonical" href="')[1].split("/tin/")[1].split("/")[0])
        else:
            kinds[page.name] = "story"
    return kinds


class ScoringGateTests(unittest.TestCase):
    def test_only_prose_that_passed_the_scoring_desk_reaches_any_reader_file(self):
        hard_error = {"kind": "role", "summary_text": "Phó Trợ lý Tổng chưởng lý",
                      "explanation": "Paragraph p3 says Associate Deputy Attorney General."}
        edited = scored(desk_row("edited"))
        edited["key_points"][0] = "Đoạn đã sửa sau khi chấm."
        rows = [
            scored(desk_row("passed")),
            desk_row("unscored", score=None),
            desk_row("never-scored"),
            scored(desk_row("below-bar"), JUST_UNDER),
            scored(desk_row("hard-error"), {"what": 10, "why": 10, "notable": 10, "meaning": 10},
                   hard_errors=[hard_error]),
            scored(desk_row("own-boat"), writer="agy", scorer="agy"),
            edited,
            {"id": "no-prose", "decision": "publish", "summary": "claims", "key_points": ["Checked claim."]},
            {**scored(desk_row("held")), "decision": "hold"},
        ]
        ids = [row["id"] for row in rows] + ["undecided"]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data" / "radar.json"
            choice = decisions_file(directory, rows)
            with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice)}):
                site_payload.write_site_snapshot(payload_with(ids), target)
            for name, shown in reader_ids(target).items():
                self.assertTrue(set(shown) <= {"passed"}, (name, shown))
            for name in READER_FILES:
                self.assertEqual(reader_ids(target)[name], ["passed"], name)
            story = json.loads(target.read_bytes())["stories"][0]
            self.assertEqual(story["key_points"], rows[0]["key_points"])
            self.assertEqual(story["editorial_headline_vi"], rows[0]["editorial_headline_vi"])
            self.assertEqual(story["key_points_source"], "nguoi-viet")
            # The newsroom still reads every story from the intake copy.
            self.assertEqual(len(json.loads(site_payload.intake_path(target).read_bytes())["stories"]), len(ids))

    def test_the_bar_is_the_named_threshold_and_the_site_recomputes_the_score(self):
        self.assertEqual(SCORE_THRESHOLD, 8.0)
        below = scored(desk_row("below"), JUST_UNDER)
        self.assertFalse(score_passed(below))
        with patch.object(newsroom_decisions, "SCORE_THRESHOLD", 7.8):
            # meaning 7 is also under the per-question floor, so the total alone does not let it through ...
            self.assertFalse(score_passed(below))
            with patch.object(newsroom_decisions, "QUESTION_FLOOR", 7):
                # ... and with both bars moved it passes: the site reads the named constants on every build.
                self.assertTrue(score_passed(below))
        # A stored value that disagrees with its four answers is not trusted.
        inflated = deepcopy(below)
        inflated["score"]["value"] = 9.0
        self.assertFalse(score_passed(inflated))
        self.assertFalse(score_passed({**scored(desk_row("old")), "score": {**scored(desk_row("old"))["score"],
                                                                              "version": "cham-0"}}))

    def test_one_question_below_the_floor_fails_however_high_the_total(self):
        # The 06/11 18:00 Cainiao story: the scorer found its cause missing, and the weighted total still passed.
        cainiao = {"what": 10, "why": 6, "notable": 10, "meaning": 9}
        self.assertEqual(QUESTION_FLOOR, 8)
        self.assertGreaterEqual(weighted_score(cainiao), SCORE_THRESHOLD)
        row = scored(desk_row("cainiao"), cainiao)
        self.assertFalse(score_passed(row))
        self.assertEqual(apply_decisions(payload_with(["cainiao"]), {"decisions": [row]})["stories"], [])
        at_floor = scored(desk_row("at-floor"), {"what": 8, "why": 8, "notable": 8, "meaning": 8})
        self.assertTrue(score_passed(at_floor))
        # The floor is one named constant: lowering it lets the same verdict through.
        with patch.object(newsroom_decisions, "QUESTION_FLOOR", 6):
            self.assertTrue(score_passed(row))

    def test_missing_malformed_or_future_decisions_hide_every_story(self):
        ids = ["passed", "other"]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            choices = {"missing": base / "missing.json", "malformed": base / "malformed.json"}
            choices["malformed"].write_text('{"schema_version":1,"generated_at":null,"decisions":[]}',
                                            encoding="utf-8")
            choices["future"] = decisions_file(base, [scored(desk_row("passed"))], age=-timedelta(hours=2))
            for name, choice in choices.items():
                self.assertIsNone(load_decisions(choice), name)
                target = base / name / "radar.json"
                with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice)}):
                    site_payload.write_site_snapshot(payload_with(ids), target)
                for file, shown in reader_ids(target).items():
                    self.assertEqual(shown, [], (name, file))
        self.assertEqual(apply_decisions(payload_with(ids), None)["stories"], [])

    def test_a_stale_file_still_shows_only_what_its_scorer_passed(self):
        ids = ["passed", "held", "unscored", "undecided"]
        rows = [scored(desk_row("passed")), {**scored(desk_row("held")), "decision": "hold"},
                desk_row("unscored", score=None)]
        with tempfile.TemporaryDirectory() as directory:
            choice = decisions_file(directory, rows, age=timedelta(hours=30))
            self.assertIsNotNone(load_decisions(choice))
            target = Path(directory) / "radar.json"
            with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice)}):
                site_payload.write_site_snapshot(payload_with(ids), target)
            for name in READER_FILES:
                self.assertEqual(reader_ids(target)[name], ["passed"], name)

    def test_story_pages_exist_only_for_passed_stories_including_archived_ones(self):
        template = reader_fixture()["stories"][0]
        archived = {sid: {**deepcopy(template), "id": sid} for sid in
                    ("passed", "unscored", "held", "archived-only", "to-unscored", "to-passed")}
        archived["archived-only"]["key_points"] = ["Văn bản cũ chưa từng được chấm."]
        archived["passed"]["key_points"] = ["Văn bản cũ trong kho lưu."]
        archived["to-unscored"]["redirect_to"] = "unscored"
        archived["to-passed"]["redirect_to"] = "passed"
        decisions = {"decisions": [scored(desk_row("passed")), desk_row("unscored", score=None),
                                   {**scored(desk_row("held")), "decision": "hold"}]}
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"
            self.assertEqual(story_pages.render_site(deepcopy(archived), site, decisions=decisions), 1)
            # Story pages: only "passed"; every other page is a redirect to it ("to-passed", coverage aliases).
            self.assertEqual(story_page_kinds(site), {"passed": "story", "redirects": {"passed"}})
            page = (site / "tin" / "passed" / "index.html").read_text(encoding="utf-8")
            self.assertIn(decisions["decisions"][0]["key_points"][0], page)
            self.assertNotIn("Văn bản cũ trong kho lưu.", page)
            sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("/tin/passed/", sitemap)
            for sid in ("unscored", "held", "archived-only", "to-unscored"):
                self.assertNotIn(f"/tin/{sid}/", sitemap)
            # No decisions: no page at all, and a sitemap without story URLs.
            self.assertEqual(story_pages.render_site(deepcopy(archived), site, decisions=None), 0)
            self.assertEqual([path.name for path in (site / "tin").iterdir()], [])
            self.assertNotIn("/tin/", (site / "sitemap.xml").read_text(encoding="utf-8"))

    def test_story_page_build_reads_the_same_decisions_file(self):
        rows = [scored(desk_row("passed")), desk_row("unscored", score=None)]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote = base / "stories.git"
            subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True, capture_output=True)
            source = base / "radar.json"
            source.write_text(json.dumps(payload_with(["passed", "unscored"]), ensure_ascii=False), encoding="utf-8")
            sample = (ROOT / "site" / "tin" / "_sample" / "index.html").read_bytes()
            for name, choice in (("with", decisions_file(base, rows)), ("missing", base / "missing.json")):
                site = base / name / "site"
                # The checkout's site carries the tracked design sample, a story no scorer read.
                (site / "tin" / "_sample").mkdir(parents=True)
                (site / "tin" / "_sample" / "index.html").write_bytes(sample)
                with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice)}):
                    story_pages.prepare(str(remote), source, site, base / name / "candidate")
                expected = {"passed": "story", "redirects": {"passed"}} if name == "with" else {"redirects": set()}
                self.assertEqual(story_page_kinds(site), expected, name)
                self.assertFalse((site / "tin" / "_sample").exists(), name)
        # The prepared site is exactly what is uploaded and deployed: story pages are prepared before the upload,
        # and the deploy job publishes that artifact.
        workflow = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
        prepared = workflow.index('python -m radar.story_pages prepare --remote "$STORY_REMOTE"')
        upload = workflow.index("name: Upload Cloudflare Pages site artifact")
        self.assertLess(prepared, upload)
        self.assertIn("name: radar-cloudflare-site-${{ github.run_id }}\n          path: site\n", workflow[upload:])
        self.assertTrue(sample)

    def test_tiers_of_passed_stories_are_kept_unless_capping_is_enabled(self):
        payload = payload_with(["passed"])
        payload["stories"][0].update(importance_tier="top", importance_weight=90, importance_reason="top story")
        decisions = {"decisions": [scored(desk_row("passed", content_kind="analysis"))]}
        with patch.dict("os.environ", {"RADAR_NEWSROOM_CAP_TIERS": ""}):
            kept = apply_decisions(payload, decisions)["stories"][0]
        self.assertEqual((kept["importance_tier"], kept["importance_weight"]), ("top", 90))
        with patch.dict("os.environ", {"RADAR_NEWSROOM_CAP_TIERS": "true"}):
            capped = apply_decisions(payload, decisions)["stories"][0]
        self.assertEqual((capped["importance_tier"], capped["importance_weight"]), ("standard", 29.99))
        # Applying the same decisions to an already filtered snapshot (translation rewrites it) changes nothing.
        once = apply_decisions(payload, decisions)
        self.assertEqual(apply_decisions(once, decisions), once)


# The 2026-11-09 Nvidia board / Jensen Huang event, with its real IDs. At 02:10Z it was story e685… (the NVIDIA
# newsroom statement, then the smallest coverage URL) and the newsroom passed desk prose for it and for the two
# stories it had absorbed. At 05:01Z a Hacker News item linking https://nvidianews.nvidia.com/news/a-message-to-our-company
# joined the cluster; that URL sorts first, so the story became e020f… with e685… as an alias, and the site, which
# looked decisions up by story ID only, dropped it.
NVIDIA_STORY = "e020f35ba82bcce76a3e"
NVIDIA_BOARD = "e68539633591cd5be6cb"       # NVIDIA newsroom statement, top
NVIDIA_VERGE = "54c06e97d6e0a2b71c0f"       # The Verge, standard, tier capped
NVIDIA_TECHCRUNCH = "3b069222ecbd3b59ba7f"  # TechCrunch, notable
NVIDIA_ALIASES = ["28f71a6dea5ea175b9c7", NVIDIA_TECHCRUNCH, NVIDIA_VERGE, NVIDIA_BOARD, "f9d98c6ed1b45770980a"]
BLOOMBERG_STATEMENTS = "8a86cf9d70b8065c8241"  # same event, a separate story the newsroom held


def nvidia_payload():
    payload = payload_with([NVIDIA_STORY, BLOOMBERG_STATEMENTS])
    payload["stories"][0].update(url="https://nvidianews.nvidia.com/news/statement-from-nvidia-board-of-directors",
                                 title="Statement From NVIDIA Board of Directors", aliases=list(NVIDIA_ALIASES),
                                 importance_tier="top", importance_weight=90)
    payload["stories"][1].update(url="https://www.bloomberg.com/news/articles/2026-11-08/read-the-statements",
                                 aliases=["19af56563fcd9d85d737"])
    return payload


def nvidia_decisions():
    return {"decisions": [
        scored(desk_row(NVIDIA_VERGE)),
        scored(desk_row(NVIDIA_TECHCRUNCH, importance_tier="notable")),
        scored(desk_row(NVIDIA_BOARD, importance_tier="top")),
        {**scored(desk_row(BLOOMBERG_STATEMENTS)), "decision": "hold"},
    ]}


class AbsorbedDecisionTests(unittest.TestCase):
    def test_a_story_whose_id_changed_keeps_the_decision_of_the_story_it_absorbed(self):
        decisions = nvidia_decisions()
        with patch.dict("os.environ", {"RADAR_NEWSROOM_CAP_TIERS": "true"}):
            result = apply_decisions(nvidia_payload(), decisions)
        self.assertEqual([story["id"] for story in result["stories"]], [NVIDIA_STORY])
        story = result["stories"][0]
        board = decisions["decisions"][2]
        # The decision for the story's own lead URL (the board statement) is taken first.
        self.assertEqual(story["editorial_headline_vi"], board["editorial_headline_vi"])
        self.assertEqual(story["key_points"], board["key_points"])
        self.assertEqual((story["importance_tier"], story["importance_weight"]), ("top", 90))
        self.assertEqual(result["sections"], {"today": [NVIDIA_STORY], "hot": [NVIDIA_STORY]})
        self.assertEqual(apply_decisions(result, decisions), result)

    def test_without_the_lead_decision_the_strongest_absorbed_tier_is_used(self):
        decisions = {"decisions": [row for row in nvidia_decisions()["decisions"] if row["id"] != NVIDIA_BOARD]}
        story = apply_decisions(nvidia_payload(), decisions)["stories"][0]
        self.assertEqual(story["editorial_headline_vi"], f"Tiêu đề biên tập của tin {NVIDIA_TECHCRUNCH}")

    def test_the_story_own_decision_wins_even_when_it_holds(self):
        decisions = nvidia_decisions()
        decisions["decisions"].append({**scored(desk_row(NVIDIA_STORY)), "decision": "hold"})
        self.assertEqual(apply_decisions(nvidia_payload(), decisions)["stories"], [])

    def test_a_decision_is_shown_once(self):
        payload = nvidia_payload()
        # A second card that also lists the board statement as an alias does not show its prose a second time.
        payload["stories"].append({**deepcopy(payload["stories"][0]), "id": "0000000000000000aaaa",
                                   "aliases": [NVIDIA_BOARD]})
        # An alias that is another visible story's own ID stays with that story.
        payload["stories"].append({**deepcopy(payload["stories"][0]), "id": NVIDIA_VERGE, "aliases": []})
        shown = {story["id"]: story["editorial_headline_vi"]
                 for story in apply_decisions(payload, nvidia_decisions())["stories"]}
        self.assertEqual(shown, {NVIDIA_STORY: f"Tiêu đề biên tập của tin {NVIDIA_BOARD}",
                                 NVIDIA_VERGE: f"Tiêu đề biên tập của tin {NVIDIA_VERGE}"})

    def test_the_story_page_follows_the_absorbed_decision_and_the_old_id_redirects(self):
        payload = nvidia_payload()
        archived = {NVIDIA_STORY: payload["stories"][0],
                    NVIDIA_BOARD: {**deepcopy(payload["stories"][0]), "id": NVIDIA_BOARD, "aliases": [],
                                   "redirect_to": NVIDIA_STORY}}
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"
            story_pages.render_site(archived, site, decisions=nvidia_decisions())
            kinds = story_page_kinds(site)
            self.assertEqual(kinds[NVIDIA_STORY], "story")
            self.assertNotIn(NVIDIA_BOARD, kinds)
            self.assertIn(NVIDIA_STORY, kinds["redirects"])
            page = (site / "tin" / NVIDIA_STORY / "index.html").read_text(encoding="utf-8")
            self.assertIn(nvidia_decisions()["decisions"][2]["key_points"][0], page)


if __name__ == "__main__":
    unittest.main()
