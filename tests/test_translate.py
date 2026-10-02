"""Offline checks for the optional headline translation step (radar/translate.py).

No model runs here: the translator is a stand-in function, so these tests cover the glossary, the
guards that refuse a bad translation, the cache, and the promise that a failed or slow model leaves
the page with its original titles and a recorded reason.
"""

from pathlib import Path
import json
import tempfile
import threading
import time
import unittest
from unittest import mock

from radar import translate as tr


def snapshot():
    """A small v2-shaped payload with every kind of string the step touches or must leave alone."""
    stories = [
        dict(id="s1", title="How Much Memory Does Your Agent Actually Need?", kind="other", groups=["press"],
             source_count=1, published_at="2026-10-02T10:00:00Z",
             coverage=[dict(source="a", title="How Much Memory Does Your Agent Actually Need?")]),
        dict(id="s2", title="Introducing Claude Sonnet 5", kind="product", groups=["lab"], source_count=2,
             published_at="2026-10-02T09:00:00Z", coverage=[dict(source="b", title="Introducing Claude Sonnet 5")]),
        dict(id="s3", title="NeurIPS 2026 - Sydney", kind="event", groups=["event"], source_count=1,
             published_at=None, coverage=[]),
        dict(id="s4", title="Cloudflare/clef-flash", kind="model", groups=["repository"], source_count=1,
             published_at=None, coverage=[]),
    ]
    return dict(stories=stories, sections=dict(hot=["s1"], today=["s1", "s2"], upcoming=["s3"], models=["s4"]),
                repos=[dict(id="o/r", description="Harness design for long-running agents")],
                live=[dict(title="OpenAI DevDay 2026 Keynote (FULL)"), dict(title="Live demo of the new voice tools")])


class FakeModel:
    """Stands in for NLLB: returns canned Vietnamese and records every segment it was asked for."""

    CANNED = {
        "How Much Memory Does Your Agent Actually Need?": "Nhân viên của bạn thực sự cần bộ nhớ bao nhiêu?",
        "Claude Sonnet 5": "Claude Sonnet 5",
        "Harness design for long-running agents": "Thiết kế vòng xoắn cho các đại lý chạy lâu dài",
        "OpenAI DevDay 2026 Keynote (FULL)": "Bài phát biểu chính OpenAI DevDay 2026 (FULL)",
    }

    def __init__(self):
        self.calls = []

    def factory(self):
        def translate(batch):
            self.calls.extend(batch)
            return [self.CANNED.get(s, "bản dịch " + s) for s in batch]
        return translate


