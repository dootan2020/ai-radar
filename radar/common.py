"""Normalization shared by public-source collectors."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
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


def resolve_timezone(tz):
    if tz is None:
        return None
    if isinstance(tz, timezone) or hasattr(tz, "utcoffset"):
        return tz
    if isinstance(tz, timedelta):
        return timezone(tz)
    if isinstance(tz, (int, float)):
        return timezone(timedelta(hours=tz))
    if isinstance(tz, str):
        tz = tz.strip()
        if tz.upper() in {"UTC", "GMT", "Z"}:
            return timezone.utc
        m = re.match(r"^UTC\s*([+-]\d{1,2})(?::?(\d{2}))?$", tz, re.I)
        if m:
            hours = int(m.group(1))
            mins = int(m.group(2) or 0)
            sign = -1 if hours < 0 else 1
            return timezone(timedelta(hours=hours, minutes=sign * mins))
        m = re.match(r"^([+-]\d{1,2})(?::?(\d{2}))?$", tz)
        if m:
            hours = int(m.group(1))
            mins = int(m.group(2) or 0)
            sign = -1 if hours < 0 else 1
            return timezone(timedelta(hours=hours, minutes=sign * mins))
        if tz in {"Asia/Ho_Chi_Minh", "Asia/Saigon", "Asia/Bangkok", "ICT"}:
            return timezone(timedelta(hours=7))
    return None


def iso_date(value, default_tz=None):
    """Accept ISO/RFC 2822 timestamps; unknown dates stay unknown."""
    if not value or not isinstance(value, (str, datetime)):
        return None
    date = None
    if isinstance(value, datetime):
        date = value
    else:
        s = value.strip()
        # A two-digit +HH/-HH offset after a time means hours (e.g. "+07" -> "+0700")
        s = re.sub(
            r'(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*)(?:GMT|UTC)?([+-]\d{2})(\s*(?:\([^)]*\))?\s*)$',
            r'\g<1>\g<2>00\g<3>',
            s
        )
        try:
            date = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            try:
                date = parsedate_to_datetime(s)
            except (ValueError, TypeError, OverflowError):
                for fmt in (
                    "%m/%d/%Y %I:%M:%S %p",
                    "%m/%d/%Y %I:%M %p",
                    "%d/%m/%Y %H:%M:%S",
                    "%d/%m/%Y %H:%M",
                    "%Y/%m/%d %H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                ):
                    try:
                        date = datetime.strptime(re.sub(r"\s+", " ", s), fmt)
                        break
                    except (ValueError, TypeError):
                        pass

    if date is None:
        return None

    resolved_tz = resolve_timezone(default_tz)
    if date.tzinfo is None:
        if resolved_tz is not None:
            date = date.replace(tzinfo=resolved_tz)
        else:
            return None

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
