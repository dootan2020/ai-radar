"""Collect and prepare separate field data; persist only its data branch."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile

from radar.field_api import GitHubAPI
from radar.field_checkpoint import restore_output
from radar.field_history import FILENAME, load, persist, restore, validate
from radar.field_rankings import collect
from radar.items import instant
from radar.pipeline import write_atomic


def prepare(remote, output, candidate, now=None, api=None, fallback=None):
    now = instant(now) if now is not None else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("Invalid field preparation timestamp")
    output, candidate = Path(output).resolve(), Path(candidate).resolve()
    if output == candidate or candidate in output.parents or output in candidate.parents:
        raise ValueError("Field output and candidate must be separate")
    if candidate.exists() and (candidate.is_symlink() or any(p.name not in {FILENAME, "manifest.json"} for p in candidate.iterdir())):
        raise ValueError("Unexpected field candidate files")
    if fallback is not None:
        restore_output(fallback, output, now)
    retained = restore_output(output, output, now)
    try:
        with tempfile.TemporaryDirectory(prefix="radar-field-prepare-") as temporary:
            base, state = restore(remote, temporary)
            if state["last_output"] and instant(state["last_output"]["generated_at"]) > now:
                raise ValueError("Field history is newer than preparation")
            if state["last_output"] and (retained is None or instant(state["last_output"]["generated_at"]) > instant(retained["generated_at"])):
                retained = state["last_output"]
                write_atomic(retained, output)
            # Seed the independent cache before collection as well: a first run
            # can restore Git history successfully and then time out collecting.
            if retained is not None and fallback is not None:
                write_atomic(retained, fallback)
                if json.loads(Path(fallback).read_text(encoding="utf-8")) != retained:
                    raise RuntimeError("Field retained cache read-back failed")
            payload, state = collect(api or GitHubAPI(), now, state)
            validate(state)
            # A failed earlier push may leave the independent public cache ahead
            # of the Git branch. Daily reuse must not regress that reader output;
            # the candidate still contains only the actual restored counters.
            if (retained is not None and retained.get("config_fingerprint") == payload.get("config_fingerprint")
                    and instant(retained["generated_at"]) > instant(payload["generated_at"])):
                payload = retained
            write_atomic(state, candidate / FILENAME)
            manifest = dict(schema_version=1, base_commit=base)
            write_atomic(manifest, candidate / "manifest.json")
            if (load(candidate / FILENAME) != state
                    or json.loads((candidate / "manifest.json").read_text(encoding="utf-8")) != manifest):
                raise RuntimeError("Field preparation read-back failed")
            write_atomic(payload, output)
            if json.loads(output.read_text(encoding="utf-8")) != payload:
                raise RuntimeError("Field public write read-back failed")
            if fallback is not None:
                write_atomic(payload, fallback)
                if json.loads(Path(fallback).read_text(encoding="utf-8")) != payload:
                    raise RuntimeError("Field cache write read-back failed")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        if retained is not None:
            write_atomic(retained, output)
            restore_output(output, output, now, failed=True)
            if fallback is not None:
                write_atomic(retained, fallback)
                if json.loads(Path(fallback).read_text(encoding="utf-8")) != retained:
                    raise RuntimeError("Field cache rollback read-back failed")
        raise
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("--remote", required=True)
    build.add_argument("--output", default="site/data/field-rankings.json")
    build.add_argument("--candidate", default="data/field-candidate")
    build.add_argument("--now")
    build.add_argument("--fallback", default="data/field-last-good.json")
    save = commands.add_parser("persist")
    save.add_argument("--remote", required=True)
    save.add_argument("--candidate", default="data/field-candidate")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            payload = prepare(args.remote, args.output, args.candidate, args.now, fallback=args.fallback)
            print(f"Field rankings prepared: generated_at={payload['generated_at']}; {len(payload['requests'])} recorded requests; complete={payload['complete']}")
        else:
            changed = persist(args.remote, args.candidate)
            print("Field history saved and read back" if changed else "Field history already saved")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        # Remote URLs and subprocess errors can carry credentials; never echo them.
        print("Field operation failed; inspect aggregate diagnostics or candidate validation")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
