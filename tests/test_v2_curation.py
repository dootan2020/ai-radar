"""Tests for GitHub repositories and Hugging Face models curation and scoring."""

from datetime import datetime, timezone
import json
import unittest

from radar.curation import (
    CATEGORIES,
    CATEGORY_PATTERNS,
    classify_areas,
    classify_category,
    curate_repos,
    extract_install_command,
    score_github_repo,
    score_hf_model,
)

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


class CurationClassificationTests(unittest.TestCase):
    def test_classify_all_eight_categories(self):
        cases = [
            ("video", "heygen-com/hyperframes", "Write HTML. Render video. Built for agents.", ["video"]),
            ("video", "remotion-dev/remotion", "Make videos programmatically with React", ["animation"]),
            ("agent-code", "stablyai/orca", "ADE for working with a fleet of parallel agents", ["claude-code"]),
            ("agent-code", "OpenHands/OpenHands", "AI-Driven Development agent", ["coding-agent"]),
            ("browser-mcp", "browser-use/browser-use", "Agents that use the browser.", ["browser-automation"]),
            ("browser-mcp", "modelcontextprotocol/servers", "Model Context Protocol servers", ["mcp"]),
            ("quant", "microsoft/qlib", "AI-oriented quantitative investment platform", ["trading", "finance"]),
            ("quant", "TauricResearch/TradingAgents", "Multi-Agents LLM Financial Trading Framework", ["quant"]),
            ("local", "ollama/ollama", "Get up and running with large language models locally", ["local-ai"]),
            ("local", "ggml-org/llama.cpp", "LLM inference in C/C++", ["llm-inference"]),
            ("fine-tune", "unslothai/unsloth", "Finetune Llama 3.3, Mistral, Phi & Gemma 2x faster", ["fine-tuning"]),
            ("fine-tune", "hiyouga/LlamaFactory", "Unified Efficient Fine-Tuning of 100+ LLMs & VLMs", ["lora", "sft"]),
            ("rag", "docling-project/docling", "Get your documents ready for gen AI", ["rag", "document-parsing"]),
            ("rag", "infiniflow/ragflow", "An open-source RAG engine based on deep document understanding", ["rag"]),
            ("voice", "resemble-ai/chatterbox", "SoTA open-source TTS with voice cloning", ["tts", "speech"]),
            ("voice", "SWivid/F5-TTS", "A Fairytaler that Fakes Fluent and Faithful Speech with Flow Matching", ["voice-cloning"]),
        ]
        for expected_cat, name, desc, topics in cases:
            with self.subTest(name=name, expected=expected_cat):
                cat = classify_category(name, description=desc, topics=topics)
                self.assertEqual(cat, expected_cat)

    def test_classify_hf_pipeline_tags(self):
        cases = [
            ("video", "text-to-video"),
            ("video", "image-to-video"),
            ("video", "text-to-image"),
            ("video", "image-to-image"),
            ("voice", "text-to-speech"),
            ("voice", "automatic-speech-recognition"),
            ("voice", "audio-to-audio"),
            ("rag", "document-question-answering"),
            ("rag", "visual-question-answering"),
            ("rag", "sentence-similarity"),
            ("rag", "feature-extraction"),
        ]
        for expected_cat, ptag in cases:
            with self.subTest(ptag=ptag):
                cat = classify_category("model-name", pipeline_tag=ptag)
                self.assertEqual(cat, expected_cat)

    def test_classify_readme_text_inspection(self):
        cat = classify_category(
            "pbakaus/impeccable",
            description="The design language that makes your AI harness better at design.",
            readme_text="# Impeccable\n\nDesign guidance for AI coding agents. 1 skill, 24 commands."
        )
        self.assertEqual(cat, "agent-code")

    def test_classify_unmatched_returns_none(self):
        cat = classify_category("Effect-TS/effect", description="Build production-ready applications in TypeScript")
        self.assertIsNone(cat)

    def test_classify_areas_multiple_matches(self):
        # A tool doing browser automation and coding agents should match both browser-mcp and agent-code
        areas = classify_areas(
            "browser-use/browser-use",
            description="Autonomous coding agent that uses the browser for web automation",
            topics=["browser-automation", "coding-agent"]
        )
        self.assertIn("browser-mcp", areas)
        self.assertIn("agent-code", areas)
        self.assertGreaterEqual(len(areas), 2)

    def test_classify_areas_empty_returns_empty_list(self):
        areas = classify_areas("Effect-TS/effect", description="Build production-ready applications in TypeScript")
        self.assertEqual(areas, [])


