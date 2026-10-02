"""Normalization shared by public-source collectors."""

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from radar.classification import classify


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_text(value, limit=300):
    parser = _Text()
    parser.feed(str(value or ""))
    return " ".join("".join(parser.parts).split())[:limit]


def iso_date(value):
    """Accept ISO/RFC 2822 timestamps; unknown dates stay unknown."""
    if not value or not isinstance(value, (str, datetime)):
        return None
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def web_url(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value or "")
        return value if parts.scheme in {"http", "https"} and parts.netloc and not parts.username else None
    except ValueError:
        return None


def number(value):
    """Missing measurements are null, never a guessed zero."""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = int(str(value).replace(",", "").strip())
        return value if value >= 0 else None
    except (TypeError, ValueError):
        return None


def stable_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def vi_error(error):
    """The reader's wording of a source failure. `error` stays the technical evidence for maintainers;
    this is what the page shows. Unknown failures get a plain sentence, never the English detail."""
    if error is None:
        return None
    text = str(error)
    if text.startswith("Disabled: "):
        return "Tạm tắt: " + text[len("Disabled: "):]
    lower = text.lower()
    status = re.search(r"\bHTTP(?: Error)? (\d{3})\b", text)
    if "build deadline" in lower:
        return "Hết thời hạn dựng bản tin trước khi nguồn trả lời"
    if "timeout" in lower or "timed out" in lower or "deadline" in lower:
        return "Nguồn không trả lời kịp thời hạn chờ"
    if status:
        return f"Nguồn trả mã lỗi HTTP {status[1]}"
    if "exceeds 8 mib" in lower or "limit" in lower:
        return "Phản hồi của nguồn vượt giới hạn 8 MiB"
    if any(word in lower for word in ("urlerror", "connection", "getaddrinfo", "unreachable", "ssl")):
        return "Không kết nối được tới nguồn"
    if any(word in lower for word in ("parseerror", "jsondecodeerror", "xml", "json", "valueerror", "keyerror", "typeerror")):
        return "Nguồn trả dữ liệu sai định dạng nên không đọc được"
    return "Không đọc được nguồn này"


def source_result(source, count=0, error=None):
    error = str(error)[:300] if error is not None else None
    return {key: source[key] for key in ("id", "name", "lab", "kind")} | {
        "ok": error is None, "count": count, "error": error, "error_vi": vi_error(error),
    }
