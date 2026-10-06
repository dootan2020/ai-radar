"""Daily AI video script generation and mechanical fact verification.

Generates a 45-second video script for Reels/TikTok/Shorts based on the top 3 AI stories:
Hook (0-3s, 15-20 words) -> Hint ("Ba tin ... trong 45 giây") -> 3 story lines (<25 words each, most surprising fact first) -> CTA.
Uses the Gemini free-tier REST client, shared ledger, and strict mechanical fact checking.
Contract output: site/data/video-script.json (served as data/video-script.json).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import unicodedata

from radar.common import iso_date
from radar.items import instant
from radar.pipeline import write_atomic
from radar import summary_budget
from radar import summary_gemini as gemini
from radar.translate import DIGITS, NUMBER_WORDS, SMALL_NUMBERS, VIETNAMESE
from radar.worth import calculate_worth, uniq_coverage

MODEL_ID = "gemini-3.8-flash"
PROMPT_VERSION = "video-script-vi-1"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent"

TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
VIETNAM = timezone(timedelta(hours=7), TIMEZONE_NAME)
SCHEDULED_START_HOUR = 5  # 05:00 VN time (22:00 UTC previous day)

# Allowed standard terms in video format boilerplate
ALLOWED_BOILERPLATE_ENTITIES = {
    "ai", "ai-radar", "radar", "reels", "tiktok", "shorts", "tv", "pro", "app"
}

# Vietnamese grammar words that can appear capitalized at sentence / clause starts
VN_GRAMMAR_CAPS = {
    "Đây", "Được", "Theo", "Các", "Những", "Người", "Một", "Hai", "Ba", "Bốn", "Năm",
    "Ngày", "Tháng", "Tuy", "Nhưng", "Vì", "Do", "Nếu", "Khi", "Sau", "Trước", "Tại",
    "Trong", "Ngoài", "Trên", "Dưới", "Để", "Với", "Về", "Bởi", "Công", "Hãng", "Mô",
    "Bản", "Việc", "Nhóm", "Dự", "Tính", "Hiện", "Báo", "Tin", "Nghiên", "Ứng", "Hệ",
    "Cụ", "Thông", "Tổng", "Thực", "Phần", "Toàn", "Quốc", "Mới", "Cũ", "Đã", "Sẽ",
    "Đang", "Có", "Không", "Chưa", "Nhiều", "Ít", "Lớn", "Nhỏ", "Mạnh", "Yếu", "Nâng",
    "Hạ", "Bạn", "Mỗi", "Lý", "Và", "Bình", "Hãy", "Đón", "Cùng", "Gợi", "Mở", "Kết",
    "Thế", "Cho", "Xem", "Nghe", "Tự", "Rất", "Quá", "Đều"
}

VIETNAMESE_NUMBERS = {
    "mot": "1", "mốt": "1", "hai": "2", "ba": "3", "bon": "4", "bốn": "4",
    "nam": "5", "năm": "5", "sau": "6", "sáu": "6", "bay": "7", "bảy": "7",
    "tam": "8", "tám": "8", "chin": "9", "chín": "9", "muoi": "10", "mười": "10",
    "tram": "100", "trăm": "100", "nghin": "1000", "nghìn": "1000", "ngan": "1000",
    "ngàn": "1000", "trieu": "1000000", "triệu": "1000000", "ty": "1000000000", "tỷ": "1000000000"
}

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "its", "are", "was", "has", "have",
    "will", "into", "over", "after", "about", "says", "said", "than", "then", "what", "when",
    "your", "their", "they", "them", "how", "why", "who", "now", "new", "via"
}

KIND_OF_VIA = {
    "feed-media": "photo",
    "og:image": "photo",
    "linked-article": "photo",
    "youtube": "photo",
    "github-social": "graphic",
    "hf-thumbnail": "graphic",
    "ai": "photo"
}

SYSTEM_INSTRUCTION = """Bạn là biên tập viên kịch bản video ngắn (Reels, TikTok, Shorts) của ai-radar.
Nhiệm vụ: Viết kịch bản video 45 giây từ 3 tin AI nổi bật nhất trong ngày được chọn sẵn.

