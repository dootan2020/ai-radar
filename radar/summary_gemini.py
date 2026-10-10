"""Bounded Gemini REST story summarizer. No SDK, retries, redirects or proxy forwarding."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

from radar.pipeline import write_atomic
from radar import gemini_paid_budget
from radar.translation_gemini import (
    HTTP_CODE_PATTERN,
    MAX_ERROR_BODY_BYTES,
    MAX_RESPONSE_BYTES,
    STATUS_PATTERN,
    _NoRedirect,
    _error_status,
    http_error_code,
)

MODEL_ID = "gemini-3.8-flash"
PROMPT_VERSION = "summary-vi-5-full"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent"
MAX_OUTPUT_TOKENS = 4096
MAX_STORY_INPUT_CHARS = 24000
MAX_ARTICLE_TEXT_CHARS = 8000
# Exact serialized UTF-8 bytes plus the output ceiling are reserved before POST.
MAX_ESTIMATED_TOKENS_PER_REQUEST = 12000
OUTPUT_SCHEMA = json.loads(Path(__file__).with_name("summary-output-schema.json").read_text(encoding="utf-8"))
SYSTEM_INSTRUCTION = Path(__file__).with_name("summary-system-prompt.txt").read_text(encoding="utf-8")


# Upstream free-tier limits for gemini-3.8-flash (e.g. 15 RPM, 1,500 RPD, 1M TPM)
# are unverified assumptions (no official source was consulted); conservative
# application ceilings (12 req/24h, 25k tokens/24h) are maintained regardless.
DEFAULT_TIMEOUT = 90.0
MAX_TIMEOUT = 180.0


@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    confirmed: bool = False
    paid: bool = False
    max_requests: int = 1
    daily_requests_limit: int = 12
    daily_tokens_limit: int = 25000
    batch_size: int = 1
    max_chars: int = MAX_STORY_INPUT_CHARS
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self):
        for name, ceiling in (("max_requests", 1), ("daily_requests_limit", 12),
                              ("daily_tokens_limit", 25000), ("batch_size", 1),
                              ("max_chars", MAX_STORY_INPUT_CHARS)):
            value = getattr(self, name)
            object.__setattr__(self, name, min(ceiling, max(0, int(value))))
        object.__setattr__(self, "timeout", min(MAX_TIMEOUT, max(0.0, float(self.timeout))))


def config_from_env(env=None) -> Config:
    env = os.environ if env is None else env
    values = {}
    for name in ("max_requests", "daily_requests_limit", "daily_tokens_limit",
                 "batch_size", "max_chars", "timeout"):
        raw = env.get("RADAR_GEMINI_SUMMARY_" + name.upper())
        if raw is not None:
            try:
                values[name] = float(raw) if name == "timeout" else int(raw)
            except (TypeError, ValueError):
                values[name] = 0
    return Config(
        api_key=env.get("GEMINI_API_KEY", ""),
        confirmed=gemini_paid_budget.enabled(env) or env.get("RADAR_GEMINI_FREE_TIER_CONFIRMED") == "1",
        paid=gemini_paid_budget.enabled(env),
        **values,
    )


class ProviderError(Exception):
    """Safe provider error codes."""


def transport(body, api_key: str, timeout: float):
    """Safe HTTPS POST to Gemini endpoint without proxies or redirects."""
    request = urllib.request.Request(
        ENDPOINT,
        data=encode_request(body),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("response_too_large")
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        code = error.code
        status = _error_status(error)
        error.close()
        raise ProviderError(http_error_code(code, status)) from None
    except ProviderError:
        raise
    except (TimeoutError, OSError):
        raise ProviderError("transport_error") from None
    except (ValueError, UnicodeError):
        raise ProviderError("malformed_response") from None


def encode_request(body: dict) -> bytes:
    """Use the same UTF-8 wire bytes for transport and conservative reservation."""
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def request_body(stories_input: list[dict]) -> dict:
    """Build structured Gemini generateContent request for a batch of stories."""
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{
            "role": "user",
            "parts": [{"text": json.dumps({"stories": stories_input}, ensure_ascii=False)}]
        }],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": "low"},
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseJsonSchema": OUTPUT_SCHEMA
        }
    }


def parse_response(response: dict, expected_ids: set[str]) -> tuple[dict[str, dict], int]:
    """Parse structured summaries response and return (dict[id -> editorial summary], tokens_used)."""
    try:
        if not isinstance(response, dict) or response.get("promptFeedback", {}).get("blockReason"):
            raise ValueError
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ValueError
        if candidates[0].get("finishReason") != "STOP":
            raise ValueError
        parts = candidates[0].get("content", {}).get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError

        final_text = []
        for part in parts:
            if not isinstance(part, dict) or set(part) - {"text", "thought", "thoughtSignature"}:
                raise ValueError
            if "thought" in part and type(part["thought"]) is not bool:
                raise ValueError
            if part.get("thought"):
                continue
            if not isinstance(part.get("text"), str):
                raise ValueError
            final_text.append(part["text"])

        raw = "".join(final_text)
        if not raw or len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError

        document = json.loads(raw)
        from radar.summary_validation import valid_shape
        if not valid_shape(document, OUTPUT_SCHEMA) or document["id"] not in expected_ids:
            raise ValueError
        outputs = {document["id"]: document}

        tokens = 0
        metadata = response.get("usageMetadata", {})
        if isinstance(metadata, dict) and "totalTokenCount" in metadata:
            total = metadata["totalTokenCount"]
            if type(total) is int and total > 0:
                tokens = total

        return outputs, tokens
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise ProviderError("invalid_response") from None


def load_cache(path: str | Path) -> dict[str, dict]:
    """Load content-hash -> editorial summary mapping."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (data.get("provider"), data.get("model"), data.get("prompt_version")) != (
                "gemini", MODEL_ID, PROMPT_VERSION):
            return {}
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return {}
        result = {}
        for k, v in entries.items():
            if isinstance(k, str) and isinstance(v, dict):
                result[k] = v
        return result
    except (OSError, ValueError, AttributeError):
        return {}


def save_cache(path: str | Path, entries: dict[str, dict]) -> None:
    """Save content-hash -> editorial summary mapping atomically."""
    write_atomic({
        "provider": "gemini",
        "model": MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "entries": dict(sorted(entries.items()))
    }, path)
