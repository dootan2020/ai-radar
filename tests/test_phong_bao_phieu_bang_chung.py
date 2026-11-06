"""The writer works from an evidence sheet taken from the article body.

The fault shapes come from nine published stories a reviewer read against their full originals on 06/11: a figure
taken from a related-articles list, a device roadmap turned into the company's motive, a point the prose dropped
while it kept secondary detail, and a partial_source label that did not match the body. The article below is
synthetic; no publisher prose.
"""

from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch

import phong_bao.newsroom as newsroom
from phong_bao.contracts import validate_writer_output
from phong_bao.newsroom import WRITER_PROMPT, WRITER_REWRITE_PROMPT, FixtureArticles, _reporter, _writer, article_body
from phong_bao.registry import load_registry
from radar.summary_validation import number_error
from test_phong_bao_writer import DISCOVERY, NOW, RecordingRunner, sentence

SID = "lumo-voice"
URL = "https://news.example/tech/lumo-voice-mode"
BODY = [
    "Tech",
    "AI",
    "Lumo has a voice mode now",
    "by Sam Ortiz",
    "Orbit Labs now lets you have voice conversations with your Lumo AI agent in real time, CEO Dana Reyes "
    "announced today.",
    "The feature has been rolled out to me, and I tried it on the iOS app while writing this article. As you chat "
    "with your Lumo agent, the avatar at the top of your conversation animates in time with the words that it says.",
    "In my brief tests, my Lumo agent responds quickly over voice, though it occasionally pauses while it looks up "
    "information. For my particular avatar, it has been a little uncanny to watch it talk.",
    "Lumo's voice mode and expressive avatars are rolling out now in the US for the app, Orbit Labs says. They are "
    "coming soon for Orbit Labs' smart glasses and its forthcoming Lumo Pendant, which is supposed to ship this year.",
]
# What followed the article on the page: a topic block, a related-articles list and a most-popular list.
FURNITURE = [
    "Follow topics and authors from this story to see more like this in your personalized homepage feed and to "
    "receive email updates.",
    "More in: All the latest news on Orbit Labs' Lumo agent",
    "10 million people have already set up Lumo agents.",
    "Orbit Labs' Lumo hits 10 million US downloads.",
    "Most Popular",
    "Those hair transplant photos are very fake",
]
PAGE = "\n".join(BODY + FURNITURE)
COVERAGE_URL = "https://other.example/lumo-calls"
COVERAGE_TEXT = "Orbit Labs' agent can now take calls as an animated avatar."

CONDITIONS = [{"text": "are rolling out now in the US for the app", "ref": "outlet:p008"}]
SHEET = {
    "what": {"point": "Lumo có chế độ trò chuyện bằng giọng nói", "ref": "outlet:p005", "speaker": "Dana Reyes",
             "quote": "Orbit Labs now lets you have voice conversations with your Lumo AI agent in real time"},
    "why": {"point": "source does not say", "quote": "", "ref": None, "speaker": None},
    "notable": {"point": "phản hồi nhanh nhưng đôi lúc tạm dừng", "ref": "outlet:p007",
                "speaker": "Sam Ortiz, the outlet's reporter",
                "quote": "my Lumo agent responds quickly over voice, though it occasionally pauses while it looks up "
                         "information"},
    "meaning": {"point": "đang triển khai ở US, sắp có trên kính", "ref": "outlet:p008", "speaker": "Orbit Labs",
                "quote": "Lumo's voice mode and expressive avatars are rolling out now in the US for the app"},
}
LEAD = sentence("Orbit Labs cho phép người dùng trò chuyện bằng giọng nói theo thời gian thực với tác tử Lumo, theo "
                "thông báo của giám đốc điều hành Dana Reyes.", "outlet:p005")
EXAMPLE = sentence("Trong các thử nghiệm ngắn của phóng viên Sam Ortiz, tác tử Lumo phản hồi nhanh bằng giọng nói "
                   "nhưng đôi lúc tạm dừng khi tra cứu thông tin.", "outlet:p007")
