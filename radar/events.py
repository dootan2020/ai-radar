"""Owner-maintained dates preserve precision; no inferred midnight or timezone."""

import json
import re
from datetime import date
from pathlib import Path

from radar.common import web_url
from radar.items import instant

SOURCE = dict(id="curated-events", name="Verified event calendar", lab="", kind="curated", url=None,
              group="event", publisher="curated-events", first_wave=True)


def load_events(path, now):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Expected event array")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Event must be an object")
        if not isinstance(row.get("id"), str) or not row["id"] or row["id"] in seen:
            raise ValueError("Event ID missing or duplicated")
        seen.add(row["id"])
        if not isinstance(row.get("title"), str) or not row["title"].strip():
            raise ValueError("Event title missing")
        if not web_url(row.get("url")) or not web_url(row.get("source_url")):
            raise ValueError("Event requires safe original and verification URLs")
        try:
            if not isinstance(row.get("start_date"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["start_date"]):
                raise ValueError("Invalid date format")
            verification = row.get("verified_at")
            if not isinstance(verification, str) or not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", verification) or instant(verification)):
                raise ValueError("Invalid verification date")
            if row.get("end_date") is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["end_date"]):
                raise ValueError("Invalid end date format")
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row.get("end_date") or row["start_date"])
            verified = date.fromisoformat(row["verified_at"][:10])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Event requires valid start/end/verification dates") from None
        if end < start or verified > now.date():
            raise ValueError("Event date order or verification date invalid")
        precision = row.get("time_precision")
        if precision == "date":
            if row.get("start_at") is not None or row.get("end_at") is not None:
                raise ValueError("Date-only events cannot contain exact timestamps")
        elif precision == "exact":
            exact_start, exact_end = instant(row.get("start_at")), instant(row.get("end_at"))
            if not exact_start or row.get("end_at") is not None and not exact_end:
                raise ValueError("Exact event timestamps require explicit timezone")
            if exact_end and exact_end < exact_start:
                raise ValueError("Event end precedes start")
        else:
            raise ValueError("Event time_precision must be date or exact")
        if end >= now.date():
            result.append(dict(row, end_date=end.isoformat(), start_at=row.get("start_at"), end_at=row.get("end_at")))
    return sorted(result, key=lambda row: (row["start_date"], row["id"]))
