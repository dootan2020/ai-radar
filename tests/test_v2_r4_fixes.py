"""Tests verifying Round 4 review fixes (Blockers B1-B5, Should-fix S1-S9, Nits)."""

import unittest
from datetime import datetime, timezone
from urllib.request import Request
from urllib.parse import urlparse

from radar.catalog import RSS
from radar.curation import (
    classify_category,
    curate_repos,
    extract_install_command,
    score_github_repo,
    score_hf_model,
)
from radar.items import relevant
from radar.transport import SafeRedirectHandler

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


class TestRound4Blockers(unittest.TestCase):
    """Tests for Blockers B1 through B5."""

    def test_b1_workflow_has_github_token_and_no_dead_token_in_curation(self):
        """B1: update.yml must pass GITHUB_TOKEN to build.py, no dead token in score_hf_model."""
        import pathlib
        import re

        workflow_path = pathlib.Path(".github/workflows/update.yml")
        content = workflow_path.read_text(encoding="utf-8")
        # Ensure build step has GITHUB_TOKEN
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", content)
        self.assertIn("run: python build.py", content)

        # Ensure no dead token variable in score_hf_model in radar/curation.py
        import inspect
        source = inspect.getsource(score_hf_model)
        self.assertNotIn("GITHUB_TOKEN", source)

    def test_b2_fallback_does_not_invent_spdx_license(self):
        """B2: Fallback branch sets license = None and flag 'chưa đo được license'."""
        gh_items = [
            {
                "repo": "getsentry/sentry",
                "url": "https://github.com/getsentry/sentry",
                "description": "Developer-first error tracking",
                "stars": 40000,
            }
        ]

        def fallback_fetcher(url, source_id=None):
            # README is fetched via raw.githubusercontent.com
            if "raw.githubusercontent.com" in url:
                return "# Sentry\nError tracking and monitoring.\n"
            # Releases atom
            if "releases.atom" in url:
                return (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<feed xmlns="http://www.w3.org/2005/Atom">\n'
                    '  <entry><title>24.1.0</title><updated>2026-09-20T00:00:00Z</updated></entry>\n'
                    '</feed>'
                )
            # GitHub API calls fail/are unavailable in fallback
            return None

        meta = {}
        curated = curate_repos(gh_items, [], fetcher=fallback_fetcher, now=NOW, meta=meta)
        self.assertEqual(len(curated), 1)
        item = curated[0]
        # Must NOT invent Apache-2.0 or GPL-3.0
        self.assertIsNone(item["license"])
        self.assertEqual(item["license_flag"], "chưa đo được license")
        self.assertNotIn("Apache-2.0", item.get("why") or "")
        self.assertFalse(item["signals"]["api_enriched"])

    def test_b3_unmeasured_signals_remain_none(self):
        """B3: Missing measurements must be None, not fabricated penalties or labels."""
        # 1. Without contents: n2_penalty, d5, has_docker must be None
        res_no_contents = score_github_repo(
            {"repo": "test/no-contents"},
            readme_text="pip install -r requirements.txt\n",
            license_name="MIT",
            contents=None,
            now=NOW,
        )
        self.assertIsNone(res_no_contents["signals"]["n2_penalty"])
        self.assertIsNone(res_no_contents["signals"]["has_manifest"])
        self.assertIsNone(res_no_contents["signals"]["has_docker"])
        self.assertIsNone(res_no_contents["signals"]["d5"])

        # 2. Without README: label and why must be None
        res_no_readme = score_github_repo(
            {"repo": "test/no-readme"},
            readme_text="",
            license_name="MIT",
            contents=["pyproject.toml"],
            now=NOW,
        )
        self.assertIsNone(res_no_readme["label"])
        self.assertIsNone(res_no_readme["why"])
        self.assertFalse(res_no_readme["signals"]["readme_measured"])

        # 3. HF model without details: label and why must be None
        hf_no_details = score_hf_model(
            {"id": "test/unmeasured-model", "type": "model"},
            model_details=None,
            now=NOW,
        )
        self.assertIsNone(hf_no_details["label"])
        self.assertIsNone(hf_no_details["why"])
        self.assertFalse(hf_no_details["signals"]["model_details_measured"])
        self.assertIsNone(hf_no_details["signals"]["spaces_count"])

    def test_b4_hf_gated_normalization(self):
        """B4: gated='auto' keeps normal label + flag; gated='manual' requires provider/quantized."""
        # Case 1: gated='auto' with quantized >= 1 (e.g. LTX-2.5 pattern) -> dung-ngay + gate flag
        details_ltx = {
            "gated": "auto",
            "library_name": "diffusers",
            "childrenModelCount": {"quantized": 30, "finetune": 5},
            "cardData": {"license": "apache-2.0"},
            "spaces": ["space1", "space2"],
        }
        res_ltx = score_hf_model({"id": "Lightricks/LTX-2.5"}, model_details=details_ltx, now=NOW)
        self.assertEqual(res_ltx["label"], "dung-ngay")
        self.assertEqual(res_ltx["signals"]["gated"], "auto")
        self.assertIn("cần đồng ý điều khoản trên HF", res_ltx["why"])

        # Case 2: gated='auto' with inferenceProviderMapping (e.g. FLUX.1-dev pattern) -> dung-ngay + gate flag
        details_flux = {
            "gated": "auto",
            "library_name": "diffusers",
            "inferenceProviderMapping": {"status": "available"},
            "cardData": {"license": "other"},
            "spaces": ["s1"],
        }
        res_flux = score_hf_model({"id": "black-forest-labs/FLUX.1-dev"}, model_details=details_flux, now=NOW)
        self.assertEqual(res_flux["label"], "dung-ngay")
        self.assertIn("cần đồng ý điều khoản trên HF", res_flux["why"])

        # Case 3: gated='manual' without provider/quantized -> nghien-cuu
        details_manual_raw = {
            "gated": "manual",
            "library_name": "transformers",
            "cardData": {"license": "apache-2.0"},
            "childrenModelCount": {"quantized": 0, "finetune": 0},
        }
        res_manual_raw = score_hf_model({"id": "test/manual-model"}, model_details=details_manual_raw, now=NOW)
        self.assertEqual(res_manual_raw["label"], "nghien-cuu")
        self.assertIn("cần xét duyệt điều khoản trên HF", res_manual_raw["why"])

        # Case 4: gated=False -> no gate flag
        details_open = {
            "gated": False,
            "library_name": "transformers",
            "inferenceProviderMapping": {"status": "available"},
            "cardData": {"license": "mit"},
        }
        res_open = score_hf_model({"id": "test/open-model"}, model_details=details_open, now=NOW)
        self.assertEqual(res_open["label"], "dung-ngay")
        self.assertNotIn("điều khoản", res_open["why"])

    def test_b5_hf_spaces_capped_at_100(self):
        """B5: When spaces length == 100, record spaces_capped: True and '100+ demo Space'."""
        details_capped = {
            "gated": False,
            "library_name": "transformers",
            "spaces": [f"space_{i}" for i in range(100)],
            "cardData": {"license": "apache-2.0"},
        }
        res_capped = score_hf_model({"id": "test/popular-model"}, model_details=details_capped, now=NOW)
        self.assertTrue(res_capped["signals"]["spaces_capped"])
        self.assertEqual(res_capped["signals"]["spaces_count"], 100)
        self.assertIn("100+ demo Space", res_capped["why"])

        details_uncapped = {
            "gated": False,
            "library_name": "transformers",
            "spaces": ["s1", "s2", "s3"],
            "cardData": {"license": "apache-2.0"},
        }
        res_uncapped = score_hf_model({"id": "test/smaller-model"}, model_details=details_uncapped, now=NOW)
        self.assertFalse(res_uncapped["signals"]["spaces_capped"])
        self.assertEqual(res_uncapped["signals"]["spaces_count"], 3)
        self.assertIn("3 demo Spaces", res_uncapped["why"])


