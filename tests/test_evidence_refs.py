"""Paragraph IDs ("outlet:p010") never reach a reader: not from a new draft, not from a story already published."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phong_bao.newsroom import _chief
from radar import site_payload, story_pages
from radar.evidence_refs import has_evidence_ref, strip_evidence_refs, unbracketed_evidence_ref
from radar.newsroom_decisions import desk_summary
from tests.test_newsroom_decisions import READER_FILES, decisions_file, desk_row, payload_with, scored
from tests import test_phong_bao_writer as writer_tests
from tests.test_phong_bao_writer import NOW, PROSE, SID, RecordingRunner, desks, sentence, story


class StripTests(unittest.TestCase):
    def test_the_published_forms_are_removed_with_their_brackets(self):
        # Copied from the four stories live on 2026-11-06.
        cases = {
            "trên ứng dụng hoặc trang web của Amazon (outlet:p016). Ông": "trên ứng dụng hoặc trang web của Amazon. Ông",
            "cho đến gợi ý quà tặng (outlet:p008, outlet:p016).": "cho đến gợi ý quà tặng.",
            "của Microsoft tại Amsterdam [outlet:p008, outlet:p016]. Dự án": "của Microsoft tại Amsterdam. Dự án",
            "biên lợi nhuận [outlet:p005].": "biên lợi nhuận.",
            "nguồn chính (primary:p012; coverage2:p003) và": "nguồn chính và",
            "(outlet:p015, theo TechCrunch) cho biết.": "(theo TechCrunch) cho biết.",
            "outlet:publisher cho biết": "cho biết",
        }
        for text, expected in cases.items():
            self.assertEqual(strip_evidence_refs(text), expected, text)
            self.assertFalse(has_evidence_ref(strip_evidence_refs(text)), text)

    def test_text_without_an_id_is_returned_unchanged(self):
        for text in ("Lúc 10:30, giá  tăng .", "Xem https://example.com/a:p1 và C:/data/x:p2", "GPT-5 đạt 90%."):
            self.assertIs(strip_evidence_refs(text), text)
            self.assertFalse(has_evidence_ref(text))

    def test_an_id_used_as_a_word_is_told_apart_from_a_citation(self):
        self.assertTrue(unbracketed_evidence_ref("Theo outlet:p010, doanh thu tăng."))
        self.assertFalse(unbracketed_evidence_ref("Doanh thu tăng (outlet:p010)."))


def _with_markers(reply):
    """The writer's reply with every sentence and the title ending in a citation, as measured on 06/11."""
    reply = deepcopy(reply)
    reply["title_vi"]["text"] += " (outlet:p001)"
    for paragraph in reply["paragraphs"]:
        for item in paragraph["sentences"]:
            refs = item["evidence_refs"]
            marker = f" ({refs[0]})" if len(refs) == 1 else f" [{', '.join(refs)}]"
            item["text"] = item["text"].rstrip(".") + marker + "."
    return reply