Cấu trúc kịch bản bắt buộc:
1. Mở đầu (hook): 0–3 giây, từ 15 đến 20 chữ. Nêu ngay sự thật/con số gây tò mò hoặc bất ngờ nhất trong 3 tin để giữ chân người xem ngay lập tức.
2. Gợi trước (hint): Khoảng 8-12 chữ, theo cấu trúc: 'Ba tin AI đáng chú ý nhất, trong 45 giây.'
3. Ba tin (stories): Đúng 3 tin tương ứng với 3 story id được cung cấp. Tin có chi tiết bất ngờ nhất ở phần Mở đầu phải được đặt làm Tin 1 để kết nối mạch lạc với Mở đầu. Mỗi tin đúng MỘT câu nói ngắn gọn, súc tích (dưới 25 chữ), nêu sự thật bất ngờ nhất lên trước.
4. Kêu gọi hành động (cta): Đúng một lời kêu gọi duy nhất (ví dụ: 'Mỗi sáng ai-radar chọn 3 tin AI đáng đọc nhất. Theo dõi để không bỏ lỡ. Bạn lo nhất tin nào? Bình luận cho mình biết.').

NGUYÊN TẮC BẮT BUỘC:
1. TUYỆT ĐỐI KHÔNG BỊA ĐẶT SỰ THẬT (No invented facts): Mọi con số, tên riêng, số tiền, ngày tháng, sản phẩm xuất hiện trong hook, từng câu tin và cta PHẢI xuất hiện chính xác trong dữ liệu được cung cấp (title, title_vi, summary, summary_vi, key_points). Tuyệt đối không tự suy diễn hay thêm bất kỳ số liệu hay tên riêng nào ngoài dữ liệu.
2. BẢO TOÀN DANH TỪ RIÊNG VÀ SỐ LIỆU: Giữ nguyên vẹn tên công ty, model, phiên bản, giá tiền, chỉ số đo lường.
3. NGÔN TỪ TỰ NHIÊN, CÔ ĐỌNG: Viết bằng tiếng Việt tự nhiên để đọc giọng nói trong 45 giây. Mỗi câu tin không quá 25 chữ.
4. ĐỊNH DẠNG: Trả về đúng JSON theo schema yêu cầu với đúng 3 stories. Không kèm lời mở đầu hay giải thích riêng."""


# ---------- Story selection (replicating site/feed.js choosePicks) ----------

def normalize_title_words(title: str) -> set[str]:
    """Normalize title words for event overlap calculation."""
    norm = unicodedata.normalize("NFKD", str(title or "").lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", norm)
    return {w for w in words if len(w) >= 3 and w not in STOP_WORDS}


def same_event(a: dict, b: dict, threshold: float = 0.34) -> bool:
    """Calculate Jaccard title overlap to prevent duplicate stories on the same event."""
    wa = normalize_title_words(a.get("title", ""))
    wb = normalize_title_words(b.get("title", ""))
    if not wa or not wb:
        return False
    inter = len(wa & wb)
    union = len(wa) + len(wb) - inter
    if union <= 0:
        return False
    return (inter / union) >= threshold


def is_news_coverage(c: dict) -> bool:
    """News coverage excludes Hacker News aggregator."""
    if not c or not isinstance(c, dict):
        return False
    return c.get("source") != "hn-ai" and c.get("publisher") != "hacker-news"


def news_coverage_of(st: dict, sources_map: dict | None = None) -> list[dict]:
    covs = uniq_coverage(st.get("coverage"), sources_map)
    return [c for c in covs if is_news_coverage(c)]


def pick_image_kind(st: dict) -> str:
    """Determine story lead image kind: 'photo', 'graphic', or 'cover'."""
    img = st.get("image")
    if img and isinstance(img, dict) and img.get("src"):
        return img.get("kind") or KIND_OF_VIA.get(img.get("via"), "photo")
    for c in st.get("coverage") or []:
        if not isinstance(c, dict):
            continue
        for m in c.get("media") or []:
            if isinstance(m, dict):
                is_img = m.get("type") == "image" or str(m.get("mime_type") or "").startswith("image/")
                if is_img and str(m.get("url") or "").startswith("https://"):
                    return "photo"
    url = str(st.get("url") or "")
    if re.search(r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)", url, re.I):
        return "photo"
    if re.search(r"https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+", url, re.I):
        return "graphic"
    if re.search(r"https?://huggingface\.co/(?:papers|models|datasets|spaces)/", url, re.I):
        return "graphic"
    return "cover"


def choose_picks(stories: list[dict],
                 sources_map: dict | None = None,
                 now_dt: datetime | None = None,
                 editor_picks: list[dict] | None = None) -> list[dict]:
    """Replicate feed.js choosePicks() in Python.

    Returns up to 3 high-worth stories backed by >= 2 independent news publishers.
    """
    story_map = {s.get("id"): s for s in stories if s.get("id")}

    def n_news(s: dict) -> int:
        return len(news_coverage_of(s, sources_map))

    def by_worth(s: dict):
        w = calculate_worth(s, now_dt, sources_map)
        pub_dt = instant(s.get("published_at"))
        ts = pub_dt.timestamp() if pub_dt else 0.0
        return (-w["score"], -ts)

    out = []
    editor_set = set()
    if editor_picks:
        for p in editor_picks:
            if len(out) >= 3:
                break
            pid = p.get("id") if isinstance(p, dict) else str(p)
            st = story_map.get(pid)
            if st and n_news(st) >= 2 and st not in out:
                out.append(st)
                editor_set.add(st["id"])

    candidates = [
        s for s in stories
        if s.get("id") not in editor_set and n_news(s) >= 2 and calculate_worth(s, now_dt, sources_map)["evidence"]
    ]
    candidates.sort(key=by_worth)

    if not out and candidates:
        photo_idx = next((i for i, s in enumerate(candidates) if pick_image_kind(s) == "photo"), -1)
        if photo_idx >= 0:
            out.append(candidates.pop(photo_idx))

    for s in candidates:
        if len(out) >= 3:
            break
        if not any(same_event(o, s) for o in out):
            out.append(s)

    if len(out) < 3:
        fallback = [
            s for s in stories
            if s.get("id") not in editor_set and s not in out and n_news(s) >= 2 and calculate_worth(s, now_dt, sources_map)["evidence"]
        ]
        fallback.sort(key=by_worth)
        for s in fallback:
            if len(out) >= 3:
                break
            if not any(same_event(o, s) for o in out):
                out.append(s)

    return out[:3]


# ---------- Mechanical fact extraction & verification ----------

def extract_numbers_from_text(text: str) -> set[str]:
    """Collect all normalized numeric representations from text."""
    numbers = set()
    if not text:
        return numbers

    # Digits and decimals / money
    for match in re.findall(r"\d+(?:[.,]\d+)?", text):
        clean = match.replace(",", ".")
        numbers.add(clean)
        for part in re.findall(r"\d+", match):
            numbers.add(part)

    # Years
    for year in re.findall(r"\b20\d\d\b", text):
        numbers.add(year)

    # English small number words and month words
    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    for num_str, word in NUMBER_WORDS.items():
        if word in words:
            numbers.add(num_str)
    for num_str, word in SMALL_NUMBERS.items():
        if word in words:
            numbers.add(num_str)

    # Vietnamese scale words (tỷ, triệu, nghìn, ngàn)
    lower_text = text.lower()
    for scale in ("tỷ", "triệu", "nghìn", "ngàn"):
        if scale in lower_text:
            numbers.add(scale)

    return numbers


def extract_entities_from_text(text: str) -> set[str]:
    """Collect capitalized entities, product names, acronyms, and labs."""
    entities = set()
    if not text:
        return entities

    # Match capitalized or acronym tokens
    tokens = re.findall(r"\b[A-Za-z0-9_.+-]*[A-Z][A-Za-z0-9_.+-]*\b", text)
    for tok in tokens:
        clean = tok.strip(".,;:!?\"'()[]{}")
        if not clean or clean in VN_GRAMMAR_CAPS:
            continue
        entities.add(clean.lower())
        for part in re.split(r"[-_.]+", clean):
            if len(part) >= 2 and part not in VN_GRAMMAR_CAPS:
                entities.add(part.lower())

    return entities


def extract_story_facts(story: dict) -> tuple[set[str], set[str]]:
    """Gather all authorized ground-truth numbers and proper entities for a story."""
    text_parts = [
        str(story.get("title") or ""),
        str(story.get("title_vi") or ""),
        str(story.get("summary") or ""),
        str(story.get("summary_vi") or ""),
    ]
    key_points = story.get("key_points")
    if isinstance(key_points, list):
        for pt in key_points:
            if isinstance(pt, str):
                text_parts.append(pt)

    for c in story.get("coverage") or []:
        if isinstance(c, dict):
            text_parts.append(str(c.get("title") or ""))
            text_parts.append(str(c.get("title_vi") or ""))
            text_parts.append(str(c.get("summary") or ""))
            text_parts.append(str(c.get("summary_vi") or ""))
            pub = c.get("publisher") or ""
            if pub:
                text_parts.append(pub.replace("-", " "))
            src = c.get("source") or ""
            if src:
                text_parts.append(src.replace("-", " "))
            lab = c.get("lab") or ""
            if lab:
                text_parts.append(lab)

    full_text = " ".join(text_parts)
    numbers = extract_numbers_from_text(full_text)
    entities = extract_entities_from_text(full_text)

    # Date differences (e.g. 2019 to 2026 is 7 years)
    pub_dt = instant(story.get("published_at"))
    if pub_dt:
        numbers.add(str(pub_dt.year))
        # If past years appear, also compute age
        for y in list(numbers):
            if y.isdigit() and len(y) == 4 and y.startswith("20") and int(y) < pub_dt.year:
                numbers.add(str(pub_dt.year - int(y)))

    return numbers, entities


def validate_video_script(script: dict,
                          stories_map: dict[str, dict],
                          expected_date: str | None = None) -> tuple[bool, str | None]:
    """Mechanically verify that every fact, number, and proper noun in the script is grounded.

    Returns (True, None) if completely verified, or (False, reason) if rejected.
    A rejected script must NEVER be written to the public location.
    """
    if not isinstance(script, dict):
        return False, "script_not_a_dict"

    for required_key in ("date", "generated_at", "prompt_version", "hook", "hint", "stories", "cta"):
        if required_key not in script:
            return False, f"missing_required_key: {required_key}"

    if expected_date and script["date"] != expected_date:
        return False, f"date_mismatch: expected {expected_date}, got {script['date']}"

    hook = str(script.get("hook") or "").strip()
    hint = str(script.get("hint") or "").strip()
    cta = str(script.get("cta") or "").strip()
    stories_list = script.get("stories")

    if not hook or not hint or not cta or not isinstance(stories_list, list):
        return False, "empty_script_fields"

    if len(stories_list) != 3:
        return False, f"expected_3_stories: got {len(stories_list)}"

    script_ids = [s.get("id") for s in stories_list if isinstance(s, dict)]
    if len(set(script_ids)) != 3 or set(script_ids) != set(stories_map.keys()):
        return False, f"stories_id_mismatch: {script_ids} vs {list(stories_map.keys())}"

    # Check word counts
    for s in stories_list:
        line = str(s.get("line") or "").strip()
        words = line.split()
        if len(words) > 35:
            return False, f"line_too_long: {len(words)} words in story {s.get('id')} (must be <= 35 words)"
        if not VIETNAMESE.search(line):
            return False, f"line_not_vietnamese: {s.get('id')}"

    if len(hook.split()) > 30:
        return False, f"hook_too_long: {len(hook.split())} words"
    if not VIETNAMESE.search(hook):
        return False, "hook_not_vietnamese"
    if not VIETNAMESE.search(cta):
        return False, "cta_not_vietnamese"

    # Pre-extract all facts per story and union for hook
    story_facts = {sid: extract_story_facts(st) for sid, st in stories_map.items()}
    all_story_numbers = set().union(*(facts[0] for facts in story_facts.values()))
    all_story_entities = set().union(*(facts[1] for facts in story_facts.values()))

    # Allowed global format numbers (3 stories, 45 seconds)
    format_numbers = {"3", "45", "1", "2"}

    # 1. Verify Story Lines: strictly grounded in each story's data
    for s in stories_list:
        sid = s["id"]
        line = s["line"]
        st_numbers, st_entities = story_facts[sid]

        line_numbers = extract_numbers_from_text(line)
        for num in line_numbers:
            if num not in st_numbers:
                return False, f"invented_number in story {sid}: {num}"

        line_entities = extract_entities_from_text(line)
        for ent in line_entities:
            if ent not in st_entities and ent not in ALLOWED_BOILERPLATE_ENTITIES:
                return False, f"invented_entity in story {sid}: {ent}"

    # 2. Verify Hook: must be grounded in the union of the 3 stories
    hook_numbers = extract_numbers_from_text(hook)
    for num in hook_numbers:
        if num not in all_story_numbers and num not in format_numbers:
            return False, f"invented_number in hook: {num}"

    hook_entities = extract_entities_from_text(hook)
    for ent in hook_entities:
        if ent not in all_story_entities and ent not in ALLOWED_BOILERPLATE_ENTITIES:
            return False, f"invented_entity in hook: {ent}"

    # 3. Verify Hint: format constants or story facts
    hint_numbers = extract_numbers_from_text(hint)
    for num in hint_numbers:
        if num not in format_numbers and num not in all_story_numbers:
            return False, f"invented_number in hint: {num}"

    hint_entities = extract_entities_from_text(hint)
    for ent in hint_entities:
        if ent not in ALLOWED_BOILERPLATE_ENTITIES and ent not in all_story_entities:
            return False, f"invented_entity in hint: {ent}"

    # 4. Verify CTA: format constants or story facts
    cta_numbers = extract_numbers_from_text(cta)
    for num in cta_numbers:
        if num not in format_numbers and num not in all_story_numbers:
            return False, f"invented_number in cta: {num}"

    cta_entities = extract_entities_from_text(cta)
    for ent in cta_entities:
        if ent not in ALLOWED_BOILERPLATE_ENTITIES and ent not in all_story_entities:
            return False, f"invented_entity in cta: {ent}"

    return True, None


# ---------- Request building and Gemini communication ----------

def build_gemini_request(stories: list[dict]) -> dict:
    """Build structured Gemini request with strict responseJsonSchema."""
    input_stories = []
    for s in stories:
        input_stories.append({
            "id": s.get("id"),
            "title": s.get("title", ""),
            "title_vi": s.get("title_vi", ""),
            "summary": s.get("summary", ""),
            "summary_vi": s.get("summary_vi", ""),
            "key_points": s.get("key_points") or [],
        })

    return {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{
            "role": "user",
            "parts": [{
                "text": "Hãy tạo kịch bản video 45 giây từ 3 tin AI sau đây:\n" + json.dumps({"stories": input_stories}, ensure_ascii=False)
            }]
        }],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": "low"},
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "required": ["hook", "hint", "stories", "cta"],
                "additionalProperties": False,
                "properties": {
                    "hook": {"type": "string"},
                    "hint": {"type": "string"},
                    "stories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "line"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "line": {"type": "string"}
                            }
                        }
                    },
                    "cta": {"type": "string"}
                }
            }
        }
    }


def parse_gemini_response(response: dict, expected_ids: set[str], date_str: str, now_iso: str) -> tuple[dict | None, int, str | None]:
    """Parse Gemini generateContent response into the video script contract."""
    try:
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            return None, 0, "invalid_candidates"
        if candidates[0].get("finishReason") != "STOP":
            return None, 0, f"finish_reason_{candidates[0].get('finishReason')}"

        parts = candidates[0].get("content", {}).get("parts")
        if not isinstance(parts, list) or not parts:
            return None, 0, "empty_content_parts"

        final_text = []
        for part in parts:
            if not isinstance(part, dict):
                return None, 0, "malformed_part"
            if part.get("thought"):
                continue
            txt = part.get("text")
            if isinstance(txt, str):
                final_text.append(txt)

        raw = "".join(final_text)
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, 0, "response_not_object"

        tokens = int(response.get("usageMetadata", {}).get("totalTokenCount", 0))

        contract = {
            "date": date_str,
            "generated_at": now_iso,
            "prompt_version": PROMPT_VERSION,
            "hook": str(data.get("hook", "")).strip(),
            "hint": str(data.get("hint", "")).strip(),
            "stories": [
                {"id": s.get("id"), "line": str(s.get("line", "")).strip()}
                for s in data.get("stories", [])
                if isinstance(s, dict)
            ],
            "cta": str(data.get("cta", "")).strip()
        }

        return contract, tokens, None
    except Exception as error:
        return None, 0, f"parse_error: {type(error).__name__}"


# ---------- Pipeline Orchestration ----------

def generate_video_script(input_path: str | Path,
                          output_path: str | Path,
                          ledger_path: str | Path,
                          editor_picks_path: str | Path | None = None,
                          force: bool = False,
                          now_val: datetime | None = None,
                          transport_fn=None) -> dict:
    """Main pipeline execution for daily video script generation."""
    transport_fn = transport_fn or gemini.transport
    now = now_val or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now_vn = now.astimezone(VIETNAM)
    today_vn = now_vn.strftime("%Y-%m-%d")

    input_path = Path(input_path)
    output_path = Path(output_path)
    ledger_path = Path(ledger_path)

    # 1. Check daily schedule window (after 05:00 VN time so it exists by 06:00 VN time)
    if not force and now_vn.hour < SCHEDULED_START_HOUR:
        return {
            "status": "outside_window",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": f"hour {now_vn.hour} is before {SCHEDULED_START_HOUR}:00 VN time"
        }

    # 2. Read input stories
    if not input_path.is_file():
        return {
            "status": "missing_input",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
        }

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as error:
        return {
            "status": "invalid_input",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": str(error)
        }

    stories = payload.get("stories") or []
    sources = {s["id"]: s for s in payload.get("sources") or [] if isinstance(s, dict) and s.get("id")}

    editor_picks = None
    if editor_picks_path and Path(editor_picks_path).is_file():
        try:
            picks_data = json.loads(Path(editor_picks_path).read_text(encoding="utf-8"))
            if isinstance(picks_data, dict):
                editor_picks = picks_data.get("picks")
        except Exception:
            pass

    # 3. Choose 3 stories
    selected = choose_picks(stories, sources_map=sources, now_dt=now, editor_picks=editor_picks)
    if len(selected) < 3:
        return {
            "status": "insufficient_stories",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": f"found only {len(selected)} eligible stories with >= 2 news sources"
        }

    stories_map = {s["id"]: s for s in selected}

    # 4b. Check if valid script for today already exists
    if output_path.is_file() and not force:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing.get("date") == today_vn:
                is_valid, _ = validate_video_script(existing, stories_map, expected_date=today_vn)
                if is_valid:
                    return {
                        "status": "already_generated",
                        "date": today_vn,
                        "tokens": 0,
                        "script_written": False,
                        "ledger_written": False,
                    }
        except (OSError, ValueError):
            pass

    # 5. Check API credentials & free-tier confirmation
    api_key = os.environ.get("GEMINI_API_KEY", "")
    confirmed = os.environ.get("RADAR_GEMINI_FREE_TIER_CONFIRMED") == "1"
    if not api_key:
        return {
            "status": "skipped",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": "missing_api_key"
        }
    if not confirmed:
        return {
            "status": "skipped",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": "free_tier_unconfirmed"
        }

    # 6. Check free-tier ledger capacity
    cap_err = summary_budget.capacity_error(ledger_path, now=now.timestamp())
    if cap_err:
        return {
            "status": "budget_exhausted",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": cap_err
        }

    # 7. Reserve budget
    estimated_tokens = 1500
    reserve_now = now.timestamp()
    reserve_err = summary_budget.reserve(
        ledger_path,
        estimated_tokens=estimated_tokens,
        now=reserve_now,
        last_story_id=selected[-1]["id"]
    )
    if reserve_err:
        return {
            "status": "reserve_failed",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": reserve_err
        }

    # 8. Call Gemini REST endpoint
    req_body = build_gemini_request(selected)
    timeout = 60.0
    try:
        response = transport_fn(req_body, api_key, timeout)
    except Exception as error:
        return {
            "status": "transport_error",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": True,
            "detail": str(error)
        }

    expected_ids = set(stories_map.keys())
    now_iso = now.isoformat()
    script_candidate, actual_tokens, parse_err = parse_gemini_response(response, expected_ids, today_vn, now_iso)
    if parse_err:
        return {
            "status": "parse_error",
            "date": today_vn,
            "tokens": actual_tokens,
            "script_written": False,
            "ledger_written": True,
            "detail": parse_err
        }

    # Record actual tokens
    if actual_tokens > 0:
        summary_budget.update_actual_tokens(ledger_path, reserve_now, actual_tokens)

    # 9. Mechanical fact verification (Strict boundary)
    valid, reject_reason = validate_video_script(script_candidate, stories_map, expected_date=today_vn)
    if not valid:
        # A rejected script means NO file for the day, never a partially checked one!
        if output_path.is_file():
            try:
                existing = json.loads(output_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and existing.get("date") == today_vn:
                    output_path.unlink(missing_ok=True)
            except Exception:
                pass
        return {
            "status": "rejected",
            "date": today_vn,
            "tokens": actual_tokens,
            "script_written": False,
            "ledger_written": True,
            "detail": reject_reason
        }

    # 10. Atomically write the validated script
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(script_candidate, output_path)

    return {
        "status": "success",
        "date": today_vn,
        "tokens": actual_tokens,
        "script_written": True,
        "ledger_written": True,
        "script": script_candidate
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="site/data/radar-ui.json",
                        help="Snapshot input path (defaults to site/data/radar-ui.json)")
    parser.add_argument("--output", default="site/data/video-script.json",
                        help="Video script output path (defaults to site/data/video-script.json)")
    parser.add_argument("--ledger", default="data/summary-gemini-ledger.json",
                        help="Path to shared Gemini summary ledger")
    parser.add_argument("--editor-picks", default="site/editor-picks.json",
                        help="Optional editor picks path")
    parser.add_argument("--force", action="store_true",
                        help="Force generation bypassing time window and daily cache")
    parser.add_argument("--now", help="Explicit ISO timestamp for offline testing")
    args = parser.parse_args(argv)

    now_val = None
    if args.now:
        now_val = instant(args.now)
        if not now_val:
            parser.error(f"Invalid timestamp: {args.now}")

    # Fallback to radar.json if radar-ui.json is not present
    input_path = Path(args.input)
    if not input_path.is_file() and input_path.name == "radar-ui.json":
        alt = input_path.with_name("radar.json")
        if alt.is_file():
            input_path = alt

    res = generate_video_script(
        input_path=input_path,
        output_path=args.output,
        ledger_path=args.ledger,
        editor_picks_path=args.editor_picks,
        force=args.force or (os.environ.get("RADAR_VIDEO_SCRIPT_FORCE") == "1"),
        now_val=now_val
    )

    script_written = res.get("script_written", False)
    ledger_written = res.get("ledger_written", False)

    if os.environ.get("GITHUB_OUTPUT"):
        try:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"video_script_written={str(script_written).lower()}\n"
                             f"video_script_ledger_written={str(ledger_written).lower()}\n")
        except OSError:
            pass

    status = res.get("status")
    detail = res.get("detail", "")
    print(f"Video script {status}: date={res.get('date')}, tokens={res.get('tokens', 0)}"
          + (f" -- {detail}" if detail else ""))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
