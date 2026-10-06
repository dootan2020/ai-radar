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
from radar import summary_budget
from radar import summary_gemini as gemini
from radar import shadow_collector, transport
from radar.common import web_url
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
    """Collect readable text from semantic article/main regions only."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.main_depth = 0
        self.skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "aside"}:
            self.skip_depth += 1
        if tag == "article":
            self.article_depth += 1
        if tag == "main":
            self.main_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "aside"}:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag == "article":
            self.article_depth = max(0, self.article_depth - 1)
        if tag == "main":
            self.main_depth = max(0, self.main_depth - 1)

    def handle_data(self, data):
        if not self.skip_depth and (self.article_depth or self.main_depth):
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def article_url(story: dict) -> str | None:
    url = web_url(story.get("url"))
    if not url:
        url = next((web_url(c.get("url")) for c in story.get("coverage") or []
                    if isinstance(c, dict) and web_url(c.get("url"))), None)
    return url


def article_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def fetch_article_result(story: dict, robots_cache: dict | None = None) -> tuple[str, str | None]:
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

    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin in robots_cache:
        robots = robots_cache[origin]
    else:
        robots = shadow_collector.check_robots(url, fetch_fn=fetch_without_redirects, robots_cache=robots_cache)
        robots_cache[origin] = robots
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

    parser = _ArticleTextParser()
    try:
        parser.feed(str(response))
    except Exception:
        return "", "error"
    text = " ".join(parser.parts)
    if PAYWALL_TEXT.search(text):
        return "", "paywall"
    if len(text) < MIN_ARTICLE_TEXT_CHARS:
        return "", "too_short"
    return text[:gemini.MAX_ARTICLE_TEXT_CHARS], None


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


def content_hash(inputs: dict[str, Any]) -> str:
    """Stable SHA-256 hash of the story inputs for content-based caching."""
    serialized = json.dumps(inputs, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
    entities = set()
    for match in ENTITY_TOKEN.finditer(full_text):
        ent = match.group().strip()
        if ent:
            entities.add(ent.lower())
            for part in ent.split():
                if len(part) >= 2:
                    entities.add(part.lower())
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
        for idx, word in enumerate(point_words):
            clean_word = re.sub(r"^[^\w]+|[^\w]+$", "", word)
            if not clean_word:
                continue
            # If word is capitalized and not first word of the sentence
            if idx > 0 and clean_word[0].isupper() and clean_word not in VN_GRAMMAR_CAPS:
                lower_val = clean_word.lower()
                # Check if it was in source entities
                if lower_val not in source_entities and not VIETNAMESE.search(clean_word):
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
                      cache: dict[str, list[str]],
                      *,
                      config: gemini.Config | None = None,
                      transport_fn=None,
                      article_fetch_fn=None,
                      article_failures: dict | None = None,
                      ledger_path: str | None = None,
                      script_path: str | None = None,
                      budget: float = DEFAULT_BUDGET,
                      clock=time.monotonic,
                      now=time.time) -> tuple[dict, bool]:
    """Summarize eligible stories in payload, annotating them with `key_points`.

    Returns (summary_stats, worker_alive).
    """
    started = clock()
    config = config or gemini.config_from_env()
    transport_fn = transport_fn or gemini.transport
    article_fetch_fn = article_fetch_fn or fetch_article_text
    article_failures = article_failures if article_failures is not None else {}

    stories = payload.get("stories") or []
    for story in stories:
        if isinstance(story, dict) and story.get("key_points_prompt_version") != gemini.PROMPT_VERSION:
            story.pop("key_points", None)
            story.pop("key_points_machine", None)
            story.pop("key_points_source", None)
            story.pop("key_points_prompt_version", None)

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
        "skipped_reasons": {},
        "rejected_reasons": [],
        "machine_written": True,
        "error": None,
    }

    # Do not fetch pages when configuration or the run deadline precludes a request.
    if not config.api_key:
        stats["error"] = "missing_key"
        stats["pending"] = len(eligible_stories)
        payload["summary"] = stats
        return stats, False
    if not config.confirmed:
        stats["error"] = "free_tier_unconfirmed"
        stats["pending"] = len(eligible_stories)
        payload["summary"] = stats
        return stats, False
    request_now = now() if callable(now) else now
    reserve_script = summary_budget.is_script_reserve_active(
        now=request_now,
        script_path=script_path,
        ledger_path=ledger_path,
    )
    capacity_error = summary_budget.capacity_error(
        ledger_path, config.daily_requests_limit, config.daily_tokens_limit,
        gemini.MAX_ESTIMATED_TOKENS_PER_REQUEST, request_now,
        reserve_for_script=reserve_script)
    if capacity_error:
        stats["error"] = capacity_error
        stats["status"] = "failed"
        stats["pending"] = len(eligible_stories)
        payload["summary"] = stats
        return stats, False

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
        if budget - (clock() - started) < MIN_REQUEST_TIMEOUT:
            stats["error"] = "time_budget"
            break
        sid = story.get("id")
        url = article_url(story)
        url_hash = article_url_hash(url) if url else None
        remembered = article_failures.get(url_hash) if url_hash else None
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
        if article_fetch_fn is fetch_article_text:
            article_text, skip_reason = fetch_article_result(story, robots_cache=shared_robots_cache)
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
        story["_summary_article_text"] = article_text[:gemini.MAX_ARTICLE_TEXT_CHARS]
        inputs = story_inputs(story)
        story.pop("_summary_article_text", None)
        chash = content_hash(inputs)
        story_map[sid] = {"story": story, "inputs": inputs, "hash": chash, "url_hash": url_hash}

        # Check content cache
        cached = cache.get(chash)
        if cached:
            valid_pts, reason = validate_key_points(inputs, cached)
            if valid_pts:
                story["key_points"] = valid_pts
                story["key_points_machine"] = True
                story["key_points_source"] = "machine"
                story["key_points_prompt_version"] = gemini.PROMPT_VERSION
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
        stats["pending"] = len(missing)
        payload["summary"] = stats
        return stats, False

    # Reserve budget in ledger
    reserve_now = now()
    # Reserve input tokens plus the full output ceiling and fixed prompt overhead.
    estimated_toks = max(
        500,
        int(batch_chars / 3.5) + gemini.MAX_OUTPUT_TOKENS + gemini.INPUT_TOKEN_OVERHEAD,
    )
    reserve_err = summary_budget.reserve(
        ledger_path,
        request_limit=config.daily_requests_limit,
        token_limit=config.daily_tokens_limit,
        estimated_tokens=estimated_toks,
        now=reserve_now,
        last_story_id=batch_items[-1]["id"],
        reserve_for_script=reserve_script,
    )

    if reserve_err:
        stats["error"] = reserve_err
        stats["pending"] = len(missing)
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
            retry_err = summary_budget.reserve(
                ledger_path,
                request_limit=config.daily_requests_limit,
                token_limit=config.daily_tokens_limit,
                estimated_tokens=estimated_toks,
                now=retry_now,
                last_story_id=batch_items[-1]["id"],
                reserve_for_script=reserve_script,
            )
            if retry_err:
                err = retry_err
            else:
                stats["requests"] += 1
                outputs, tokens, err, alive = _request_gemini(
                    batch_items, config, transport_fn,
                    min(config.timeout, max(0.0, budget - (clock() - started))),
                )
    stats["tokens"] = tokens
    stats["error"] = err

    if tokens and ledger_path:
        summary_budget.update_actual_tokens(ledger_path, retry_now or reserve_now, tokens)

    # Process and validate outputs
    for item in batch_items:
        sid = item["id"]
        story_info = story_map[sid]
        story_obj = story_info["story"]
        story_h = story_info["hash"]

        candidate_pts = outputs.get(sid)
        if candidate_pts:
            valid_pts, reason = validate_key_points(story_info["inputs"], candidate_pts)
            if valid_pts:
                story_obj["key_points"] = valid_pts
                story_obj["key_points_machine"] = True
                story_obj["key_points_source"] = "machine"
                story_obj["key_points_prompt_version"] = gemini.PROMPT_VERSION
                cache[story_h] = valid_pts
                stats["summarized"] += 1
                if story_info["url_hash"]:
                    article_failures.pop(story_info["url_hash"], None)
            else:
                stats["rejected"] += 1
                if reason and len(stats["rejected_reasons"]) < 10:
                    stats["rejected_reasons"].append({"id": sid, "reason": reason})
        else:
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