class WriterGateTests(unittest.TestCase):
    setUp = writer_tests.WriterDeskTests.setUp
    write = writer_tests.WriterDeskTests.write

    def test_citations_in_the_text_never_reach_the_scorer_or_the_reader(self):
        clean, _, _ = self.write(deepcopy(PROSE))
        runner = RecordingRunner({"writer": {SID: _with_markers(PROSE)}})
        row, _, runner = self.write(runner=runner)
        self.assertTrue(row["written"], row)
        self.assertEqual(row["key_points"], clean["key_points"])
        self.assertEqual(row["editorial_headline_vi"], clean["editorial_headline_vi"])
        self.assertEqual(row["dropped_points"], [])
        for desk, rows, _ in runner.calls:
            if desk in {"scorer", "rescorer"}:
                for packet in rows:
                    self.assertFalse(has_evidence_ref(json.dumps(
                        [packet["headline_vi"], packet["paragraphs_vi"]], ensure_ascii=False)), packet)
        intake, reporter, editor, checker = desks()
        decision = _chief([story()], intake, reporter, editor, checker, NOW, {SID: row})[0]
        self.assertFalse(has_evidence_ref(json.dumps([decision["key_points"], decision["editorial_headline_vi"]],
                                                     ensure_ascii=False)))

    def test_a_citation_does_not_carry_an_invented_number_past_the_checks(self):
        reply = deepcopy(PROSE)
        reply["paragraphs"][2]["sentences"].append(
            sentence("HelioLab cho biết CanvasKit đã chạy trên 500 GPU trong thử nghiệm (outlet:p002).", "outlet:p002"))
        row, _, _ = self.write(reply)
        self.assertTrue(row["written"], row)
        self.assertNotIn("500", " ".join(row["key_points"]))
        self.assertEqual([(d["role"], d["error"]) for d in row["dropped_points"]],
                         [("examples", "invented_number: 500")])

    def test_an_id_used_as_a_word_drops_its_sentence(self):
        reply = deepcopy(PROSE)
        reply["paragraphs"][2]["sentences"].append(
            sentence("Theo outlet:p002, Python điều khiển hành động của tác tử trong thí nghiệm.", "outlet:p002"))
        row, _, _ = self.write(reply)
        self.assertTrue(row["written"], row)
        self.assertEqual([(d["role"], d["error"]) for d in row["dropped_points"]],
                         [("examples", "evidence_ref_in_text")])
        self.assertFalse(has_evidence_ref(" ".join(row["key_points"])))


def _published_with_markers(sid):
    row = desk_row(sid)
    row["key_points"] = [point.rstrip(".") + " (outlet:p00{0}).".format(index + 1)
                         for index, point in enumerate(row["key_points"])]
    row["key_points"][1] = row["key_points"][1].replace(" (outlet:p002).", " [outlet:p002, outlet:p003].")
    return row


class PublishedStoryTests(unittest.TestCase):
    def test_a_passed_story_with_citations_is_shown_clean_in_every_reader_file_and_page(self):
        passed = scored(_published_with_markers("passed"))
        written = desk_summary(passed)
        self.assertEqual(written["key_points"], [strip_evidence_refs(p) for p in passed["key_points"]])
        self.assertEqual(written["key_points"][1], "Đoạn 2 của tin passed, viết bằng tiếng Việt.")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data" / "radar.json"
            choice = decisions_file(directory, [passed])
            with patch.dict("os.environ", {"RADAR_NEWSROOM_DECISIONS": str(choice)}):
                site_payload.write_site_snapshot(payload_with(["passed"]), target)
            for name in READER_FILES:
                text = (target.parent / name).read_text(encoding="utf-8")
                self.assertIn('"passed"', text, name)
                self.assertFalse(has_evidence_ref(text), name)
            site = Path(directory) / "site"
            template = payload_with(["passed"])["stories"][0]
            self.assertEqual(story_pages.render_site({"passed": template}, site,
                                                     decisions={"decisions": [passed]}), 1)
            page = (site / "tin" / "passed" / "index.html").read_text(encoding="utf-8")
            self.assertIn(written["key_points"][0], page)
            self.assertNotIn("outlet:p0", page)

    def test_cleaning_never_lets_unscored_text_through(self):
        # Text edited after its verdict stays hidden, whether the edit removed the citations or added a sentence.
        stripped = scored(_published_with_markers("stripped"))
        stripped["key_points"] = [strip_evidence_refs(p) for p in stripped["key_points"]]
        invented = scored(_published_with_markers("invented"))
        invented["key_points"][2] += " Công ty đã thu về 900 triệu USD (outlet:p003)."
        self.assertIsNone(desk_summary(stripped))
        self.assertIsNone(desk_summary(invented))
        only_ids = scored(desk_row("only-ids", key_points=["(outlet:p001)", "Đoạn hai.", "Đoạn ba."]))
        self.assertIsNone(desk_summary(only_ids))


if __name__ == "__main__":
    unittest.main()
