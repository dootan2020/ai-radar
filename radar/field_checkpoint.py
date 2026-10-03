"""Independent CI attempt reservation and validated public-output fallback."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid

from radar.common import iso_date
from radar.field_history import MAX_BYTES, validate_output
from radar.items import instant
from radar.pipeline import write_atomic


def reserve(path, now=None):
    """Prepare a six-hour cache key; CI must save and read it back before work."""
    now = instant(now) if now is not None else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("Invalid attempt time")
    slot = f"{now.date().isoformat()}-{now.hour // 6}"
    payload = dict(schema_version=1, slot=slot, attempted_at=iso_date(now), claim=uuid.uuid4().hex)
    write_atomic(payload, path)
    if json.loads(Path(path).read_text(encoding="utf-8")) != payload:
        raise RuntimeError("Attempt write read-back failed")
    return slot


def verify_reservation(path, claim, slot):
    """An existing slot is insufficient: the restored marker must be our claim."""
    path = Path(path)
    if (not isinstance(claim, str) or not re.fullmatch(r"[0-9a-f]{32}", claim)
            or path.is_symlink() or not path.is_file() or path.stat().st_size > 1024):
        raise ValueError("Invalid field reservation")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "slot", "attempted_at", "claim"}
            or type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or payload["claim"] != claim or payload["slot"] != slot or instant(payload["attempted_at"]) is None):
        raise ValueError("Field reservation belongs to another attempt")
    at = instant(payload["attempted_at"])
    if slot != f"{at.date().isoformat()}-{at.hour // 6}":
        raise ValueError("Invalid field reservation slot")
    return True


def restore_output(source, output, now=None, failed=False):
    """Keep observation timestamps intact; an invalid backup is never published."""
    source = Path(source)
    if not source.exists():
        return None
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid field fallback file")
    payload = deepcopy(validate_output(json.loads(source.read_text(encoding="utf-8"))))
    now = instant(now) if now is not None else datetime.now(timezone.utc)
    if now is None or instant(payload["generated_at"]) > now:
        raise ValueError("Future field fallback")
    target = Path(output)
    if not failed and target.exists() and target.resolve() != source.resolve():
        # A surviving workspace can be newer than the external cache. Never
        # replace that validated evidence with an older successful collection.
        try:
            if target.is_symlink() or target.stat().st_size > MAX_BYTES:
                raise ValueError("Invalid existing field output")
            existing = validate_output(json.loads(target.read_text(encoding="utf-8")))
            if instant(payload["generated_at"]) < instant(existing["generated_at"]) <= now:
                payload = deepcopy(existing)
        except (OSError, ValueError):
            pass
    if failed:
        payload.update(complete=False, preparation_status="failed_retained")
        for field in payload["fields"]:
            rows = field["ranked"] + field["tracking"]
            field.update(status="stale" if rows else "unavailable", status_reason="preparation_failed",
                         ranked=[], tracking=[dict(row, stale=True) for row in rows][:40])
    write_atomic(payload, output)
    if json.loads(Path(output).read_text(encoding="utf-8")) != payload:
        raise RuntimeError("Fallback write read-back failed")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("reserve", "restore", "verify", "clear"))
    parser.add_argument("--path", default="data/field-attempt.json")
    parser.add_argument("--source", default="data/field-last-good.json")
    parser.add_argument("--output", default="site/data/field-rankings.json")
    parser.add_argument("--now")
    parser.add_argument("--claim")
    parser.add_argument("--slot")
    parser.add_argument("--failed", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "reserve":
            slot = reserve(args.path, args.now)
            if os.environ.get("GITHUB_OUTPUT"):
                claim = json.loads(Path(args.path).read_text(encoding="utf-8"))["claim"]
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                    stream.write(f"slot={slot}\nclaim={claim}\n")
            print(f"Field attempt slot: {slot}; cache save/read-back required before collection")
        elif args.command == "verify":
            verify_reservation(args.path, args.claim, args.slot)
            print("Restored field checkpoint belongs to this attempt")
        elif args.command == "clear":
            Path(args.path).unlink(missing_ok=True)
            if Path(args.path).exists():
                raise RuntimeError("Local field checkpoint removal failed")
            print("Local field checkpoint removed before cache read-back")
        else:
            payload = restore_output(args.source, args.output, args.now, args.failed)
            print("Validated field output retained" if payload else "No previous field output available")
    except (OSError, ValueError, RuntimeError):
        print("Field checkpoint operation failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
