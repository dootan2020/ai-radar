"""Fail-closed monthly Gemini USD budget shared by all Gemini workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from radar.pipeline import write_atomic

LEDGER_VERSION = 1
STORE_BRANCH = "radar-gemini-paid-budget"
STORE_REF = f"refs/heads/{STORE_BRANCH}"
RUN_ALLOWANCE_USD = Decimal("1")
DAILY_CAP_USD = Decimal("6")
DEFAULT_CAP_USD = Decimal("20")
MAX_CAP_USD = Decimal("20")
MODEL_ID = "gemini-3.8-flash"
MISSING_CODE = "paid_budget_ledger_unavailable"


def enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get("RADAR_GEMINI_PAID_ENABLED") == "1"


def cap_usd(env=None) -> Decimal:
    """Read a downward-only cap; invalid values disable paid spending."""
    env = os.environ if env is None else env
    raw = env.get("RADAR_GEMINI_PAID_MONTHLY_CAP_USD")
    try:
        value = Decimal(raw) if raw else DEFAULT_CAP_USD
        if not value.is_finite() or value <= 0:
            return Decimal(0)
        return min(value, MAX_CAP_USD)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def ledger_path(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("RADAR_GEMINI_PAID_LEDGER", "data/gemini-paid-ledger.json"))


def _month(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")


def _run_number(env=None) -> int | None:
    env = os.environ if env is None else env
    try:
        value = int(env.get("GITHUB_RUN_NUMBER", ""))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _run_key(env=None) -> str | None:
    env = os.environ if env is None else env
    run_id = env.get("GITHUB_RUN_ID")
    attempt = env.get("GITHUB_RUN_ATTEMPT")
    if not run_id or not attempt or not run_id.isdigit() or not attempt.isdigit():
        return None
    return f"{run_id}-{attempt}"


def _git_environment(remote: str) -> dict[str, str]:
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
    return env


def _git(repo: Path, remote: str, *args: str, allowed=(0,)):
    result = subprocess.run(["git", "-C", str(repo), *args], env=_git_environment(remote),
                            capture_output=True, timeout=120)
    if result.returncode not in allowed:
        raise RuntimeError(f"Paid budget Git {args[0]} failed (exit {result.returncode})")
    return result


def _restore(remote: str, repo: Path, now: float):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, remote, "init", "--quiet")
    result = _git(repo, remote, "ls-remote", "--exit-code", "--refs", remote, STORE_REF,
                  allowed=(0, 2))
    if result.returncode == 2:
        return None
    lines = result.stdout.decode("utf-8").splitlines()
    if len(lines) != 1 or lines[0].split()[1:] != [STORE_REF]:
        raise ValueError("Unexpected paid budget branch lookup result")
    advertised = lines[0].split()[0]
    _git(repo, remote, "fetch", "--quiet", "--no-tags", remote, STORE_REF)
    commit = _git(repo, remote, "rev-parse", "FETCH_HEAD").stdout.decode().strip()
    if commit != advertised:
        raise ValueError("Paid budget branch changed during restore; retry the run")
    entries = _git(repo, remote, "ls-tree", "-r", "-z", commit).stdout.decode("utf-8").split("\0")
    paths = []
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        if not metadata.startswith("100644 blob ") or name != "ledger.json":
            raise ValueError("Paid budget branch contains an unexpected path or file type")
        paths.append(name)
    if paths != ["ledger.json"]:
        raise ValueError("Paid budget branch must contain exactly one ledger")
    _git(repo, remote, "checkout", "--quiet", "--detach", commit)
    data = json.loads((repo / "ledger.json").read_text(encoding="utf-8"))
    return _validate_store(data, now)


def _validate_store(data, now: float):
    if (not isinstance(data, dict) or data.get("version") != LEDGER_VERSION
            or not isinstance(data.get("month"), str)
            or type(data.get("settled_micros")) is not int or data["settled_micros"] < 0
            or not isinstance(data.get("pending"), dict)):
        raise ValueError("Paid budget branch ledger is invalid")
    for key, amount in data["pending"].items():
        if not isinstance(key, str) or type(amount) is not int or amount < 0:
            raise ValueError("Paid budget branch ledger is invalid")
    data.setdefault("settled_daily", {})
    data.setdefault("pending_days", {})
    current_day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    for key in data["pending"]:
        data["pending_days"].setdefault(key, current_day)
    if (not isinstance(data["settled_daily"], dict) or not isinstance(data["pending_days"], dict)
            or not set(data["pending_days"]).issubset(data["pending"])):
        raise ValueError("Paid budget branch ledger is invalid")
    for day, amount in data["settled_daily"].items():
        if not isinstance(day, str) or type(amount) is not int or amount < 0:
            raise ValueError("Paid budget branch ledger is invalid")
    for key, day in data["pending_days"].items():
        if not isinstance(key, str) or not isinstance(day, str):
            raise ValueError("Paid budget branch ledger is invalid")
    if data["month"] != _month(now):
        return {"version": LEDGER_VERSION, "month": _month(now), "settled_micros": 0,
                "pending": {}, "settled_daily": {}, "pending_days": {}}
    return data


def _push(remote: str, data: dict, now: float | None = None) -> None:
    with tempfile.TemporaryDirectory(prefix="radar-gemini-paid-") as temporary:
        repo = Path(temporary) / "repo"
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        current = _restore(remote, repo, now)
        # Restore into an empty repository; then reset the worktree to the current durable base.
        if current is not None:
            _git(repo, remote, "checkout", "--quiet", "-B", STORE_BRANCH, "FETCH_HEAD")
        else:
            _git(repo, remote, "checkout", "--quiet", "--orphan", STORE_BRANCH)
            for child in repo.iterdir():
                if child.name != ".git":
                    child.unlink()
        (repo / "ledger.json").write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
        _git(repo, remote, "add", "--", "ledger.json")
        _git(repo, remote, "-c", "user.name=github-actions[bot]", "-c",
             "user.email=41898282+github-actions[bot]@users.noreply.github.com",
             "commit", "--quiet", "-m", "Update Gemini paid budget")
        _git(repo, remote, "push", "--quiet", remote, f"HEAD:{STORE_REF}")
        saved = json.loads((repo / "ledger.json").read_text(encoding="utf-8"))
        if saved != data:
            raise RuntimeError("Paid budget ledger read-back failed")


def _read(path: Path, now: float):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION or not isinstance(data.get("reservations"), list):
        return None
    if data.get("month") != _month(now):
        return {"version": LEDGER_VERSION, "month": _month(now), "last_run_number": None,
                "reservations": []}
    for item in data["reservations"]:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or type(item.get("micros")) is not int or item["micros"] < 0):
            return None
    return data


def prepare(path: str | Path, *, paid: bool, now: float | None = None, run_number: int | None = None,
            remote: str | None = None, run_key: str | None = None) -> str | None:
    """Durably reserve a bounded run allowance before any paid provider call."""
    path = Path(path)
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    if not math.isfinite(now):
        return "paid_budget_invalid_time"
    run_number = _run_number() if run_number is None else run_number
    if remote:
        run_key = _run_key() if run_key is None else run_key
        if paid and run_key is None:
            return "paid_budget_run_identity_unavailable"
        try:
            with tempfile.TemporaryDirectory(prefix="radar-gemini-restore-") as temporary:
                store = _restore(remote, Path(temporary) / "repo", now)
            store_was_missing = store is None
            if store is None:
                if paid:
                    return MISSING_CODE
                store = {"version": LEDGER_VERSION, "month": _month(now),
                         "settled_micros": 0, "pending": {},
                         "settled_daily": {}, "pending_days": {}}
            allowance = int((RUN_ALLOWANCE_USD * Decimal(1_000_000)).to_integral_value())
            pending = store["pending"]
            if paid:
                charge = pending.get(run_key, allowance)
                cap = cap_usd()
                cap_micros = int((cap * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))
                day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
                daily_cap_micros = int((DAILY_CAP_USD * Decimal(1_000_000)).to_integral_value())
                daily_reserved = sum(value for key, value in pending.items()
                                     if store["pending_days"].get(key) == day)
                if (cap <= 0 or store["settled_micros"] + sum(pending.values())
                        + (0 if run_key in pending else charge) > cap_micros):
                    return "paid_monthly_cap"
                if run_key not in pending:
                    daily_remaining = daily_cap_micros - store["settled_daily"].get(day, 0) - daily_reserved
                    if daily_remaining <= 0:
                        return "paid_daily_cap"
                    charge = min(allowance, daily_remaining)
                pending[run_key] = charge
                store["pending_days"].setdefault(run_key, day)
            if paid or store_was_missing:
                _push(remote, store, now)
            data = {"version": LEDGER_VERSION, "month": _month(now), "last_run_number": run_number,
                    "reservations": [], "run_key": run_key,
                    "run_allowance_micros": pending.get(run_key, 0),
                    "run_day": store["pending_days"].get(run_key)}
            write_atomic(data, path)
            return None
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            return MISSING_CODE
    if run_number is None:
        return "paid_budget_run_number_unavailable" if paid else None
    lock = path.with_suffix(path.suffix + ".lock")
    acquired = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        acquired = True
        os.close(descriptor)
        if path.exists():
            data = _read(path, now)
            if data is None:
                return MISSING_CODE if paid else "paid_budget_ledger_invalid"
        else:
            if paid:
                return MISSING_CODE
            data = {"version": LEDGER_VERSION, "month": _month(now), "last_run_number": None,
                    "reservations": []}

        data["last_run_number"] = run_number
        data["updated_at"] = now
        write_atomic(data, path)
        return None
    except (OSError, ValueError):
        return MISSING_CODE
    finally:
        if acquired:
            try:
                lock.unlink()
            except OSError:
                pass


def _price_per_million(now: float) -> Decimal:
    # Charge every used token at the model's higher output rate. This safely
    # overestimates mixed input/output billing while relying on provider usage.
    return Decimal("3.75") if _month(now) <= "2026-12" else Decimal("7.50")


def _micros(tokens: int, now: float) -> int:
    return int((Decimal(max(0, int(tokens))) * _price_per_million(now)).to_integral_value(rounding=ROUND_CEILING))


def reserve(path: str | Path, estimated_tokens: int, *, now: float | None = None,
            run_number: int | None = None, cap: Decimal | None = None) -> tuple[str | None, str | None]:
    """Persist an upper-bound charge before sending a paid API request."""
    path = Path(path)
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    run_number = _run_number() if run_number is None else run_number
    cap = cap_usd() if cap is None else min(Decimal(cap), MAX_CAP_USD)
    if not math.isfinite(now) or run_number is None or cap <= 0:
        return "paid_budget_configuration", None
    lock = path.with_suffix(path.suffix + ".lock")
    acquired = False
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        acquired = True
        os.close(descriptor)
        data = _read(path, now)
        if data is None or data.get("last_run_number") != run_number:
            return MISSING_CODE, None
        request_id = uuid.uuid4().hex
        amount = _micros(estimated_tokens, now)
        cap_micros = int((cap * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))
        used = sum(item["micros"] for item in data["reservations"])
        max_run_allowance = int((RUN_ALLOWANCE_USD * Decimal(1_000_000)).to_integral_value())
        allowance = data.get("run_allowance_micros", min(cap_micros, max_run_allowance))
        if type(allowance) is not int or allowance < 0 or allowance > max_run_allowance:
            return MISSING_CODE, None
        if used + amount > allowance or used + amount > cap_micros:
            return "paid_monthly_cap", None
        data["reservations"].append({"id": request_id, "micros": amount})
        data["updated_at"] = now
        write_atomic(data, path)
        return None, request_id
    except (OSError, ValueError):
        return MISSING_CODE, None
    finally:
        if acquired:
            try:
                lock.unlink()
            except OSError:
                pass


def settle(path: str | Path, request_id: str | None, actual_tokens: int, *, now: float | None = None) -> None:
    """Replace a worst-case reservation using totalTokenCount from usageMetadata."""
    if not request_id or type(actual_tokens) is not int or actual_tokens <= 0:
        return
    path = Path(path)
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    lock = path.with_suffix(path.suffix + ".lock")
    acquired = False
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        acquired = True
        os.close(descriptor)
        data = _read(path, now)
        if data is None:
            return
        for item in data["reservations"]:
            if item["id"] == request_id:
                item["micros"] = _micros(actual_tokens, now)
                data["updated_at"] = now
                write_atomic(data, path)
                return
    except (OSError, ValueError):
        return
    finally:
        if acquired:
            try:
                lock.unlink()
            except OSError:
                pass


def total_micros(path: str | Path, *, now: float | None = None) -> int:
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    data = _read(Path(path), now)
    if data is None:
        raise ValueError(MISSING_CODE)
    return sum(item["micros"] for item in data["reservations"])


def finalize(path: str | Path, remote: str, *, now: float | None = None,
             run_key: str | None = None) -> str | None:
    """Settle the durable per-attempt hold; an interrupted run keeps its full hold."""
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    run_key = _run_key() if run_key is None else run_key
    if run_key is None:
        return "paid_budget_run_identity_unavailable"
    data = _read(Path(path), now)
    if data is None or data.get("run_key") != run_key:
        return MISSING_CODE
    try:
        with tempfile.TemporaryDirectory(prefix="radar-gemini-finalize-") as temporary:
            store = _restore(remote, Path(temporary) / "repo", now)
        if store is None:
            return MISSING_CODE
        allowance = store["pending"].get(run_key)
        if allowance is None:
            return None
        spent = sum(item["micros"] for item in data["reservations"])
        if spent > allowance:
            return "paid_budget_run_allowance_exceeded"
        store["settled_micros"] += spent
        del store["pending"][run_key]
        day = store["pending_days"].pop(run_key, None)
        if day is None:
            return MISSING_CODE
        store["settled_daily"][day] = store["settled_daily"].get(day, 0) + spent
        cap = cap_usd()
        cap_micros = int((cap * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))
        if store["settled_micros"] + sum(store["pending"].values()) > cap_micros:
            return "paid_monthly_cap"
        daily_cap_micros = int((DAILY_CAP_USD * Decimal(1_000_000)).to_integral_value())
        daily_pending = sum(value for key, value in store["pending"].items()
                            if store["pending_days"].get(key) == day)
        if store["settled_daily"][day] + daily_pending > daily_cap_micros:
            return "paid_daily_cap"
        _push(remote, store, now)
        return None
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return MISSING_CODE


def main(argv=None) -> int:
    path = ledger_path()
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "finalize"), nargs="?", default="prepare")
    args = parser.parse_args(argv)
    remote = os.environ.get("RADAR_GEMINI_PAID_REMOTE")
    if args.command == "finalize":
        error = finalize(path, remote) if remote else MISSING_CODE
    else:
        error = prepare(path, paid=enabled(), remote=remote)
    state = "ready" if error is None else error
    print(f"Gemini paid ledger {state}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        try:
            with open(output, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"ledger_ready={str(error is None).lower()}\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
