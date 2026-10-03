"""Verified, immutable daily files with a repairable archive index."""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import tempfile

from radar.common import web_url
from radar.editions import MAX_STORIES, TIMEZONE_NAME, build_edition, edition_window
from radar.items import instant, measured
from radar.pipeline import write_atomic
from radar.publication import assess_publication

DAY_FILE = re.compile(r"\d{4}-\d{2}-\d{2}\.json")


def _inspect_reason(reason, coverage, generated):
    if (not isinstance(reason, dict) or not isinstance(reason.get("code"), str)
            or not isinstance(reason.get("text"), str) or not reason["text"].strip()):
        raise ValueError("invalid archived selection reason")
    code = reason["code"]
    if code == "primary_release":
        ids = reason.get("observation_ids")
        known = {row["id"] for row in coverage}
        valid = isinstance(ids, list) and bool(ids) and all(isinstance(id_, str) and id_ in known for id_ in ids)
    elif code == "publisher_coverage":
        publishers = sorted({row["publisher"] for row in coverage})
        valid = len(publishers) >= 2 and reason.get("publishers") == publishers
    elif code == "measured_attention":
        percentile, evidence = measured(reason.get("percentile")), reason.get("measurement")
        if not isinstance(evidence, dict):
            raise ValueError("invalid archived attention measurement")
        value, observed = measured(evidence.get("value")), instant(evidence.get("observed_at"))
        metric = evidence.get("metric")
        valid = (percentile is not None and .8 <= percentile <= 1 and value is not None and value > 0
                 and observed is not None and observed <= generated and isinstance(metric, str)
                 and any(row["source"] == evidence.get("source") and measured(row["metrics"].get(metric)) == value
                         for row in coverage))
    else:
        valid = False
    if not valid:
        raise ValueError("invalid archived selection reason evidence")


def publication_eligible(payload, status, now):
    """Check matching successful publication evidence without filesystem effects."""
    if not isinstance(status, dict) or status.get("published") is not True or status.get("reason") is not None:
        return False
    if not isinstance(payload, dict) or not isinstance(status.get("freshness"), dict):
        return False
    generated, attempted, now = instant(payload.get("generated_at")), instant(status.get("attempted_at")), instant(now)
    if (not generated or not attempted or not now or not generated <= attempted <= now
            or status["freshness"].get("generated_at") != payload.get("generated_at")):
        return False
    return assess_publication(payload, None, now)["published"]


def _inspect_edition(edition, filename):
    if not isinstance(edition, dict) or type(edition.get("schema_version")) is not int or edition["schema_version"] != 1:
        raise ValueError("invalid edition schema")
    day = edition.get("date")
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or filename != day + ".json":
        raise ValueError("invalid edition date or filename")
    created, cutoff = instant(edition.get("created_at")), instant(edition.get("cutoff_at"))
    start, generated = instant(edition.get("window_start_at")), instant(edition.get("snapshot_generated_at"))
    if (not created or not cutoff or not start or not generated or not cutoff <= generated <= created
            or start != cutoff - timedelta(days=1) or edition_window(created)[2] != cutoff
            or edition_window(created)[2].date().isoformat() != day or edition.get("timezone") != TIMEZONE_NAME):
        raise ValueError("invalid edition timestamps or timezone")
    stories = edition.get("stories")
    if not isinstance(stories, list) or len(stories) > MAX_STORIES:
        raise ValueError("invalid edition stories")
    identities = set()
    for story in stories:
        if (not isinstance(story, dict) or not isinstance(story.get("id"), str) or not story["id"]
                or story["id"] in identities or not isinstance(story.get("title"), str) or not story["title"].strip()
                or not web_url(story.get("url"))):
            raise ValueError("invalid archived story")
        identities.add(story["id"])
        published = instant(story.get("published_at"))
        if story.get("time_basis") != "published" or not published or not start <= published < cutoff:
            raise ValueError("invalid archived story time")
        coverage, selection = story.get("coverage"), story.get("selection")
        if (not isinstance(coverage, list) or not coverage or not isinstance(selection, dict)
                or not isinstance(selection.get("reasons"), list) or not selection["reasons"]
                or not isinstance(selection.get("signals"), dict)):
            raise ValueError("invalid archived story evidence")
        for row in coverage:
            if (not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                    for key in ("id", "title", "source", "publisher")) or not web_url(row.get("url"))):
                raise ValueError("invalid archived coverage")
            published, observed = instant(row.get("published_at")), instant(row.get("observed_at"))
            if (row.get("time_basis") != "published" or published is None or not start <= published < cutoff
                    or observed is None or observed > generated or not isinstance(row.get("metrics"), dict)):
                raise ValueError("invalid archived coverage time or metrics")
        for reason in selection["reasons"]:
            _inspect_reason(reason, coverage, generated)
        if type(story.get("source_count")) is not int or story["source_count"] != len({row["publisher"] for row in coverage}):
            raise ValueError("invalid archived publisher count")
    if not isinstance(edition.get("policy"), dict) or not isinstance(edition.get("source_health"), dict):
        raise ValueError("missing edition policy or source health")
    json.dumps(edition, allow_nan=False)
    return edition


