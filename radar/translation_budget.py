"""Conservative local attempt ledger: at most twelve requests in any rolling day.

This is application accounting, not Google's quota or a distributed billing guard.
The caller persists it between scheduled runs. A corrupt/unwritable ledger fails closed.
"""

import json
import hashlib
import math
import os
from pathlib import Path

from radar.pipeline import write_atomic
from radar.translation_gemini import MODEL_ID, PROMPT_VERSION


def _source_id(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def rotate_sources(path, sources):
    """Continue after the last attempt so rejected priority text cannot starve later text."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("cursor_scope") != ["gemini", MODEL_ID, PROMPT_VERSION]:
            return sources
        for index, source in enumerate(sources):
            if _source_id(source) == data.get("cursor"):
                return sources[index + 1:] + sources[:index + 1]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return sources


def reserve(path, limit, now, *, last_source=None):
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
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"version": 1, "attempts": []}
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("attempts"), list):
            return "ledger_invalid"
        attempts = data["attempts"]
        if not math.isfinite(now) or any(type(t) not in (int, float) or not math.isfinite(t) or t > now for t in attempts):
            return "ledger_invalid"
        attempts = [t for t in attempts if now - t < 86400]
        if len(attempts) >= min(12, max(0, limit)):
            return "daily_limit"
        updated = dict(data, version=1, attempts=[*attempts, now])
        if last_source is not None:
            updated.update(cursor_scope=["gemini", MODEL_ID, PROMPT_VERSION], cursor=_source_id(last_source))
        write_atomic(updated, path)
        # Count before sending, including failed requests and interrupted processes.
        return None
    except (OSError, ValueError):
        return "ledger_unavailable"
    finally:
        if acquired:
            try:
                lock.unlink()
            except OSError:
                pass


def cooling_sources(path, now):
    """Validated negative-cache entries are scoped to model and prompt."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("failure_scope") != [MODEL_ID, PROMPT_VERSION]:
            return set()
        return {key for key, stamp in data.get("failures", {}).items()
                if type(stamp) in (int, float) and 0 <= now - stamp < 86400}
    except (OSError, ValueError, TypeError, AttributeError):
        return set()


def record_failures(path, sources, now):
    if path is None:
        return "ledger_unavailable"
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"version": 1, "attempts": []}
        if not isinstance(data, dict) or data.get("version") != 1:
            return "ledger_invalid"
        active = cooling_sources(path, now)
        failures = {key: stamp for key, stamp in data.get("failures", {}).items() if key in active}
        failures.update({_source_id(source): now for source in sources})
        data.update(failures=failures, failure_scope=[MODEL_ID, PROMPT_VERSION])
        write_atomic(data, path)
    except (OSError, ValueError, TypeError):
        return "ledger_unavailable"
    return None
