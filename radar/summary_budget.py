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

import json
import math
import os
from pathlib import Path

from radar.pipeline import write_atomic

LEDGER_VERSION = 1
DEFAULT_DAILY_REQUESTS = 12
DEFAULT_DAILY_TOKENS = 25000


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
            last_story_id: str | None = None) -> str | None:
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
        if len(valid_attempts) >= req_ceiling:
            return "daily_limit"

        # Token ceiling check
        tok_ceiling = min(DEFAULT_DAILY_TOKENS, max(0, int(token_limit)))
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
