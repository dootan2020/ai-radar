"""Synthetic HTTP response boundaries retain observed status after headers."""

import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from radar import catalog, pipeline, transport, youtube
from test_v2_support import NOW


class SyntheticResponse(io.BytesIO):
    status = 200

    def __init__(self, content_length):
        super().__init__(b"x" * 11)
        self.headers = Message()
        if content_length:
            self.headers["Content-Length"] = "11"

    def geturl(self):
        return "https://fixture.invalid/oversized"


class ResponseEvidenceTests(unittest.TestCase):
    def test_oversized_header_or_body_retains_received_http_status(self):
        source = {"id": "oversized", "name": "Oversized fixture", "url": "https://fixture.invalid/oversized",
                  "parser": "feed", "kind": "rss", "lab": "", "group": "press", "publisher": "fixture",
                  "first_wave": True}
        for content_length in [True, False]:
            with self.subTest(content_length=content_length), tempfile.TemporaryDirectory() as folder:
                events = Path(folder) / "events.json"
                events.write_bytes(b"[]")
                with patch.object(catalog, "sources", return_value=[source]), \
                     patch.object(youtube, "collect", return_value=([], [])), \
                     patch.object(transport, "MAX_BYTES", 10), \
                     patch.object(transport, "urlopen", side_effect=lambda *args, **kwargs: SyntheticResponse(content_length)):
                    result = pipeline.build_v2(fetch=transport.read_url, now=NOW, events_path=events)
                record = next(row for row in result["sources"] if row["id"] == "oversized")
                self.assertFalse(record["ok"])
                self.assertIn("limit", record["error"])
                self.assertEqual(record["http_status"], 200)
                self.assertEqual(record["http_requests"][0]["http_status"], 200)
