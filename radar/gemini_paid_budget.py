"""Fail-closed monthly Gemini USD budget shared by all Gemini workflows."""

from __future__ import annotations

from copy import deepcopy
import calendar
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from radar.pipeline import write_atomic

LEDGER_VERSION = 1
_UNCHECKED_STORE = object()
STORE_BRANCH = "radar-gemini-paid-budget"
STORE_REF = f"refs/heads/{STORE_BRANCH}"
RUN_ALLOWANCE_USD = Decimal("1")
DAILY_CAP_USD = Decimal("6")
DAILY_PACE_USD = Decimal("0.57")
MAX_BOOST_USD = Decimal("2")
RUN_HOLD_USD = Decimal("0.20")
CONSUMER_TOKENS = {"translation": 40_000, "summary": 100_000, "video": 12_000}
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


def boost_usd(day: str, env=None) -> Decimal:
    """Return the bounded boost for one UTC day; invalid settings do nothing."""
    env = os.environ if env is None else env
    raw = env.get("RADAR_GEMINI_PAID_BOOST", "")
    if not isinstance(raw, str):
        return Decimal(0)
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}):(\d+(?:\.\d+)?)", raw)
    if not match or match.group(1) != day:
        return Decimal(0)
    try:
        datetime.strptime(match.group(1), "%Y-%m-%d")
        amount = Decimal(match.group(2))
        return min(amount, MAX_BOOST_USD) if amount.is_finite() and amount > 0 else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


