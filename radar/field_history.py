"""Validated, bounded repository counters on an isolated data-only Git branch."""

from datetime import date, timedelta
import json
from pathlib import Path
import re
import tempfile

from radar.edition_history import git
from radar.field_config import RETENTION_DAYS
from radar.field_rankings import empty_state
from radar.items import instant
from radar.pipeline import write_atomic

REF = "refs/heads/radar-field-history"
FILENAME = "field-history.json"
MAX_BYTES = 64 * 1024 * 1024
# Historical safety ceilings are deliberately independent of today's field set.
MAX_FIELDS = 64
MAX_CATALOGUE = 2000
MAX_DAILY_POINTS = 10000
MAX_FIELD_ROWS = 100


def validate(state):
    if (not isinstance(state, dict) or set(state) != {"schema_version", "snapshots", "catalogue", "first_seen", "last_output"}
            or type(state["schema_version"]) is not int or state["schema_version"] != 1
            or not isinstance(state["snapshots"], dict) or len(state["snapshots"]) > RETENTION_DAYS
            or not isinstance(state["catalogue"], dict) or len(state["catalogue"]) > MAX_CATALOGUE
            or not isinstance(state["first_seen"], dict) or len(state["first_seen"]) > 100000):
        raise ValueError("Invalid field history state")
    for identity, seen in state["first_seen"].items():
        if not isinstance(identity, str) or not re.fullmatch(r"[1-9][0-9]*", identity) or instant(seen) is None:
            raise ValueError("Invalid first seen identity")
    for identity, entry in state["catalogue"].items():
        if (not isinstance(identity, str) or not re.fullmatch(r"[1-9][0-9]*", identity) or not isinstance(entry, dict)
                or instant(entry.get("tracking_since")) is None or not isinstance(entry.get("full_name"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", entry["full_name"])):
            raise ValueError("Invalid field catalogue identity")
        if "last_refresh_attempt" in entry and instant(entry["last_refresh_attempt"]) is None:
            raise ValueError("Invalid refresh timestamp")
    for day, points in state["snapshots"].items():
        if (not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or date.fromisoformat(day).isoformat() != day
                or not isinstance(points, dict) or len(points) > MAX_DAILY_POINTS):
            raise ValueError("Invalid field snapshot date")
        for identity, point in points.items():
            if (not isinstance(identity, str) or not re.fullmatch(r"[1-9][0-9]*", identity) or not isinstance(point, dict)
                    or set(point) != {"stars", "observed_at"} or type(point["stars"]) is not int or point["stars"] < 0
                    or instant(point["observed_at"]) is None or point["observed_at"][:10] != day):
                raise ValueError("Invalid field snapshot point")
    output = state["last_output"]
    if output is not None:
        if (not isinstance(output, dict) or output.get("schema_version") != 1
                or instant(output.get("generated_at")) is None or type(output.get("complete")) is not bool
                or output.get("metric") != "stars_net_7d" or not isinstance(output.get("fields"), list)
                or not 1 <= len(output["fields"]) <= MAX_FIELDS):
            raise ValueError("Invalid field output")
        ids = [field.get("id") if isinstance(field, dict) else None for field in output["fields"]]
        if (any(not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identity) for identity in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("Invalid field identifiers")
        if "config_fingerprint" in output and (not isinstance(output["config_fingerprint"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", output["config_fingerprint"])):
            raise ValueError("Invalid configuration fingerprint")
        for field in output["fields"]:
            if field.get("status") not in {"ready", "tracking", "empty", "partial", "stale", "unavailable"}:
                raise ValueError("Invalid field status")
            for key in ("ranked", "tracking"):
                if not isinstance(field.get(key), list) or len(field[key]) > MAX_FIELD_ROWS * (2 if key == "tracking" else 1):
                    raise ValueError("Invalid field rows")
                for row in field[key]:
                    if (not isinstance(row, dict) or type(row.get("repository_id")) is not int or row["repository_id"] <= 0
                            or type(row.get("stars")) is not int or row["stars"] < 0
                            or instant(row.get("observed_at")) is None or instant(row.get("tracking_since")) is None
                            or not isinstance(row.get("full_name"), str)
                            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", row["full_name"])
                            or row.get("url") != "https://github.com/" + row["full_name"]
                            or row.get("stars_net_7d") is not None and type(row["stars_net_7d"]) is not int):
                        raise ValueError("Invalid field row evidence")
                    if key == "ranked" and (row.get("method") != "snapshot_net" or row.get("stars_net_7d") is None):
                        raise ValueError("Unmeasured field rank")
        current = instant(output["generated_at"])
        if any(instant(p["observed_at"]) > current for points in state["snapshots"].values() for p in points.values()):
            raise ValueError("Future field snapshot")
    json.dumps(state, allow_nan=False)
    return state


def validate_output(output):
    """Validate a restored public payload using the same historical safety rules."""
    state = empty_state()
    state["last_output"] = output
    validate(state)
    if output is None:
        raise ValueError("Missing field output")
    return output


def load(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid field history file")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def restore(remote, repo):
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    if any(repo.iterdir()):
        raise ValueError("Field restore requires empty directory")
    git(repo, remote, "init", "--quiet")
    git(repo, remote, "config", "core.autocrlf", "false")
    lookup = git(repo, remote, "ls-remote", "--exit-code", "--refs", remote, REF, allowed=(0, 2))
    if lookup.returncode == 2:
        return None, empty_state()
    lines = lookup.stdout.decode().splitlines()
    if len(lines) != 1 or lines[0].split()[1:] != [REF]:
        raise ValueError("Unexpected field history reference")
    git(repo, remote, "fetch", "--quiet", "--no-tags", remote, REF)
    commit = git(repo, remote, "rev-parse", "FETCH_HEAD").stdout.decode().strip()
    if commit != lines[0].split()[0]:
        raise ValueError("Field history advanced during restore")
    tree = git(repo, remote, "ls-tree", "-r", "-z", commit).stdout.decode()
    entries = tree.rstrip("\0").split("\0")
    if (len(entries) != 1 or "\t" not in entries[0]
            or entries[0].split("\t", 1)[1] != FILENAME
            or not entries[0].startswith("100644 blob ")):
        raise ValueError("Unexpected field history path or type")
    git(repo, remote, "checkout", "--quiet", "--detach", commit)
    return commit, load(repo / FILENAME)


def persist(remote, candidate):
    candidate = Path(candidate)
    if candidate.is_symlink() or {p.name for p in candidate.iterdir()} != {"manifest.json", FILENAME}:
        raise ValueError("Invalid field candidate layout")
    if (candidate / "manifest.json").is_symlink():
        raise ValueError("Invalid field manifest")
    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "base_commit"}
            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["base_commit"] is not None and not re.fullmatch(r"[0-9a-f]{40,64}", str(manifest["base_commit"]))):
        raise ValueError("Invalid field manifest")
    desired = load(candidate / FILENAME)
    with tempfile.TemporaryDirectory(prefix="radar-fields-") as temporary:
        repo = Path(temporary)
        base, existing = restore(remote, repo)
        if desired == existing:
            return False
        if base != manifest["base_commit"]:
            raise ValueError("Field history advanced; prepare again")
        current = instant(desired["last_output"]["generated_at"]) if desired["last_output"] else None
        if current is None:
            raise ValueError("Missing field attempt")
        if existing["last_output"] and current <= instant(existing["last_output"]["generated_at"]):
            raise ValueError("Field output must advance")
        cutoff = (current.date() - timedelta(days=RETENTION_DAYS - 1)).isoformat()
        for day, points in existing["snapshots"].items():
            if day >= cutoff:
                if any(desired["snapshots"].get(day, {}).get(key) != value for key, value in points.items()):
                    raise ValueError("Field snapshots are immutable")
        for key, seen in existing["first_seen"].items():
            if desired["first_seen"].get(key) != seen:
                raise ValueError("Field tracking date is immutable")
        write_atomic(desired, repo / FILENAME)
        if load(repo / FILENAME) != desired:
            raise RuntimeError("Field write read-back failed")
        git(repo, remote, "add", "--", FILENAME)
        git(repo, remote, "-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "--quiet", "-m", "feat: preserve field star measurements")
        git(repo, remote, "push", "--quiet", remote, f"HEAD:{REF}")
        head = git(repo, remote, "rev-parse", "HEAD").stdout.decode().strip()
        observed = git(repo, remote, "ls-remote", "--exit-code", "--refs", remote, REF).stdout.decode().split()[0]
        if head != observed:
            raise RuntimeError("Field push read-back failed")
    return True