class CurationInstallCommandTests(unittest.TestCase):
    def test_package_binary_install_patterns(self):
        cases = [
            ("pip install docling", "pip install docling", "binary"),
            ("pip install -U f5-tts", "pip install -U f5-tts", "binary"),
            ("uv add browser-use", "uv add browser-use", "binary"),
            ("uv pip install unsloth", "uv pip install unsloth", "binary"),
            ("npx hyperframes", "npx hyperframes", "binary"),
            ("npx create-video@latest", "npx create-video@latest", "binary"),
            ("npm i -g @caveman-ai/cli", "npm i -g @caveman-ai/cli", "binary"),
            ("brew install --cask orca", "brew install --cask orca", "binary"),
            ("winget install ollama", "winget install ollama", "binary"),
            ("docker run -p 8080:8080 sentry", "docker run -p 8080:8080 sentry", "binary"),
            ("docker compose up -d", "docker compose up -d", "binary"),
            ("curl -fsSL https://ollama.com/install.sh | sh", "curl -fsSL https://ollama.com/install.sh | sh", "binary"),
        ]
        for text, expected_cmd, expected_type in cases:
            with self.subTest(text=text):
                cmd, itype = extract_install_command(f"```bash\n{text}\n```")
                self.assertEqual(cmd, expected_cmd)
                self.assertEqual(itype, expected_type)

    def test_prefix_handling(self):
        cmd, itype = extract_install_command("> pip install f5-tts")
        self.assertEqual(cmd, "pip install f5-tts")
        self.assertEqual(itype, "binary")

        cmd, itype = extract_install_command("$ brew install orca")
        self.assertEqual(cmd, "brew install orca")
        self.assertEqual(itype, "binary")

    def test_inline_code_detection(self):
        cmd, itype = extract_install_command("To install, run `pip install docling` in your terminal.")
        self.assertEqual(cmd, "pip install docling")
        self.assertEqual(itype, "binary")

    def test_source_install_fallback(self):
        cases = [
            ("pip install -r requirements.txt", "pip install -r requirements.txt", "source"),
            ("pip install .", "pip install .", "source"),
            ("pip install -e .", "pip install -e .", "source"),
        ]
        for text, expected_cmd, expected_type in cases:
            with self.subTest(text=text):
                cmd, itype = extract_install_command(f"Install:\n{text}")
                self.assertEqual(cmd, expected_cmd)
                self.assertEqual(itype, expected_type)

    def test_empty_or_no_install(self):
        self.assertEqual(extract_install_command(""), (None, None))
        self.assertEqual(extract_install_command(None), (None, None))
        self.assertEqual(extract_install_command("Just read the paper."), (None, None))