class GlossaryTests(unittest.TestCase):
    def test_agent_stays_agent(self):
        for wrong in ("Nhân viên của bạn cần gì?", "Các đại lý của bạn cần gì?", "Đặc vụ của bạn cần gì?"):
            out = tr.apply_glossary("What does your agent need?", wrong)
            self.assertRegex(out, r"^(Các )?[Aa]gent của bạn", out)
        self.assertEqual(tr.apply_glossary("Make your AI agent think", "Làm cho nhân viên trí tuệ nhân tạo của bạn nghĩ"),
                         "Làm cho agent AI của bạn nghĩ")

    def test_rule_fires_only_when_the_source_uses_the_term(self):
        # A layoffs headline that never says "agent" keeps its employees.
        self.assertEqual(tr.apply_glossary("Startup lays off 200 employees", "Startup sa thải 200 nhân viên"),
                         "Startup sa thải 200 nhân viên")

    def test_harness_frontier_finetuning_benchmark(self):
        self.assertIn("khung chạy", tr.apply_glossary("Harness design for long apps", "Thiết kế vòng xoắn cho ứng dụng"))
        self.assertEqual(tr.apply_glossary("our next era of frontier intelligence",
                                           "kỷ nguyên tiếp theo của tình báo biên giới"),
                         "kỷ nguyên tiếp theo của trí tuệ tiên phong")
        self.assertIn("tinh chỉnh", tr.apply_glossary("Fine-tuning results", "Kết quả điều chỉnh tinh tế"))
        self.assertIn("bài đo chuẩn", tr.apply_glossary("A new benchmark", "Một điểm chuẩn mới"))

    def test_open_source_is_not_doubled(self):
        self.assertEqual(tr.apply_glossary("An open-source tool", "Một công cụ mã nguồn mở"), "Một công cụ mã nguồn mở")
        self.assertEqual(tr.apply_glossary("An open-source tool", "Một công cụ nguồn mở"), "Một công cụ mã nguồn mở")

    def test_training_means_huan_luyen_only_for_models(self):
        self.assertEqual(tr.apply_glossary("Training world models", "Đào tạo mô hình thế giới"), "Huấn luyện mô hình thế giới")
        self.assertEqual(tr.apply_glossary("Training for nurses", "Đào tạo cho y tá"), "Đào tạo cho y tá")

    def test_introducing_becomes_ra_mat(self):
        cache = {"Contextual Retrieval": "Khám phá ngữ cảnh"}
        self.assertEqual(tr.compose("Introducing Contextual Retrieval", cache), ("Ra mắt khám phá ngữ cảnh", None))
        # A bare name after "Introducing" never reaches the model.
        self.assertEqual(tr.split_source("Introducing GPT-6.1 Sol"), ("Ra mắt ", [], "GPT-6.1 Sol"))
        self.assertEqual(tr.compose("Introducing GPT-6.1 Sol", {}), ("Ra mắt GPT-6.1 Sol", None))

    def test_name_case_and_newsletter_tag_are_restored(self):
        self.assertEqual(tr.apply_glossary("xAI raises $6B", "XAI tăng 6B"), "xAI tăng 6B")
        prefix, segments, _ = tr.split_source("[AINews] Grok 3 now available")
        self.assertEqual((prefix, segments), ("[AINews] ", ["Grok 3 now available"]))

    def test_names_around_the_sentence_are_kept_as_written(self):
        self.assertEqual(tr.split_source("Why LLMs Might Hit a Wall - Noam Brown"),
                         ("", ["Why LLMs Might Hit a Wall"], " - Noam Brown"))
        self.assertEqual(tr.split_source("Memorizon: Training World Models Beyond Their Context Window"),
                         ("Memorizon: ", ["Training World Models Beyond Their Context Window"], ""))
        self.assertEqual(tr.split_source("Introducing Quine: An AI research system for biology"),
                         ("Ra mắt Quine: ", ["An AI research system for biology"], ""))
        self.assertEqual(tr.compose("Quoting Anthropic Frontier Red Team", {}), ("Trích lời Anthropic Frontier Red Team", None))
        cache = {"Why LLMs Might Hit a Wall": "Tại sao LLM có thể chạm vào tường"}
        self.assertEqual(tr.compose("Why LLMs Might Hit a Wall - Noam Brown", cache),
                         ("Tại sao LLM có thể chạm vào tường - Noam Brown", None))

    def test_abbreviations_do_not_split_sentences(self):
        self.assertEqual(tr.split_source("Mistral CEO says U.S. AI safety debate masks rivals")[1],
                         ["Mistral CEO says U.S. AI safety debate masks rivals"])
        self.assertEqual(tr.split_source("Affected by layoffs? Don't miss this deal")[1],
                         ["Affected by layoffs?", "Don't miss this deal"])


