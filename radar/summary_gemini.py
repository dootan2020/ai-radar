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
from radar.translation_gemini import (
    HTTP_CODE_PATTERN,
    MAX_ERROR_BODY_BYTES,
    MAX_RESPONSE_BYTES,
    STATUS_PATTERN,
    _NoRedirect,
    _error_status,
    http_error_code,
)
from radar.translate import VIETNAMESE, NUMBER_WORDS, SMALL_NUMBERS

MODEL_ID = "gemini-3.8-flash"
PROMPT_VERSION = "summary-vi-1"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent"
MAX_OUTPUT_TOKENS = 4096

SYSTEM_INSTRUCTION = """Bạn là trợ lý tin tức công nghệ AI chuyên nghiệp của ai-radar.
Nhiệm vụ: Đọc kỹ toàn bộ tiêu đề và nội dung tóm tắt từ các nguồn tin (coverage) của mỗi bài viết AI, sau đó viết từ 1 đến 3 ý chính (key points) bằng tiếng Việt tự nhiên, súc tích.

NGUYÊN TẮC BẮT BUỘC:
1. TUYỆT ĐỐI KHÔNG BỊA ĐẶT SỰ THẬT (No invented facts): Mọi ý chính phải dựa hoàn toàn trên dữ liệu nguồn được cung cấp. Không suy diễn, không tự thêm bối cảnh bên ngoài.
2. DỮ LIỆU MỎNG THÌ TÓM TẮT NGẮN: Khi nguồn tin chỉ có 1 tiêu đề ngắn hoặc nội dung rất mỏng, chỉ xuất ĐÚNG 1 ý chính duy nhất. Tuyệt đối không viết thêm để đệm chữ.
3. BẢO TOÀN DANH TỪ RIÊNG, SỐ LIỆU VÀ TÍNH PHỦ ĐỊNH: Tên sản phẩm, model, công ty, tên người, phiên bản, chỉ số đo lường, và ngữ cảnh phủ định/nghi vấn phải được giữ nguyên vẹn, chính xác.
4. ĐỊNH DẠNG: Mỗi ý chính là một câu tiếng Việt hoàn chỉnh, ngắn gọn, súc tích, đứng độc lập.
5. Trả về đúng JSON theo schema yêu cầu, một mục cho mỗi story id. Không kèm lời mở đầu, giải thích hay suy nghĩ riêng."""


# Upstream free-tier limits for gemini-3.8-flash (e.g. 15 RPM, 1,500 RPD, 1M TPM)
# are unverified assumptions (no official source was consulted); conservative
# application ceilings (12 req/24h, 25k tokens/24h) are maintained regardless.
@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    confirmed: bool = False
    max_requests: int = 1
    daily_requests_limit: int = 12
    daily_tokens_limit: int = 25000
    batch_size: int = 10
    max_chars: int = 15000
    timeout: float = 45.0

    def __post_init__(self):
        for name, ceiling in (("max_requests", 1), ("daily_requests_limit", 12),
                              ("daily_tokens_limit", 25000), ("batch_size", 10),
                              ("max_chars", 15000)):
            value = getattr(self, name)
            object.__setattr__(self, name, min(ceiling, max(0, int(value))))
        object.__setattr__(self, "timeout", min(45.0, max(0.0, float(self.timeout))))


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
        confirmed=env.get("RADAR_GEMINI_FREE_TIER_CONFIRMED") == "1",
        **values,
    )


class ProviderError(Exception):
    """Safe provider error codes."""


def transport(body, api_key: str, timeout: float):
    """Safe HTTPS POST to Gemini endpoint without proxies or redirects."""
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
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
            "responseJsonSchema": {
                "type": "object",
                "required": ["summaries"],
                "additionalProperties": False,
                "properties": {
                    "summaries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "key_points"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "key_points": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            }
        }
    }


def parse_response(response: dict, expected_ids: set[str]) -> tuple[dict[str, list[str]], int]:
    """Parse structured summaries response and return (dict[id -> list[points]], tokens_used)."""
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
        if not isinstance(document, dict) or set(document) != {"summaries"}:
            raise ValueError
        rows = document["summaries"]
        if not isinstance(rows, list):
            raise ValueError

        outputs = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"id", "key_points"}:
                raise ValueError
            sid = row["id"]
            pts = row["key_points"]
            if not isinstance(sid, str) or sid not in expected_ids or sid in outputs:
                raise ValueError
            if not isinstance(pts, list) or not all(isinstance(p, str) for p in pts):
                raise ValueError
            outputs[sid] = [p.strip() for p in pts if p.strip()]

        tokens = 0
        metadata = response.get("usageMetadata", {})
        if isinstance(metadata, dict) and "totalTokenCount" in metadata:
            tokens = int(metadata["totalTokenCount"])

        return outputs, tokens
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise ProviderError("invalid_response") from None


def load_cache(path: str | Path) -> dict[str, list[str]]:
    """Load content-hash -> key_points mapping."""
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
            if isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v):
                result[k] = v
        return result
    except (OSError, ValueError, AttributeError):
        return {}


def save_cache(path: str | Path, entries: dict[str, list[str]]) -> None:
    """Save content-hash -> key_points mapping atomically."""
    write_atomic({
        "provider": "gemini",
        "model": MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "entries": dict(sorted(entries.items()))
    }, path)