class GitHubScoringTests(unittest.TestCase):
    def test_dung_ngay_binary_install_and_recent_release(self):
        repo_info = {"repo": "test/pkg", "stars": 1000, "stars_today": 120}
        readme = "```bash\npip install mypkg\n```\nSee our demo at https://huggingface.co/spaces/test/demo"
        release = {"tag_name": "v1.0.0", "published_at": "2026-10-01T00:00:00Z", "assets": []}
        res = score_github_repo(repo_info, readme_text=readme, license_name="MIT", release_info=release, now=NOW)
        self.assertEqual(res["label"], "dung-ngay")
        self.assertGreaterEqual(res["d_score"], 35)
        self.assertIn("Dùng ngay", res["why"])
        self.assertIn("pip install mypkg", res["why"])
        self.assertIn("MIT", res["why"])

    def test_dung_ngay_release_assets_and_demo(self):
        repo_info = {"repo": "test/binary-tool", "stars": 500, "homepage": "https://mytool.ai"}
        readme = "Official site: https://mytool.ai"
        release = {
            "tag_name": "v0.5.0",
            "published_at": "2026-09-15T00:00:00Z",
            "assets": [{"name": "tool-linux-amd64.tar.gz"}]
        }
        contents = ["CMakeLists.txt", "examples"]
        res = score_github_repo(
            repo_info,
            readme_text=readme,
            license_name="Apache-2.0",
            release_info=release,
            contents=contents,
            now=NOW
        )
        self.assertEqual(res["label"], "dung-ngay")
        self.assertEqual(res["signals"]["d2"], 10)
        self.assertEqual(res["signals"]["d3"], 15)
        self.assertEqual(res["signals"]["d4"], 10)
        self.assertIn("có bản dựng sẵn", res["why"])

    def test_xao_nau_permissive_with_examples_and_quickstart(self):
        repo_info = {"repo": "test/framework", "stars": 2000, "stars_today": 50}
        readme = "### Quickstart\n\npip install -e .\n\n### Examples\nCheck examples folder."
        contents = ["examples", "pyproject.toml", "src"]
        res = score_github_repo(
            repo_info,
            readme_text=readme,
            license_name="MIT",
            contents=contents,
            pushed_at="2026-10-01T00:00:00Z",
            now=NOW
        )
        self.assertEqual(res["label"], "xao-nau")
        self.assertGreaterEqual(res["x_score"], 25)
        self.assertLess(res["d_score"], 35)
        self.assertIn("Xào nấu được", res["why"])
        self.assertIn("có thư mục ví dụ", res["why"])

    def test_nghien_cuu_deepseek_v3_pattern(self):
        repo_info = {
            "repo": "deepseek-ai/DeepSeek-V3",
            "description": "PyTorch implementation of DeepSeek-V3",
            "stars": 50000
        }
        readme = "Inference with DeepSeek-Infer Demo (example only).\n\npip install -r requirements.txt\n\nBibTeX: @article{deepseek}"
        res = score_github_repo(repo_info, readme_text=readme, license_name=None, contents=[], now=NOW)
        self.assertEqual(res["label"], "nghien-cuu")
        self.assertLess(res["d_score"], 35)
        self.assertLess(res["x_score"], 25)
        self.assertTrue(res["signals"]["has_paper"])
        self.assertTrue(res["signals"]["non_commercial"])
        self.assertEqual(res["signals"]["n2_penalty"], -15)
        self.assertIn("Nghiên cứu", res["why"])
        self.assertIn("⚠ hạn chế thương mại", res["why"])

    def test_copyleft_flag_and_custom_license(self):
        repo_info = {"repo": "test/gpl-repo"}
        res_gpl = score_github_repo(repo_info, license_name="GPL-3.0", now=NOW)
        self.assertEqual(res_gpl["license_flag"], "giấy phép buộc mở mã khi phát hành lại")

        res_none = score_github_repo(repo_info, license_name="NOASSERTION", now=NOW)
        self.assertEqual(res_none["license_flag"], "giấy phép riêng, đọc trước khi dùng thương mại")

    def test_archived_or_stale_repo_is_nghien_cuu(self):
        repo_archived = {"repo": "test/archived", "archived": True}
        readme = "pip install tool\n"
        release = {"tag_name": "v1.0.0", "published_at": "2026-10-01T00:00:00Z", "assets": [1]}
        res = score_github_repo(repo_archived, readme_text=readme, license_name="MIT", release_info=release, now=NOW)
        self.assertEqual(res["label"], "nghien-cuu")

        repo_stale = {"repo": "test/stale"}
        res_stale = score_github_repo(
            repo_stale,
            readme_text=readme,
            license_name="MIT",
            release_info=release,
            pushed_at="2024-01-01T00:00:00Z",
            now=NOW
        )
        self.assertEqual(res_stale["label"], "nghien-cuu")


class HuggingFaceScoringTests(unittest.TestCase):
    def test_hf_dung_ngay_gguf(self):
        model_info = {"id": "author/model-GGUF", "likes": 200, "downloads": 5000}
        details = {"gated": False, "library_name": "gguf", "pipeline_tag": "text-generation", "cardData": {"license": "apache-2.0"}}
        res = score_hf_model(model_info, model_details=details, now=NOW)
        self.assertEqual(res["label"], "dung-ngay")
        self.assertIn("định dạng GGUF chạy máy", res["why"])
        self.assertIn("apache-2.0", res["why"])

    def test_hf_dung_ngay_quantized_derivatives(self):
        model_info = {"id": "author/base-model", "likes": 1500}
        details = {
            "gated": False,
            "library_name": "transformers",
            "childrenModelCount": {"quantized": 12, "finetune": 5},
            "cardData": {"license": "mit"}
        }
        res = score_hf_model(model_info, model_details=details, now=NOW)
        self.assertEqual(res["label"], "dung-ngay")
        self.assertIn("có 12 bản lượng tử", res["why"])

    def test_hf_dung_ngay_api_provider(self):
        model_info = {"id": "author/api-model", "likes": 800}
        details = {
            "gated": False,
            "library_name": "transformers",
            "inferenceProviderMapping": {"hf-inference": {}},
            "cardData": {"license": "apache-2.0"}
        }
        res = score_hf_model(model_info, model_details=details, now=NOW)
        self.assertEqual(res["label"], "dung-ngay")
        self.assertIn("gọi được qua API", res["why"])

    def test_hf_xao_nau_transformers_with_spaces(self):
        model_info = {"id": "author/library-model", "likes": 300}
        details = {
            "gated": False,
            "library_name": "transformers",
            "spaces": ["space1", "space2", "space3"],
            "childrenModelCount": {"quantized": 0, "finetune": 2},
            "cardData": {"license": "apache-2.0"}
        }
        res = score_hf_model(model_info, model_details=details, now=NOW)
        self.assertEqual(res["label"], "xao-nau")
        self.assertIn("Xào nấu được", res["why"])
        self.assertIn("3 bản chạy thử trên Spaces", res["why"])

    def test_hf_nghien_cuu_gated_or_missing_library(self):
        model_info = {"id": "author/gated-model", "likes": 50}
        details = {"gated": True, "library_name": "transformers"}
        res_gated = score_hf_model(model_info, model_details=details, now=NOW)
        self.assertEqual(res_gated["label"], "nghien-cuu")

        model_raw = {"id": "nvidia/Kumo-Tabular", "likes": 10}
        details_raw = {"gated": False, "library_name": None, "pipeline_tag": None}
        res_raw = score_hf_model(model_raw, model_details=details_raw, now=NOW)
        self.assertEqual(res_raw["label"], "nghien-cuu")
        self.assertIn("chưa có bản chạy chuẩn", res_raw["why"])


