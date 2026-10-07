"""Offline workflow-contract checks and fault injection at the CLI boundary."""

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from radar.edition_publish import main

ROOT = Path(__file__).resolve().parents[1]


def property_value(block, name, indent):
    match = re.search(rf"(?m)^{' ' * indent}{re.escape(name)}: (.+)$", block)
    return match.group(1).strip() if match else None


def condition_matches(expression, context):
    """Evaluate only equality conjunctions; reject unfamiliar Actions syntax.

    This is a scoped contract check, not a GitHub Actions runner emulator.
    """
    if expression is None:
        return True
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    values = []
    for clause in expression.split("&&"):
        match = re.fullmatch(r"\s*([\w.-]+) == '([^']*)'\s*", clause)
        if not match:
            raise AssertionError(f"Unsupported workflow condition: {clause}")
        values.append(context.get(match[1], "") == match[2])
    return all(values)


class EditionWorkflowFailureTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/update.yml").read_text(encoding="utf-8")
        self.jobs = dict(re.findall(r"(?ms)^  (\w+):\n(.*?)(?=^  \w+:\n|\Z)",
                                    self.workflow.split("\njobs:\n", 1)[1]))
        self.update = self.jobs["update"]

    def step(self, name):
        return self.update.split("      - name: " + name + "\n", 1)[1].split("      - ", 1)[0]

    def scheduled(self, name, results, context):
        job = self.jobs[name]
        needs = property_value(job, "needs", 4)
        self.assertIsNotNone(needs)
        dependencies = [value.strip() for value in needs.strip("[]").split(",")]
        # No status-function override: Actions requires successful needs first.
        return (all(results.get(value) == "success" for value in dependencies)
                and condition_matches(property_value(job, "if", 4), context))

    def simulate_update(self, preparation="success", upload="success", published="true"):
        context = {"github.ref": "refs/heads/main", "steps.collect.outputs.published": published}
        result = "success"
        for name, outcome in (("Prepare daily editions", preparation),
                              ("Upload edition history candidate", upload)):
            step = self.step(name)
            executed = result == "success" and condition_matches(property_value(step, "if", 8), context)
            outcome = outcome if executed else "skipped"
            identity = property_value(step, "id", 8)
            if identity:
                context[f"steps.{identity}.outcome"] = outcome
            if outcome == "failure" and property_value(step, "continue-on-error", 8) != "true":
                result = "failure"
        output = property_value(self.update, "edition_candidate", 6)
        self.assertIsNotNone(output, "persist needs an output derived from this run's candidate upload")
        match = re.fullmatch(r"\$\{\{ (steps\.[\w-]+\.outcome) }}", output)
        self.assertIsNotNone(match, "candidate status must come from actual upload outcome")
        context["needs.update.outputs.edition_candidate"] = context.get(match[1], "")
        context["needs.update.result"] = result
        return result, context

    def assert_pages_upload_runs(self, result, context):
        step = self.step("Upload Cloudflare Pages site artifact")
        self.assertEqual(result, "success")
        self.assertTrue(condition_matches(property_value(step, "if", 8), context))
        self.assertIn("actions/upload-artifact@", step)

    def test_optional_archive_has_bounded_time_and_job_headroom(self):
        for name, limit in (("Prepare daily editions", 3), ("Upload edition history candidate", 2)):
            with self.subTest(step=name):
                timeout = property_value(self.step(name), "timeout-minutes", 8)
                self.assertIsNotNone(timeout)
                self.assertLessEqual(int(timeout), limit)
                self.assertGreater(int(timeout), 0)
        self.assertGreaterEqual(int(property_value(self.update, "timeout-minutes", 4)), 30)

    def test_persist_failure_or_timeout_never_blocks_healthy_deploy(self):
        self.assertEqual(property_value(self.jobs["deploy"], "needs", 4), "update")
        for persist_result in ("failure", "cancelled", "skipped", "success"):
            with self.subTest(persist=persist_result):
                self.assertTrue(self.scheduled("deploy", {"update": "success", "persist": persist_result},
                                              {"github.ref": "refs/heads/main", "needs.update.result": "success"}))

    def test_update_failure_or_cancellation_never_deploys(self):
        for result in ("failure", "cancelled", "skipped"):
            with self.subTest(result=result):
                self.assertFalse(self.scheduled("deploy", {"update": result, "persist": "success"},
                                               {"github.ref": "refs/heads/main", "needs.update.result": result}))

    def test_prepare_failure_skips_upload_and_persist_but_keeps_pages_deploy(self):
        self.assertIn(".outcome == 'success'", property_value(self.step("Upload edition history candidate"), "if", 8))
        result, context = self.simulate_update(preparation="failure")
        self.assertEqual(result, "success")
        self.assertEqual(context["needs.update.outputs.edition_candidate"], "skipped")
        self.assert_pages_upload_runs(result, context)
        self.assertFalse(self.scheduled("persist", {"update": result}, context))
        self.assertTrue(self.scheduled("deploy", {"update": result, "persist": "skipped"}, context))

    def test_candidate_upload_failure_keeps_pages_deploy_and_skips_persist(self):
        result, context = self.simulate_update(upload="failure")
        self.assertEqual(result, "success")
        self.assertEqual(context["needs.update.outputs.edition_candidate"], "failure")
        self.assert_pages_upload_runs(result, context)
        self.assertFalse(self.scheduled("persist", {"update": result}, context))
        self.assertTrue(self.scheduled("deploy", {"update": result, "persist": "skipped"}, context))

    def test_no_published_candidate_skips_persist(self):
        result, context = self.simulate_update(published="false")
        self.assertEqual(result, "success")
        self.assertEqual(context["needs.update.outputs.edition_candidate"], "skipped")
        self.assertFalse(self.scheduled("persist", {"update": result}, context))

    def test_successful_upload_allows_persist_and_deploy(self):
        result, context = self.simulate_update()
        self.assertTrue(self.scheduled("persist", {"update": result}, context))
        self.assertTrue(self.scheduled("deploy", {"update": result, "persist": "success"}, context))
        context["github.ref"] = "refs/heads/topic"
        self.assertFalse(self.scheduled("persist", {"update": result}, context))
        self.assertFalse(self.scheduled("deploy", {"update": result}, context))


class EditionCLIErrorTests(unittest.TestCase):
    def test_subprocess_failures_return_nonzero_without_command_or_remote_diagnostics(self):
        marker = "PRIVATE_REMOTE_DIAGNOSTIC"
        exceptions = (subprocess.TimeoutExpired(["git", marker], 120, output=marker, stderr=marker),
                      subprocess.CalledProcessError(1, ["git", marker], output=marker, stderr=marker),
                      subprocess.SubprocessError(marker))
        for command in ("prepare", "persist"):
            for error in exceptions:
                with self.subTest(command=command, kind=type(error).__name__):
                    output = StringIO()
                    with patch(f"radar.edition_publish.{command}", side_effect=error), \
                            redirect_stdout(output), redirect_stderr(output):
                        result = main([command, "--remote", "unused-local-remote"])
                    self.assertEqual(result, 1)
                    self.assertIn("Edition operation failed", output.getvalue())
                    self.assertNotIn(marker, output.getvalue())
                    self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
