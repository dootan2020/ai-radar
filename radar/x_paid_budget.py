"""Durable fail-closed monthly and daily budget for official X reads."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

from radar.pipeline import write_atomic

STORE_BRANCH = "radar-x-paid-budget"
STORE_REF = f"refs/heads/{STORE_BRANCH}"
LEDGER_VERSION = 1
MONTHLY_CAP_MICROS = 30_000_000
DAILY_CAP_MICROS = 1_000_000
POST_READ_MICROS = 5_000
RUN_ALLOWANCE_MICROS = DAILY_CAP_MICROS
MISSING_CODE = "x_budget_ledger_unavailable"


def enabled(env=None):
    return (os.environ if env is None else env).get("RADAR_X_ENABLED") == "1"


def ledger_path(env=None):
    return Path((os.environ if env is None else env).get("RADAR_X_LEDGER", "data/x-paid-ledger.json"))


def _month(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")


def _day(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


def _run_key(env=None):
    env = os.environ if env is None else env
    run_id, attempt = env.get("GITHUB_RUN_ID"), env.get("GITHUB_RUN_ATTEMPT")
    if not run_id or not attempt or not run_id.isdigit() or not attempt.isdigit():
        return None
    return f"{run_id}-{attempt}"


def _git(repo, remote, *args, allowed=(0,)):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = env.get("GITHUB_TOKEN")
    server = env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if token and remote.startswith(server + "/"):
        import base64
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env[f"GIT_CONFIG_KEY_{count}"] = f"http.{server}/.extraheader"
        env[f"GIT_CONFIG_VALUE_{count}"] = "AUTHORIZATION: basic " + auth
        env["GIT_CONFIG_COUNT"] = str(count + 1)
    result = subprocess.run(["git", "-C", str(repo), *args], env=env,
                            capture_output=True, timeout=120)
    if result.returncode not in allowed:
        raise RuntimeError("X budget Git operation failed")
    return result


def _empty(now):
    return {"version": LEDGER_VERSION, "month": _month(now), "settled_micros": 0,
            "settled_daily": {}, "pending": {}, "pending_days": {}, "cursors": {},
            "reconciled_day": None}


def _validate(data, now):
    if (not isinstance(data, dict) or data.get("version") != LEDGER_VERSION
            or data.get("month") != _month(now)
            or type(data.get("settled_micros")) is not int or data["settled_micros"] < 0
            or not isinstance(data.get("settled_daily"), dict)
            or not isinstance(data.get("pending"), dict)
            or not isinstance(data.get("pending_days"), dict)
            or not isinstance(data.get("cursors"), dict)
            or data.get("reconciled_day") is not None
            and (not isinstance(data["reconciled_day"], str)
                 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["reconciled_day"]))
            or set(data["pending_days"]) != set(data["pending"])):
        raise ValueError("Invalid X budget ledger")
    for mapping in (data["settled_daily"], data["pending"]):
        if any(not isinstance(key, str) or type(amount) is not int or amount < 0
               for key, amount in mapping.items()):
            raise ValueError("Invalid X budget ledger")
    for key, day in data["pending_days"].items():
        if (not isinstance(key, str) or not isinstance(day, str)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)):
            raise ValueError("Invalid X budget ledger")
    for key, cursor in data["cursors"].items():
        if (not isinstance(key, str) or not isinstance(cursor, dict)
                or cursor.get("since_id") is not None and not re.fullmatch(r"[0-9]{1,19}", str(cursor["since_id"]))
                or cursor.get("next_token") is not None and not isinstance(cursor["next_token"], str)):
            raise ValueError("Invalid X budget ledger")
    if data["settled_micros"] + sum(data["pending"].values()) > MONTHLY_CAP_MICROS:
        raise ValueError("X budget ledger exceeds monthly cap")
    for day, amount in data["settled_daily"].items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid X budget ledger")
        try:
            if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
                raise ValueError("Invalid X budget ledger")
        except ValueError as error:
            raise ValueError("Invalid X budget ledger") from error
        pending = sum(value for key, value in data["pending"].items()
                      if data["pending_days"].get(key) == day)
        if amount + pending > DAILY_CAP_MICROS:
            raise ValueError("X budget ledger exceeds daily cap")
    return data


def _restore(remote, repo, now):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, remote, "init", "--quiet")
    lookup = _git(repo, remote, "ls-remote", "--exit-code", "--refs", remote, STORE_REF, allowed=(0, 2))
    if lookup.returncode == 2:
        return None
    lines = lookup.stdout.decode("utf-8").splitlines()
    if len(lines) != 1 or lines[0].split()[1:] != [STORE_REF]:
        raise ValueError("Unexpected X budget branch lookup")
    _git(repo, remote, "fetch", "--quiet", "--no-tags", remote, STORE_REF)
    commit = _git(repo, remote, "rev-parse", "FETCH_HEAD").stdout.decode().strip()
    if commit != lines[0].split()[0]:
        raise ValueError("X budget changed during restore")
    entries = _git(repo, remote, "ls-tree", "-r", "-z", commit).stdout.decode().rstrip("\0").split("\0")
    if (len(entries) != 1 or "\t" not in entries[0]
            or entries[0].split("\t", 1)[1] != "ledger.json"
            or not entries[0].startswith("100644 blob ")):
        raise ValueError("Unexpected X budget branch contents")
    _git(repo, remote, "checkout", "--quiet", "--detach", commit)
    try:
        data = json.loads((repo / "ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Unreadable X budget ledger") from error
    if not isinstance(data, dict):
        raise ValueError("Unreadable X budget ledger")
    if data.get("month") != _month(now):
        return _empty(now)
    return _validate(data, now)


def _push(remote, data, now):
    with tempfile.TemporaryDirectory(prefix="radar-x-budget-") as temporary:
        repo = Path(temporary) / "repo"
        current = _restore(remote, repo, now)
        if current is None:
            _git(repo, remote, "checkout", "--quiet", "--orphan", STORE_BRANCH)
            for child in repo.iterdir():
                if child.name != ".git":
                    child.unlink()
        else:
            _git(repo, remote, "checkout", "--quiet", "-B", STORE_BRANCH, "FETCH_HEAD")
        write_atomic(data, repo / "ledger.json", compact=True)
        _git(repo, remote, "add", "--", "ledger.json")
        _git(repo, remote, "-c", "user.name=github-actions[bot]", "-c",
             "user.email=41898282+github-actions[bot]@users.noreply.github.com",
             "commit", "--quiet", "-m", "Update X paid budget")
        _git(repo, remote, "push", "--quiet", remote, f"HEAD:{STORE_REF}")
        saved = json.loads((repo / "ledger.json").read_text(encoding="utf-8"))
        if saved != data:
            raise RuntimeError("X budget read-back failed")


def prepare(path, *, paid, remote, now=None, run_key=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    run_key = _run_key() if run_key is None else run_key
    try:
        if not remote:
            return MISSING_CODE if paid else "x_budget_remote_unavailable"
        with tempfile.TemporaryDirectory(prefix="radar-x-restore-") as temporary:
            store = _restore(remote, Path(temporary) / "repo", now)
        if store is None:
            if paid:
                return MISSING_CODE
            store = _empty(now)
        if paid:
            if not run_key:
                return MISSING_CODE
            allowance = store["pending"].get(run_key)
            if allowance is None:
                day = _day(now)
                daily_pending = sum(value for key, value in store["pending"].items()
                                    if store["pending_days"].get(key) == day)
                remaining = min(DAILY_CAP_MICROS - store["settled_daily"].get(day, 0) - daily_pending,
                                MONTHLY_CAP_MICROS - store["settled_micros"] - sum(store["pending"].values()))
                if remaining <= 0:
                    return "x_daily_cap" if DAILY_CAP_MICROS - store["settled_daily"].get(day, 0) - daily_pending <= 0 else "x_monthly_cap"
                allowance = min(RUN_ALLOWANCE_MICROS, remaining)
                store["pending"][run_key] = allowance
                store["pending_days"][run_key] = day
            _push(remote, store, now)
        elif not store["pending"] and store["settled_micros"] == 0 and store["cursors"] == {}:
            # Seed the independent ledger while collection is disabled.
            _push(remote, store, now)
        local = {"version": LEDGER_VERSION, "month": _month(now), "run_key": run_key,
                 "run_day": store["pending_days"].get(run_key),
                 "run_allowance_micros": store["pending"].get(run_key, 0),
                 "reservations": [], "cursors": store["cursors"],
                 "reconciled_day": store.get("reconciled_day")}
        write_atomic(local, path)
        return None
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return MISSING_CODE


def _read_local(path, now):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("version") != LEDGER_VERSION
            or data.get("month") != _month(now) or not isinstance(data.get("reservations"), list)
            or not isinstance(data.get("cursors"), dict)
            or data.get("reconciled_day") is not None
            and (not isinstance(data["reconciled_day"], str)
                 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["reconciled_day"]))
            or type(data.get("run_allowance_micros")) is not int
            or not 0 <= data["run_allowance_micros"] <= RUN_ALLOWANCE_MICROS):
        return None
    for row in data["reservations"]:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or type(row.get("micros")) is not int or row["micros"] < 0):
            return None
    return data


def reserve(path, *, now=None, max_results=10):
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    data = _read_local(path, now)
    if (data is None or not data.get("run_key") or type(max_results) is not int
            or not 10 <= max_results <= 100):
        return MISSING_CODE, None
    amount = max_results * POST_READ_MICROS
    if sum(row["micros"] for row in data["reservations"]) + amount > data["run_allowance_micros"]:
        return "x_run_cap", None
    request_id = uuid.uuid4().hex
    data["reservations"].append({"id": request_id, "micros": amount})
    write_atomic(data, path)
    return None, request_id


def settle(path, request_id, returned_posts, *, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    data = _read_local(path, now)
    if data is None or type(returned_posts) is not int or returned_posts < 0:
        return MISSING_CODE
    for row in data["reservations"]:
        if row["id"] == request_id:
            if returned_posts > 100:
                return MISSING_CODE
            row["micros"] = returned_posts * POST_READ_MICROS
            write_atomic(data, path)
            return None
    return MISSING_CODE


def update_cursor(path, group_id, since_id, next_token, *, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    data = _read_local(path, now)
    if (data is None or not isinstance(group_id, str)
            or since_id is not None and not re.fullmatch(r"[0-9]{1,19}", str(since_id))
            or next_token is not None and not isinstance(next_token, str)):
        return MISSING_CODE
    data["cursors"][group_id] = {"since_id": since_id, "next_token": next_token}
    write_atomic(data, path)
    return None


def mark_reconciled(path, day, *, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    data = _read_local(path, now)
    if data is None or not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return MISSING_CODE
    data["reconciled_day"] = day
    write_atomic(data, path)
    return None


def finalize(path, remote, *, now=None, run_key=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    run_key = _run_key() if run_key is None else run_key
    local = _read_local(path, now)
    if local is None or local.get("run_key") != run_key or local.get("run_day") is None:
        return MISSING_CODE
    try:
        with tempfile.TemporaryDirectory(prefix="radar-x-finalize-") as temporary:
            store = _restore(remote, Path(temporary) / "repo", now)
        if store is None or run_key not in store["pending"]:
            return MISSING_CODE
        spent = sum(row["micros"] for row in local["reservations"])
        allowance = store["pending"][run_key]
        if spent > allowance:
            return MISSING_CODE
        store["settled_micros"] += spent
        day = store["pending_days"].pop(run_key)
        del store["pending"][run_key]
        store["settled_daily"][day] = store["settled_daily"].get(day, 0) + spent
        store["cursors"] = local["cursors"]
        store["reconciled_day"] = local.get("reconciled_day") or store.get("reconciled_day")
        _validate(store, now)
        _push(remote, store, now)
        return None
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return MISSING_CODE


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "finalize"), nargs="?", default="prepare")
    args = parser.parse_args(argv)
    path = ledger_path()
    remote = os.environ.get("RADAR_X_BUDGET_REMOTE")
    error = finalize(path, remote) if args.command == "finalize" and remote else (
        prepare(path, paid=enabled(), remote=remote) if args.command == "prepare" else MISSING_CODE)
    print("X budget ledger ready" if error is None else f"X budget ledger unavailable: {error}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        try:
            with open(output, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"ledger_ready={str(error is None).lower()}\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