def archive_index(editions):
    """Project index metadata from validated immutable files, newest first."""
    rows = [dict(date=row["date"], path=row["date"] + ".json", story_count=len(row["stories"]),
                 cutoff_at=row["cutoff_at"], created_at=row["created_at"],
                 snapshot_generated_at=row["snapshot_generated_at"])
            for row in sorted(editions, key=lambda row: row["date"], reverse=True)]
    latest = dict(date=rows[0]["date"], path=rows[0]["path"]) if rows else None
    return dict(schema_version=1, timezone=TIMEZONE_NAME, latest=latest, editions=rows)


def load_archive(archive_dir):
    """Reject corrupt history/index; a missing index entry is a repairable crash gap."""
    root = Path(archive_dir)
    if not root.exists():
        return []
    editions, index = [], None
    for path in sorted(root.iterdir()):
        if path.name.startswith(".edition-") and path.suffix == ".tmp" and path.is_file():
            continue
        if path.is_symlink() or not path.is_file() or (path.name != "index.json" and not DAY_FILE.fullmatch(path.name)):
            raise ValueError(f"unexpected archive entry: {path.name}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "index.json":
                index = value
                if not isinstance(index, dict):
                    raise ValueError("invalid archive index")
            else:
                editions.append(_inspect_edition(value, path.name))
        except (TypeError, KeyError, ValueError) as error:
            raise ValueError(f"invalid archive file: {path.name}: {error}") from error
    editions.sort(key=lambda row: row["date"], reverse=True)
    if index is not None:
        expected = archive_index(editions)
        if (type(index.get("schema_version")) is not int or index["schema_version"] != 1
                or index.get("timezone") != TIMEZONE_NAME or not isinstance(index.get("editions"), list)):
            raise ValueError("invalid archive index schema")
        by_date = {row["date"]: row for row in expected["editions"]}
        listed = index["editions"]
        if any(not isinstance(row, dict) or row != by_date.get(row.get("date")) for row in listed):
            raise ValueError("archive index references missing or conflicting history")
        dates = [row["date"] for row in listed]
        if dates != sorted(set(dates), reverse=True):
            raise ValueError("archive index dates must be unique and ordered")
        latest = dict(date=listed[0]["date"], path=listed[0]["path"]) if listed else None
        if index.get("latest") != latest:
            raise ValueError("archive latest disagrees with index")
    return editions


def _write_once(payload, destination):
    """Publish flushed bytes atomically without replacing an existing daily file."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
                                         prefix=".edition-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            pass
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def append_archive(payload, publication_status, archive_dir, now):
    """Append after verification; a rejected publication performs zero archive I/O."""
    if not publication_eligible(payload, publication_status, now):
        return None
    edition = build_edition(payload, now)
    if edition is None:
        return None
    root = Path(archive_dir)
    editions = load_archive(root)
    existing = next((row for row in editions if row["date"] == edition["date"]), None)
    if existing is None:
        _inspect_edition(edition, edition["date"] + ".json")
        root.mkdir(parents=True, exist_ok=True)
        _write_once(edition, root / (edition["date"] + ".json"))
        editions = load_archive(root)
        existing = next(row for row in editions if row["date"] == edition["date"])
    index = archive_index(editions)
    index_path = root / "index.json"
    if not index_path.exists() or json.loads(index_path.read_text(encoding="utf-8")) != index:
        write_atomic(index, index_path)
    return existing
