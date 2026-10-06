"""Conservative rolling-day ledger for story summaries: requests and tokens.

Tracks provider billable units (requests and tokens) over a rolling 24-hour window.
A missing ledger starts a fresh one (a lost cache costs at most one extra day's ceiling,
still far inside the free tier). An unreadable, malformed, or future-dated ledger refuses.

Note on quotas: Upstream free-tier limits for gemini-3.8-flash (e.g. 15 RPM, 1,500 RPD,
1,000,000 TPM) are unverified assumptions (no official source was consulted). The conservative
internal application ceilings (12 requests / 24 hours, 25,000 tokens / 24 hours) are
maintained regardless to guarantee safe free-tier operation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time

from radar.pipeline import write_atomic

LEDGER_VERSION = 1
DEFAULT_DAILY_REQUESTS = 12
DEFAULT_DAILY_TOKENS = 25000
ESTIMATED_TOKENS_PER_REQUEST = (4500 * 2 + 6) // 7 + 1024 + 512
MAX_STORIES_PER_DAY = min(
    DEFAULT_DAILY_REQUESTS,
    DEFAULT_DAILY_TOKENS // ESTIMATED_TOKENS_PER_REQUEST,
)

TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
VIETNAM = timezone(timedelta(hours=7), TIMEZONE_NAME)
SCHEDULED_END_HOUR = 6
SCRIPT_RESERVED_REQUESTS = 1
SCRIPT_RESERVED_TOKENS = 1500


def capacity_error(path: str | Path | None,
                   request_limit: int = DEFAULT_DAILY_REQUESTS,
                   token_limit: int = DEFAULT_DAILY_TOKENS,
                   estimated_tokens: int = 1500,
                   now: float = 0.0,
                   *,
                   reserve_for_script: bool = False) -> str | None:
    """Check whether a request can fit before spending time fetching its input."""
    if path is None:
        return "ledger_unavailable"
    if not math.isfinite(now):
        return "ledger_invalid"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {"version": LEDGER_VERSION, "attempts": []}
    except (OSError, ValueError):
        return "ledger_invalid"
    if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION or not isinstance(data.get("attempts"), list):
        return "ledger_invalid"
    active = []
    for entry in data["attempts"]:
        if isinstance(entry, (int, float)):
            timestamp, tokens = entry, 0
        elif isinstance(entry, dict):
            timestamp, tokens = entry.get("time"), entry.get("tokens", 0)
        else:
            return "ledger_invalid"
        if (not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp > now
                or not isinstance(tokens, (int, float)) or not math.isfinite(tokens) or tokens < 0):
            return "ledger_invalid"
        if now - timestamp < 86400:
            active.append(int(tokens))

    req_ceiling = min(DEFAULT_DAILY_REQUESTS, max(0, int(request_limit)))
    tok_ceiling = min(DEFAULT_DAILY_TOKENS, max(0, int(token_limit)))
    if reserve_for_script:
        req_ceiling = max(0, req_ceiling - SCRIPT_RESERVED_REQUESTS)
        tok_ceiling = max(0, tok_ceiling - SCRIPT_RESERVED_TOKENS)

    if len(active) >= req_ceiling:
        return "daily_limit"
    if sum(active) + max(0, int(estimated_tokens)) > tok_ceiling:
        return "daily_token_limit"
    return None


def init_ledger(path: str | Path) -> None:
    """Explicitly initialize a new empty ledger file."""
    p = Path(path)
    if not p.exists():
        write_atomic({"version": LEDGER_VERSION, "attempts": []}, p)


def reserve(path: str | Path | None,
            request_limit: int = DEFAULT_DAILY_REQUESTS,
            token_limit: int = DEFAULT_DAILY_TOKENS,
            estimated_tokens: int = 1500,
            now: float = 0.0,
            *,
            last_story_id: str | None = None,
            reserve_for_script: bool = False) -> str | None:
    """Reserve quota for one summary request and estimated tokens.

    Returns None on success, or a safe error code:
    'ledger_unavailable', 'ledger_invalid', 'daily_limit', 'daily_token_limit'.
    """
    if path is None:
        return "ledger_unavailable"
    path = Path(path)

    lock = path.with_suffix(path.suffix + ".lock")
    acquired = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        acquired = True
        os.close(descriptor)

        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except FileNotFoundError:
            data = {"version": LEDGER_VERSION, "attempts": []}
        except (OSError, ValueError):
            return "ledger_invalid"

        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            return "ledger_invalid"
        attempts = data.get("attempts")
        if not isinstance(attempts, list):
            return "ledger_invalid"

        if not math.isfinite(now):
            return "ledger_invalid"

        # Validate entries and reject future timestamps
        valid_attempts = []
        for entry in attempts:
            if isinstance(entry, (int, float)):
                t = float(entry)
                toks = 0
            elif isinstance(entry, dict) and "time" in entry:
                t = entry["time"]
                toks = entry.get("tokens", 0)
                if not (isinstance(toks, (int, float)) and math.isfinite(toks) and toks >= 0):
                    return "ledger_invalid"
            else:
                return "ledger_invalid"

            if not (isinstance(t, (int, float)) and math.isfinite(t)) or t > now:
                return "ledger_invalid"

            if now - t < 86400:
                valid_attempts.append({"time": t, "tokens": int(toks)})

        # Request ceiling check
        req_ceiling = min(DEFAULT_DAILY_REQUESTS, max(0, int(request_limit)))
        tok_ceiling = min(DEFAULT_DAILY_TOKENS, max(0, int(token_limit)))
        if reserve_for_script:
            req_ceiling = max(0, req_ceiling - SCRIPT_RESERVED_REQUESTS)
            tok_ceiling = max(0, tok_ceiling - SCRIPT_RESERVED_TOKENS)

        if len(valid_attempts) >= req_ceiling:
            return "daily_limit"

        # Token ceiling check
        current_tokens = sum(entry["tokens"] for entry in valid_attempts)
        if current_tokens + max(0, estimated_tokens) > tok_ceiling:
            return "daily_token_limit"

        # Reserve with estimated tokens
        new_entry = {"time": now, "tokens": max(0, int(estimated_tokens))}
        updated = {
            "version": LEDGER_VERSION,
            "attempts": [*valid_attempts, new_entry],
        }
        if last_story_id:
            updated["last_story_id"] = str(last_story_id)

        write_atomic(updated, path)
        return None
    except (OSError, ValueError):
        return "ledger_unavailable"
    finally:
        if acquired:
            try:
                lock.unlink()
            except OSError:
                pass


def update_actual_tokens(path: str | Path, now: float, actual_tokens: int) -> None:
    """Update the attempt at timestamp `now` with real measured token count from provider metadata."""
    if not math.isfinite(now) or actual_tokens < 0:
        return
    path = Path(path)
    if not path.is_file():
        return
    lock = path.with_suffix(path.suffix + ".lock")
    acquired = False
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        acquired = True
        os.close(descriptor)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            return
        attempts = data.get("attempts", [])
        updated_attempts = []
        for entry in attempts:
            if isinstance(entry, dict) and entry.get("time") == now:
                updated_attempts.append({"time": now, "tokens": int(actual_tokens)})
            else:
                updated_attempts.append(entry)
        data["attempts"] = updated_attempts
        write_atomic(data, path)
    except Exception:
        pass
    finally:
        if acquired:
            try:
                lock.unlink()
            except OSError:
                pass


def is_script_written_today(script_path: str | Path | None = None,
                            ledger_path: str | Path | None = None,
                            today_vn: str | None = None) -> bool:
    """Return True if today's video script has already been written."""
    if today_vn is None:
        today_vn = datetime.now(VIETNAM).strftime("%Y-%m-%d")

    # 1. Check video-script.json file
    p = Path(script_path) if script_path else Path("site/data/video-script.json")
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("date") == today_vn:
                stories = data.get("stories")
                if data.get("hook") and data.get("hint") and isinstance(stories, list) and len(stories) == 3:
                    return True
        except (OSError, ValueError):
            pass

    # 2. Check ledger file for script_date
    if ledger_path:
        lp = Path(ledger_path)
        if lp.is_file():
            try:
                ldata = json.loads(lp.read_text(encoding="utf-8"))
                if isinstance(ldata, dict) and ldata.get("script_date") == today_vn:
                    return True
            except (OSError, ValueError):
                pass

    return False


