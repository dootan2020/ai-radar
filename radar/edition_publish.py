"""Prepare post-translation editions, then persist only their data branch."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from radar.edition_archive import append_archive, archive_index, load_archive, publication_eligible
from radar.edition_history import files, persist, restore
from radar.items import instant
from radar.pipeline import write_atomic


def check_destination(destination, desired):
    """A rerun may append history but cannot silently erase a local edition."""
    if not destination.exists():
        return
    existing = files(destination)
    for name, content in existing.items():
        if name != "index.json" and desired.get(name) != content:
            raise ValueError("Local archive conflicts with durable edition history")


def copy_archive(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        shutil.copyfile(path, destination / path.name)


def prepare(remote, input_path, status_path, output, candidate, now=None):
    """Validate eligibility before any archive read, remote access or file write."""
    now = instant(now) if now is not None else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("Invalid edition preparation time")
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    status = json.loads(Path(status_path).read_text(encoding="utf-8"))
    if not publication_eligible(payload, status, now):
        raise ValueError("Edition publication rejected: missing, stale or mismatched successful gate")
    output, candidate = Path(output).resolve(), Path(candidate).resolve()
    if output == candidate or output in candidate.parents or candidate in output.parents:
        raise ValueError("Public archive and candidate must be separate directories")
    if candidate.exists() and (candidate.is_symlink()
                              or {p.name for p in candidate.iterdir()} != {"manifest.json", "editions"}):
        raise ValueError("Candidate directory contains unexpected files")
    with tempfile.TemporaryDirectory(prefix="radar-edition-") as temporary:
        repo = Path(temporary)
        base = restore(remote, repo)
        archive = repo / "editions"
        edition = append_archive(payload, status, archive, now)
        # A first successful run before the cutoff exports an honestly empty index.
        write_atomic(archive_index(load_archive(archive)), archive / "index.json")
        desired = files(archive)
        check_destination(output, desired)
        check_destination(candidate / "editions", desired)
        copy_archive(archive, output)
        copy_archive(archive, candidate / "editions")
        write_atomic(dict(schema_version=1, base_commit=base), candidate / "manifest.json")
        if files(output) != desired or files(candidate / "editions") != desired:
            raise RuntimeError("Edition copy read-back failed")
    return edition


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare", help="Prepare eligible editions without pushing")
    build.add_argument("--remote", required=True)
    build.add_argument("--input", default="site/data/radar.json")
    build.add_argument("--status", default="data/publish-status.json")
    build.add_argument("--output", default="site/data/editions")
    build.add_argument("--candidate", default="data/edition-candidate")
    build.add_argument("--now", help="Explicit aware timestamp for reproducible offline checks")
    save = commands.add_parser("persist", help="Append candidate to radar-editions only")
    save.add_argument("--remote", required=True)
    save.add_argument("--candidate", default="data/edition-candidate")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.remote, args.input, args.status, args.output, args.candidate, args.now)
            print("Edition archive prepared and read back")
        else:
            changed = persist(args.remote, args.candidate)
            print("Edition history saved and read back" if changed else "Edition history already saved")
    except subprocess.SubprocessError:
        # Exception strings may include commands, credential-bearing remotes or server output.
        print("Edition operation failed: Git subprocess failed or timed out")
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Edition operation failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
