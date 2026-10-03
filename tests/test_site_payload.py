"""Complete reader projection and publication failure behavior, entirely offline."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build
from radar import site_payload, translate, translation_pipeline
from test_publication import snapshot

ROOT = Path(__file__).resolve().parents[1]


def reader_fixture():
    data = snapshot()
    story = data["stories"][0]
    story.update(title_vi="Tin AI", summary="Original summary", summary_vi="Tóm tắt",
                 time_basis="repository_created", published_at=data["generated_at"], kind="model",
                 hot_signals={"measurement": {"source": "remote-0", "metric": "points", "observed_at": data["generated_at"]},
                              "freshness": 0.9}, primary_section="models", groups=["lab"])
    story["coverage"][0].update(publisher="official", lab="openai", title_vi="Tin AI",
        canonical_url=story["url"], summary="Duplicate summary", summary_vi="Bản dịch",
        group="lab", kind="model", time_basis="published", status="upcoming",
        start_at="2026-10-04T12:00:00Z", end_at=None, time_precision="exact", time_text="Scheduled",
        media=[{"type": "video", "url": "https://youtube.com/watch?v=abcdefghijk"}])
    data["translation"] = {"provider": "mixed", "status": "partial", "license": "CC-BY-NC-4.0"}
    data["sources"][0].update(error_vi="Không đọc được", http_requests=[{"url": "https://example.org"}])
    return data


class SitePayloadTests(unittest.TestCase):
    def test_preserves_every_reader_field_and_does_not_mutate_input(self):
        data = reader_fixture()
        before = deepcopy(data)
        result = site_payload.page_payload(data)
        self.assertEqual(data, before)
        self.assertEqual(result["sections"], data["sections"])
        self.assertEqual([s["id"] for s in result["stories"]], [s["id"] for s in data["stories"]])
        story, original = result["stories"][0], data["stories"][0]
        for key in ("title", "title_vi", "summary", "summary_vi", "time_basis", "published_at", "kind"):
            self.assertEqual(story[key], original[key])
        self.assertEqual(story["hot_signals"]["measurement"], original["hot_signals"]["measurement"])
        coverage, full = story["coverage"][0], original["coverage"][0]
        for key in ("id", "source", "title", "title_vi", "publisher", "lab", "metrics", "url", "status",
                    "start_at", "end_at", "time_precision", "time_text", "media"):
            self.assertEqual(coverage[key], full[key])
        for reduced, source in zip(result["sources"], data["sources"]):
            for key in ("id", "ok", "disabled", "error", "error_vi", "count"):
                self.assertEqual(reduced.get(key), source.get(key))
        self.assertEqual(result["translation"], data["translation"])
        self.assertEqual(result["generated_at"], data["generated_at"])
        self.assertNotIn("updates", result)
        self.assertNotIn("summary", coverage)

    def test_compact_full_and_projection_follow_custom_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "custom.json"
            data = reader_fixture()
            site_payload.write_site_snapshot(data, target)
            reader = site_payload.page_path(target)
            self.assertEqual(reader.name, "custom-ui.json")
            self.assertEqual(json.loads(target.read_bytes()), data)
            self.assertEqual(json.loads(reader.read_bytes()), site_payload.page_payload(data))
            self.assertEqual(reader.read_bytes().count(b"\n"), 1)

    def test_failed_companion_write_invalidates_old_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "radar.json"
            site_payload.write_site_snapshot(reader_fixture(), target)
            real_writer = site_payload.write_atomic
            def fail_companion(payload, path, **kwargs):
                if kwargs.get("compact"):
                    raise OSError("projection write failed")
                return real_writer(payload, path, **kwargs)
            changed = reader_fixture()
            changed["stories"][0]["title_vi"] = "Bản dịch mới"
            with patch.object(site_payload, "write_atomic", side_effect=fail_companion):
                with self.assertRaises(OSError):
                    site_payload.write_site_snapshot(changed, target)
            self.assertEqual(json.loads(target.read_bytes()), changed)
            self.assertFalse(site_payload.page_path(target).exists())

    def test_invalid_full_write_preserves_both_previous_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "radar.json"
            site_payload.write_site_snapshot(reader_fixture(), target)
            before = {p: p.read_bytes() for p in (target, site_payload.page_path(target))}
            with self.assertRaises(ValueError):
                site_payload.write_site_snapshot({"bad": float("nan")}, target)
            self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_build_refuses_projection_cache_collisions_before_collecting(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "radar.json"
            for name in ("RADAR_BASELINE", "RADAR_PUBLISHED_SNAPSHOT", "RADAR_PUBLISH_STATUS", "RADAR_SITEMAP"):
                with self.subTest(name=name), patch.dict(os.environ, {"RADAR_OUTPUT": str(target),
                        name: str(site_payload.page_path(target))}, clear=True), patch.object(build, "build_v2") as collect:
                    with self.assertRaisesRegex(ValueError, "different files"):
                        build.main()
                    collect.assert_not_called()

    def test_translation_failure_refreshes_companion_and_custom_output(self):
        with tempfile.TemporaryDirectory() as directory:
            src, out = Path(directory) / "input.json", Path(directory) / "output.json"
            site_payload.write_site_snapshot(reader_fixture(), src)
            before = src.read_bytes()
            with patch.dict(os.environ, {}, clear=True), patch.object(translation_pipeline, "translate_payload",
                    side_effect=RuntimeError("offline failure")), redirect_stdout(io.StringIO()):
                translate.main(["--input", str(src), "--output", str(out), "--cache", str(Path(directory) / "cache.json")])
            full = json.loads(out.read_bytes())
            self.assertEqual(full["translation"]["status"], "failed")
            self.assertEqual(json.loads(site_payload.page_path(out).read_bytes()), site_payload.page_payload(full))
            self.assertEqual(src.read_bytes(), before)

    def test_translation_refuses_companion_cache_collision(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            translate.main(["--input", "radar.json", "--cache", "radar-ui.json"])

    @unittest.skipUnless(shutil.which("node"), "Node required for reader contract tests")
    def test_reader_fallback_and_rendered_content_equivalence(self):
        with tempfile.TemporaryDirectory() as directory:
            data = reader_fixture()
            path = Path(directory) / "radar.json"
            site_payload.write_site_snapshot(data, path)
            result = subprocess.run(["node", str(ROOT / "tests" / "verify-reader-payload.mjs"), str(path),
                                     str(site_payload.page_path(path))], capture_output=True, text=True,
                                    encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