def days_left_in_month(day_or_dt: str | datetime | float) -> int:
    """Return number of days remaining in the calendar month, including the current day."""
    if isinstance(day_or_dt, (int, float)):
        dt = datetime.fromtimestamp(day_or_dt, timezone.utc)
    elif isinstance(day_or_dt, datetime):
        dt = day_or_dt
    else:
        dt = datetime.strptime(str(day_or_dt), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    _, total_days = calendar.monthrange(dt.year, dt.month)
    return max(1, total_days - dt.day + 1)


def daily_pace_usd(now: float | str | datetime | None = None, store: dict | None = None, env=None) -> Decimal:
    """Pacing that spreads what is left of the monthly cap over days left in the month."""
    if now is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    elif isinstance(now, (int, float)):
        now_ts = float(now)
    elif isinstance(now, datetime):
        now_ts = now.timestamp()
    else:
        now_ts = datetime.strptime(str(now), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()

    day = _day(now_ts)
    days_left = days_left_in_month(now_ts)
    cap = cap_usd(env)
    if cap <= 0:
        return Decimal(0)

    if store is not None:
        settled_today = store.get("settled_daily", {}).get(day, 0)
        settled_before_today = max(0, store.get("settled_micros", 0) - settled_today)
        pending_before_today = sum(
            amount for key, amount in store.get("pending", {}).items()
            if store.get("pending_days", {}).get(key) != day
        )
        spent_before_today = Decimal(settled_before_today + pending_before_today) / Decimal(1_000_000)
        month_left = max(Decimal(0), cap - spent_before_today)
    else:
        month_left = cap

    return month_left / Decimal(days_left)


def _daily_limit_usd(day: str, now: float | None = None, store: dict | None = None, env=None) -> Decimal:
    boost = boost_usd(day, env=env)
    pace = daily_pace_usd(now if now is not None else day, store=store, env=env)
    return min(DAILY_CAP_USD + boost, pace + boost)


def _consumer_tokens(name: str, now: float, store: dict | None = None) -> int:
    tokens = CONSUMER_TOKENS[name]
    if name == "summary":
        day = _day(now)
        limit = _daily_limit_usd(day, now=now, store=store)
        other_micros = _micros(CONSUMER_TOKENS["translation"], now) + _micros(CONSUMER_TOKENS["video"], now)
        limit_micros = int((limit * Decimal(1_000_000)).to_integral_value())
        if limit_micros <= other_micros:
            tokens = int(Decimal(limit_micros) / _price_per_million(now))
        else:
            summary_micros = limit_micros - other_micros
            tokens = int(Decimal(summary_micros) / _price_per_million(now))
    return tokens


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
    if not isinstance(data["settled_daily"], dict) or not isinstance(data["pending_days"], dict):
        raise ValueError("Paid budget branch ledger is invalid")
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
                "pending": {}, "settled_daily": {}, "pending_days": {}, "settled_consumers": {}}
    if not isinstance(data.get("video_dates", []), list) or any(
            not isinstance(day, str) for day in data.get("video_dates", [])):
        raise ValueError("Invalid video dates")
    consumers = data.setdefault("settled_consumers", {})
    if not isinstance(consumers, dict):
        raise ValueError("Invalid consumer accounting")
    for day, amounts in consumers.items():
        if (not isinstance(day, str) or not isinstance(amounts, dict)
                or any(name not in CONSUMER_TOKENS or type(value) is not int or value < 0
                       for name, value in amounts.items())
                or sum(amounts.values()) > data["settled_daily"].get(day, 0)):
            raise ValueError("Invalid consumer accounting")
    return data


def _push(remote: str, data: dict, now: float | None = None, *, expected=_UNCHECKED_STORE) -> None:
    with tempfile.TemporaryDirectory(prefix="radar-gemini-paid-") as temporary:
        repo = Path(temporary) / "repo"
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        current = _restore(remote, repo, now)
        if expected is not _UNCHECKED_STORE and current != expected:
            raise RuntimeError("Paid budget changed before reservation; retry the run")
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
                or type(item.get("micros")) is not int or item["micros"] < 0
                or item.get("consumer", "summary") not in CONSUMER_TOKENS):
            return None
    remaining = data.get("consumer_remaining_micros")
    if "run_key" in data and (not isinstance(remaining, dict) or set(remaining) != set(CONSUMER_TOKENS)):
        return None
    def max_consumer_micros(name: str) -> int:
        if name == "summary":
            return int((DAILY_CAP_USD + MAX_BOOST_USD) * 1_000_000)
        return _micros(CONSUMER_TOKENS[name], now)

    if remaining is not None and (not isinstance(remaining, dict) or any(
            name not in CONSUMER_TOKENS or type(amount) is not int
            or not 0 <= amount <= max_consumer_micros(name)
            for name, amount in remaining.items())):
        return None
    for key in ("monthly_remaining_micros", "daily_remaining_micros", "settled_daily_micros"):
        if key in data and (type(data[key]) is not int or data[key] < 0):
            return None
    if not isinstance(data.get("video_dates", []), list) or any(
            not isinstance(day, str) for day in data.get("video_dates", [])):
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
                         "settled_daily": {}, "pending_days": {}, "settled_consumers": {}}
            expected_store = deepcopy(store) if not store_was_missing else None
            allowance = int((RUN_ALLOWANCE_USD * Decimal(1_000_000)).to_integral_value())
            pending = store["pending"]
            day = _day(now)
            daily_limit = _daily_limit_usd(day, now=now, store=store)
            daily_cap_micros = int(daily_limit * 1_000_000)
            if paid:
                # An attempt may only be prepared once: never reset local charges
                # while reusing an existing durable hold after a crash or retry.
                if run_key in pending:
                    return "paid_budget_attempt_already_reserved"
                cap = cap_usd()
                cap_micros = int(cap * 1_000_000)
                daily_reserved = sum(value for key, value in pending.items()
                                     if store["pending_days"].get(key) == day)
                monthly_remaining = cap_micros - store["settled_micros"] - sum(pending.values())
                daily_remaining = daily_cap_micros - store["settled_daily"].get(day, 0) - daily_reserved
                if cap <= 0 or monthly_remaining <= 0:
                    return "paid_monthly_cap"
                if daily_remaining <= 0:
                    return "paid_daily_cap"
                consumer_remaining = sum(_consumer_remaining(store, now).values())
                if consumer_remaining <= 0:
                    return "paid_consumer_daily_cap"
                charge = min(allowance, int(RUN_HOLD_USD * 1_000_000),
                             monthly_remaining, daily_remaining, consumer_remaining)
                pending[run_key] = charge
                store["pending_days"].setdefault(run_key, day)
            if paid or store_was_missing:
                _push(remote, store, now, expected=expected_store)
            data = {"version": LEDGER_VERSION, "month": _month(now), "last_run_number": run_number,
                    "reservations": [], "run_key": run_key,
                    "run_allowance_micros": pending.get(run_key, 0),
                    "run_day": store["pending_days"].get(run_key),
                    "consumer_remaining_micros": _consumer_remaining(store, now, exclude_run=run_key),
                    "settled_daily_micros": store["settled_daily"].get(_day(now), 0),
                    "daily_limit_micros": daily_cap_micros,
                    "video_dates": store.get("video_dates", [])}
            if paid:
                data["monthly_remaining_micros"] = monthly_remaining
                data["daily_remaining_micros"] = daily_remaining
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