REPLY = {
    "id": SID, "status": "ready", "sheet": SHEET, "conditions": CONDITIONS,
    "title_vi": sentence("Orbit Labs thêm chế độ trò chuyện bằng giọng nói cho tác tử Lumo", "outlet:p005"),
    "paragraphs": [
        {"role": "development", "sentences": [
            LEAD,
            sentence("Khi người dùng trò chuyện, hình đại diện ở đầu cuộc hội thoại cử động khớp với lời tác tử nói.",
                     "outlet:p006")]},
        {"role": "cause", "sentences": [
            sentence("Phóng viên Sam Ortiz đã dùng thử tính năng này trên ứng dụng iOS trong lúc viết bài.",
                     "outlet:p006"),
            sentence("Hình đại diện ở đầu cuộc trò chuyện chuyển động theo từng lời tác tử Lumo nói ra.",
                     "outlet:p006")]},
        {"role": "examples", "sentences": [EXAMPLE]},
        {"role": "significance", "sentences": [
            sentence("Orbit Labs cho biết chế độ giọng nói và hình đại diện đang được triển khai cho ứng dụng tại US, "
                     "và sẽ sớm có trên kính thông minh của hãng.", "outlet:p008")]},
    ],
    "used_source_ids": ["outlet"], "limitations": [],
}
# The 06/11 story's unsupported motive: a device roadmap written as the company's reason, and its follow-on.
MOTIVE = sentence("Theo Orbit Labs, tính năng này là bước chuẩn bị để đưa Lumo lên kính thông minh và thiết bị đeo "
                  "của hãng.", "outlet:p008")
WANTS = sentence("Orbit Labs muốn mở rộng trải nghiệm Lumo từ điện thoại sang phần cứng sắp ra mắt.", "outlet:p008")


def item(coverage=()):
    return {"id": SID, "title": "Lumo has a voice mode now", "url": URL, "summary": "Publisher excerpt.",
            "published_at": (NOW - timedelta(hours=2)).isoformat(),
            "coverage": [{"id": "c1", "url": URL, "publisher": "Example News"}, *coverage]}


def desks():
    intake = {SID: {"id": SID, "pass": True, "reason": "eligible for reporting"}}
    reporter = {SID: {"id": SID, "readable": True, "selected_url": URL, "source_text": "", "reason": "source selected",
                      "invalid_response": False, "representative_status": "readable"}}
    editor = {SID: {"id": SID, "news": True, "content_kind": "event_news", "analysis_kind": None,
                    "reason": "editor news", "importance": "standard", "event_at": None, "claims": [],
                    "same_event_coverage_ids": ["c1"], "split_coverage_ids": [], "boat": "codex"}}
    return intake, reporter, editor


class EvidenceSheetTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()

    def write(self, reply=None, *, rewrite=None, page=PAGE, story=None):
        replies = {"writer": {SID: deepcopy(reply or REPLY)}}
        if rewrite is not None:
            replies["rewrite-writer"] = {SID: rewrite}
        runner = RecordingRunner(replies)
        intake, reporter, editor = desks()
        articles = FixtureArticles({"articles": {URL: {"text": page, "reason": None}}})
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            output, _ = _writer([story or item()], intake, reporter, editor, articles, self.tools, DISCOVERY,
                                runner, NOW)
        return output[SID], runner

    def main_row(self, reply, **kwargs):
        """The row main's checks give the same reply: every validation without the sheet rules."""
        original = newsroom._written_prose

        def without_sheet(*args, **options):
            return original(*args, **{**options, "sheet_required": False})

        with patch.object(newsroom, "_written_prose", side_effect=without_sheet):
            return self.write(reply, **kwargs)[0]

    def assert_kept_as_main(self, row, reply, path, sheet_error, **kwargs):
        main = self.main_row(reply, **kwargs)
        self.assertTrue(main["written"], main)
        self.assertTrue(row["written"], row)
        self.assertEqual(row["key_points"], main["key_points"])
        self.assertEqual((row["sheet_path"], row.get("sheet_error")), (path, sheet_error))
        self.assertTrue(validate_writer_output(row))

    def test_a_reply_that_carries_its_sheet_is_written(self):
        row, runner = self.write()
        self.assertTrue(row["written"], row)
        self.assertTrue(validate_writer_output(row))
        self.assertEqual(row["dropped_points"], [])
        self.assertEqual(row["evidence_sheet"], SHEET)
        self.assertEqual(row["sheet_path"], "sheet")
        self.assertNotIn("sheet_error", row)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][2], WRITER_PROMPT)
        for phrase in ("sheet: {what, why, notable, meaning}", "source does not say", "article body only"):
            self.assertIn(phrase, WRITER_PROMPT)

    def test_the_related_articles_block_never_reaches_the_writer(self):
        row, runner = self.write()
        sent = [part["text"] for part in runner.calls[0][1][0]["sources"][0]["paragraphs"]]
        self.assertEqual(sent, BODY)
        self.assertFalse(any("10 million" in text for text in sent))
        # The published sentence of 06/11 cited the list's lines; here they have no paragraph ID to cite.
        reply = deepcopy(REPLY)
        reply["paragraphs"][0]["sentences"].append(sentence(
            "Bản cập nhật ra mắt khi ứng dụng Lumo đã đạt mốc 10 triệu lượt tải xuống tại US.",
            "outlet:p011", "outlet:p012"))
        row, _ = self.write(reply)
        self.assertTrue(row["written"], row)
        self.assertNotIn("10 triệu", " ".join(row["key_points"]))
        self.assertEqual(row["dropped_points"][0]["role"], "development")

    def test_a_missing_sheet_is_asked_for_once_and_the_prose_is_never_lost(self):
        missing = deepcopy(REPLY)
        del missing["sheet"]
        row, runner = self.write(missing)
        # The rewrite lane gave nothing: the story keeps the prose main would have published.
        self.assert_kept_as_main(row, missing, "without_sheet", "sheet_missing")
        self.assertEqual(row["rewrite"], {"roles": [], "result": "rewrite_model_failure"})
        desk, rows, instruction = runner.calls[1]
        self.assertEqual((desk, rows[0]["rewrite"]["sheet_error"], rows[0]["rewrite"]["roles"]),
                         ("rewrite-writer", "sheet_missing", []))
        self.assertIn("sheet_error", instruction)
        # A rewrite that returns the sheet puts the story back under the sheet rules.
        rewrite = {"id": SID, "status": "ready", "sheet": deepcopy(SHEET), "conditions": [], "paragraphs": []}
        row, _ = self.write(missing, rewrite=rewrite)
        self.assertTrue(row["written"], row)
        self.assertEqual(row["sheet_path"], "sheet_after_rewrite")
        self.assertEqual(row["rewrite"], {"roles": [], "result": "written"})

    def test_an_invalid_sheet_falls_back_to_mains_checks(self):
        for name, change, error in (
                ("what", {"quote": "Orbit Labs now lets everyone talk to Lumo"}, "sheet_quote_not_in_body: what"),
                ("meaning", {"ref": "outlet:p005"}, "sheet_quote_not_in_body: meaning"),
                ("notable", {"speaker": ""}, "sheet_speaker_missing: notable"),
                # Only why may be empty.
                ("meaning", {"quote": "", "ref": None}, "sheet_quote_not_in_body: meaning"),
                # A quote from the related-articles list is not body evidence.
                ("notable", {"quote": "Orbit Labs' Lumo hits 10 million US downloads."},
                 "sheet_quote_not_in_body: notable")):
            reply = deepcopy(REPLY)
            reply["sheet"][name].update(change)
            row, _ = self.write(reply)
            self.assert_kept_as_main(row, reply, "without_sheet", error)

    def test_a_coverage_excerpt_is_not_body_evidence_for_the_sheet(self):
        story = item([{"id": "c2", "url": COVERAGE_URL, "publisher": "Other News", "summary": COVERAGE_TEXT}])
        reply = deepcopy(REPLY)
        reply["sheet"]["what"] = {"point": "nhận cuộc gọi", "ref": "coverage1:p001", "speaker": "Other News",
                                  "quote": COVERAGE_TEXT}
        row, _ = self.write(reply, story=story)
        self.assertEqual(row["sheet_error"], "sheet_quote_not_in_body: what")
        self.assertEqual(row["sheet_path"], "without_sheet")

    def test_with_no_cause_in_the_source_an_invented_motive_is_dropped(self):
        reply = deepcopy(REPLY)
        reply["paragraphs"][1]["sentences"] += [MOTIVE, WANTS]
        row, _ = self.write(reply)
        self.assertTrue(row["written"], row)
        self.assertEqual(row["sheet_path"], "sheet")
        self.assertEqual([(d["role"], d["error"]) for d in row["dropped_points"]],
                         [("cause", "cause_not_in_source")] * 2)
        published = " ".join(row["key_points"])
        self.assertNotIn("bước chuẩn bị", published)
        self.assertNotIn("muốn", published)

    def test_a_cause_paragraph_made_only_of_invented_motives_is_rewritten_never_lost(self):
        reply = deepcopy(REPLY)
        reply["paragraphs"][1]["sentences"] = [MOTIVE, WANTS]
        row, runner = self.write(reply)
        self.assertIn("cause_not_in_source", runner.calls[1][2])
        self.assertEqual(row["rewrite"], {"roles": ["cause"], "result": "rewrite_model_failure"})
        # The rewrite failed: deleting both sentences would empty the paragraph, so main's prose stands.
        self.assert_kept_as_main(row, reply, "without_sheet", "paragraph_lost")
        rewrite = {"id": SID, "status": "ready", "conditions": [], "paragraphs": [deepcopy(REPLY["paragraphs"][1])]}
        row, _ = self.write(reply, rewrite=rewrite)
        self.assertEqual(row["sheet_path"], "sheet_after_rewrite")
        self.assertNotIn("bước chuẩn bị", " ".join(row["key_points"]))

    def test_non_causes_are_not_deleted_when_the_source_gives_no_cause(self):
        reply = deepcopy(REPLY)
        reply["paragraphs"][1]["sentences"] += [
            # "Vì vậy" joins two facts.
            sentence("Vì vậy, người dùng tại US có thể trò chuyện với tác tử Lumo bằng giọng nói ngay trên ứng dụng.",
                     "outlet:p008"),
            # The cause word sits inside a quotation.
            sentence("Phóng viên Sam Ortiz viết rằng việc nhìn hình đại diện trò chuyện \"khiến anh thấy kỳ lạ\".",
                     "outlet:p007")]
        row, _ = self.write(reply)
        self.assertTrue(row["written"], row)
        self.assertEqual((row["sheet_path"], row["dropped_points"]), ("sheet", []))
        self.assertIn("Vì vậy", row["key_points"][1])
        self.assertFalse(newsroom._states_cause("Ứng dụng Muốn Gì Có Nấy của Orbit Labs nay có giọng nói."))
        self.assertTrue(newsroom._states_cause("Muốn mở rộng sang kính, Orbit Labs thêm giọng nói."))
        self.assertTrue(newsroom._states_cause("Orbit Labs thêm giọng nói vì người dùng yêu cầu."))

    def test_a_reason_the_cited_paragraph_states_is_kept_and_an_invented_one_is_not(self):
        reason = ("Reyes said the company added voice because people asked to talk with their agents while "
                  "driving to work.")
        page = "\n".join(BODY + [reason] + FURNITURE)
        stated = sentence("Theo Dana Reyes, công ty bổ sung giọng nói vì người dùng muốn trò chuyện với tác tử khi lái "
                          "xe đi làm.", "outlet:p009")
        for why in ({"point": "người dùng muốn nói chuyện khi lái xe", "ref": "outlet:p009", "speaker": "Dana Reyes",
                     "quote": reason},
                    # The writer left the reason out of its sheet; the quoted person's own reason still stands.
                    deepcopy(SHEET["why"])):
            reply = deepcopy(REPLY)
            reply["sheet"]["why"] = why
            reply["paragraphs"][1]["sentences"] = [stated, REPLY["paragraphs"][1]["sentences"][1], MOTIVE]
            row, _ = self.write(reply, page=page)
            self.assertTrue(row["written"], row)
            self.assertIn("lái xe", row["key_points"][1])
            # The roadmap paragraph gives no reason, so the motive hung on it goes when the sheet has no why.
            self.assertEqual([d["error"] for d in row["dropped_points"]],
                             [] if why["quote"] else ["cause_not_in_source"])

    def test_a_context_word_like_amid_does_not_ground_an_invented_cause(self):
        # Codex's round-3 review: with "amid" counted as a stated reason, any cause citing this paragraph passed.
        context = "Amid privacy concerns, Orbit Labs keeps voice recordings on the phone instead of its servers."
        page = "\n".join(BODY + [context] + FURNITURE)
        reply = deepcopy(REPLY)
        reply["paragraphs"][1]["sentences"].append(sentence(
            "Orbit Labs lưu bản ghi giọng nói trên điện thoại vì muốn tăng doanh thu.", "outlet:p009"))
        row, _ = self.write(reply, page=page)
        self.assertEqual(row["sheet_path"], "sheet")
        self.assertEqual([(d["role"], d["error"]) for d in row["dropped_points"]], [("cause", "cause_not_in_source")])
        self.assertNotIn("doanh thu", " ".join(row["key_points"]))

    def test_a_title_with_an_invented_motive_falls_back_to_mains_title_check(self):
        reply = deepcopy(REPLY)
        reply["title_vi"] = sentence("Orbit Labs thêm giọng nói cho Lumo, bước chuẩn bị đưa tác tử lên kính thông minh",
                                     "outlet:p008")
        row, _ = self.write(reply)
        self.assert_kept_as_main(row, reply, "without_sheet", "title_rejected")

    def dropped_teaching(self):
        # The 06/11 Nemotron story: the sentence carrying the headline's proof failed a check and the paragraph
        # survived on its secondary details, so the published story lost the point.
        reply = deepcopy(REPLY)
        reply["paragraphs"][2]["sentences"] = [
            sentence("Phóng viên Sam Ortiz thử tính năng nhằm kiểm tra tốc độ phản hồi của tác tử Lumo.", "outlet:p007"),
            sentence("Phóng viên Sam Ortiz dùng ứng dụng iOS và thấy hình đại diện cử động theo lời nói.", "outlet:p006")]
        return reply

    def test_a_paragraph_that_drops_its_sheet_point_is_caught_and_rewritten(self):
        row, runner = self.write(self.dropped_teaching())
        self.assertEqual(row["rewrite"], {"roles": ["examples"], "result": "rewrite_model_failure"})
        desk, rows, instruction = runner.calls[1]
        self.assertEqual((desk, instruction), ("rewrite-writer", WRITER_REWRITE_PROMPT))
        self.assertEqual(rows[0]["rewrite"]["sheet"], SHEET)
        self.assertEqual([(item["role"], item["error"]) for item in rows[0]["rewrite"]["rejected"]],
                         [("examples", "unsupported_purpose"), ("examples", "sheet_point_dropped: notable")])
        self.assert_kept_as_main(row, self.dropped_teaching(), "without_sheet", "sheet_point_dropped")

        rewrite = {"id": SID, "status": "ready", "paragraphs": [{"role": "examples", "sentences": [EXAMPLE]}]}
        row, _ = self.write(self.dropped_teaching(), rewrite=rewrite)
        self.assertTrue(row["written"], row)
        self.assertEqual((row["sheet_path"], row["rewrite"]), ("sheet_after_rewrite",
                                                               {"roles": ["examples"], "result": "written"}))
        self.assertIn("tạm dừng", row["key_points"][2])

    def test_a_reply_that_never_cites_a_sheet_point_is_caught(self):
        reply = deepcopy(REPLY)
        reply["paragraphs"][0]["sentences"] = [sentence(
            "Phóng viên Sam Ortiz cho biết hình đại diện của tác tử Lumo cử động khớp với lời nói trong ứng dụng iOS.",
            "outlet:p006")]
        row, runner = self.write(reply)
        self.assertEqual(runner.calls[1][1][0]["rewrite"]["rejected"],
                         [{"role": "development", "text": SHEET["what"]["point"], "error": "sheet_point_dropped: what"}])
        self.assertEqual(row["sheet_error"], "sheet_point_dropped")

    def test_a_point_cited_by_ref_but_not_said_is_caught(self):
        # The 06/11 Cloudflare story: the paragraph announced a coalition and described the protocol; the prose
        # cited it for the protocol only, so the announcement, the news, was gone.
        announcement = ("We are also announcing the Lumo Partner coalition today, and the protocol signs every "
                        "agent request with a delegation token that sites can verify.")
        page = "\n".join(BODY + [announcement] + FURNITURE)
        reply = deepcopy(REPLY)
        reply["sheet"]["what"] = {"point": "lập liên minh Lumo Partner", "ref": "outlet:p009", "speaker": "Orbit Labs",
                                  "quote": "We are also announcing the Lumo Partner coalition today"}
        protocol_only = sentence("Giao thức của Lumo ký mỗi yêu cầu của tác tử bằng một mã ủy quyền mà trang web có "
                                 "thể kiểm tra.", "outlet:p009")
        reply["paragraphs"][0]["sentences"] = [LEAD, protocol_only]
        row, runner = self.write(reply, page=page)
        self.assertEqual(runner.calls[1][1][0]["rewrite"]["roles"], ["development"])
        self.assertEqual(row["sheet_error"], "sheet_point_dropped")
        said = sentence("Bên cạnh đó, liên minh Lumo Partner được lập, và giao thức ký mỗi yêu cầu của tác tử bằng "
                        "một mã ủy quyền.", "outlet:p009")
        reply["paragraphs"][0]["sentences"] = [LEAD, said]
        row, _ = self.write(reply, page=page)
        self.assertEqual(row["sheet_path"], "sheet")

    def test_merged_cause_and_examples_carry_the_notable_point_in_cause(self):
        reply = deepcopy(REPLY)
        reply["paragraphs"][1]["sentences"].append(EXAMPLE)
        del reply["paragraphs"][2]
        row, _ = self.write(reply)
        self.assertTrue(row["written"], row)
        self.assertEqual(row["sheet_path"], "sheet")
        self.assertEqual(row["reason"].split(",")[0], "prose written: development/cause/significance")


