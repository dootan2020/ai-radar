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
from radar.headlines import annotate_headlines, compact_headline
from test_publication import snapshot

ROOT = Path(__file__).resolve().parents[1]


def reader_fixture():
    data = snapshot()
    story = data["stories"][0]
    story.update(title="A new model release with measured improvements. " + "Original context. " * 12,
                 title_vi="Mô hình mới được công bố với số đo cụ thể. " + "Chi tiết đầy đủ. " * 12,
                 image_screened=True,
                 image={"src": "assets/ai/story.jpg", "via": "ai", "kind": "photo"},
                 summary="Original summary", summary_vi="Tóm tắt",
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
    annotate_headlines(story)
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
        for key in ("title", "title_vi", "headline", "headline_vi", "image_screened", "image",
                    "summary", "summary_vi", "time_basis", "published_at", "kind"):
            self.assertEqual(story[key], original[key])
        self.assertEqual(story["hot_signals"]["measurement"], original["hot_signals"]["measurement"])
        coverage, full = story["coverage"][0], original["coverage"][0]
        for key in ("id", "source", "title", "title_vi", "headline", "headline_vi", "publisher", "lab", "metrics", "url", "status",
                    "start_at", "end_at", "time_precision", "time_text", "media"):
            self.assertEqual(coverage[key], full[key])
        for reduced, source in zip(result["sources"], data["sources"]):
            for key in ("id", "ok", "disabled", "error", "error_vi", "count"):
                self.assertEqual(reduced.get(key), source.get(key))
        self.assertEqual(result["translation"], data["translation"])
        self.assertEqual(result["generated_at"], data["generated_at"])
        self.assertNotIn("updates", result)
        self.assertNotIn("summary", coverage)
        self.assertLess(len(story["headline_vi"]), len(story["title_vi"]))

    def test_screened_image_absence_survives_reader_projections(self):
        data = reader_fixture()
        del data["stories"][0]["image"]
        for payload in (site_payload.page_payload(data), site_payload.head_payload(data)):
            projected = next(s for s in payload["stories"] if s["id"] == data["stories"][0]["id"])
            self.assertTrue(projected["image_screened"])
            self.assertNotIn("image", projected)
            self.assertEqual(projected["headline_vi"], data["stories"][0]["headline_vi"])

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
            self.assertNotIn("headline_vi", full["stories"][0])
            self.assertEqual(full["stories"][0]["headline"], compact_headline(full["stories"][0]["title"]))
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


    def test_head_projection_and_thumbnail_discovery(self):
        data = reader_fixture()
        self.assertEqual(site_payload.head_path("site/data/radar.json").name, "radar-head.json")
        head = site_payload.head_payload(data)
        self.assertEqual(head["schema_version"], 2)
        self.assertEqual(head["generated_at"], data["generated_at"])
        self.assertEqual(head.get("freshness"), data.get("freshness"))
        self.assertTrue(len(head["stories"]) <= len(data["stories"]))

        # Thumbnail detection for ended stream
        ended_data = reader_fixture()
        ended_data["stories"][0]["coverage"][0]["status"] = "ended"
        ended_data["stories"][0]["coverage"][0]["media"] = [{"type": "video", "url": "https://www.youtube.com/watch?v=Fls_onRviPM"}]
        thumb = site_payload.first_screen_thumbnail(ended_data)
        self.assertEqual(thumb, "https://i.ytimg.com/vi/Fls_onRviPM/hqdefault.jpg")

        # Live now stream suppresses thumbnail
        live_now_data = deepcopy(ended_data)
        live_now_data["stories"][0]["coverage"].append({"status": "live", "url": "https://example.org/live"})
        self.assertIsNone(site_payload.first_screen_thumbnail(live_now_data))

    def test_index_thumbnail_injection_and_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            site_dir = Path(directory) / "site"
            data_dir = site_dir / "data"
            data_dir.mkdir(parents=True)
            index_path = site_dir / "index.html"
            index_path.write_text(
                """<!doctype html><html><head><link rel="preload" href="data/radar-head.json" as="fetch" crossorigin>
<link rel="stylesheet" href="tokens.css"></head></html>""",
                encoding="utf-8"
            )
            site_payload.update_index_thumbnail(index_path, "https://i.ytimg.com/vi/test1234567/hqdefault.jpg")
            text = index_path.read_text(encoding="utf-8")
            self.assertIn('<link rel="preload" as="image" href="https://i.ytimg.com/vi/test1234567/hqdefault.jpg" fetchpriority="high">', text)

            site_payload.update_index_thumbnail(index_path, "https://i.ytimg.com/vi/other123456/hqdefault.jpg")
            text = index_path.read_text(encoding="utf-8")
            self.assertNotIn("test1234567", text)
            self.assertIn('<link rel="preload" as="image" href="https://i.ytimg.com/vi/other123456/hqdefault.jpg" fetchpriority="high">', text)

            site_payload.update_index_thumbnail(index_path, None)
            text = index_path.read_text(encoding="utf-8")
            self.assertNotIn('<link rel="preload" as="image"', text)

    def test_write_site_snapshot_writes_head_and_cleans_up_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            data = reader_fixture()
            target = Path(directory) / "radar.json"
            site_payload.write_site_snapshot(data, target)
            self.assertTrue(site_payload.page_path(target).is_file())
            self.assertTrue(site_payload.head_path(target).is_file())

            real_writer = site_payload.write_atomic
            def fail_head(payload, path, **kwargs):
                if "head" in str(path):
                    raise OSError("head write failed")
                return real_writer(payload, path, **kwargs)

            with patch.object(site_payload, "write_atomic", side_effect=fail_head):
                with self.assertRaises(OSError):
                    site_payload.write_site_snapshot(data, target)
            self.assertFalse(site_payload.head_path(target).exists())

    def test_window_projection_keeps_what_the_first_screen_can_show(self):
        data = reader_fixture()
        data["ranking"] = {"window_hours": 72}
        data["generated_at"] = "2026-10-10T12:00:00+00:00"
        base = data["stories"][0]
        def story(sid, published, **extra):
            return {**deepcopy(base), "id": sid, "url": f"https://example.org/{sid}", "title": sid,
                    "published_at": published, **extra}
        data["stories"] = [
            story("fresh", "2026-10-10T11:00:00Z"),
            story("edge-old", "2026-10-07T12:00:00Z"),            # exactly at the window start: kept
            story("near-future", "2026-10-10T12:04:00Z"),          # inside the reader's five-minute allowance
            story("future", "2026-10-10T12:30:00Z"),
            story("old", "2026-10-01T00:00:00Z"),
            story("old-event", "2026-09-01T00:00:00Z"),
            story("old-event-title", "2026-09-01T00:00:00Z"),
            story("old-upcoming", "2026-09-01T00:00:00Z"),
            story("undated", None),
            story("unreadable", "not a time"),
        ]
        data["events"] = [{"url": "https://example.org/old-event", "title": "x"}, {"url": None, "title": "old-event-title"}]
        data["sections"] = {"upcoming": ["old-upcoming"], "today": ["old"]}
        page = site_payload.page_payload(data)
        window = site_payload.window_payload(page)
        self.assertEqual([s["id"] for s in window["stories"]],
                         ["fresh", "edge-old", "near-future", "old-event", "old-event-title", "old-upcoming",
                          "undated", "unreadable"])
        self.assertEqual({k: v for k, v in window.items() if k != "stories"},
                         {k: v for k, v in page.items() if k != "stories"})
        self.assertEqual(window["stories"][0], page["stories"][0])
        self.assertEqual(site_payload.window_path("site/data/radar.json").name, "radar-window.json")

    def test_window_projection_keeps_every_story_when_the_snapshot_time_is_unreadable(self):
        page = site_payload.page_payload(reader_fixture())
        page["generated_at"] = "unknown"
        self.assertEqual(site_payload.window_payload(page)["stories"], page["stories"])

    def test_window_projection_defaults_to_the_reader_window(self):
        page = site_payload.page_payload(reader_fixture())
        page["generated_at"] = "2026-10-10T12:00:00Z"
        page["ranking"] = {"window_hours": "bad"}
        page["stories"][0]["published_at"] = "2026-10-07T13:00:00Z"
        self.assertEqual(len(site_payload.window_payload(page)["stories"]), 1)
        page["stories"][0]["published_at"] = "2026-10-07T11:00:00Z"
        self.assertEqual(site_payload.window_payload(page)["stories"], [])

    def test_write_site_snapshot_writes_window_and_cleans_up_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            data = reader_fixture()
            target = Path(directory) / "radar.json"
            site_payload.write_site_snapshot(data, target)
            window = site_payload.window_path(target)
            self.assertEqual(json.loads(window.read_bytes()),
                             site_payload.window_payload(site_payload.page_payload(data)))
            self.assertEqual(window.read_bytes().count(b"\n"), 1)

            real_writer = site_payload.write_atomic
            def fail_window(payload, path, **kwargs):
                if "window" in str(path):
                    raise OSError("window write failed")
                return real_writer(payload, path, **kwargs)

            with patch.object(site_payload, "write_atomic", side_effect=fail_window):
                with self.assertRaises(OSError):
                    site_payload.write_site_snapshot(data, target)
            self.assertFalse(window.exists())
            self.assertFalse(site_payload.head_path(target).exists())
            self.assertTrue(site_payload.page_path(target).exists())

    def test_build_refuses_window_collisions_before_collecting(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "radar.json"
            with patch.dict(os.environ, {"RADAR_OUTPUT": str(target),
                    "RADAR_BASELINE": str(site_payload.window_path(target))}, clear=True), \
                    patch.object(build, "build_v2") as collect:
                with self.assertRaisesRegex(ValueError, "different files"):
                    build.main()
                collect.assert_not_called()

if __name__ == "__main__":
    unittest.main()
