"""Fail-closed monthly Gemini USD budget shared by all Gemini workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import math
import os
from pathlib import Path
import sys
import uuid

from radar.pipeline import write_atomic

LEDGER_VERSION = 1
DEFAULT_CAP_USD = Decimal("20")
MAX_CAP_USD = Decimal("20")
MODEL_ID = "gemini-3.8-flash"
STALE_RUN_CODE = "paid_budget_run_gap"
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


def prepare(path: str | Path, *, paid: bool, now: float | None = None, run_number: int | None = None) -> str | None:
    """Seed while off; when paid, reject missing or skipped-run state."""
    path = Path(path)
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    if not math.isfinite(now):
        return "paid_budget_invalid_time"
    run_number = _run_number() if run_number is None else run_number
    if run_number is None:
        return "paid_budget_run_number_unavailable" if paid else None
    lock = path.with_suffix(path.suffix + ".lock")
    acquired = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        acquired = True
        os.close(descriptor)
        old_month = None
        if path.exists():
            try:
                old_month = json.loads(path.read_text(encoding="utf-8")).get("month")
            except (OSError, ValueError, AttributeError):
                pass
            data = _read(path, now)
            if data is None:
                return MISSING_CODE if paid else "paid_budget_ledger_invalid"
        else:
            if paid:
                return MISSING_CODE
            data = {"version": LEDGER_VERSION, "month": _month(now), "last_run_number": None,
                    "reservations": []}

        month_rolled = old_month is not None and old_month != _month(now)
        previous_run = data.get("last_run_number")
        if paid and not month_rolled and previous_run is not None and previous_run != run_number - 1 and previous_run != run_number:
            return STALE_RUN_CODE
        if paid and not month_rolled and previous_run is None:
            return STALE_RUN_CODE
        if (not paid and not month_rolled and previous_run is not None
                and data["reservations"] and previous_run != run_number - 1 and previous_run != run_number):
            return STALE_RUN_CODE
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
        if sum(item["micros"] for item in data["reservations"]) + amount > cap_micros:
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


def main() -> int:
    path = ledger_path()
    error = prepare(path, paid=enabled())
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