class GuardTests(unittest.TestCase):
    def test_names_ids_events_and_vietnamese_are_not_translated(self):
        for text in ("Cloudflare/clef-flash", "GPT-6", "Qwen3.8-27B", "Bản tin AI hôm nay", "利用 AI 大模型 generate videos"):
            self.assertFalse(tr.needs_translation(text), text)
        self.assertTrue(tr.needs_translation("AI Makes Me Sad"))

    def test_bad_outputs_are_refused(self):
        self.assertEqual(tr.rejection("Long enough source sentence here", "kỹ năng năng năng năng suất"), "repetition")
        self.assertEqual(tr.rejection("A fully open-source coder model", "Một mã hóa mã hóa mã nguồn mở"), "repetition")
        self.assertIsNone(tr.rejection("Slowly but surely we get there", "Từ từ nhưng chắc chắn chúng ta tới đó"))
        self.assertTrue(tr.rejection("Affected by layoffs? Don't miss this $75 deal for your pass",
                                     "Đừng bỏ lỡ").startswith("too short"))
        self.assertTrue(tr.rejection("Codestral 25.08 for enterprise", "Codestral 25 cho doanh nghiệp").startswith("number lost"))
        self.assertTrue(tr.rejection("Efficient MoE Training", "Đào tạo hiệu quả").startswith("name lost"))
        self.assertTrue(tr.rejection("Wire It, Run It, Deploy It", "Wire It, Run It, Deploy It").startswith("untranslated"))
        self.assertTrue(tr.rejection("Ship it for others", "Phát hành 3 cho người khác").startswith("number added"))
        self.assertIsNone(tr.rejection("The latest news from September 2026", "Tin mới nhất tháng 9 năm 2026"))
        self.assertIsNone(tr.rejection("Mistral CEO speaks", "Giám đốc điều hành Mistral phát biểu"))


class TranslatePayloadTests(unittest.TestCase):
    def test_translated_fields_sit_next_to_the_originals(self):
        payload, model = snapshot(), FakeModel()
        stats, alive = tr.translate_payload(payload, {}, factory=model.factory, budget=10)
        self.assertFalse(alive)
        s1, s2, s3, s4 = payload["stories"]
        self.assertEqual(s1["title"], "How Much Memory Does Your Agent Actually Need?")
        self.assertEqual(s1["title_vi"], "Agent của bạn thực sự cần bộ nhớ bao nhiêu?")
        self.assertEqual(s1["coverage"][0]["title_vi"], s1["title_vi"])
        self.assertEqual(s2["title_vi"], "Ra mắt Claude Sonnet 5")
        self.assertNotIn("title_vi", s3)  # event names are proper names
        self.assertNotIn("title_vi", s4)  # model ids are names
        self.assertEqual(payload["repos"][0]["description_vi"], "Thiết kế khung chạy cho các agent chạy lâu dài")
        self.assertNotIn("title_vi", payload["live"][0])  # names plus one English word: kept as written
        self.assertEqual(payload["live"][1]["title_vi"], "Bản dịch Live demo of the new voice tools")
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(payload["translation"]["license"], "CC-BY-NC-4.0")
        self.assertEqual(payload["translation"]["model"], "facebook/nllb-200-distilled-600M")
        self.assertNotIn("NeurIPS 2026 - Sydney", model.calls)

    def test_failed_model_keeps_original_titles_and_records_why(self):
        payload = snapshot()
        payload["stories"][0]["title_vi"] = "stale translation from an older build"

        def missing():
            raise ModuleNotFoundError("No module named 'torch'")

        stats, _ = tr.translate_payload(payload, {}, factory=missing, budget=5)
        self.assertEqual(stats["status"], "failed")
        self.assertIn("ModuleNotFoundError", stats["error"])
        self.assertIn("chưa cài thư viện dịch", stats["error_vi"])
        for story in payload["stories"]:
            self.assertNotIn("title_vi", story)
        self.assertNotIn("description_vi", payload["repos"][0])
        self.assertEqual(payload["stories"][0]["title"], "How Much Memory Does Your Agent Actually Need?")

    def test_slow_model_hits_the_budget_and_the_page_still_builds(self):
        payload, release = snapshot(), threading.Event()

        def hangs():
            release.wait(5)  # a download or load that never finishes in time
            raise RuntimeError("released")

        started = time.monotonic()
        stats, alive = tr.translate_payload(payload, {}, factory=hangs, budget=0.3)
        release.set()
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(alive)
        self.assertIn("Time budget", stats["error"])
        self.assertIn("hết thời gian", stats["error_vi"])
        self.assertEqual(stats["status"], "failed")
        self.assertGreater(stats["pending"], 0)
        self.assertNotIn("title_vi", payload["stories"][0])

    def test_error_midway_keeps_what_was_finished(self):
        payload, calls = snapshot(), []

        def factory():
            def translate(batch):
                calls.append(batch)
                if len(calls) > 1:
                    raise RuntimeError("out of memory")
                return ["bản dịch " + s for s in batch]
            return translate

        stats, _ = tr.translate_payload(payload, {}, factory=factory, budget=10, batch_size=1)
        self.assertEqual(stats["status"], "partial")
        self.assertEqual(stats["translated"], 1)
        self.assertIn("out of memory", stats["error"])

    def test_cached_strings_are_never_translated_again(self):
        payload, model = snapshot(), FakeModel()
        cache = {}
        tr.translate_payload(payload, cache, factory=model.factory, budget=10)
        first = list(model.calls)
        self.assertTrue(first)
        model.calls.clear()
        loads = []
        stats, _ = tr.translate_payload(snapshot(), cache, factory=lambda: loads.append(1) or model.factory(), budget=10)
        self.assertEqual(model.calls, [])
        self.assertEqual(loads, [], "the model is not even loaded when everything is cached")
        self.assertEqual(stats["new_segments"], 0)
        # One new headline: only it goes to the model.
        payload = snapshot()
        payload["stories"].append(dict(id="s5", title="A brand new headline today", kind="other", groups=["press"],
                                       source_count=1, coverage=[]))
        tr.translate_payload(payload, cache, factory=model.factory, budget=10)
        self.assertEqual(model.calls, ["A brand new headline today"])

    def test_cache_round_trip_and_model_change_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "translations-vi.json"
            tr.save_cache(path, {"Hello world": "Xin chào thế giới"})
            self.assertEqual(tr.load_cache(path), {"Hello world": "Xin chào thế giới"})
            data = json.loads(path.read_text(encoding="utf-8"))
            data["revision"] = "another-revision"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(tr.load_cache(path), {})
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(tr.load_cache(path), {})
            self.assertEqual(tr.load_cache(Path(tmp) / "missing.json"), {})


