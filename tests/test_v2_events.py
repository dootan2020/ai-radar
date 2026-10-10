"""Synthetic curated events prove URL safety and honest time precision."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from radar.events import load_events
if __package__:
    from .test_v2_support import NOW
else:
    from test_v2_support import NOW


def event(**changes):
    row = {"id": "synthetic-conference", "title": "Synthetic AI conference",
           "url": "https://conference.example/event", "source_url": "https://conference.example/schedule",
           "start_date": "2026-10-10", "end_date": "2026-10-12",
           "start_at": None, "end_at": None, "time_precision": "date",
           "timezone": "Asia/Ho_Chi_Minh",
           "location": None, "verified_at": "2026-10-02"}
    row.update(changes)
    return row


class EventTests(unittest.TestCase):
    def load(self, rows, now=NOW):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.json"
            path.write_bytes(json.dumps(rows).encode("utf-8"))
            return load_events(path, now)

    def test_date_only_preserves_timezone_without_inventing_timestamps(self):
        row = self.load([event()])[0]
        self.assertEqual(row["start_date"], "2026-10-10")
        self.assertEqual(row["end_date"], "2026-10-12")
        self.assertEqual(row["time_precision"], "date")
        self.assertIsNone(row["start_at"])
        self.assertIsNone(row["end_at"])
        self.assertEqual(row["timezone"], "Asia/Ho_Chi_Minh")

    def test_timezone_is_required_and_must_be_an_iana_identifier(self):
        missing = event()
        del missing["timezone"]
        for row in [missing] + [event(timezone=value) for value in [None, "", 7, {}, "+05:30", "Not/A_Zone"]]:
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "IANA timezone"):
                self.load([row])

    def test_exact_start_unknown_end_preserves_precision_and_local_day_boundary(self):
        row = event(time_precision="exact", timezone="Asia/Kolkata", start_date="2026-10-16",
                    end_date="2026-10-16", start_at="2026-10-16T14:00:00+05:30")
        boundary = datetime.fromisoformat("2026-10-16T18:30:00+00:00")
        kept = self.load([row], boundary - timedelta(microseconds=1))[0]
        self.assertEqual(kept["start_at"], row["start_at"])
        self.assertIsNone(kept["end_at"])
        self.assertEqual(self.load([row], boundary), [])

    def test_local_end_boundary_handles_sydney_dst_and_negative_offsets(self):
        for zone, day, boundary in [
            ("Australia/Sydney", "2026-12-12", "2026-12-12T13:00:00+00:00"),
            ("Australia/Sydney", "2026-10-04", "2026-10-04T13:00:00+00:00"),
            ("Australia/Sydney", "2026-04-05", "2026-04-05T14:00:00+00:00"),
            ("America/Los_Angeles", "2026-10-16", "2026-10-17T07:00:00+00:00"),
        ]:
            with self.subTest(zone=zone, day=day):
                row = event(timezone=zone, start_date=day, end_date=day, verified_at="2026-01-01")
                end = datetime.fromisoformat(boundary)
                self.assertEqual(len(self.load([row], end - timedelta(microseconds=1))), 1)
                self.assertEqual(self.load([row], end), [])

    def test_exact_end_takes_precedence_over_end_date(self):
        row = event(time_precision="exact", start_at="2026-10-10T14:00:00+07:00",
                    end_at="2026-10-12T17:00:00+07:00")
        end = datetime.fromisoformat("2026-10-12T10:00:00+00:00")
        self.assertEqual(len(self.load([row], end - timedelta(microseconds=1))), 1)
        self.assertEqual(self.load([row], end), [])

    def test_exact_dates_are_checked_in_the_event_timezone(self):
        row = event(time_precision="exact", timezone="Australia/Sydney", start_date="2026-12-06",
                    end_date="2026-12-06", start_at="2026-12-05T13:00:00Z")
        self.assertEqual(len(self.load([row])), 1)
        for changes in [{"start_at": "2026-12-05T12:59:59Z"}, {"end_at": "2026-12-06T13:00:00Z"}]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "match dates"):
                self.load([row | changes])

    def test_curated_rows_match_verified_opening_facts(self):
        rows = load_events(Path(__file__).resolve().parents[1] / "data/events.json",
                           datetime.fromisoformat("2026-10-10T12:00:00+00:00"))
        bengaluru, sydney = rows
        self.assertEqual(bengaluru["start_at"], "2026-10-16T14:00:00+05:30")
        self.assertIsNone(bengaluru["end_at"])
        self.assertEqual(bengaluru["timezone"], "Asia/Kolkata")
        self.assertEqual(sydney["timezone"], "Australia/Sydney")
        self.assertEqual((sydney["start_date"], sydney["end_date"]), ("2026-12-06", "2026-12-12"))
        self.assertEqual(sydney["time_precision"], "date")
        self.assertIsNone(sydney["start_at"])
        self.assertIsNone(sydney["end_at"])
        self.assertTrue(all(row["verified_at"] == "2026-10-10" for row in rows))

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
