"""Synthetic curated events prove URL safety and honest time precision."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from radar.events import load_events
from test_v2_support import NOW


def event(**changes):
    row = {"id": "synthetic-conference", "title": "Synthetic AI conference",
           "url": "https://conference.example/event", "source_url": "https://conference.example/schedule",
           "start_date": "2026-10-10", "end_date": "2026-10-12",
           "start_at": None, "end_at": None, "time_precision": "date",
           "location": None, "verified_at": "2026-10-02"}
    row.update(changes)
    return row


class EventTests(unittest.TestCase):
    def load(self, rows):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.json"
            path.write_bytes(json.dumps(rows).encode("utf-8"))
            return load_events(path, NOW)

    def test_date_only_does_not_invent_midnight_or_timezone(self):
        row = self.load([event()])[0]
        self.assertEqual(row["start_date"], "2026-10-10")
        self.assertEqual(row["end_date"], "2026-10-12")
        self.assertEqual(row["time_precision"], "date")
        self.assertIsNone(row["start_at"])
        self.assertIsNone(row["end_at"])

    def test_exact_times_preserve_real_offset_instant_and_calendar_dates(self):
        row = self.load([event(time_precision="exact", start_at="2026-10-10T14:00:00+07:00",
                               end_at="2026-10-12T17:00:00+07:00")])[0]
        self.assertEqual(datetime.fromisoformat(row["start_at"].replace("Z", "+00:00")),
                         datetime.fromisoformat("2026-10-10T07:00:00+00:00"))
        self.assertEqual(datetime.fromisoformat(row["end_at"].replace("Z", "+00:00")),
                         datetime.fromisoformat("2026-10-12T10:00:00+00:00"))
        self.assertEqual(row["start_date"], "2026-10-10")
        self.assertEqual(row["end_date"], "2026-10-12")
        self.assertEqual(row["time_precision"], "exact")

    def test_timezone_free_exact_time_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load([event(time_precision="exact", start_at="2026-10-10T14:00:00")])

    def test_invalid_calendar_day_or_reversed_range_is_rejected(self):
        for changes in [{"start_date": "2026-02-30"}, {"end_date": "2026-10-09"},
                        {"time_precision": "exact", "start_at": "2026-10-10T14:00:00Z",
                         "end_at": "2026-10-10T13:00:00Z"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load([event(**changes)])

    def test_invalid_precision_and_inconsistent_date_precision_are_rejected(self):
        for changes in [{"time_precision": "approximate"},
                        {"time_precision": "date", "start_at": "2026-10-10T14:00:00Z"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load([event(**changes)])

    def test_unsafe_destination_or_evidence_urls_are_rejected(self):
        for field in ["url", "source_url"]:
            for value in ["javascript:alert(1)", "file:///private", "https://user:pass@example.org/"]:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.load([event(**{field: value})])

    def test_empty_calendar_and_past_events_do_not_create_placeholders(self):
        self.assertEqual(self.load([]), [])
        self.assertEqual(self.load([event(start_date="2026-09-28", end_date="2026-10-01")]), [])

    def test_ongoing_multiday_event_survives_until_end_date(self):
        rows = self.load([event(start_date="2026-10-01", end_date="2026-10-03")])
        self.assertEqual(len(rows), 1)

    def test_bad_entry_fails_entire_source_instead_of_silently_hiding_it(self):
        with self.assertRaises(ValueError):
            self.load([event(), {"id": "broken"}])

    def test_non_array_root_is_not_a_valid_empty_calendar(self):
        with self.assertRaises(ValueError):
            self.load({"events": []})
