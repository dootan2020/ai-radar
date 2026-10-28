"""Source editor pass for the local writer desk, exercised without model calls."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phong_bao.newsroom import SOURCE_EDITOR_ENV, SOURCE_EDITOR_PROMPT, _writer
from phong_bao.runner import CLIRunner, RunnerError
from test_phong_bao_writer import (DISCOVERY, EXAMPLE, NOW, PROSE, SID, RecordingRunner,
                                   articles, desks, sentence, story)
from phong_bao.registry import load_registry


def edited_final():
    final = deepcopy(PROSE)
    final["paragraphs"][0]["sentences"][0] = sentence(
        "HelioLab giới thiệu CanvasKit, khung mô phỏng AI dựng xưởng ảo để tác tử hoạt động bên trong.",
        "outlet:p001")
    return final


def editor_reply(final=None, issues=None):
    return {"id": SID, "issues": [] if issues is None else issues,
            "final": edited_final() if final is None else final}


class SourceEditorTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()

    def write(self, editor=None, *, runner=None, text=None, raw_dir=None):
        intake, reporter, classification, _ = desks()
        runner = runner or RecordingRunner({"writer": {SID: deepcopy(PROSE)},
                                            "editor-source": {SID: editor_reply() if editor is None else editor}})
        with patch.dict(os.environ, {SOURCE_EDITOR_ENV: "1"}), \
                patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            output, usage = _writer([story()], intake, reporter, classification,
                                    articles() if text is None else articles(text), self.tools,
                                    DISCOVERY, runner, NOW, raw_dir=raw_dir)
        return output[SID], usage, runner

    def test_edited_final_is_published_with_full_source_packet_and_audit(self):
        issue = {"kind": "weak_example", "draft_text": "", "explanation_vi": "Cần ví dụ cụ thể.",
                 "evidence_refs": ["outlet:p002"]}
        with tempfile.TemporaryDirectory() as raw_dir:
            row, usage, runner = self.write(editor_reply(issues=[issue]), raw_dir=raw_dir)
            raw = list(Path(raw_dir).glob("editor-source-*.json"))
            self.assertEqual(len(raw), 1)
            self.assertEqual(json.loads(raw[0].read_text(encoding="utf-8"))["stories"][0]["issues"], [issue])
        self.assertTrue(row["written"], row)
        self.assertEqual(row["key_points"][0], " ".join(
            item["text"] for item in edited_final()["paragraphs"][0]["sentences"]))
        self.assertEqual((row["editor_provider"], row["editor_boat"]), ("codex", "codex"))
        self.assertEqual([call[0] for call in runner.calls], ["writer", "editor-source"])
        packet = runner.calls[1][1][0]
        self.assertEqual(set(packet), {"id", "sources", "missing_primary", "linked_primary", "draft"})
        self.assertEqual(packet["draft"], PROSE["paragraphs"])
        self.assertNotIn("conditions", packet)
        self.assertEqual([p["text"] for p in packet["sources"][0]["paragraphs"]], EXAMPLE["paragraphs"])
        self.assertEqual(runner.calls[1][2], SOURCE_EDITOR_PROMPT)
        self.assertTrue(any(item.get("desk") == "editor-source" for item in usage))

    def test_insufficient_evidence_defers_to_api(self):
        final = {"id": SID, "status": "insufficient_evidence", "conditions": [],
                 "title_vi": {"text": "", "evidence_refs": []}, "paragraphs": [],
                 "used_source_ids": [], "limitations": ["insufficient_evidence"]}
        row, _, _ = self.write(editor_reply(final))
        self.assertFalse(row["written"])
        self.assertFalse(row["invalid_response"])
        self.assertEqual(row["key_points"], [])
        self.assertEqual(row["reason"], "editor_insufficient_evidence")

    def test_runner_error_or_timeout_defers(self):
        for message in ("editor failed", "editor timed out"):
            with self.subTest(message=message):
                class Failing(RecordingRunner):
                    def run(self, desk, rows, provider, instruction):
                        if desk == "editor-source":
                            self.calls.append((desk, deepcopy(rows), instruction))
                            raise RunnerError(message)
                        return super().run(desk, rows, provider, instruction)

                runner = Failing({"writer": {SID: deepcopy(PROSE)}})
                row, _, _ = self.write(runner=runner)
                self.assertFalse(row["written"])
                self.assertFalse(row["invalid_response"])
                self.assertEqual(row["reason"], "editor_model_failure")
                self.assertEqual([call[0] for call in runner.calls], ["writer", "editor-source"])

    def test_malformed_json_defers(self):
        class Malformed(RecordingRunner):
            def run(self, desk, rows, provider, instruction):
                if desk == "editor-source":
                    return CLIRunner().run(desk, rows, provider, instruction)
                return super().run(desk, rows, provider, instruction)

        completed = type("Completed", (), {"returncode": 0, "stdout": "not-json", "stderr": ""})()
        with patch("phong_bao.runner.subprocess.run", return_value=completed), \
                patch("phong_bao.runner.shutil.which", side_effect=lambda name: name):
            row, _, _ = self.write(runner=Malformed({"writer": {SID: deepcopy(PROSE)}}))
        self.assertFalse(row["written"])
        self.assertEqual(row["reason"], "editor_model_failure")

    def test_rejected_edited_sentence_does_not_publish_shortened_prose(self):
        final = edited_final()
        final["paragraphs"][2]["sentences"].append(
            sentence("HelioLab thử CanvasKit trên 500 GPU.", "outlet:p002"))
        row, _, _ = self.write(editor_reply(final))
        self.assertFalse(row["written"])
        self.assertEqual(row["reason"], "editor_validation_dropped")
        self.assertEqual(row["key_points"], [])
        self.assertEqual(row["dropped_points"][0]["error"], "invented_number: 500")

    def test_packet_over_limit_defers_without_truncating_or_editing(self):
        body = "\n".join([*EXAMPLE["paragraphs"], "Extra evidence. " * 2500])
        runner = RecordingRunner({"writer": {SID: deepcopy(PROSE)}})
        row, _, runner = self.write(runner=runner, text=body)
        self.assertFalse(row["written"])
        self.assertFalse(row["invalid_response"])
        self.assertEqual(row["reason"], "editor_input_limit")
        self.assertEqual([call[0] for call in runner.calls], ["writer"])

    def test_one_editor_pass_even_when_final_is_invalid(self):
        final = edited_final()
        final["paragraphs"] = final["paragraphs"][:2]
        row, _, runner = self.write(editor_reply(final))
        self.assertFalse(row["written"])
        self.assertEqual(row["reason"], "editor_invalid")
        self.assertEqual([call[0] for call in runner.calls], ["writer", "editor-source"])

    def test_unset_switch_keeps_writer_output_and_skips_editor(self):
        intake, reporter, classification, _ = desks()
        runner = RecordingRunner({"writer": {SID: deepcopy(PROSE)}})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SOURCE_EDITOR_ENV, None)
            output, usage = _writer([story()], intake, reporter, classification,
                                    articles(), self.tools, DISCOVERY, runner, NOW)
        row = output[SID]
        self.assertTrue(row["written"])
        self.assertEqual([call[0] for call in runner.calls], ["writer"])
        self.assertNotIn("editor_provider", row)
        self.assertNotIn("editor_boat", row)
        self.assertFalse(any(item.get("desk") == "editor-source" for item in usage))


if __name__ == "__main__":
    unittest.main()