def is_script_reserve_active(now: float | datetime | None = None,
                             script_path: str | Path | None = None,
                             ledger_path: str | Path | None = None) -> bool:
    """Return True if summaries must reserve quota for today's video script.

    Summaries stop short of the script's share before the script ran today.
    They may use it after the script is written or after the window passes.
    """
    if callable(now):
        now = now()
    if isinstance(now, (int, float)):
        if now <= 0.0:
            now = time.time()
        dt_now = datetime.fromtimestamp(now, tz=timezone.utc)
    elif isinstance(now, datetime):
        dt_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    else:
        dt_now = datetime.now(timezone.utc)

    now_vn = dt_now.astimezone(VIETNAM)
    today_vn = now_vn.strftime("%Y-%m-%d")

    # If the window has passed today (after 06:00 VN time), summaries may use it
    if now_vn.hour >= SCHEDULED_END_HOUR:
        return False

    # If the script is already written for today, summaries may use it
    if is_script_written_today(script_path=script_path, ledger_path=ledger_path, today_vn=today_vn):
        return False

    # Before the script ran today and before the window passes: reserve is active
    return True


def mark_script_completed(path: str | Path | None, today_vn: str) -> None:
    """Record today's date in the ledger indicating video script has been generated."""
    if not path:
        return
    path = Path(path)
    if not path.is_file():
        return
    lock = path.with_suffix(path.suffix + ".lock")
    acquired = False
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        acquired = True
        os.close(descriptor)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version") == LEDGER_VERSION:
            data["script_date"] = str(today_vn)
            write_atomic(data, path)
    except Exception:
        pass
    finally:
        if acquired:
            try:
                lock.unlink()
            except OSError:
                pass