class CommandLineTests(unittest.TestCase):
    def test_cli_without_model_libraries_writes_a_valid_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, cache = Path(tmp) / "radar.json", Path(tmp) / "cache.json"
            src.write_text(json.dumps(snapshot()), encoding="utf-8")

            def missing():
                raise ImportError("transformers is not installed")

            with mock.patch.object(tr, "nllb_factory", missing), mock.patch.dict("os.environ", {"GITHUB_OUTPUT": ""}):
                self.assertEqual(tr.main(["--input", str(src), "--cache", str(cache), "--budget", "5"]), 0)
            out = json.loads(src.read_text(encoding="utf-8"))
            self.assertEqual(out["translation"]["status"], "failed")
            self.assertEqual(out["stories"][0]["title"], "How Much Memory Does Your Agent Actually Need?")
            self.assertNotIn("title_vi", out["stories"][0])
            self.assertFalse(cache.exists())

    def test_cli_with_a_model_fills_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, cache, gh = Path(tmp) / "radar.json", Path(tmp) / "cache.json", Path(tmp) / "out.txt"
            src.write_text(json.dumps(snapshot()), encoding="utf-8")
            with mock.patch.object(tr, "nllb_factory", FakeModel().factory), \
                    mock.patch.dict("os.environ", {"GITHUB_OUTPUT": str(gh)}):
                tr.main(["--input", str(src), "--cache", str(cache), "--budget", "5"])
            self.assertIn("How Much Memory Does Your Agent Actually Need?", tr.load_cache(cache))
            self.assertIn("cache_written=true", gh.read_text(encoding="utf-8"))
            self.assertIn("model_ready=true", gh.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