def _consumer_remaining(store, now, *, exclude_run=None):
    day = _day(now)
    amounts = store.get("settled_consumers", {}).get(day, {})
    # Legacy spend before consumer attribution was incurred by translation
    # and summary workflows; video had no legacy spend. Distribute legacy spend
    # proportionally between translation and summary according to their quota ratio
    # (40k vs 100k tokens), without double-counting against either.
    legacy = max(0, store["settled_daily"].get(day, 0) - sum(amounts.values()))
    pending = sum(value for key, value in store["pending"].items()
                  if key != exclude_run and store["pending_days"].get(key) == day)

    legacy_base = CONSUMER_TOKENS["translation"] + CONSUMER_TOKENS["summary"]
    legacy_trans = min(_micros(CONSUMER_TOKENS["translation"], now),
                       int(legacy * CONSUMER_TOKENS["translation"] / legacy_base))
    legacy_summary = min(_micros(_consumer_tokens("summary", now, store=store), now),
                         legacy - legacy_trans)
    legacy_video = max(0, legacy - legacy_trans - legacy_summary)
    legacy_amounts = {
        "translation": legacy_trans,
        "summary": legacy_summary,
        "video": legacy_video,
    }

    # Interrupted run holds have unknown attribution. Distribute pending holds
    # proportionally across consumers according to their quotas rather than
    # charging the entire hold against each consumer (which would exceed translation's daily budget).
    total_tokens = sum(CONSUMER_TOKENS.values())
    pending_trans = min(_micros(CONSUMER_TOKENS["translation"], now),
                        int(pending * CONSUMER_TOKENS["translation"] / total_tokens))
    pending_summary = min(_micros(_consumer_tokens("summary", now, store=store), now),
                          int(pending * CONSUMER_TOKENS["summary"] / total_tokens))
    pending_video = min(_micros(CONSUMER_TOKENS["video"], now),
                        pending - pending_trans - pending_summary)
    unallocated_pending = pending - (pending_trans + pending_summary + pending_video)
    if unallocated_pending > 0:
        pending_summary += unallocated_pending
    pending_amounts = {
        "translation": pending_trans,
        "summary": pending_summary,
        "video": pending_video,
    }

    return {name: max(0, _micros(_consumer_tokens(name, now, store=store), now) - amounts.get(name, 0)
                      - pending_amounts.get(name, 0) - legacy_amounts.get(name, 0))
            for name in CONSUMER_TOKENS}


def boost_usage(path: str | Path, *, now: float) -> dict | None:
    """Report charged spend above the ordinary daily pace on an active boost day."""
    day = _day(now)
    boost_micros = int(boost_usd(day) * 1_000_000)
    if not boost_micros:
        return None
    data = _read(Path(path), now)
    spent = None
    if data is not None and data.get("run_day") == day and "settled_daily_micros" in data:
        charged = data["settled_daily_micros"] + sum(item["micros"] for item in data["reservations"])
        spent = min(boost_micros, max(0, charged - int(DAILY_PACE_USD * 1_000_000)))
    return {"date": day, "limit_micros": boost_micros, "used_micros": spent}


