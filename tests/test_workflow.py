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

    def test_main_deployment_guards_and_latest_verified_majors(self):
        self.assertIn("  deploy:\n    if: github.ref == 'refs/heads/main'", self.text)
        self.assertIn("actions/upload-pages-artifact@v5\n        if: github.ref == 'refs/heads/main'", self.text)
        for action in ("cache/restore@v6", "cache/save@v6", "upload-artifact@v7"):
            self.assertIn("actions/" + action, self.text)

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
        self.assertLess(names.index("Translate headlines"), names.index("actions/upload-pages-artifact@v5"))

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


if __name__ == "__main__":
    unittest.main()
