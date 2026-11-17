"""Video candidates: the rubric, the exclusion gates, chain grouping and the keyword fallback.

The fixture is trimmed from real data: the hco.news snapshot of 2026-11-17 17:26 UTC, the 12/11 radar-ui.json and the
newsroom decisions.json. It holds the stories behind the three defects of the 2026-11-18 back-test.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar import video_script as v
from phong_bao.contracts import validate_chief_output, video_labels

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "video-candidates-real.json").read_text(encoding="utf-8"))
STORIES = {s["id"]: s for s in FIXTURE["stories"]}
ROWS = {r["id"]: r for r in FIXTURE["decisions"]}
REPOS = {r["id"]: r for r in FIXTURE["repos"]}
HUANG = "33a0483307191e736514"        # 09/11, Nvidia investigates CEO Jensen Huang, 5 sources
TRANSITION = "75fc88ac047912f1bb09"   # 12/11, Nvidia announces CEO transition, 6 sources
FOLLOW_UP = "cd1d1951ef503cb3a6c3"    # 13/11, Huang's resignation and open-source AI, 2 sources
LEAKER = "9836df3492903c3f1307"       # 11/11, a leaker on Apple's Harbor app, 1 source
LAUNCH = "55cb0588b3e8436e78b2"       # 10/11, Gemini 4 Carbon is now available, 1 source
LAWSUIT = "a90e63d4594ce7aea5b9"      # 17/11, California sues OpenAI, 3 sources


def story(sid, **changes):
    return {**deepcopy(STORIES[sid]), **changes}


def row(sid, **changes):
    return {**deepcopy(ROWS[sid]), **changes}


def labels(hook, people=(), availability="global", leak=False):
    return {"video_hook": hook, "named_people": list(people), "availability": availability, "is_leak": leak}


class ScoringTests(unittest.TestCase):
    def test_person_drama_scores_hook_brand_momentum_and_photo(self):
        c = v.score_story(story(HUANG), row(HUANG))
        b = c["breakdown"]
        self.assertEqual((b["hook"]["hook"], b["hook"]["points"], b["hook"]["labels"]), ("drama_person", 40, "keyword"))
        self.assertEqual(b["vietnam"]["points"], 7)        # Nvidia / Jensen Huang: a brand Vietnamese readers know
        self.assertEqual((b["momentum"]["sources"], b["momentum"]["points"]), (5, 20))
        self.assertEqual(b["visual"]["points"], 10)        # a real feed photo
        self.assertEqual((c["score"], c["gates"], c["lane"]), (77, [], v.LANE_HOT))
        self.assertEqual(c["hco_url"], f"https://hco.news/tin/{HUANG}/")
        self.assertTrue(c["source_urls"] and c["visual_links"])

    def test_hacker_news_points_add_to_momentum_up_to_25(self):
        s = story(LAWSUIT)
        s["coverage"][0]["metrics"] = {"points": 320}
        self.assertEqual(v.score_story(s, row(LAWSUIT))["breakdown"]["momentum"]["points"], 20)  # 3 sources 10 + 10
        s["source_count"] = 6
        self.assertEqual(v.score_story(s, row(LAWSUIT))["breakdown"]["momentum"]["points"], 25)

    def test_model_launch_is_not_usable_now(self):
        # Back-test defect: "Gemini 4 Carbon is now available" was scored as usable now through "available".
        c = v.score_story(story(LAUNCH), row(LAUNCH))
        self.assertEqual(c["breakdown"]["hook"]["hook"], "launch")
        self.assertLess(c["score"], v.CANDIDATE_THRESHOLD)

    def test_free_tool_gets_usable_lane_and_replacement_bonus(self):
        s = story(LAUNCH, title="Open-source CapCut alternative is free for everyone", title_vi="")
        c = v.score_story(s, row(LAUNCH, editorial_headline_vi="Bản mã nguồn mở thay CapCut miễn phí"))
        self.assertEqual((c["lane"], c["breakdown"]["hook"]["points"]), (v.LANE_USABLE, 40))


class LabelFallbackTests(unittest.TestCase):
    def test_editor_labels_override_keywords(self):
        c = v.score_story(story(LAUNCH), row(LAUNCH, video_labels=labels("usable_now")))
        self.assertEqual((c["breakdown"]["hook"]["labels"], c["breakdown"]["hook"]["hook"]), ("editor", "usable_now"))
        self.assertEqual(c["breakdown"]["vietnam"]["points"], 15)   # usable now and global: usable in Vietnam

    def test_old_rows_without_labels_and_malformed_labels_use_keywords(self):
        for bad in (None, {"video_hook": "viral"}, labels("launch") | {"is_leak": "no"}):
            c = v.score_story(story(HUANG), row(HUANG, video_labels=bad))
            self.assertEqual(c["breakdown"]["hook"]["labels"], "keyword")
            self.assertEqual(c["score"], 77)

    def test_story_without_any_decision_row_still_scores(self):
        # A reader snapshot (radar-ui.json) carries the desk headline on the story itself.
        s = story(HUANG, key_points_source="nguoi-viet", key_points=["Một ý đã kiểm."],
                  editorial_headline_vi=ROWS[HUANG]["editorial_headline_vi"])
        c = v.score_story(s, None)
        self.assertEqual((c["score"], c["gates"]), (77, []))
        self.assertIn("chưa có quyết định phòng báo", v.score_story(story(HUANG), None)["gates"])

    def test_editor_label_contract(self):
        good = {"video_hook": "drama_person", "named_people": ["Jensen Huang", " jensen huang "],
                "availability": "region_locked:US", "is_leak": False}
        self.assertEqual(video_labels(good)["named_people"], ["Jensen Huang"])
        self.assertIsNone(video_labels({**good, "video_hook": "viral"}))
        self.assertIsNone(video_labels({**good, "availability": "everywhere"}))
        self.assertIsNone(video_labels({**good, "is_leak": None}))
        self.assertIsNone(video_labels({k: good[k] for k in ("video_hook", "is_leak")}))


class GateTests(unittest.TestCase):
    def test_leaker_rumour_under_three_sources_is_excluded(self):
        # Back-test defect: "Leaker Aaron Perris tiết lộ..." passed because "leaker" was not a rumour word.
        self.assertIn("tin đồn/rò rỉ, dưới 3 nguồn độc lập", v.score_story(story(LEAKER), row(LEAKER))["gates"])
        labelled = row(LEAKER, editorial_headline_vi="Apple phát triển ứng dụng Harbor",
                       video_labels=labels("launch", leak=True))
        s = story(LEAKER, title="Apple has new Mac app", title_vi="")
        self.assertIn("tin đồn/rò rỉ, dưới 3 nguồn độc lập", v.score_story(s, labelled)["gates"])
        self.assertNotIn("tin đồn/rò rỉ, dưới 3 nguồn độc lập",
                         v.score_story({**s, "source_count": 3}, labelled)["gates"])

    def test_person_drama_needs_three_independent_sources(self):
        # Owner decision 1 (2026-11-18): personal drama only on verified facts carried by at least 3 sources.
        c = v.score_story(story(FOLLOW_UP), row(FOLLOW_UP))
        self.assertEqual(c["breakdown"]["hook"]["hook"], "drama_person")
        self.assertIn("drama về người cần ít nhất 3 nguồn độc lập", c["gates"])
        self.assertNotIn("drama về người cần ít nhất 3 nguồn độc lập",
                         v.score_story(story(FOLLOW_UP, source_count=3), row(FOLLOW_UP))["gates"])

    def test_unverified_story_is_excluded(self):
        self.assertIn("tiêu đề chưa được kiểm", v.score_story(story(HUANG), row(HUANG, use_original_title=True))["gates"])
        self.assertIn("phòng báo giữ lại", v.score_story(story(HUANG), row(HUANG, decision="hold"))["gates"])
        self.assertIn("không có tóm tắt đã kiểm", v.score_story(story(HUANG), row(HUANG, key_points=[]))["gates"])

    def test_ai_image_is_not_a_real_visual(self):
        s = story(HUANG, image={"src": "https://hco.news/anh/x.webp", "via": "ai", "kind": "photo"})
        self.assertIn("không có hình thật", v.score_story(s, row(HUANG))["gates"])

    def test_region_locked_feature_is_excluded_unless_vietnam_is_named(self):
        r = row(LAUNCH, video_labels=labels("usable_now", availability="region_locked:US"))
        self.assertIn("chỉ có ở nước ngoài", v.score_story(story(LAUNCH), r)["gates"])
        r = row(LAUNCH, video_labels=labels("usable_now", availability="region_locked:US, Vietnam"))
        self.assertNotIn("chỉ có ở nước ngoài", v.score_story(story(LAUNCH), r)["gates"])

    def test_sensitive_topic_is_excluded(self):
        s = story(LAWSUIT, title="Chatbot linked to teen suicide faces lawsuit")
        self.assertIn("chủ đề nhạy cảm", v.score_story(s, row(LAWSUIT))["gates"])

    # Regression tests for the review of 2026-11-18 (F1-F3).
    def test_person_drama_outside_the_name_list_needs_three_sources(self):
        s = story(LAWSUIT, title="OpenAI researcher fired after scandal", title_vi="", source_count=1,
                  url="https://www.youtube.com/watch?v=abc")
        s["coverage"][0]["metrics"] = {"points": 350}
        r = row(LAWSUIT, editorial_headline_vi="Nhà nghiên cứu OpenAI bị sa thải sau bê bối")
        self.assertIn("drama về người cần ít nhất 3 nguồn độc lập", v.score_story(s, r)["gates"])
        self.assertNotIn("drama về người cần ít nhất 3 nguồn độc lập",
                         v.score_story({**s, "source_count": 3}, r)["gates"])
        day = v.video_candidates([s], {LAWSUIT: r}, [], now=datetime(2026, 11, 17, 5, tzinfo=v.VIETNAM))
        self.assertEqual(day["days"][0]["picks"], [])

    def test_hot_lane_needs_two_independent_sources(self):
        s = story(LAWSUIT, source_count=1, url="https://www.youtube.com/watch?v=abc")
        s["coverage"][0]["metrics"] = {"points": 400}
        self.assertIn("tin nóng cần ít nhất 2 nguồn độc lập", v.score_story(s, row(LAWSUIT))["gates"])
        jobs = story(LAWSUIT, title="Amazon layoffs hit 16,000 workers as AI takes their jobs", title_vi="",
                     source_count=1)
        c = v.score_story(jobs, row(LAWSUIT, editorial_headline_vi="Amazon sa thải 16.000 nhân viên"))
        self.assertEqual(c["breakdown"]["hook"]["hook"], "money_jobs")
        self.assertIn("tin nóng cần ít nhất 2 nguồn độc lập", c["gates"])
        self.assertNotIn("tin nóng cần ít nhất 2 nguồn độc lập", v.score_story(story(LAWSUIT), row(LAWSUIT))["gates"])

    def test_vietnamese_headline_words_are_not_company_drama(self):
        for title, headline in (("Google unveils Gemini 5 at I/O", "Google ra mắt Gemini 5 tại sự kiện I/O"),
                                ("OpenAI issues new rules for GPT-6", "OpenAI ban hành quy tắc mới cho GPT-6"),
                                ("Meta unveils a new model", "Meta công bố mô hình mới, bản ban đầu"),
                                ("Anthropic restructures its team", "Anthropic kiện toàn đội ngũ"),
                                ("Fine-tuning Llama gets cheaper", "Tinh chỉnh Llama rẻ hơn")):
            c = v.score_story(story(LAUNCH, title=title, title_vi=""), row(LAUNCH, editorial_headline_vi=headline))
            self.assertNotEqual(c["breakdown"]["hook"]["hook"], "drama_company", headline)
            self.assertEqual(c["chain"]["orgs"], [], headline)
        sued = v.score_story(story(LAUNCH, title="x", title_vi=""), row(LAUNCH, editorial_headline_vi="California kiện OpenAI"))
        self.assertEqual(sued["breakdown"]["hook"]["hook"], "drama_company")
        banned = v.score_story(story(LAUNCH, title="Italy bans DeepSeek", title_vi=""), row(LAUNCH))
        self.assertEqual(banned["breakdown"]["hook"]["hook"], "drama_company")


def vn(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=v.VIETNAM)


def run(stories, repos, now, previous=None, rows=ROWS):
    return v.video_candidates(stories, rows, repos, now=now, previous=previous)


def picks_by_day(result):
    return {d["date"]: [p["id"] for p in d["picks"]] for d in result["days"]}


class ChainTests(unittest.TestCase):
    def picked(self, sid, at, **changes):
        return {**v.score_story(story(sid, **changes), row(sid)), "picked_at": at.isoformat()}

    def test_same_person_and_same_company_drama_are_one_chain(self):
        lead = v.score_story(story(HUANG), row(HUANG))
        follow = v.score_story(story(FOLLOW_UP), row(FOLLOW_UP))
        transition = v.score_story(story(TRANSITION), row(TRANSITION))   # names no person: chained by Nvidia
        self.assertTrue(v.same_chain(lead, follow))
        self.assertTrue(v.same_chain(lead, transition))
        self.assertFalse(v.same_chain(lead, v.score_story(story(LAWSUIT), row(LAWSUIT))))

    def test_editor_subject_groups_a_chain_only_when_specific(self):
        a = v.score_story(story(LAWSUIT), row(LAWSUIT, subject="California v OpenAI"))
        b = v.score_story(story(LAUNCH), row(LAUNCH, subject="california v openai"))
        self.assertTrue(v.same_chain(a, b))
        a = v.score_story(story(LAWSUIT), row(LAWSUIT, subject="DeepSeek"))
        b = v.score_story(story(LAUNCH), row(LAUNCH, subject="DeepSeek"))
        self.assertFalse(v.same_chain(a, b))     # a bare company name covers a financing story and a launch alike

    def test_follow_up_needs_seventy_and_a_new_major_development(self):
        lead = self.picked(HUANG, vn(10, 5))
        transition = v.score_story(story(TRANSITION), row(TRANSITION))
        self.assertGreaterEqual(transition["score"], v.MAJOR_THRESHOLD)
        self.assertIsNone(v.chain_block(dict(transition), [lead], vn(12, 21, 30)))   # resignation: new, 72 points
        again = v.score_story(story(FOLLOW_UP, source_count=3), row(FOLLOW_UP))
        self.assertEqual(v.major_turn(again), "resignation")
        shown = {**transition, "picked_at": vn(12, 21, 30).isoformat()}
        self.assertEqual(v.chain_block(again, [lead, shown], vn(13, 22)),
                         "cùng chuỗi tin đã làm trong 3 ngày")              # a second resignation story is not new
        weak = {**transition, "score": 65}
        self.assertEqual(v.chain_block(weak, [lead], vn(12, 21, 30)), "cùng chuỗi tin đã làm trong 3 ngày")

    def test_chain_reopens_on_the_third_day_after(self):
        lead = self.picked(HUANG, vn(10, 5))
        weak = {**v.score_story(story(TRANSITION), row(TRANSITION)), "score": 61}
        self.assertEqual(v.chain_block(dict(weak), [lead], vn(12, 23, 59)), "cùng chuỗi tin đã làm trong 3 ngày")
        self.assertIsNone(v.chain_block(dict(weak), [lead], vn(13, 0, 1)))

    def test_one_chain_never_fills_a_week_of_picks(self):
        # The back-test top 10 had 7 Jensen Huang stories. Runs at 05:00 and 21:30 each day, each fed the file the
        # run before published, offer the lead and one new turn only.
        stories = [story(HUANG), story(TRANSITION), story(FOLLOW_UP, source_count=4)]
        previous = None
        for day in range(10, 15):
            for hour, minute in ((5, 0), (21, 30)):
                previous = run(stories, [], vn(day, hour, minute), previous)
        offered = [p for d in reversed(previous["days"]) for p in picks_by_day(previous)[d["date"]]]
        self.assertEqual(offered, [HUANG, TRANSITION])

    # Regression tests for the review of 2026-11-18 (F5, F6).
    def test_two_unrelated_events_of_one_company_are_two_chains(self):
        lawsuit = v.score_story(story(LAWSUIT), row(LAWSUIT))
        outage = v.score_story(story(LAWSUIT, id="outage", title="OpenAI outage takes ChatGPT down for hours",
                                     title_vi=""), row(LAWSUIT, editorial_headline_vi="ChatGPT sập nhiều giờ"))
        self.assertEqual(outage["breakdown"]["hook"]["hook"], "drama_company")
        self.assertFalse(v.same_chain(lawsuit, outage))

    def test_a_person_quoted_outside_drama_does_not_chain(self):
        a = v.score_story(story(LAWSUIT, title="Trump signs AI chip export order", title_vi=""),
                          row(LAWSUIT, editorial_headline_vi="Trump ký lệnh xuất khẩu chip AI"))
        b = v.score_story(story(LAUNCH, title="Trump praises new US AI datacenter", title_vi=""),
                          row(LAUNCH, editorial_headline_vi="Trump khen trung tâm dữ liệu AI mới"))
        self.assertFalse(v.same_chain(a, b))

    def test_full_names_from_labels_do_not_collide_on_a_given_name(self):
        drama = labels("drama_person", people=["Nguyễn Văn Minh"])
        a = v.score_story(story(HUANG), row(HUANG, video_labels=drama))
        b = v.score_story(story(LAWSUIT), row(LAWSUIT, video_labels=labels("drama_person", people=["Trần Minh"])))
        self.assertFalse(v.same_chain(a, b))
        c = v.score_story(story(FOLLOW_UP), row(FOLLOW_UP, video_labels=labels("drama_person", ["Nguyen Van Minh"])))
        self.assertTrue(v.same_chain(a, c))


class DayTests(unittest.TestCase):
    def test_hot_lane_takes_one_and_repos_two(self):
        day = run([story(HUANG)], list(REPOS.values()), vn(10, 5))["days"][0]
        self.assertEqual([p["lane"] for p in day["picks"]], [v.LANE_HOT, v.LANE_USABLE, v.LANE_USABLE])
        self.assertEqual(day["picks"][1]["id"], "meta/astryx")
        self.assertTrue(all(p["reason"] and p["breakdown"] and p["chain"] for p in day["picks"]))

    def test_without_a_hot_story_the_usable_lane_takes_at_most_two(self):
        # Owner decision 3 with spec §4.2 (review F8): the usable lane fills a day without a hot pick, 1-2 slots.
        repos = list(REPOS.values()) + [{**REPOS["meta/astryx"], "id": "example/third", "full_name": "example/third"}]
        picks = run([story(LAWSUIT)], repos, vn(17, 5))["days"][0]["picks"]
        self.assertEqual(len(picks), 2)
        self.assertFalse(any(p["lane"] == v.LANE_HOT for p in picks))

    def test_a_day_with_nothing_above_the_threshold_has_no_video(self):
        day = run([story(LAWSUIT), story(LAUNCH)], [], vn(17, 5))["days"][0]
        self.assertEqual((day["picks"], day["no_video"]), ([], True))

    def test_stories_older_than_48_hours_are_not_candidates(self):
        self.assertEqual(run([story(HUANG)], [], vn(11, 23))["days"][0]["picks"], [])

    # Regression tests for the review of 2026-11-18 (F4): the memory is the published file, not a replay.
    def test_a_repo_is_offered_once_per_three_days_across_runs(self):
        repos = list(REPOS.values())
        first = run([], repos, vn(18, 5))
        rerun = run([], repos, vn(18, 5, 20), first)                 # same day, 20 minutes later
        self.assertEqual(picks_by_day(rerun)["2026-11-18"], ["meta/astryx", "mattpocock/skills"])
        again = run([], repos, vn(18, 5, 40), rerun)
        self.assertEqual(picks_by_day(again)["2026-11-18"], ["meta/astryx", "mattpocock/skills"])
        d1 = run([], repos, vn(19, 5), again)
        d2 = run([], repos, vn(20, 5), d1)
        self.assertEqual((picks_by_day(d1)["2026-11-19"], picks_by_day(d2)["2026-11-20"]), ([], []))
        self.assertEqual(picks_by_day(d2)["2026-11-18"], ["meta/astryx", "mattpocock/skills"])   # kept verbatim
        d3 = run([], repos, vn(21, 5), d2)
        self.assertEqual(picks_by_day(d3)["2026-11-21"], ["meta/astryx", "mattpocock/skills"])

    def test_a_story_that_heats_up_overnight_is_offered_on_the_live_day(self):
        cold = story(LAWSUIT, source_count=1)
        day1 = run([cold], [], vn(17, 5))
        self.assertEqual(picks_by_day(day1)["2026-11-17"], [])
        hot = story(LAWSUIT, source_count=6)
        hot["coverage"][0]["metrics"] = {"points": 400}
        day2 = run([hot], [], vn(18, 5), day1)
        self.assertEqual(picks_by_day(day2), {"2026-11-18": [LAWSUIT], "2026-11-17": []})

    def test_bad_previous_file_is_a_cold_start(self):
        for bad in (None, [], {"days": "x"}, {"days": [{"date": "x", "picks": []}, 3, {"date": "2026-11-17"}]}):
            result = run([story(HUANG)], [], vn(10, 5), bad)
            self.assertEqual(picks_by_day(result), {"2026-11-10": [HUANG]})


class RepoTests(unittest.TestCase):
    def test_trending_repo_with_install_command(self):
        c = v.score_repo(REPOS["meta/astryx"])
        self.assertEqual((c["score"], c["gates"], c["lane"]), (90, [], v.LANE_USABLE))
        self.assertEqual(c["install_command"], "npm i -g @astryxdesign/cli")
        self.assertEqual(c["breakdown"]["momentum"]["stars_week"], 10939)

    def test_cold_and_research_repos_are_excluded(self):
        self.assertIn("repo dưới 3.000 sao/tuần", v.score_repo(REPOS["google-labs-code/stitch-skills"])["gates"])
        self.assertIn("không phải công cụ dùng ngay",
                      v.score_repo(REPOS["GoogleChrome/modern-web-guidance-src"])["gates"])


class FileTests(unittest.TestCase):
    def test_write_reads_snapshot_and_decisions_and_writes_payload(self):
        now = datetime(2026, 11, 10, 5, tzinfo=v.VIETNAM)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "radar-ui.json").write_text(json.dumps({"stories": list(STORIES.values()),
                                                           "repos": list(REPOS.values())}), encoding="utf-8")
            (tmp / "decisions.json").write_text(json.dumps({
                "schema_version": 1, "generated_at": "2026-11-09T20:00:00+00:00",
                "decisions": list(ROWS.values())}), encoding="utf-8")
            out = tmp / "video-candidates.json"
            result = v.write_video_candidates(tmp / "radar-ui.json", out, tmp / "decisions.json", now=now)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), result)
            today = result["days"][0]
            self.assertEqual(today["date"], "2026-11-10")
            self.assertEqual(today["picks"][0]["id"], HUANG)
            self.assertLessEqual(len(today["picks"]), 3)
            self.assertEqual(result["rubric"]["threshold"], 60)

    def test_cli_writes_candidates_beside_the_script_output_without_a_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "radar-ui.json").write_text(json.dumps({"stories": list(STORIES.values()),
                                                           "repos": list(REPOS.values())}), encoding="utf-8")
            code = v.main(["--input", str(tmp / "radar-ui.json"), "--output", str(tmp / "data" / "video-script.json"),
                           "--ledger", str(tmp / "ledger.json"), "--ref", "main", "--decisions", str(tmp / "none.json"),
                           "--now", "2026-11-17T10:00:00Z"])
            self.assertEqual(code, 0)
            self.assertTrue((tmp / "data" / "video-candidates.json").is_file())
            self.assertFalse((tmp / "data" / "video-script.json").exists())   # outside the 05:00 window
            self.assertFalse((tmp / "ledger.json").exists())

    def test_chief_rows_with_video_fields_validate(self):
        base = {"id": "x", "decision": "publish", "content_kind": "event_news", "analysis_kind": None,
                "round": "chief", "reason": "ok", "importance_tier": "standard", "tier_capped": False,
                "summary": "none", "degradation_reasons": [], "use_original_title": False,
                "source_url": "https://example.org", "key_points": [], "same_event_coverage_ids": [],
                "split_coverage_ids": []}
        self.assertTrue(validate_chief_output({**base, "subject": "Nvidia", "video_labels": labels("launch")}))
        self.assertTrue(validate_chief_output({**base, "subject": None, "video_labels": None}))
        self.assertFalse(validate_chief_output({**base, "video_labels": {"video_hook": "viral"}}))


if __name__ == "__main__":
    unittest.main()
