"""Offline checks for the workflow's baseline isolation and deployment boundary."""

from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/update.yml"


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_cross_branch_restore_is_ordered_and_versioned(self):
        block = self.text.split("restore-keys: |", 1)[1].split("      - ", 1)[0]
        prefixes = [line.strip() for line in block.splitlines() if line.strip()]
        self.assertEqual(prefixes, ["radar-measurements-v2-${{ github.ref_name }}-",
                                    "radar-measurements-v2-main-"])

    def test_only_promoted_baseline_is_cached(self):
        block = self.text.split("- name: Save measurement snapshot", 1)[1].split("      - ", 1)[0]
        self.assertIn("if: steps.collect.outputs.baseline_updated == 'true'", block)
        self.assertIn("path: data/measurement-baseline.json", block)
        self.assertNotIn("path: site/data/radar.json", block)
        restore = self.text.split("- name: Restore previous measurement snapshot", 1)[1].split("      - ", 1)[0]
        self.assertIn("path: data/measurement-baseline.json", restore)
        self.assertIn("id: collect", self.text)

    def test_reruns_have_unique_keys_and_branches_have_independent_concurrency(self):
        keys = [k for k in re.findall(r"^\s+key: (.+)$", self.text, re.MULTILINE) if "radar-measurements" in k]
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])
        self.assertIn("${{ github.run_attempt }}", keys[0])
        self.assertIn("group: github-pages-${{ github.ref }}", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_main_deployment_guards_and_job_permissions(self):
        self.assertIn("  deploy:\n    if: github.ref == 'refs/heads/main'", self.text)
        self.assertIn("if: github.ref == 'refs/heads/main'", self.steps()["Upload Pages artifact"])
        update, deploy = self.text.split("\n  deploy:")
        self.assertNotIn("pages: write", update)
        self.assertNotIn("id-token: write", update)
        self.assertIn("pages: write", deploy)
        self.assertIn("id-token: write", deploy)
        self.assertNotIn("issues: write", self.text)

    def test_every_action_is_immutable_and_dependabot_monitors_actions(self):
        for path in WORKFLOW.parent.glob("*.yml"):
            uses = re.findall(r"(?m)^\s+(?:- )?uses: (.+)$", path.read_text(encoding="utf-8"))
            self.assertTrue(uses, path.name)
            for action in uses:
                self.assertRegex(action, r"^actions/[a-z/-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$", path.name)
        dependabot = (WORKFLOW.parent.parent / "dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("package-ecosystem: github-actions", dependabot)
        self.assertIn("interval: weekly", dependabot)

    def test_push_and_pr_run_offline_without_deploy_or_write_tokens(self):
        ci = (WORKFLOW.parent / "ci.yml").read_text(encoding="utf-8")
        self.assertRegex(ci, r"(?m)^  push:$")
        self.assertRegex(ci, r"(?m)^  push:\n    branches: \[main\]\n  pull_request:")
        self.assertRegex(ci, r"(?m)^  pull_request:$")
        self.assertIn("run: python -m unittest discover -s tests", ci)
        self.assertIn("run: node --version", ci)
        for forbidden in ("write", "build.py", "deploy", "secrets.", "pull_request_target", "pip install"):
            self.assertNotIn(forbidden, ci)
        self.assertNotRegex(self.text, r"(?m)^  (push|pull_request):$")

    def test_failure_observer_reconciles_actionable_results_and_executes_trusted_code(self):
        alert = (WORKFLOW.parent / "failure-alert.yml").read_text(encoding="utf-8")
        self.assertIn("workflows: [Update AI Radar]", alert)
        self.assertIn("types: [completed]", alert)
        for conclusion in ("failure", "timed_out", "action_required", "startup_failure", "success"):
            self.assertIn(f'"{conclusion}"', alert)
        for conclusion in ("cancelled", "stale", "neutral", "skipped"):
            self.assertNotIn(f'"{conclusion}"', alert)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", alert)
        self.assertIn("head_repository.full_name == github.repository", alert)
        self.assertIn("path: ${{ runner.temp }}/radar-publish-diagnostics", alert)
        self.assertIn("actions: read", alert)
        self.assertIn("issues: write", alert)
        self.assertIn("cancel-in-progress: false", alert)
        self.assertIn("run: python -m radar.failure_alert", alert)
        self.assertNotIn("workflow_run.head_sha", alert)
        self.assertNotIn("pages: write", alert)
        self.assertNotIn("id-token: write", alert)

    def test_diagnostics_always_upload_and_publication_cache_follows_deployment(self):
        steps = self.steps()
        diagnostic = steps["Upload publish diagnostics"]
        self.assertIn("if: always()", diagnostic)
        self.assertIn("path: data/publish-status.json", diagnostic)
        candidate = steps["Upload publication candidate"]
        self.assertIn("steps.collect.outputs.published_snapshot_updated == 'true'", candidate)
        restore = steps["Restore last published snapshot"]
        save = steps["Save published snapshot"]
        self.assertIn("path: data/published-snapshot.json", restore)
        self.assertIn("path: data/published-snapshot.json", save)
        self.assertIn("steps.deployment.outcome == 'success'", save)
        self.assertIn("steps.published-snapshot.outcome == 'success'", save)
        self.assertIn("radar-publication-v1-main-", restore)
        self.assertNotIn("Save published snapshot", self.text.split("\n  deploy:")[0])
        # A deploy-only rerun must fetch the original candidate, not the new attempt number.
        for block in (candidate, steps["Download published snapshot"]):
            self.assertIn("name: radar-publication-${{ github.run_id }}\n", block)
            self.assertNotIn("github.run_attempt", block)
        self.assertIn("overwrite: true", candidate)
        self.assertIn("continue-on-error: true", steps["Download published snapshot"])

    def steps(self):
        """name -> step text, for every step in the update job."""
        out = {}
        for chunk in self.text.split("\n      - ")[1:]:
            match = re.match(r"(?:name: (.+)|uses: (.+))", chunk)
            out[(match.group(1) or match.group(2)).strip()] = chunk
        return out

    def test_translation_is_optional_and_cannot_fail_the_build(self):
        steps = self.steps()
        for name in ("Install translation libraries", "Restore translation model", "Restore translation cache",
                     "Translate headlines", "Save translation model", "Save translation cache"):
            self.assertIn("continue-on-error: true", steps[name], name)
        self.assertIn("requirements-translate.txt", steps["Install translation libraries"])
        names = list(steps)
        # Translation runs after the core build and before anything is uploaded or deployed.
        self.assertLess(names.index("Fetch public sources"), names.index("Translate headlines"))
        self.assertLess(names.index("Translate headlines"), names.index("Upload collected source evidence"))
        self.assertLess(names.index("Translate headlines"), names.index("Upload Pages artifact"))

    def test_translation_has_a_time_limit_and_its_caches_survive_runs(self):
        steps = self.steps()
        translate = steps["Translate headlines"]
        self.assertIn("RADAR_TRANSLATE_BUDGET: '600'", translate)
        self.assertIn("timeout-minutes:", translate)
        self.assertIn("HF_HOME: ${{ runner.temp }}/hf-home", translate)
        self.assertIn("python -m radar.translate --input site/data/radar.json --cache data/translations-vi.json", translate)
        model_key = "key: mt-nllb-200-distilled-600M-a3e77be-v1"
        self.assertIn(model_key, steps["Restore translation model"])
        self.assertIn(model_key, steps["Save translation model"])
        self.assertIn("steps.translate.outputs.model_ready == 'true'", steps["Save translation model"])
        cache_key = "key: radar-translations-v1-${{ github.ref_name }}-${{ github.run_id }}-${{ github.run_attempt }}"
        self.assertIn(cache_key, steps["Restore translation cache"])
        self.assertIn(cache_key, steps["Save translation cache"])
        self.assertIn("radar-translations-v1-main-", steps["Restore translation cache"])
        job_limit = int(re.search(r"update:\n    runs-on: .+\n(?:    #.*\n)?    timeout-minutes: (\d+)", self.text).group(1))
        self.assertGreaterEqual(job_limit, 20)

    def test_translation_requirements_pin_cpu_torch(self):
        text = (WORKFLOW.parents[2] / "requirements-translate.txt").read_text(encoding="utf-8")
        self.assertIn("--extra-index-url https://download.pytorch.org/whl/cpu", text)
        self.assertRegex(text, r"(?m)^torch==[\d.]+\+cpu$")
        for package in ("transformers==", "huggingface_hub==", "safetensors==", "sentencepiece=="):
            self.assertIn(package, text)

    def test_gemini_credentials_are_isolated_to_optional_translation_step(self):
        steps = self.steps()
        translate = steps["Translate headlines"]
        self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", translate)
        self.assertIn("RADAR_GEMINI_FREE_TIER_CONFIRMED: ${{ vars.RADAR_GEMINI_FREE_TIER_CONFIRMED }}", translate)
        self.assertIn("continue-on-error: true", translate)
        summarize = steps.get("Summarize stories")
        if summarize:
            self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", summarize)
            self.assertIn("RADAR_GEMINI_FREE_TIER_CONFIRMED: ${{ vars.RADAR_GEMINI_FREE_TIER_CONFIRMED }}", summarize)
            self.assertIn("continue-on-error: true", summarize)
            self.assertNotRegex(summarize, r"(?i)(?:echo|print|--api-key).*GEMINI_API_KEY")
        video_script_step = steps.get("Generate daily video script")
        if video_script_step:
            self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", video_script_step)
            self.assertIn("RADAR_GEMINI_FREE_TIER_CONFIRMED: ${{ vars.RADAR_GEMINI_FREE_TIER_CONFIRMED }}", video_script_step)
            self.assertIn("continue-on-error: true", video_script_step)
            self.assertNotRegex(video_script_step, r"(?i)(?:echo|print|--api-key).*GEMINI_API_KEY")
        for name, step in steps.items():
            if name not in ("Translate headlines", "Summarize stories", "Generate daily video script"):
                self.assertNotIn("secrets.GEMINI_API_KEY", step, name)
        self.assertNotRegex(translate, r"(?i)(?:echo|print|--api-key).*GEMINI_API_KEY")

    def test_gemini_cache_and_failed_attempts_persist_separately_from_nllb(self):
        steps = self.steps()
        restore = steps["Restore Gemini translation cache and attempt ledger"]
        save = steps["Save Gemini translation cache and attempt ledger"]
        cache_key = "key: radar-gemini-vi-1-${{ github.ref_name }}-${{ github.run_id }}-${{ github.run_attempt }}"
        for block in (restore, save):
            self.assertIn("continue-on-error: true", block)
            self.assertIn("data/translations-gemini-vi.json", block)
            self.assertIn("data/translation-gemini-attempts.json", block)
            self.assertIn(cache_key, block)
            self.assertNotIn("data/translations-vi.json", block)
        self.assertIn("if: always()", save)
        self.assertIn("steps.translate.outputs.gemini_cache_written == 'true'", save)
        self.assertIn("|| steps.translate.outputs.gemini_ledger_written == 'true'", save)
        self.assertIn("radar-gemini-vi-1-main-", restore)
        names = list(steps)
        self.assertLess(names.index("Restore Gemini translation cache and attempt ledger"), names.index("Translate headlines"))
        self.assertLess(names.index("Translate headlines"), names.index("Save Gemini translation cache and attempt ledger"))


if __name__ == "__main__":
    unittest.main()