class TestRound4ShouldFix(unittest.TestCase):
    """Tests for Should-fix S1 through S9."""

    def test_s1_sentry_monorepo_fsl_license_and_no_star_elevation(self):
        """S1: Monorepo without install command gets nghien-cuu, FSL flag, stars don't elevate."""
        repo_info = {
            "repo": "getsentry/sentry",
            "stars": 40000,
            "stars_this_week": 500,
            "description": "Developer-first error tracking and performance monitoring",
        }
        readme = "# Sentry\nError tracking system.\nLicensed under Functional Source License (FSL-1.1-Apache-2.0).\n"
        res = score_github_repo(repo_info, readme_text=readme, license_name="NOASSERTION", contents=[], now=NOW)
        # Without install command, d_score is low -> nghien-cuu
        self.assertEqual(res["label"], "nghien-cuu")
        self.assertIn("license FSL", res["license_flag"])

    def test_s2_install_command_targets_repo_or_package_only(self):
        """S2: D1 only awarded when command targets repo or package name; runner commands ignored."""
        # Unrelated package installation
        cmd_foreign, itype_foreign = extract_install_command("pip install torch", repo="owner/my-tool")
        self.assertIsNone(cmd_foreign)
        self.assertIsNone(itype_foreign)

        # Related package installation
        cmd_matched, itype_matched = extract_install_command("pip install my-tool", repo="owner/my-tool")
        self.assertEqual(cmd_matched, "pip install my-tool")
        self.assertEqual(itype_matched, "binary")

        # Dev runner like npx skills add ignored
        cmd_runner, itype_runner = extract_install_command("npx skills add anthropics/prompt", repo="owner/skills")
        self.assertIsNone(cmd_runner)
        self.assertIsNone(itype_runner)

    def test_s3_fallback_d3_assets_not_parsed_from_release_note(self):
        """S3: Fallback D3 does not parse words in release note; assets is None."""
        release_info = {
            "tag_name": "v1.0.0",
            "published_at": "2026-10-01T00:00:00Z",
            "assets": None,
            "estimated": True,
        }
        res = score_github_repo(
            {"repo": "owner/repo"},
            readme_text="pip install repo\n",
            license_name="MIT",
            release_info=release_info,
            now=NOW,
        )
        self.assertIsNone(res["signals"]["d3"])
        self.assertFalse(res["signals"]["has_binary_assets"])

    def test_s4_hf_xao_nau_requirements(self):
        """S4: HF xao-nau requires library AND permissive license AND (spaces>=3 or finetune>=1)."""
        # Valid xao-nau: transformers + apache-2.0 + finetune=2
        details_valid = {
            "library_name": "transformers",
            "cardData": {"license": "apache-2.0"},
            "childrenModelCount": {"finetune": 2, "quantized": 0},
            "spaces": [],
        }
        res_valid = score_hf_model({"id": "test/model"}, model_details=details_valid, now=NOW)
        self.assertEqual(res_valid["label"], "xao-nau")

        # Invalid: missing library
        details_no_lib = {
            "library_name": None,
            "cardData": {"license": "apache-2.0"},
            "childrenModelCount": {"finetune": 2},
        }
        res_no_lib = score_hf_model({"id": "test/model"}, model_details=details_no_lib, now=NOW)
        self.assertEqual(res_no_lib["label"], "nghien-cuu")

        # Invalid: non-permissive license (nc)
        details_nc = {
            "library_name": "transformers",
            "cardData": {"license": "cc-by-nc-4.0"},
            "childrenModelCount": {"finetune": 2},
        }
        res_nc = score_hf_model({"id": "test/model"}, model_details=details_nc, now=NOW)
        self.assertEqual(res_nc["label"], "nghien-cuu")

        # Invalid: neither spaces >= 3 nor finetune >= 1
        details_no_derivatives = {
            "library_name": "transformers",
            "cardData": {"license": "apache-2.0"},
            "childrenModelCount": {"finetune": 0, "quantized": 0},
            "spaces": ["s1", "s2"],
        }
        res_no_deriv = score_hf_model({"id": "test/model"}, model_details=details_no_derivatives, now=NOW)
        self.assertEqual(res_no_deriv["label"], "nghien-cuu")

    def test_s5_transport_hostname_and_redirect_security(self):
        """S5: Exact api.github.com check and Authorization stripped on non-GitHub redirect."""
        # Test exact hostname check
        self.assertNotEqual(urlparse("https://api.github.com.attacker.com/repos").hostname, "api.github.com")
        self.assertEqual(urlparse("https://api.github.com/repos").hostname, "api.github.com")

        # Test SafeRedirectHandler strips Authorization header
        handler = SafeRedirectHandler()
        req = Request("https://api.github.com/repos/owner/repo/releases/assets/123", headers={"Authorization": "token secret123"})
        req.unredirected_hdrs["Authorization"] = "token secret123"

        # Redirect to external host (e.g. AWS S3 download)
        new_req = handler.redirect_request(req, None, 302, "Found", {}, "https://github-production-release-asset.s3.amazonaws.com/123")
        self.assertNotIn("Authorization", new_req.headers)
        self.assertNotIn("Authorization", getattr(new_req, "unredirected_hdrs", {}))

    def test_s6_d5_dockerfile_root_only(self):
        """S6: D5 only checks root files, does not award D5 for 'docker run' in README."""
        res_readme_only = score_github_repo(
            {"repo": "owner/repo"},
            readme_text="```bash\ndocker run -p 8080:8080 myimage\n```",
            license_name="MIT",
            contents=["src", "README.md"],
            now=NOW,
        )
        self.assertIsNone(res_readme_only["signals"]["d5"])
        self.assertFalse(res_readme_only["signals"]["has_docker"])

        res_with_dockerfile = score_github_repo(
            {"repo": "owner/repo"},
            readme_text="Some tool\n",
            license_name="MIT",
            contents=["Dockerfile", "src", "README.md"],
            now=NOW,
        )
        self.assertEqual(res_with_dockerfile["signals"]["d5"], 5)
        self.assertTrue(res_with_dockerfile["signals"]["has_docker"])

    def test_s7_repos_meta_records_dropped_items_and_fallback_reasons(self):
        """S7: curate_repos records dropped items and fallback reasons in meta dict."""
        gh_items = [
            {"repo": "test/normal", "url": "https://github.com/test/normal"},
            {"repo": "test/dropped-missing-readme", "url": "https://github.com/test/dropped-missing-readme"},
        ]

        def custom_fetcher(url, source_id=None):
            if "test/normal/HEAD/README.md" in url:
                return "pip install test-normal\n"
            return None

        meta = {}
        curated = curate_repos(gh_items, [], fetcher=custom_fetcher, now=NOW, meta=meta)
        self.assertEqual(meta["fallback_count"], 2)
        self.assertIn("thiếu GITHUB_TOKEN", meta["fallback_reasons"])
        self.assertEqual(meta["dropped_count"], 1)
        self.assertEqual(meta["dropped_items"][0]["id"], "test/dropped-missing-readme")

    def test_s8_hf_score_and_unified_sorting(self):
        """S8: HF models have fair score scale (0-100) and sort with GitHub repos."""
        details_strong = {
            "inferenceProviderMapping": {"status": "available"},
            "library_name": "transformers",
            "cardData": {"license": "apache-2.0"},
            "spaces": ["s1", "s2", "s3"],
            "childrenModelCount": {"quantized": 5, "finetune": 2},
        }
        res_strong = score_hf_model({"id": "top/model"}, model_details=details_strong, now=NOW)
        self.assertGreater(res_strong["signals"]["hf_score"], 50)

        # Test curate_repos sorting integrates HF models properly
        hf_models = [
            {
                "id": "org/top-hf-model",
                "type": "model",
                "url": "https://huggingface.co/org/top-hf-model",
                "likes": 500,
            }
        ]
        gh_repos = [
            {
                "repo": "org/weak-gh-repo",
                "url": "https://github.com/org/weak-gh-repo",
                "stars": 10,
            }
        ]

        def test_fetcher(url, source_id=None):
            if "top-hf-model" in url:
                import json
                return json.dumps(details_strong)
            if "weak-gh-repo/HEAD/README.md" in url:
                return "Some research notes.\n"
            return None

        curated = curate_repos(gh_repos, hf_models, fetcher=test_fetcher, now=NOW)
        # The top HF model (dung-ngay) should rank above the weak GH repo (nghien-cuu)
        self.assertEqual(curated[0]["id"], "org/top-hf-model")
        self.assertEqual(curated[0]["label"], "dung-ngay")

    def test_s9_vnexpress_regression_and_ai_terms(self):
        """S9: Regression for VnExpress feed URL and Vietnamese AI term filtering."""
        # 1. Regression text: 'Mong ngồi bên em trong im lặng…' with summary '…cùng ai đó chia sẻ…'
        title = "Mong ngồi bên em trong im lặng…"
        summary = "…cùng ai đó chia sẻ…"
        self.assertFalse(relevant(title, summary))

        # 2. Positive matches for Vietnamese and AI terms
        self.assertTrue(relevant("Phát triển ứng dụng AI mới nhất"))
        self.assertTrue(relevant("Nghiên cứu trí tuệ nhân tạo tại Việt Nam"))
        self.assertTrue(relevant("Áp dụng học máy trong y tế"))
        self.assertTrue(relevant("Ra mắt mô hình ngôn ngữ tiếng Việt"))
        self.assertTrue(relevant("Cổ phiếu NVIDIA đạt đỉnh"))

        # 3. Catalog must use so-hoa.rss
        vnexpress_source = next(s for s in RSS if s[0] == "vnexpress-tech")
        self.assertEqual(vnexpress_source[4], "https://vnexpress.net/rss/so-hoa.rss")