def remaining_tokens(path, consumer, *, now=None, run_number=None):
    """Return the current run's safe consumer headroom without reserving it."""
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    data = _read(Path(path), now)
    run_number = _run_number() if run_number is None else run_number
    if not data or data.get("last_run_number") != run_number or consumer not in CONSUMER_TOKENS:
        return 0
    used = sum(item["micros"] for item in data["reservations"])
    consumer_used = sum(item["micros"] for item in data["reservations"]
                        if item.get("consumer", "summary") == consumer)
    available = data.get("consumer_remaining_micros", {}).get(consumer, _micros(_consumer_tokens(consumer, now), now))
    allowance = data.get("run_allowance_micros", data.get("daily_limit_micros", int(DAILY_PACE_USD * 1_000_000)))
    return max(0, int(min(allowance - used, available - consumer_used) / _price_per_million(now)))


def reserve(path: str | Path, estimated_tokens: int, *, now: float | None = None,
            run_number: int | None = None, cap: Decimal | None = None,
            consumer: str = "summary", idempotency_key: str | None = None) -> tuple[str | None, str | None]:
    """Persist an upper-bound charge before sending a paid API request."""
    path = Path(path)
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    run_number = _run_number() if run_number is None else run_number
    cap = cap_usd() if cap is None else min(Decimal(cap), MAX_CAP_USD)
    if (not math.isfinite(now) or run_number is None or cap <= 0
            or consumer not in CONSUMER_TOKENS or type(estimated_tokens) is not int or estimated_tokens <= 0):
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
        if data.get("run_day") and data["run_day"] != _day(now):
            return "paid_budget_day_changed", None
        if idempotency_key and idempotency_key in data.get("video_dates", []):
            return "paid_video_already_attempted", None
        request_id = uuid.uuid4().hex
        amount = _micros(estimated_tokens, now)
        cap_micros = int((cap * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))
        used = sum(item["micros"] for item in data["reservations"])
        max_run_allowance = int((RUN_ALLOWANCE_USD * Decimal(1_000_000)).to_integral_value())
        allowance = data.get("run_allowance_micros", min(cap_micros, max_run_allowance))
        if type(allowance) is not int or allowance < 0 or allowance > max_run_allowance:
            return MISSING_CODE, None
        if used + amount > cap_micros:
            return "paid_monthly_cap", None
        if used + amount > data.get("monthly_remaining_micros", cap_micros):
            return "paid_monthly_cap", None
        if used + amount > data.get("daily_remaining_micros", int(_daily_limit_usd(_day(now)) * 1_000_000)):
            return "paid_daily_cap", None
        if used + amount > allowance:
            return "paid_run_allowance", None
        if estimated_tokens > remaining_tokens(path, consumer, now=now, run_number=run_number):
            return "paid_" + consumer + "_daily_tokens", None
        data["reservations"].append({"id": request_id, "micros": amount, "consumer": consumer})
        if idempotency_key:
            data.setdefault("video_dates", []).append(idempotency_key)
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
        expected_store = deepcopy(store)
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
        consumers = store.setdefault("settled_consumers", {}).setdefault(day, {})
        for item in data["reservations"]:
            name = item.get("consumer", "summary")
            consumers[name] = consumers.get(name, 0) + item["micros"]
        store["video_dates"] = sorted(set(store.get("video_dates", []) + data.get("video_dates", [])))
        cap = cap_usd()
        cap_micros = int((cap * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))
        if store["settled_micros"] + sum(store["pending"].values()) > cap_micros:
            return "paid_monthly_cap"
        daily_cap_micros = int((_daily_limit_usd(day, now=now, store=store) * Decimal(1_000_000)).to_integral_value())
        daily_pending = sum(value for key, value in store["pending"].items()
                            if store["pending_days"].get(key) == day)
        if store["settled_daily"][day] + daily_pending > daily_cap_micros:
            return "paid_daily_cap"
        _push(remote, store, now, expected=expected_store)
        print("Gemini paid pacing " + json.dumps({
            "day": day, "daily_micros": store["settled_daily"][day],
            "monthly_micros": store["settled_micros"], "run_micros": spent,
            "hold_micros": allowance, "consumer_micros": consumers,
            "pending_micros": sum(store["pending"].values()),
            "daily_pace_micros": daily_cap_micros}, sort_keys=True))
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