class PartialSourceTests(unittest.TestCase):
    """partial_source says the article body the writer read was cut, nothing else."""

    def setUp(self):
        self.tools = load_registry()

    def write(self, page, reply, story):
        runner = RecordingRunner({"writer": {SID: reply}})
        intake, reporter, editor = desks()
        articles = FixtureArticles({"articles": {URL: {"text": page, "reason": None}}})
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            output, _ = _writer([story], intake, reporter, editor, articles, self.tools, DISCOVERY, runner, NOW)
        return output[SID], runner

    def test_citing_a_coverage_excerpt_beside_a_complete_body_is_not_partial(self):
        story = item([{"id": "c2", "url": COVERAGE_URL, "publisher": "Other News", "summary": COVERAGE_TEXT}])
        reply = deepcopy(REPLY)
        reply["paragraphs"][0]["sentences"].append(sentence(
            "Một trang tin khác cũng cho biết tác tử của Orbit Labs nay có thể nhận cuộc gọi dưới dạng hình đại diện "
            "động.",
            "coverage1:p001"))
        row, runner = self.write(PAGE, reply, story)
        self.assertTrue(row["written"], row)
        self.assertIn("coverage1", [source["id"] for source in runner.calls[0][1][0]["sources"]])
        self.assertTrue(any("cuộc gọi" in text for text in row["key_points"]))
        self.assertTrue(row["writer_sources"][0]["body_complete"])
        self.assertEqual(row["summary_limitations"], [])

    def test_a_body_cut_to_fit_the_writer_is_partial_even_beside_coverage(self):
        filler = [f"Background paragraph {index} describes the history of voice assistants in some detail, "
                  f"covering earlier products, interface conventions and the people who designed them over many "
                  f"years of development work across several companies and research groups." for index in range(60)]
        page = "\n".join(BODY + filler + FURNITURE)
        story = item([{"id": "c2", "url": COVERAGE_URL, "publisher": "Other News", "summary": COVERAGE_TEXT}])
        with patch.object(newsroom, "writer_length", return_value={"least": 50, "aim": 150, "most": 600}):
            row, runner = self.write(page, deepcopy(REPLY), story)
        self.assertTrue(row["written"], row)
        self.assertFalse(row["writer_sources"][0]["body_complete"])
        self.assertEqual(row["summary_limitations"], ["partial_source"])