class TestRound4Nits(unittest.TestCase):
    """Tests for review Nits."""

    def test_nit1_commercial_restriction_wording(self):
        """Nit 1: Use '⚠ hạn chế thương mại' instead of 'trọng số phi thương mại'."""
        res = score_github_repo(
            {"repo": "test/nc-repo"},
            readme_text="pip install test-nc\nThis model is for non-commercial research purposes only.\n",
            license_name="MIT",
            contents=["pyproject.toml"],
            now=NOW,
        )
        self.assertEqual(res["license_flag"], "⚠ hạn chế thương mại")
        self.assertIn("⚠ hạn chế thương mại", res["why"])
        self.assertNotIn("trọng số phi thương mại", res["why"])

    def test_nit2_nc_license_token_matching(self):
        """Nit 2: Match token (^|-)nc(-|$) instead of arbitrary substring."""
        # cc-by-nc-4.0 has -nc-
        details_nc = {
            "library_name": "transformers",
            "cardData": {"license": "cc-by-nc-4.0"},
        }
        res_nc = score_hf_model({"id": "test/nc"}, model_details=details_nc, now=NOW)
        self.assertEqual(res_nc["license_flag"], "⚠ hạn chế thương mại")

        # sync or bounce should not match nc
        details_sync = {
            "library_name": "transformers",
            "cardData": {"license": "sync-license"},
        }
        res_sync = score_hf_model({"id": "test/sync"}, model_details=details_sync, now=NOW)
        self.assertNotEqual(res_sync["license_flag"], "⚠ hạn chế thương mại")

    def test_nit3_noassertion_not_valid_for_xao_nau(self):
        """Nit 3: NOASSERTION is not counted as permissive license for xao-nau."""
        res = score_github_repo(
            {"repo": "test/noassertion"},
            readme_text="# Test\n## Examples\nUsage examples\n## Quick Start\nQuick start guide\n",
            license_name="NOASSERTION",
            contents=["pyproject.toml"],
            now=NOW,
        )
        # Even with high x_score (examples + quickstart), NOASSERTION cannot give xao-nau
        self.assertNotEqual(res["label"], "xao-nau")
        self.assertEqual(res["label"], "nghien-cuu")

    def test_nit4_weekly_trending_regex_anchors_on_h2_a(self):
        """Nit 4: Weekly trending regex anchors on h2 a to avoid matching other links in article."""
        weekly_html = """
        <article class="Box-row">
          <p><a href="/sponsor/link">sponsor link</a></p>
          <h2 class="h3 lh-condensed">
            <a href="/owner/weekly-winner">owner/weekly-winner</a>
          </h2>
          <div><span>1,234 stars this week</span></div>
        </article>
        """
        def fetcher(url, source_id=None):
            if "trending" in url:
                return weekly_html
            if "weekly-winner/HEAD/README.md" in url:
                return "pip install weekly-winner\n"
            return None

        curated = curate_repos([{"repo": "owner/weekly-winner", "url": "https://github.com/owner/weekly-winner"}], [], fetcher=fetcher, now=NOW)
        self.assertEqual(len(curated), 1)
        self.assertEqual(curated[0]["stars_gained_7d"], 1234)

    def test_nit5_homepage_is_product_page_not_demo(self):
        """Nit 5: Homepage alone is recorded as product/docs page, not demo."""
        res = score_github_repo(
            {"repo": "test/docs-site", "homepage": "https://myproject.org"},
            readme_text="pip install docs-site\n",
            license_name="MIT",
            contents=["pyproject.toml"],
            now=NOW,
        )
        self.assertFalse(res["signals"]["has_demo"])
        self.assertTrue(res["signals"]["has_product_page"])
        self.assertEqual(res["signals"]["d4"], 10)


if __name__ == "__main__":
    unittest.main()
