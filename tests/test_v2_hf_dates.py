"""Synthetic repository timestamps must not acquire invented precision in v2."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radar import catalog, huggingface, pipeline, youtube
if __package__:
    from .test_v2_support import NOW
else:
    from test_v2_support import NOW


class RepositoryDateTests(unittest.TestCase):
    def test_release_projection_and_coverage_preserve_only_aware_creation_times(self):
        source = huggingface.SOURCES[0]
        rows = [{"id": "synthetic/" + name, "createdAt": value} for name, value in [
            ("date-only", "2026-10-02"), ("naive", "2026-10-02T11:00:00"),
            ("aware", "2026-10-02T11:00:00+07:00")]]
        def fetch(url, **kwargs):
            if url == source["url"]:
                return json.dumps(rows)
            raise OSError("synthetic unavailable source")
        with tempfile.TemporaryDirectory() as folder:
            events = Path(folder) / "events.json"
            events.write_bytes(b"[]")
            with patch.object(huggingface, "SOURCES", [source]), \
                 patch.object(catalog, "sources", return_value=[]), \
                 patch.object(youtube, "collect", return_value=([], [])):
                result = pipeline.build_v2(fetch=fetch, now=NOW, events_path=events)
        releases = {row["id"]: row for row in result["hf_releases"]}
        coverage = {item["url"]: item for story in result["stories"] for item in story["coverage"]}
        for name, expected in [("date-only", None), ("naive", None), ("aware", "2026-10-02T04:00:00Z")]:
            with self.subTest(name=name):
                row = releases["synthetic/" + name]
                self.assertEqual(row["created_at"], expected)
                self.assertEqual(coverage[row["url"]]["published_at"], expected)