class ArticleBodyTests(unittest.TestCase):
    def test_furniture_after_the_body_is_cut(self):
        self.assertEqual(article_body(PAGE), "\n".join(BODY))
        nvidia = "\n".join([BODY[5], "Hear more by following the livestream series.", "Categories:", "AI", "Tags:",
                            "Nemotron", "Share This", "Facebook"])
        self.assertEqual(article_body(nvidia), "\n".join([BODY[5], "Hear more by following the livestream series."]))

    def test_an_inline_link_inside_the_article_drops_only_its_own_line(self):
        later = ("The company also said the avatars can be switched off in settings, and that recordings of voice "
                 "conversations are kept for thirty days unless the user deletes them from the history page.")
        page = "\n".join([BODY[5], "Read more: Orbit Labs launches Lumo", later, *FURNITURE])
        self.assertEqual(article_body(page), "\n".join([BODY[5], later]))

    def test_a_short_closing_paragraph_after_a_related_label_stays(self):
        closing = "Orbit Labs said more languages will follow next month."
        page = "\n".join([*BODY, "Related", "Orbit Labs launches Lumo", closing, *FURNITURE])
        self.assertEqual(article_body(page), "\n".join([*BODY, "Orbit Labs launches Lumo", closing]))

    def test_a_real_related_articles_list_is_cut(self):
        # The last lines of a stored IEEE Spectrum writer input (cycle 20261104T163154Z): the article's closing
        # paragraphs, then the page's own and outside related-article lists.
        closing = [
            "Hopefully, the combination of specialized AI models and formal verification tools will make patching "
            "vulnerabilities nearly as automatable as finding them.",
            "One thing’s for sure—PHP2Shell is just the beginning. “This won’t be the last one for sure,” Jana says. "
            "“It’s just who finds it. Hopefully, the white-hat hackers find it first, like this one.”"]
        own_site = ["From Your Site Articles", "Your AI Agent Is Now a Target for Email Phishing ›",
                    "With $1 Cyberattacks on the Rise, Durable Defenses Pay Off ›",
                    "What Anthropic’s Mythos Means for the Future of Cybersecurity ›"]
        related = [
            "Related Articles Around the Web",
            "The PHP Foundation — The PHP Foundation — Supporting, Advancing, and Developing the PHP Language ›",
            "cybersecurityinternetartificial intelligence", "Dina Genkina",
            "Dina Genkina is an associate editor at IEEE Spectrum focused on computing and hardware. She holds a PhD "
            "in atomic physics and lives in Brooklyn.",
            "How a Kenyan Startup Is Rethinking AI for Small Businesses", "03 Nov 2026", "5 min read",
            "Consumer Appetite for Personal AI Goes Mainstream", "29 Oct 2026", "5 min read",
            "What Would a U.S. Telecommunications Act 2.0 Look Like?", "02 Nov 2026", "5 min read",
            "Crooks Are Learning to Love AI Hallucinations",
            "With $1 Cyberattacks on the Rise, Durable Defenses Pay Off",
            "What Anthropic’s Mythos Means for the Future of Cybersecurity"]
        body = article_body("\n".join(closing + own_site + related)).splitlines()
        self.assertEqual(body[:2], closing)
        self.assertFalse(set(related) & set(body), body)
        # Story 3's related list stays out too.
        self.assertFalse(any("10 million" in line for line in article_body(PAGE).splitlines()))

    def test_a_sentence_that_opens_with_read_more_is_body(self):
        sentence_line = "Read more about the voice research in the company's paper, which it published in May."
        page = "\n".join([*BODY, sentence_line, *FURNITURE])
        self.assertEqual(article_body(page), "\n".join([*BODY, sentence_line]))

    def test_a_menu_above_the_article_does_not_end_it(self):
        page = "\n".join(["Most Popular", "Some other story", *BODY, *FURNITURE])
        self.assertEqual(article_body(page), "\n".join(["Some other story", *BODY]))