class CurateReposIntegrationTests(unittest.TestCase):
    def test_curate_repos_empty(self):
        self.assertEqual(curate_repos([], [], fetcher=None, now=NOW), [])
        self.assertEqual(curate_repos(None, None, fetcher=None, now=NOW), [])

    def test_curate_repos_enrichment_and_schema(self):
        gh_items = [
            {
                "repo": "owner/fast-agent",
                "url": "https://github.com/owner/fast-agent",
                "description": "Coding agent framework with local CLI",
                "stars": 1200,
                "stars_today": 350
            }
        ]
        hf_items = [
            {
                "id": "owner/speech-model",
                "url": "https://huggingface.co/owner/speech-model",
                "type": "model",
                "pipeline_tag": "text-to-speech",
                "likes": 500,
                "downloads": 10000
            }
        ]

        def mock_fetcher(url, source_id=None):
            if "raw.githubusercontent.com/owner/fast-agent/HEAD/README.md" in url:
                return "```bash\npip install fast-agent\n```\nOfficial tools."
            if "raw.githubusercontent.com/owner/fast-agent/HEAD/LICENSE" in url:
                return "MIT License"
            if url.endswith("/releases/latest"):
                return json.dumps({
                    "tag_name": "v1.0.0",
                    "published_at": "2026-10-01T00:00:00Z",
                    "assets": []
                })
            if "api.github.com/repos/owner/fast-agent" in url:
                return json.dumps({
                    "id": 1,
                    "stargazers_count": 1200,
                    "description": "Coding agent framework with local CLI",
                    "license": {"spdx_id": "MIT"},
                    "pushed_at": "2026-10-01T00:00:00Z",
                    "archived": False,
                    "fork": False
                })
            if "huggingface.co/api/models/owner/speech-model" in url:
                return json.dumps({
                    "id": "owner/speech-model",
                    "gated": False,
                    "library_name": "transformers",
                    "pipeline_tag": "text-to-speech",
                    "inferenceProviderMapping": {"hf": {}},
                    "cardData": {"license": "apache-2.0"}
                })
            return None

        results = curate_repos(gh_items, hf_items, fetcher=mock_fetcher, now=NOW)
        self.assertEqual(len(results), 2)

        required_keys = {
            "id", "full_name", "url", "description", "label",
            "category", "why", "license", "license_flag",
            "stars", "stars_gained_7d", "signals", "source"
        }
        for item in results:
            self.assertTrue(required_keys.issubset(set(item.keys())))
            self.assertIn(item["label"], {"dung-ngay", "xao-nau", "nghien-cuu"})
            self.assertIn(item["source"], {"github-trending", "hf"})

        gh_result = next(r for r in results if r["source"] == "github-trending")
        self.assertEqual(gh_result["label"], "dung-ngay")
        self.assertEqual(gh_result["category"], "agent-code")
        self.assertIn("areas", gh_result)
        self.assertIn("agent-code", gh_result["areas"])
        self.assertEqual(gh_result["license"], "MIT")

        hf_result = next(r for r in results if r["source"] == "hf")
        self.assertEqual(hf_result["label"], "dung-ngay")
        self.assertEqual(hf_result["category"], "voice")
        self.assertIn("areas", hf_result)
        self.assertIn("voice", hf_result["areas"])
        self.assertEqual(hf_result["license"], "apache-2.0")

    def test_curate_repos_network_failure_fallback(self):
        gh_items = [
            {
                "repo": "owner/offline-repo",
                "url": "https://github.com/owner/offline-repo",
                "description": "Some AI agent tool",
                "stars": 100
            }
        ]

        def failing_fetcher(url, source_id=None):
            raise ConnectionError("Network unreachable")

        results = curate_repos(gh_items, [], fetcher=failing_fetcher, now=NOW)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["id"], "owner/offline-repo")
        self.assertIn("api_fallback_reason", item["signals"])
        self.assertFalse(item["signals"]["api_enriched"])
        self.assertIsNone(item["label"])
        self.assertIsNone(item["why"])
        self.assertIsNone(item["license"])
        self.assertEqual(item["license_flag"], "chưa đo được giấy phép")


if __name__ == "__main__":
    unittest.main()
