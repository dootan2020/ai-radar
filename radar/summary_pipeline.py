"""Story summarization orchestration: inputs extraction, content caching,
strict fact validation, and bounded Gemini execution.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from radar.items import instant
from radar.reader_priority import ordered_stories, load_editor_picks
from radar import summary_budget
from radar import summary_gemini as gemini
from radar import gemini_paid_budget
from radar import shadow_collector, transport
from radar.common import web_url
from radar.summary_sources import (source_record, primary_link, fit_inputs, clear_summary,
                                   publish_summary, SELECTION_VERSION)
from radar.summary_validation import validate_summary
from radar.translate import DIGITS, NUMBER_WORDS, SMALL_NUMBERS, VIETNAMESE

# Capitalized entities pattern (e.g. OpenAI, DeepSeek, Claude, Apple, Google, macOS)
ENTITY_TOKEN = re.compile(r"\b[A-Z][A-Za-z0-9_.+-]*(?:\s+[A-Z][A-Za-z0-9_.+-]*)*\b")
MIN_ARTICLE_TEXT_CHARS = 300
SUMMARY_RETRY_DELAY = 0.25
DEFAULT_BUDGET = 180.0
MIN_REQUEST_TIMEOUT = 3.0
ARTICLE_FAILURE_TTL = 24 * 60 * 60
PAYWALL_TEXT = re.compile(
    r"\b(?:subscribe to (?:read|continue)|sign in to (?:read|continue)|"
    r"subscriber[- ]only|members[- ]only|unlock the full article|please subscribe)\b",
    re.IGNORECASE,
)


class _ArticleTextParser(HTMLParser):
    """Preserve paragraph boundaries and in-body links, excluding publisher furniture."""

    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "blockquote", "figcaption", "tr", "div"}

    def __init__(self, prefer_body=False, prefer_article=False, article_depth=1):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts, self.links, self.buffer = [], [], [], []
        self.anchor = None
        self.prefer_body, self.has_body = prefer_body, False
        self.prefer_article, self.has_article = prefer_article, False
        self.article_depth, self.max_article_depth = article_depth, 0

    def flush(self):
        value = " ".join("".join(self.buffer).split())
        if value:
            self.parts.append(value)
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            if tag == "br":
                self.buffer.append(" ")
            return
        attrs = dict(attrs)
        if tag in self.BLOCKS:
            self.flush()
        body = "entry-content" in attrs.get("class", "").split() or (
            attrs.get("data-framer-name") == "Blog content"
            and attrs.get("data-framer-component-type") == "RichTextContainer")
        self.has_body |= body
        self.has_article |= tag == "article"
        depth = sum(t == "article" for t, _, _ in self.stack) + (tag == "article")
        self.max_article_depth = max(self.max_article_depth, depth)
        readable = body or (not self.prefer_body and (
            (tag == "article" and depth >= self.article_depth)
            or (tag == "main" and not self.prefer_article)))
        classes = attrs.get("class", "") + " " + attrs.get("id", "")
        skipped = tag in {"script", "style", "noscript", "nav", "footer", "header", "aside"} or bool(
            re.search(r"(?:^|[ _-])(?:related|recommended|advertisement|author-bio|newsletter|cookie|social-share)(?:$|[ _-])", classes, re.I))
        self.stack.append((tag, readable, skipped))
        if tag == "a" and self.readable():
            self.anchor = [attrs.get("href", ""), ""]

    def readable(self):
        return not any(skip for _, _, skip in self.stack) and any(read for _, read, _ in self.stack)

    def handle_endtag(self, tag):
        if tag in self.BLOCKS or tag in {"article", "main"}:
            self.flush()
        if tag == "a" and self.anchor:
            self.links.append(tuple(self.anchor))
            self.anchor = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.readable():
            self.buffer.append(data)
            if self.anchor:
                self.anchor[1] += data


def _pandaily_article_html(html: str, url: str) -> str:
    """Read only the matching post from public Remix loader data, never execute JS."""
    if urlsplit(url).hostname not in {"pandaily.com", "www.pandaily.com"}:
        return ""
    pattern = r'window\.__remixContext\.streamController\.enqueue\(("(?:[^"\\]|\\.)*")\)'
    for match in re.finditer(pattern, html):
        try:
            values = json.loads(json.loads(match[1]))
            if not isinstance(values, list):
                continue

            def field(node, name):
                if not isinstance(node, dict):
                    return None
                for key, ref in node.items():
                    if (isinstance(key, str) and re.fullmatch(r"_\d+", key)
                            and int(key[1:]) < len(values) and values[int(key[1:])] == name
                            and type(ref) is int and 0 <= ref < len(values)):
                        return values[ref]
                return None

            post = field(field(field(values[0], "loaderData"), "routes/$slug"), "post")
            content = field(post, "content")
            if field(post, "slug") == urlsplit(url).path.strip("/") and isinstance(content, str):
                return content
        except (ValueError, TypeError, IndexError):
            continue
    return ""


def article_url(story: dict) -> str | None:
    url = web_url(story.get("url"))
    if not url:
        url = next((web_url(c.get("url")) for c in story.get("coverage") or []
                    if isinstance(c, dict) and web_url(c.get("url"))), None)
    return url


def parse_article(html, url):
    """Prefer the labelled article body over a main region containing related news."""
    parser = _ArticleTextParser()
    parser.feed(html)
    parser.flush()
    if parser.has_body or parser.has_article:
        parser = _ArticleTextParser(prefer_body=parser.has_body, prefer_article=True,
                                    article_depth=parser.max_article_depth)
        parser.feed(html)
        parser.flush()
    if not parser.parts:
        article_html = _pandaily_article_html(html, url)
        if article_html:
            parser = _ArticleTextParser()
            parser.feed("<article>" + article_html + "</article>")
            parser.flush()
    return parser


def article_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def fetch_article_result(story: dict, robots_cache: dict | None = None, *, details=None) -> tuple[str, str | None]:
    """Return article text and a safe skip reason, respecting robots.txt."""
    url = article_url(story)
    if not url:
        return "", "no_url"
    if not url.lower().startswith("https://"):
        return "", "non_https"

    def fetch_without_redirects(target):
        return transport.read_url(target, allow_redirects=False)

    if robots_cache is None:
        robots_cache = {}

    # Cache parsed rules per origin, but evaluate permission for every path.
    robots = shadow_collector.check_robots(url, fetch_fn=fetch_without_redirects, robots_cache=robots_cache)
    if robots["robots_status"] not in (200, 404) or robots["disallowed"]:
        return "", "robots"

    try:
        response = fetch_without_redirects(url)
    except Exception as error:
        status = getattr(error, "code", getattr(error, "http_status", None))
        if isinstance(status, int) and 300 <= status < 400:
            return "", "redirect"
        return "", "error"
    if (getattr(response, "status", None) != 200
            or getattr(response, "url", url) != url):
        return "", "redirect" if getattr(response, "status", None) in range(300, 400) or getattr(response, "url", url) != url else "error"
    if "html" not in getattr(response, "content_type", "").lower():
        return "", "non_html"

    try:
        parser = parse_article(str(response), url)
    except Exception:
        return "", "error"
    text = "\n".join(parser.parts)
    if PAYWALL_TEXT.search(text):
        return "", "paywall"
    if len(text) < MIN_ARTICLE_TEXT_CHARS:
        return "", "too_short"
    if details is not None:
        details["links"] = parser.links
    return text, None


def fetch_article_text(story: dict, robots_cache: dict | None = None) -> str:
    """Compatibility wrapper returning text only for a readable publisher page."""
    return fetch_article_result(story, robots_cache=robots_cache)[0]

# Common Vietnamese words that may appear capitalized at sentence starts
VN_GRAMMAR_CAPS = {
    "Đây", "Được", "Theo", "Các", "Những", "Người", "Một", "Hai", "Ba", "Bốn", "Năm",
    "Ngày", "Tháng", "Năm", "Tuy", "Nhưng", "Vì", "Do", "Nếu", "Khi", "Sau", "Trước",
    "Tại", "Trong", "Ngoài", "Trên", "Dưới", "Để", "Với", "Về", "Bởi", "Công", "Hãng",
    "Mô", "Bản", "Việc", "Nhóm", "Dự", "Tính", "Hiện", "Báo", "Tin", "Nghiên", "Ứng",
    "Hệ", "Cụ", "Thông", "Tổng", "Thực", "Phần", "Toàn", "Quốc", "Mới", "Cũ", "Đã", "Sẽ",
    "Đang", "Có", "Không", "Chưa", "Nhiều", "Ít", "Lớn", "Nhỏ", "Mạnh", "Yếu", "Nâng", "Hạ"
}


def story_inputs(story: dict) -> dict[str, Any]:
    """Extract canonical input data available in the pipeline for this story."""
    coverage_items = []
    for c in story.get("coverage") or []:
        if isinstance(c, dict):
            coverage_items.append({
                "publisher": str(c.get("publisher") or ""),
                "title": str(c.get("title") or "").strip(),
                "summary": str(c.get("summary") or "").strip(),
                "url": str(c.get("url") or "").strip(),
                "published_at": str(c.get("published_at") or ""),
                "metrics": c.get("metrics") if isinstance(c.get("metrics"), dict) else {}
            })
    # Deterministic sort for stable content hashing
    coverage_items.sort(key=lambda x: (x["publisher"], x["title"], x["published_at"]))

    return {
        "id": str(story.get("id") or ""),
        "title": str(story.get("title") or "").strip(),
        "summary": str(story.get("summary") or "").strip(),
        "article_text": str(story.get("_summary_article_text") or "").strip(),
        "published_at": str(story.get("published_at") or ""),
        "coverage": coverage_items
    }


def article_signature(story):
    stable = {key: story.get(key) for key in ("id", "url", "title", "summary")}
    stable["coverage"] = sorted([
        {key: c.get(key) for key in ("url", "title", "summary", "publisher")}
        for c in story.get("coverage") or [] if isinstance(c, dict)
    ], key=lambda c: json.dumps(c, sort_keys=True))
    return content_hash(stable)


def content_hash(inputs: dict[str, Any]) -> str:
    """Identity includes model/prompt/selection and every source hash, excluding fetch time."""
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k != "fetched_at"}
        if isinstance(value, list):
            return [stable(v) for v in value]
        return value
    serialized = json.dumps([gemini.MODEL_ID, gemini.PROMPT_VERSION, SELECTION_VERSION, gemini.SYSTEM_INSTRUCTION, gemini.OUTPUT_SCHEMA, stable(inputs)],
                            sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def fit_story_inputs(inputs: dict[str, Any], max_chars: int) -> dict[str, Any] | None:
    return fit_inputs(inputs, max_chars)


def collect_inputs(story, article_text, links, robots_cache, *, fetch_primary=True, fetched_at=""):
    url = article_url(story) or ""
    publisher = next((c.get("publisher") for c in story.get("coverage") or []
                      if isinstance(c, dict) and c.get("url") == url and c.get("publisher")), "")
    outlet = source_record("outlet", "outlet", url, str(story.get("title") or ""), publisher,
                           article_text, fetched_at=fetched_at)
    outlet["published_at"] = story.get("published_at")
    sources = [outlet]
    primary = primary_link(links, url, str(story.get("title") or ""), article_text)
    missing_primary = bool(primary)
    if primary and fetch_primary:
        text, reason = fetch_article_result({"url": primary}, robots_cache=robots_cache)
        if text and not reason:
            sources.append(source_record("primary", "primary", primary, "", "", text, fetched_at=fetched_at))
            missing_primary = False
    seen = {source["url"] for source in sources}
    for coverage in story.get("coverage") or []:
        if not isinstance(coverage, dict):
            continue
        target = web_url(coverage.get("url"))
        text = str(coverage.get("summary") or "").strip()
        if not target or target in seen or not text or text in article_text:
            continue
        seen.add(target)
        sources.append(source_record(f"coverage{sum(s['role'] == 'coverage' for s in sources) + 1}",
                                     "coverage", target, str(coverage.get("title") or ""),
                                     str(coverage.get("publisher") or ""), text, excerpt=True))
        if sum(s["role"] == "coverage" for s in sources) == 2:
            break
    return {"id": str(story.get("id") or ""), "sources": sources, "missing_primary": missing_primary,
            "linked_primary": {"url": primary, "name": urlsplit(primary).hostname} if primary else None}


def is_thin_story(inputs: dict[str, Any]) -> bool:
    """Return True if the story has only 1 source and thin text content."""
    coverage = inputs.get("coverage") or []
    if len(coverage) > 1:
        return False
    total_chars = sum(len(inputs.get(key, "")) for key in ("title", "summary", "article_text"))
    for c in coverage:
        total_chars += len(c.get("title", "")) + len(c.get("summary", ""))
    return total_chars < 180


def extract_source_numbers(inputs: dict[str, Any]) -> set[str]:
    """Collect all valid numbers from story inputs (digits, month words, metrics)."""
    texts = [inputs.get("title", ""), inputs.get("summary", ""), inputs.get("article_text", "")]
    for c in inputs.get("coverage") or []:
        texts.append(c.get("title", ""))
        texts.append(c.get("summary", ""))
        metrics = c.get("metrics")
        if isinstance(metrics, dict):
            for v in metrics.values():
                if isinstance(v, (int, float)):
                    texts.append(str(int(v) if int(v) == v else v))

    full_text = " ".join(texts)
    numbers = set(DIGITS.findall(full_text))

    # Add standard month numbers and small number words from source
    lower_words = set(re.findall(r"[a-z]+", full_text.lower()))
    for num_str, word in NUMBER_WORDS.items():
        if word in lower_words:
            numbers.add(num_str)
    for num_str, word in SMALL_NUMBERS.items():
        if word in lower_words:
            numbers.add(num_str)

    # If publication year is in dates
    for d in re.findall(r"\b20\d\d\b", inputs.get("published_at", "") + full_text):
        numbers.add(d)

    return numbers


def extract_source_entities(inputs: dict[str, Any]) -> set[str]:
    """Collect proper nouns, model names, and publishers present in the inputs."""
    texts = [inputs.get("title", ""), inputs.get("summary", ""), inputs.get("article_text", "")]
    for c in inputs.get("coverage") or []:
        texts.append(c.get("title", ""))
        texts.append(c.get("summary", ""))
        pub = c.get("publisher", "")
        if pub:
            texts.append(pub.replace("-", " ").title())

    full_text = " ".join(texts)
    entities = {token.strip("._+-") for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_.+-]*", full_text.lower())}
    for match in ENTITY_TOKEN.finditer(full_text):
        ent = match.group().strip()
        if ent:
            entities.add(ent.lower())
            for part in ent.split():
                if len(part) >= 2:
                    entities.add(part.lower())
    # Vietnamese language names may be ASCII capitals; allow their translated
    # form only when the corresponding source language is explicitly present.
    for source_name, translated_name in (("english", "anh"), ("chinese", "trung")):
        if source_name in entities:
            entities.add(translated_name)
    return entities


def validate_key_points(inputs: dict[str, Any], key_points: list[str]) -> tuple[list[str] | None, str | None]:
    """Strictly validate generated key points against source inputs.

    Catches:
    - Invented facts / numbers / entities
    - Padding on thin inputs
    - Repetitive text or English leakage
    - Out-of-bounds length or empty output
    """
    if not isinstance(key_points, list) or not key_points:
        return None, "empty_output"

    cleaned = [p.strip() for p in key_points if isinstance(p, str) and p.strip()]
    if not cleaned:
        return None, "empty_output"

    # Thin input enforcement: when inputs are thin, emit at most 1 point; reject padding.
    thin = is_thin_story(inputs)
    if thin and len(cleaned) > 1:
        return None, "padding_rejected: thin story must emit at most 1 point"

    if len(cleaned) > 5:
        return None, "too_many_points"
    if inputs.get("article_text") and len(cleaned) < 3:
        return None, "too_few_points"
    if len({" ".join(point.lower().split()) for point in cleaned}) != len(cleaned):
        return None, "duplicate_points"

    source_numbers = extract_source_numbers(inputs)
    source_entities = extract_source_entities(inputs)

    for point in cleaned:
        if len(point) < 15:
            return None, "point_too_short"
        if len(point) > 300:
            return None, "point_too_long"

        # Must be natural Vietnamese
        if not VIETNAMESE.search(point):
            return None, "untranslated_vietnamese_missing"

        # Repetition loop check
        words = point.lower().split()
        for i in range(len(words) - 2):
            if words[i] == words[i + 1] == words[i + 2]:
                return None, "repetition_detected"

        # Number integrity: any number in point must be grounded in source
        point_numbers = set(DIGITS.findall(point))
        added_numbers = point_numbers - source_numbers
        if added_numbers:
            return None, f"invented_number: {','.join(sorted(added_numbers))}"

        # Entity integrity: any distinctive capitalized entity in point must be grounded in source
        point_words = point.split()
        for word in point_words:
            clean_word = re.sub(r"^[^\w]+|[^\w]+$", "", word)
            if not clean_word:
                continue
            # Sentence-leading entities need the same grounding as other entities.
            if clean_word[0].isupper() and clean_word not in VN_GRAMMAR_CAPS:
                lower_val = clean_word.lower()
                # Check if it was in source entities
                if lower_val not in source_entities and clean_word.isascii():
                    return None, f"invented_entity: {clean_word}"

    return cleaned, None


def _request_gemini(stories_batch: list[dict], config: gemini.Config, transport_fn, timeout: float):
    """Execute REST request in a bounded daemon thread."""
    state = {}

    def work():
        try:
            body = gemini.request_body(stories_batch)
            response = transport_fn(body, config.api_key, timeout)
            expected_ids = {s["id"] for s in stories_batch}
            outputs, tokens = gemini.parse_response(response, expected_ids)
            state["outputs"] = outputs
            state["tokens"] = tokens
        except gemini.ProviderError as error:
            code = str(error)
            state["error"] = code if gemini.HTTP_CODE_PATTERN.fullmatch(code) or code in {
                "http_error", "transport_error", "malformed_response", "response_too_large", "invalid_response"
            } else "provider_error"
        except Exception:
            state["error"] = "provider_error"

    worker = threading.Thread(target=work, daemon=True, name="radar-summary-gemini")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return {}, 0, "timeout", True
    return state.get("outputs", {}), state.get("tokens", 0), state.get("error"), False


def story_worth_score(story: dict, now_dt: datetime | None = None) -> float:
    """Extract or calculate the worth score for a story, defaulting to 0.0."""
    ws = story.get("worth_score")
    if ws is not None:
        try:
            return float(ws)
        except (ValueError, TypeError):
            pass
    if now_dt:
        try:
            from radar.worth import calculate_worth
            w = calculate_worth(story, now_dt)
            return float(w.get("score") or 0.0)
        except Exception:
            pass
    return 0.0


def is_in_ranking_window(story: dict, gen_dt: datetime, window_hours: float) -> bool:
    """Return True if story was published within the ranking window from generated_at.

    Matches site/feed.js:
    const t = ms(st.published_at); return t && t >= from && t <= gen + 3e5;
    """
    pub_dt = instant(story.get("published_at"))
    if not pub_dt:
        return False
    from_dt = gen_dt - timedelta(hours=window_hours)
    to_dt = gen_dt + timedelta(seconds=300)
    return from_dt <= pub_dt <= to_dt


def summarize_payload(payload: dict,
                      cache: dict[str, dict],
                      *,
                      config: gemini.Config | None = None,
                      transport_fn=None,
                      article_fetch_fn=None,
                      article_failures: dict | None = None,
                      article_inputs: dict | None = None,
                      editor_picks: list | None = None,
                      ledger_path: str | None = None,
                      script_path: str | None = None,
                      budget: float = DEFAULT_BUDGET,
                      clock=time.monotonic,
                      now=None) -> tuple[dict, bool]:
    """Summarize eligible stories in payload, annotating them with `key_points`.

    Returns (summary_stats, worker_alive).
    """
    # Resolve the wall clock per call, not at import time: summarize.main
    # prunes the stamps written here with time.time(), so both must share it.
    now = time.time if now is None else now
    started = clock()
    config = config or gemini.config_from_env()
    transport_fn = transport_fn or gemini.transport
    article_fetch_fn = article_fetch_fn or fetch_article_text
    article_failures = article_failures if article_failures is not None else {}

    article_inputs = article_inputs if article_inputs is not None else {}
    stories = payload.get("stories") or []
    for story in stories:
        if isinstance(story, dict):
            # Restore only from validated evidence, never stale retained public fields.
            clear_summary(story)

    # Ranking window matching site/feed.js:
    # winH = Number(D.ranking && D.ranking.window_hours);
    # if (!Number.isFinite(winH) || winH <= 0) winH = 72;
    # const gen = ms(D.generated_at), from = gen - winH * 36e5;
    # allStories = asArray(D.stories).filter(st => { const t = ms(st.published_at); return t && t >= from && t <= gen + 3e5; })
    ranking = payload.get("ranking")
    win_h = ranking.get("window_hours") if isinstance(ranking, dict) else None
    try:
        window_hours = float(win_h) if win_h is not None and float(win_h) > 0 else 72.0
    except (ValueError, TypeError):
        window_hours = 72.0

    gen_dt = instant(payload.get("generated_at"))
    if gen_dt is None:
        pub_dates = [instant(s.get("published_at")) for s in stories if isinstance(s, dict)]
        pub_dates = [dt for dt in pub_dates if dt]
        if pub_dates:
            gen_dt = max(pub_dates)
        else:
            now_val = now() if callable(now) else now
            gen_dt = datetime.fromtimestamp(now_val, tz=timezone.utc) if isinstance(now_val, (int, float)) else datetime.now(timezone.utc)

    eligible_stories = []
    for s in stories:
        if not isinstance(s, dict):
            continue
        if s.get("kind") == "event" or "event" in (s.get("groups") or []):
            continue
        if not is_in_ranking_window(s, gen_dt, window_hours):
            # Stories outside the window are not summarised at all
            continue
        eligible_stories.append(s)

    # Order stories: highest worth_score first, newest first on ties
    def sort_key(s: dict):
        score = story_worth_score(s, gen_dt)
        pub = instant(s.get("published_at"))
        ts = pub.timestamp() if pub else 0.0
        return (score, ts)

    eligible_stories.sort(key=sort_key, reverse=True)
    if config.paid:
        ordered, _ = ordered_stories(payload, editor_picks if editor_picks is not None else load_editor_picks())
        order = {id(story): index for index, story in enumerate(ordered)}
        eligible_stories.sort(key=lambda story: order[id(story)])

    stats = {
        "model": gemini.MODEL_ID,
        "prompt_version": gemini.PROMPT_VERSION,
        "status": "disabled",
        "stories": len(eligible_stories),
        "summarized": 0,
        "cache_hits": 0,
        "pending": 0,
        "requests": 0,
        "tokens": 0,
        "rejected": 0,
        "skipped": 0,
        "trimmed": 0,
        "input_chars": 0,
        "skipped_reasons": {},
        "rejected_reasons": [],
        "machine_written": True,
        "error": None,
    }

    request_now = now() if callable(now) else now
    restored = set()
    # The article cache carries the exact evidence used for validation. It can
    # restore every later story even when the first uncached story cannot run.
    for story in eligible_stories:
        signature = article_signature(story)
        entry = article_inputs.get(signature)
        if not isinstance(entry, dict) or entry.get("prompt_version") != gemini.PROMPT_VERSION:
            continue
        stamp, inputs = entry.get("time"), entry.get("inputs")
        if (type(stamp) not in (int, float) or not 0 <= request_now - stamp < ARTICLE_FAILURE_TTL
                or not isinstance(inputs, dict) or not isinstance(inputs.get("sources"), list)):
            continue
        cached = cache.get(content_hash(inputs))
        if cached:
            points, _ = validate_summary(inputs, cached)
            if points:
                publish_summary(story, points, inputs, gemini.PROMPT_VERSION)
                stats["cache_hits"] += 1
                restored.add(id(story))
    if eligible_stories and len(restored) == len(eligible_stories):
        stats["status"] = "cache"
        payload["summary"] = stats
        return stats, False
    reserve_script = not config.paid and summary_budget.is_script_reserve_active(
        now=request_now, script_path=script_path, ledger_path=ledger_path)
    gate_error = None
    if not config.api_key:
        gate_error = "missing_key"
    elif not config.confirmed:
        gate_error = "free_tier_unconfirmed"
    elif not config.max_requests or not config.batch_size or not config.max_chars:
        gate_error = "configuration_limit"
    elif config.paid:
        if not gemini_paid_budget.remaining_tokens(gemini_paid_budget.ledger_path(), "summary", now=request_now):
            gate_error = "paid_summary_daily_tokens"
    else:
        gate_error = summary_budget.capacity_error(
            ledger_path, config.daily_requests_limit, config.daily_tokens_limit,
            gemini.MAX_ESTIMATED_TOKENS_PER_REQUEST, request_now,
            reserve_for_script=reserve_script)
    if gate_error:
        stats["error"] = gate_error
        stats["pending"] = len(eligible_stories) - stats["cache_hits"]
        stats["status"] = "partial" if stats["cache_hits"] else "failed"
        payload["summary"] = stats
        return stats, False
    stats["status"] = "failed"

    # Check if remaining time is insufficient before starting story loop
    if budget - (clock() - started) < MIN_REQUEST_TIMEOUT:
        stats["error"] = "time_budget"
        stats["pending"] = len(eligible_stories)
        stats["status"] = "failed"
        payload["summary"] = stats
        return stats, False

    # Read in ranking order and stop once a request-sized batch is ready.
    story_map = {}
    missing = []
    failure_now = now() if callable(now) else now
    shared_robots_cache = {}
    for story in eligible_stories:
        if id(story) in restored:
            continue
        if budget - (clock() - started) < MIN_REQUEST_TIMEOUT:
            stats["error"] = "time_budget"
            break
        sid = story.get("id")
        url = article_url(story)
        url_hash = article_url_hash(url) if url else None
        remembered = article_failures.get(article_signature(story)) or (article_failures.get(url_hash) if url_hash else None)
        if remembered:
            failed_at = remembered.get("time") if isinstance(remembered, dict) else None
            if isinstance(failed_at, (int, float)) and 0 <= failure_now - failed_at < ARTICLE_FAILURE_TTL:
                reason = remembered.get("reason", "error")
                stats["skipped"] += 1
                stats["skipped_reasons"][reason] = stats["skipped_reasons"].get(reason, 0) + 1
                story.pop("key_points", None)
                story.pop("key_points_machine", None)
                story.pop("key_points_source", None)
                continue
            article_failures.pop(url_hash, None)
            article_failures.pop(article_signature(story), None)
        details = {}
        if article_fetch_fn is fetch_article_text:
            article_text, skip_reason = fetch_article_result(story, robots_cache=shared_robots_cache, details=details)
        else:
            try:
                article_text = article_fetch_fn(story, robots_cache=shared_robots_cache)
            except TypeError:
                article_text = article_fetch_fn(story)
            skip_reason = None
        if len(article_text or "") < MIN_ARTICLE_TEXT_CHARS:
            skip_reason = skip_reason or "too_short"
            stats["skipped"] += 1
            stats["skipped_reasons"][skip_reason] = stats["skipped_reasons"].get(skip_reason, 0) + 1
            if url_hash:
                article_failures[url_hash] = {"reason": skip_reason, "time": failure_now}
            story.pop("key_points", None)
            story.pop("key_points_machine", None)
            story.pop("key_points_source", None)
            continue
        inputs = collect_inputs(story, article_text, details.get("links", []), shared_robots_cache,
                                fetch_primary=budget - (clock() - started) >= MIN_REQUEST_TIMEOUT,
                                fetched_at=datetime.fromtimestamp(failure_now, timezone.utc).isoformat())
        fitted = fit_story_inputs(inputs, config.max_chars)
        if fitted is None:
            if url_hash:
                article_failures[article_signature(story)] = {"reason": "input_limit", "time": failure_now}
            stats["skipped"] += 1
            stats["skipped_reasons"]["input_limit"] = stats["skipped_reasons"].get("input_limit", 0) + 1
            for key in ("key_points", "key_points_machine", "key_points_source", "key_points_prompt_version"):
                story.pop(key, None)
            continue
        if len(json.dumps(inputs, ensure_ascii=False)) > config.max_chars:
            stats["trimmed"] += 1
        inputs = fitted
        article_inputs[article_signature(story)] = {
            "inputs": inputs, "time": failure_now, "prompt_version": gemini.PROMPT_VERSION}
        chash = content_hash(inputs)
        story_map[sid] = {"story": story, "inputs": inputs, "hash": chash, "url_hash": url_hash}

        # Check content cache
        cached = cache.get(chash)
        if cached:
            valid_pts, reason = validate_summary(inputs, cached)
            if valid_pts:
                publish_summary(story, valid_pts, inputs, gemini.PROMPT_VERSION)
                stats["cache_hits"] += 1
                continue
            else:
                del cache[chash]

        missing.append(sid)
        if len(missing) >= config.batch_size:
            break

    if not missing:
        pending_count = len(eligible_stories) - (stats["cache_hits"] + stats["summarized"])
        stats["pending"] = pending_count if stats["error"] else stats["skipped"]
        stats["status"] = "partial" if stats["skipped"] or stats["error"] else ("cache" if stats["cache_hits"] else "ok")
        payload["summary"] = stats
        return stats, False

    if budget - (clock() - started) < MIN_REQUEST_TIMEOUT:
        stats["error"] = "time_budget"
        stats["pending"] = len(eligible_stories) - (stats["cache_hits"] + stats["summarized"])
        stats["status"] = "partial" if stats["cache_hits"] else "failed"
        payload["summary"] = stats
        return stats, False

    # Prepare batch of stories to request
    batch_items = []
    batch_chars = 0
    for sid in missing:
        item_inputs = story_map[sid]["inputs"]
        serialized_len = len(json.dumps(item_inputs, ensure_ascii=False))
        if len(batch_items) >= config.batch_size or batch_chars + serialized_len > config.max_chars:
            break
        batch_items.append(item_inputs)
        batch_chars += serialized_len

    if not batch_items:
        stats["error"] = "input_limit"
        stats["status"] = "partial" if stats["cache_hits"] else "failed"
        stats["pending"] = len(eligible_stories) - stats["cache_hits"]
        payload["summary"] = stats
        return stats, False

    # Reserve budget in ledger
    reserve_now = now()
    # Reserve input tokens plus the full output ceiling and fixed prompt overhead.
    request_body = gemini.request_body(batch_items)
    stats["input_chars"] = batch_chars
    stats["input_bytes"] = len(gemini.encode_request(request_body))
    stats["source_chars"] = sum(len(p["text"]) for item in batch_items for source in item["sources"] for p in source["paragraphs"])
    estimated_toks = len(gemini.encode_request(request_body)) + gemini.MAX_OUTPUT_TOKENS
    paid_reservation = None
    reserve_err = None if config.paid else summary_budget.reserve(
        ledger_path,
        request_limit=config.daily_requests_limit,
        token_limit=config.daily_tokens_limit,
        estimated_tokens=estimated_toks,
        now=reserve_now,
        last_story_id=batch_items[-1]["id"],
        reserve_for_script=reserve_script,
    )
    if not reserve_err and config.paid:
        reserve_err, paid_reservation = gemini_paid_budget.reserve(
            gemini_paid_budget.ledger_path(), estimated_toks, now=reserve_now, consumer="summary")

    if reserve_err:
        stats["error"] = reserve_err
        stats["pending"] = len(eligible_stories) - stats["cache_hits"]
        stats["status"] = "failed"
        payload["summary"] = stats
        return stats, False

    # Execute REST request
    stats["requests"] = 1
    remaining_time = min(config.timeout, max(0.0, budget - (clock() - started)))
    outputs, tokens, err, alive = _request_gemini(batch_items, config, transport_fn, remaining_time)
    retry_now = None
    if err and err.startswith("http_503:"):
        remaining_time = min(config.timeout, max(0.0, budget - (clock() - started)))
        if remaining_time > SUMMARY_RETRY_DELAY:
            time.sleep(SUMMARY_RETRY_DELAY)
            retry_now = now()
            retry_err = None if config.paid else summary_budget.reserve(
                ledger_path,
                request_limit=config.daily_requests_limit,
                token_limit=config.daily_tokens_limit,
                estimated_tokens=estimated_toks,
                now=retry_now,
                last_story_id=batch_items[-1]["id"],
                reserve_for_script=reserve_script,
            )
            if not retry_err and config.paid:
                retry_err, retry_reservation = gemini_paid_budget.reserve(
                    gemini_paid_budget.ledger_path(), estimated_toks, now=retry_now, consumer="summary")
            if retry_err:
                err = retry_err
            else:
                stats["requests"] += 1
                if config.paid:
                    paid_reservation = retry_reservation
                outputs, tokens, err, alive = _request_gemini(
                    batch_items, config, transport_fn,
                    min(config.timeout, max(0.0, budget - (clock() - started))),
                )
    stats["tokens"] = tokens
    stats["error"] = err

    if config.paid:
        gemini_paid_budget.settle(gemini_paid_budget.ledger_path(), paid_reservation, tokens,
                                 now=retry_now or reserve_now)
    if tokens and ledger_path and not config.paid:
        summary_budget.update_actual_tokens(ledger_path, retry_now or reserve_now, tokens)

    # Process and validate outputs
    for item in batch_items:
        sid = item["id"]
        story_info = story_map[sid]
        story_obj = story_info["story"]
        story_h = story_info["hash"]

        candidate_pts = outputs.get(sid)
        if candidate_pts:
            valid_pts, reason = validate_summary(story_info["inputs"], candidate_pts)
            if valid_pts:
                publish_summary(story_obj, valid_pts, story_info["inputs"], gemini.PROMPT_VERSION)
                cache[story_h] = valid_pts
                stats["summarized"] += 1
                if story_info["url_hash"]:
                    article_failures.pop(story_info["url_hash"], None)
            else:
                stats["rejected"] += 1
                if story_info["url_hash"]:
                    article_failures[article_signature(story_obj)] = {"reason": "validation_rejected", "time": reserve_now}
                for key in ("key_points", "key_points_machine", "key_points_source", "key_points_prompt_version"):
                    story_obj.pop(key, None)
                if reason and len(stats["rejected_reasons"]) < 10:
                    stats["rejected_reasons"].append({"id": sid, "reason": reason})
        else:
            # A failed or empty attempt must not monopolize the next run.
            if story_info["url_hash"]:
                article_failures[article_signature(story_obj)] = {"reason": "generation_failed", "time": reserve_now}
            # Leave story without key points, never a stub
            story_obj.pop("key_points", None)
            story_obj.pop("key_points_machine", None)
            story_obj.pop("key_points_source", None)

    pending_count = len(eligible_stories) - (stats["cache_hits"] + stats["summarized"])
    stats["pending"] = pending_count
    if stats["error"]:
        stats["status"] = "partial" if stats["summarized"] else "failed"
    else:
        stats["status"] = "ok" if pending_count == 0 else "partial"

    payload["summary"] = stats
    return stats, alive