class ReporterBodyTests(unittest.TestCase):
    """The stored source the editor and checker read is the body, long enough to hold what the writer reads."""

    def run_reporter(self, page):
        def fake_desk(desk, payload, *args, **kwargs):
            return {row["id"]: {"id": row["id"], "selected_url": URL, "same_event": True, "reason": "readable",
                                "provider": "agy", "boat": "gemini"} for row in payload}, []

        story = item()
        with patch.object(newsroom, "_agent_desk", side_effect=fake_desk):
            output, _ = _reporter([story], {SID: {"pass": True}}, FixtureArticles({"articles": {URL: {"text": page}}}),
                                  load_registry(), DISCOVERY, None, [])
        return output[SID]

    def test_the_stored_source_has_no_related_list_so_its_figure_fails_the_number_check(self):
        row = self.run_reporter(PAGE)
        self.assertEqual(row["source_text"], "\n".join(BODY))
        # The checker's number check reads this text; a figure from the related list is not in it.
        self.assertTrue(number_error("Lumo reached 10 million US downloads.", row["source_text"]))
        self.assertFalse(number_error("Lumo's voice mode is rolling out in the US.", row["source_text"]))

    def test_a_late_paragraph_of_a_long_body_is_stored(self):
        filler = [f"Paragraph {index} of the article explains one more part of the rollout in plain words for "
                  f"readers who want the full detail." for index in range(40)]
        ending = "Orbit Labs said it will publish a privacy report on voice recordings in December."
        row = self.run_reporter("\n".join(BODY + filler + [ending] + FURNITURE))
        self.assertGreater(len("\n".join(BODY + filler)), 3200)
        self.assertIn(ending, row["source_text"])


if __name__ == "__main__":
    unittest.main()
