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
from radar.site_config import SITE_BASE_URL
from radar import summary_budget
from radar import gemini_paid_budget
from radar import summary_gemini as gemini
from radar.translate import DIGITS, NUMBER_WORDS, SMALL_NUMBERS, VIETNAMESE
from radar.worth import calculate_worth, first_hand_of, uniq_coverage

MODEL_ID = "gemini-3.8-flash"
PROMPT_VERSION = "video-script-vi-2"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent"

TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
VIETNAM = timezone(timedelta(hours=7), TIMEZONE_NAME)
SCHEDULED_START_HOUR = 5  # 05:00 VN time (22:00 UTC previous day)
SCHEDULED_END_HOUR = 6    # 06:00 VN time (23:00 UTC previous day)


def is_scheduled_window(now_vn: datetime) -> bool:
    """Return True if Vietnam time is within the scheduled daily window [05:00, 06:00)."""
    return SCHEDULED_START_HOUR <= now_vn.hour < SCHEDULED_END_HOUR


def is_non_main_ref(ref: str | None) -> bool:
    """Return True if git ref represents a branch run other than main.

    Non-main refs (e.g. refs/heads/feat/video-script or feat/video-script) bypass the
    morning schedule window so coordinators can test real script generation on demand
    before merging. Empty/None refs are treated as main/offline by default.
    """
    if not ref:
        return False
    normalized = ref.strip().lower()
    return normalized not in (
        "refs/heads/main",
        "main",
        "refs/heads/master",
        "master",
    )

# Allowed standard terms in video format boilerplate
ALLOWED_BOILERPLATE_ENTITIES = {
    "ai", "halcyon", "news", "radar", "reels", "tiktok", "shorts", "tv", "pro", "app"
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

SYSTEM_INSTRUCTION = """Bạn là biên tập viên kịch bản video ngắn (Reels, TikTok, Shorts) của Halcyon.
Nhiệm vụ: Viết kịch bản video 45 giây từ 3 tin AI nổi bật nhất trong ngày được chọn sẵn.

Cấu trúc kịch bản bắt buộc:
1. Mở đầu (hook): 0–3 giây, từ 15 đến 20 chữ. Nêu ngay sự thật/con số gây tò mò hoặc bất ngờ nhất trong 3 tin để giữ chân người xem ngay lập tức.
2. Gợi trước (hint): Khoảng 8-12 chữ, theo cấu trúc: 'Ba tin AI đáng chú ý nhất, trong 45 giây.'
3. Ba tin (stories): Đúng 3 tin tương ứng với 3 story id được cung cấp. Tin có chi tiết bất ngờ nhất ở phần Mở đầu phải được đặt làm Tin 1 để kết nối mạch lạc với Mở đầu. Mỗi tin đúng MỘT câu nói ngắn gọn, súc tích (dưới 25 chữ), nêu sự thật bất ngờ nhất lên trước.
4. Kêu gọi hành động (cta): Đúng một lời kêu gọi duy nhất (ví dụ: 'Mỗi sáng Halcyon chọn 3 tin AI đáng đọc nhất. Theo dõi kênh để cập nhật tin AI nóng nhất. Bạn quan tâm tin nào nhất? Bình luận cho mình biết nhé.').

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


def is_translated_story(st: dict) -> bool:
    """Return True if the story has a non-empty Vietnamese title."""
    title_vi = st.get("title_vi")
    return bool(title_vi and isinstance(title_vi, str) and title_vi.strip())


def choose_picks(stories: list[dict],
                 sources_map: dict | None = None,
                 now_dt: datetime | None = None,
                 editor_picks: list[dict] | None = None,
                 *, require_translation: bool = True) -> list[dict]:
    """Replicate feed.js choosePicks() in Python for translated stories.

    Returns up to 3 high-worth translated stories backed by >= 2 independent news publishers.
    """
    story_map = {s.get("id"): s for s in stories if s.get("id")}

    def eligible(story):
        # Spending priority must include promoted stories awaiting translation.
        return is_translated_story(story) if require_translation else bool(story.get("title"))

    def n_news(s: dict) -> int:
        return len(news_coverage_of(s, sources_map))

    def by_worth(s: dict):
        if isinstance(s.get("worth_score"), (int, float)):
            score = float(s["worth_score"])
        else:
            w = calculate_worth(s, now_dt, sources_map)
            score = w["score"]
        pub_dt = instant(s.get("published_at"))
        ts = pub_dt.timestamp() if pub_dt else 0.0
        return (-score, -ts)

    def has_evidence(s: dict) -> bool:
        if isinstance(s.get("worth_score"), (int, float)):
            meas = (s.get("hot_signals") or {}).get("measurement")
            hot = max(0.0, float(s.get("hot_score") or 0.0)) if meas and isinstance(s.get("hot_score"), (int, float)) else 0.0
            n = len(uniq_coverage(s.get("coverage"), sources_map))
            fh = first_hand_of(s, sources_map)
            parts = s.get("worth_parts")
            return bool(fh or n >= 2 or hot > 0 or (isinstance(parts, dict) and bool(parts)))
        return calculate_worth(s, now_dt, sources_map)["evidence"]

    out = []
    editor_set = set()
    if editor_picks:
        for p in editor_picks:
            if len(out) >= 3:
                break
            pid = p.get("id") if isinstance(p, dict) else str(p)
            st = story_map.get(pid)
            if st and eligible(st) and n_news(st) >= 2 and st not in out:
                out.append(st)
                editor_set.add(st["id"])

    candidates = [
        s for s in stories
        if s.get("id") not in editor_set and eligible(s) and n_news(s) >= 2 and has_evidence(s)
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
            if s.get("id") not in editor_set and s not in out and eligible(s) and n_news(s) >= 2 and has_evidence(s)
        ]
        fallback.sort(key=by_worth)
        for s in fallback:
            if len(out) >= 3:
                break
            if not any(same_event(o, s) for o in out):
                out.append(s)

    return out[:3]


# ---------- Video candidates: the 0-3 stories a day most worth a short video ----------
#
# The rubric is the research proposal the owner approved on 2026-11-18 01:04 ("Duyệt cả 3"), with his three
# decisions: (1) drama about a person is allowed only on verified facts carried by at least 3 independent
# sources; (2) the video labels ride on the existing editor call, never a new model call; (3) a day with no
# "Tin nóng" story at or above the threshold gets none, the "Dùng được ngay" lane fills it, and when that is
# empty too the day has no video. Weights are a first proposal, to be recalibrated against Halcyon's own
# 48-hour view counts after the first 10-15 videos. Pure code: no model call, no network.

CANDIDATES_VERSION = "video-diem-1"
CANDIDATE_THRESHOLD = 60
MAJOR_THRESHOLD = 70          # a follow-up in a recent chain must reach this and be a new major development
CHAIN_DAYS = 3                # one video per story chain per 3 days
FRESH_HOURS = 48              # a story is a candidate for 48 hours after publication
MIN_PERSON_DRAMA_SOURCES = 3  # owner decision 1
MIN_RUMOUR_SOURCES = 3        # a leak or unconfirmed report needs this many independent publishers
MIN_REPO_WEEK_STARS = 3000    # below this a trending repo is too often a clone or spam
MAX_PER_DAY = 3
MAX_HOT_PER_DAY = 1
MAX_USABLE_PER_DAY = 2
MIN_HOT_SOURCES = 2           # spec §1: "Tin nóng" needs at least 2 independent publishers
HISTORY_DAYS = 14             # earlier days kept in the published file; only CHAIN_DAYS of them block
LANE_HOT = "tin-nong"
LANE_USABLE = "dung-duoc-ngay"
LANE_GUIDE = "huong-dan"
LANE_NAMES = {LANE_HOT: "Tin nóng", LANE_USABLE: "Dùng được ngay", LANE_GUIDE: "Hướng dẫn"}
# The how-to lane (owner approval 2026-11-20: one video in three is a guide). A guide is a hand-written article that
# radar.huong_dan injects into the story stream with kind "huong-dan" only after the owner approved it, so the kind
# is the marker. It is evergreen (no freshness limit), at most one is offered a day, and it takes one of the day's
# MAX_PER_DAY slots from the usable lane: "Tin nóng" is perishable and keeps its slot, repo picks are the most
# replaceable. The 1-in-3 ratio of videos actually made is enforced by the builder's ledger, not here.
GUIDE_KIND = "huong-dan"
GUIDE_SCORE = 75
MAX_GUIDE_PER_DAY = 1
VIDEO_HOOKS = ("drama_person", "drama_company", "usable_now", "money_jobs", "launch", "other")
HOOK_POINTS = {"drama_person": 40, "usable_now": 35, "drama_company": 30, "money_jobs": 25, "launch": 10, "other": 5}
HOOK_NAMES = {"drama_person": "drama có tên người thật", "drama_company": "drama công ty",
              "usable_now": "miễn phí, dùng được ngay", "money_jobs": "tiền và việc làm",
              "launch": "ra mắt model/sản phẩm", "other": "loại khác"}

# Keyword fallback for stories the editor has not labelled yet (decided before the labels existed).
_PERSON = re.compile(r"\b(Huang|Altman|Musk|Zuckerberg|Pichai|Nadella|Amodei|Hassabis|Kress|Bezos|Cook|Sutskever|"
                     r"Karpathy|Murati|LeCun|Suleyman|Brockman|Trump)\b", re.I)
_DRAMA_PERSON = re.compile(r"\b(resign\w*|step(?:s|ped)? down|ousted|fired|scandal|affair|testif\w*|arrest\w*|"
                           r"indict\w*|quits?|feud|accus\w*|blasts?|slams?|reinstat\w*)\b|"
                           r"từ chức|bê bối|sa thải CEO|bị cách chức|ngoại tình|điều trần|cáo buộc|chỉ trích|"
                           r"phục chức", re.I)
# An investigation is drama only when it names a person ("Nvidia investigates CEO Jensen Huang"), not in
# "Blueprint coordinates AI agents to investigate production issues".
_PERSON_PROBE = re.compile(r"\b(investigat\w*|probe[sd]?)\b|điều tra", re.I)
# Companies whose scandals readers follow; two drama stories naming one of them are one chain.
_ORG = re.compile(r"\b(Nvidia|OpenAI|Google|Apple|Meta|Microsoft|Amazon|Anthropic|xAI|Tesla|Samsung|TikTok|"
                  r"ByteDance|Huawei|DeepSeek|Alibaba|Baidu|Intel|AMD|TSMC|Perplexity|Mistral)\b", re.I)
# Every published story also carries a Vietnamese headline, so the English words must not match Vietnamese ones:
# "ban hành" (issue), "ban đầu" (initial), "sự kiện" (event), "kiện toàn" (consolidate), and "fine-tuning".
_DRAMA_COMPANY = re.compile(r"\b(lawsuit|sues?|sued|suing|court|judge|probe|investigation|breach|hack\w*|antitrust|"
                            r"settle\w*|outage|copyright)\b|\bban(?:s|ned)?\b(?! (?:hành|đầu|giám|chỉ|lãnh|ngày|đêm|"
                            r"tổ|biên|nhạc|bè))|\bfine[sd]?\b(?!-)|khởi kiện|đâm đơn kiện|bị kiện|kiện tụng|"
                            r"(?<!điều )(?<!sự )(?-i:kiện (?=[A-ZĐ]))|tòa án|cấm|bị điều tra|mở (?:cuộc )?điều tra|"
                            r"tấn công mạng|phạt|sập", re.I)
# "Free" must be said outright: "available" and "rolls out" also describe paid model launches (back-test: a
# Gemini model launch was scored as usable now).
_FREE = re.compile(r"\b(free|open[- ]source|open[- ]weights?|no cost)\b|miễn phí|mã nguồn mở", re.I)
_MODEL_LAUNCH = re.compile(r"\b(model|GPT-?\d|Gemini \d|Claude|Llama|Qwen|DeepSeek|Grok \d|benchmark|"
                           r"release[sd]?|launch\w*|unveil\w*|announc\w*|introduc\w*)\b|ra mắt|công bố|mô hình", re.I)
_POPULAR_TOOL = re.compile(r"\b(ChatGPT|Gemini|Claude|Copilot|CapCut|Canva|Photoshop|Siri|iPhone|Android|Chrome|"
                           r"YouTube|TikTok|Facebook|Instagram|WhatsApp|Zalo|Grok|Midjourney|Sora|Veo|NotebookLM|"
                           r"Granola|Notion|Excel|Word|PowerPoint)\b", re.I)
_REPLACEABLE_TOOL = re.compile(r"\b(CapCut|ChatGPT Plus|Canva|Photoshop|Premiere|Midjourney|Notion|Granola|"
                               r"Grammarly|Otter|Descript)\b", re.I)
_MONEY_JOBS = re.compile(r"\b(layoffs?|lay off|job cuts?|jobs?|salar\w*|hiring|workers?|employees?|"
                         r"price (?:cut|hike)|cheaper|subscription)\b|sa thải|việc làm|lương|giảm giá|tăng giá", re.I)
_VIETNAM = re.compile(r"Viet ?nam|Việt Nam|tiếng Việt|\bVN\b|Viettel|FPT|VinAI|Vingroup|VinFast|Zalo|MoMo|\bVNG\b|"
                      r"Hà Nội|TP\.? ?HCM|Sài Gòn", re.I)
_VN_BRAND = re.compile(r"\b(ChatGPT|OpenAI|Gemini|Google|Apple|iPhone|Siri|Samsung|TikTok|Meta|Facebook|Nvidia|"
                       r"Microsoft|Tesla|Elon Musk|Jensen Huang|Sam Altman)\b", re.I)
# Rumour and leak words (back-test: a leaker's rumour passed because "leaker" was not in the list).
_RUMOUR = re.compile(r"\b(reportedly|rumou?r\w*|leak(?:er|ers|ed|s)?|tipster|insiders?|sources say|"
                     r"people familiar|according to (?:a )?(?:report|sources)|in talks|considering|alleged\w*)\b|"
                     r"tin đồn|được cho là|rò rỉ|theo nguồn tin|đang đàm phán|cân nhắc", re.I)
_SENSITIVE = re.compile(r"\b(suicide|self-harm|child|children|minors?|killed|death|dies|died|war|military|weapons?|"
                        r"missiles?|South China Sea|elections?)\b|tự tử|tự hại|trẻ em|tử vong|chiến tranh|"
                        r"quân sự|vũ khí|Biển Đông|bầu cử", re.I)
_REGION_ONLY = re.compile(r"\b(in the US|U\.S\.-only|US-only|only in|in America|in China|in Japan|in Korea|"
                          r"in the UK|in Europe|in India)\b|chỉ có ở|chỉ tại|tại Mỹ|ở Mỹ|tại Trung Quốc|tại Nhật|"
                          r"tại Hàn|tại Anh|tại châu Âu|tại Ấn Độ", re.I)
# A new major development in a chain: the kind of turn, so a second story of the same turn is not "new".
_MAJOR_TURNS = (
    ("resignation", re.compile(r"\b(resign\w*|step(?:s|ped)? down|ousted|fired)\b|từ chức|bị cách chức|sa thải CEO", re.I)),
    ("return", re.compile(r"\b(reinstat\w*|returns?|comeback|rehired)\b|phục chức|quay lại|trở lại", re.I)),
    ("verdict", re.compile(r"\b(verdict|ruling|rules|convicted|cleared|charged|indicted|settles?|findings?|"
                           r"concludes?)\b|kết luận|phán quyết|bị truy tố|dàn xếp", re.I)),
    ("arrest", re.compile(r"\b(arrest\w*)\b|bị bắt", re.I)),
)
_VIDEO_URL = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be|vimeo\.com)/", re.I)
_REPO_URL = re.compile(r"https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+", re.I)


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def _story_title(story: dict, row: dict | None) -> str:
    row = row or {}
    return " ".join(filter(None, [_str(story.get("title")), _str(story.get("title_vi")),
                                  _str(row.get("editorial_headline_vi")) or _str(story.get("editorial_headline_vi"))]))


def editor_video_labels(row: dict | None) -> dict | None:
    """The editor's video labels on a decision row, or None for older rows (and malformed ones)."""
    labels = (row or {}).get("video_labels")
    if not isinstance(labels, dict) or labels.get("video_hook") not in VIDEO_HOOKS:
        return None
    if type(labels.get("is_leak")) is not bool or not isinstance(labels.get("availability"), str):
        return None
    people = labels.get("named_people")
    if not isinstance(people, list) or not all(isinstance(p, str) for p in people):
        return None
    return labels


def _person_name(name: str) -> str:
    """A name casefolded without accents: the editor's full name, or a surname from the keyword list."""
    norm = unicodedata.normalize("NFKD", name.strip().casefold())
    return " ".join("".join(c for c in norm if not unicodedata.combining(c)).split())


def _people(story: dict, row: dict | None, labels: dict | None) -> set[str]:
    names = list(labels["named_people"]) if labels else [m.group(0) for m in _PERSON.finditer(_story_title(story, row))]
    return {key for key in (_person_name(n) for n in names) if key}


def _same_person(a: str, b: str) -> bool:
    """Full names must match exactly ("Nguyen Van Minh" is not "Tran Minh"); a keyword surname matches a full name
    ending with it ("huang" and "jensen huang")."""
    if a == b:
        return True
    short, full = sorted((a, b), key=lambda name: len(name.split()))
    return len(short.split()) == 1 and len(full.split()) > 1 and full.split()[-1] == short


def _keyword_hook(title: str) -> str:
    if _PERSON.search(title) and (_DRAMA_PERSON.search(title) or _PERSON_PROBE.search(title)):
        return "drama_person"
    if _DRAMA_COMPANY.search(title) or _DRAMA_PERSON.search(title):
        return "drama_company"
    if _FREE.search(title):
        return "usable_now"
    if _MONEY_JOBS.search(title):
        return "money_jobs"
    if _MODEL_LAUNCH.search(title):
        return "launch"
    return "other"


def _region_locked(availability: str) -> bool:
    return availability.startswith("region_locked:") and not _VIETNAM.search(availability)


def _story_visual(story: dict) -> tuple[int, str, list[str]]:
    """(points, why, links) for the strongest real visual: a video, a repo page, or a real photo. AI art is none."""
    covs = [c for c in story.get("coverage") or [] if isinstance(c, dict)]
    urls = [u for u in [_str(story.get("url"))] + [_str(c.get("url")) for c in covs] if u]
    videos = [u for u in urls if _VIDEO_URL.match(u)]
    videos += [_str(m.get("url")) for c in covs for m in c.get("media") or []
               if isinstance(m, dict) and m.get("type") == "video" and _str(m.get("url")).startswith("https://")]
    if videos:
        return 20, "có video demo", list(dict.fromkeys(videos))
    repos = [u for u in urls if _REPO_URL.match(u)]
    if repos:
        return 12, "trang repo có README minh hoạ", list(dict.fromkeys(repos))
    img = story.get("image") if isinstance(story.get("image"), dict) else {}
    src = _str(img.get("src"))
    if (src.startswith("https://") and img.get("via") != "ai" and img.get("kind") != "ai"
            and (img.get("quality") or {}).get("keep", True) is not False):
        return 10, f"ảnh thật từ nguồn ({img.get('via') or 'nguồn'})", [src]
    return 0, "không có hình thật", []


def _momentum(story: dict) -> tuple[int, dict]:
    n = story.get("source_count") if isinstance(story.get("source_count"), int) else 0
    points = {0: 0, 1: 0, 2: 5, 3: 10, 4: 15}.get(n, 20)
    hn = max([c["metrics"]["points"] for c in story.get("coverage") or [] if isinstance(c, dict)
              and isinstance(c.get("metrics"), dict) and isinstance(c["metrics"].get("points"), (int, float))],
             default=0)
    points += 10 if hn >= 300 else 5 if hn >= 100 else 0
    return min(points, 25), {"sources": n, "hn_points": int(hn)}


def _verified(story: dict, row: dict | None) -> str | None:
    """Why the story is not a verified hco.news article, or None. A video must lead to a checked article."""
    if row is None:
        # Snapshots built for readers only hold stories whose desk prose passed (radar.newsroom_decisions).
        return None if story.get("key_points_source") == "nguoi-viet" and story.get("key_points") else \
            "chưa có quyết định phòng báo"
    if row.get("decision") != "publish":
        return "phòng báo giữ lại"
    if row.get("use_original_title"):
        return "tiêu đề chưa được kiểm"
    if not row.get("key_points"):
        return "không có tóm tắt đã kiểm"
    return None


def is_guide(story: dict) -> bool:
    return isinstance(story, dict) and story.get("kind") == GUIDE_KIND


def _guide_sources(story: dict) -> list[str]:
    """The official pages the guide was checked against: `summary_sources` holds URLs or objects with a `url`."""
    out = []
    for item in story.get("summary_sources") or []:
        url = _str(item.get("url")) if isinstance(item, dict) else _str(item)
        if url.startswith("https://"):
            out.append(url)
    return out


def score_guide(story: dict) -> dict:
    """An approved guide: a fixed score above the threshold and no gates (the loader already refused an unapproved
    file). The pick carries every field a story pick has, so the video builder reads it the same way."""
    sid = story.get("id")
    page = f"{SITE_BASE_URL.rstrip('/')}/tin/{sid}/" if sid else None
    return {
        "id": sid, "kind": "story", "lane": LANE_GUIDE, "score": GUIDE_SCORE,
        "breakdown": {
            "hook": {"points": 0, "max": 40, "hook": "guide", "why": "bài hướng dẫn Halcyon tự viết, chủ đã duyệt",
                     "labels": "huong-dan"},
            "vietnam": {"points": 0, "max": 15, "why": "viết riêng cho người xem Việt Nam"},
            "momentum": {"points": 0, "max": 25, "sources": 0, "hn_points": 0},
            "visual": {"points": 0, "max": 20, "why": "trang hướng dẫn trên hco.news"},
        },
        "gates": [] if sid and page else ["hướng dẫn thiếu mã bài"],
        "title": _str(story.get("title")),
        "headline_vi": _str(story.get("editorial_headline_vi")) or _str(story.get("title_vi")) or _str(story.get("title")),
        "published_at": _str(story.get("published_at")),
        "hco_url": page,
        "source_urls": list(dict.fromkeys(u for u in [page] + _guide_sources(story) if u)),
        "visual_links": [page] if page else [],
        "chain": {"person_drama": False, "people": [], "orgs": [], "subject": f"guide:{sid}"},
        "hot_score": 0,
    }


def score_story(story: dict, row: dict | None = None) -> dict:
    """Score one feed story on the 100-point rubric and list every exclusion gate it fails."""
    if is_guide(story):
        return score_guide(story)
    labels = editor_video_labels(row)
    title = _story_title(story, row)
    text = " ".join([title] + [p for p in (row or {}).get("key_points") or story.get("key_points") or []
                               if isinstance(p, str)])
    hook = labels["video_hook"] if labels else _keyword_hook(title)
    hook_points = HOOK_POINTS[hook] + (5 if hook == "usable_now" and _REPLACEABLE_TOOL.search(title) else 0)
    availability = labels["availability"] if labels else ("region_locked:" if _REGION_ONLY.search(title) else "unknown")
    if _VIETNAM.search(text) or (hook == "usable_now" and availability == "global"):
        vn_points, vn_why = 15, "nhắc Việt Nam hoặc dùng được ở Việt Nam"
    elif _VN_BRAND.search(title):
        vn_points, vn_why = 7, "thương hiệu người Việt dùng hằng ngày"
    else:
        vn_points, vn_why = 0, "không có góc Việt Nam"
    momentum, signals = _momentum(story)
    visual, visual_why, visual_links = _story_visual(story)
    n = signals["sources"]
    leak = labels["is_leak"] if labels else bool(_RUMOUR.search(title))

    gates = []
    why_unverified = _verified(story, row)
    if why_unverified:
        gates.append(why_unverified)
    if leak and n < MIN_RUMOUR_SOURCES:
        gates.append("tin đồn/rò rỉ, dưới 3 nguồn độc lập")
    # Without editor labels the keyword list of famous names decides drama_person, so drama about anyone else
    # ("OpenAI researcher fired after scandal") would bypass owner decision 1; the person-drama words decide it.
    person_drama = hook == "drama_person" or (not labels and bool(_DRAMA_PERSON.search(title)))
    if person_drama and n < MIN_PERSON_DRAMA_SOURCES:
        gates.append("drama về người cần ít nhất 3 nguồn độc lập")
    lane = LANE_USABLE if hook == "usable_now" else LANE_HOT
    if lane == LANE_HOT and n < MIN_HOT_SOURCES:
        gates.append("tin nóng cần ít nhất 2 nguồn độc lập")
    if _SENSITIVE.search(title):
        gates.append("chủ đề nhạy cảm")
    if visual == 0:
        gates.append("không có hình thật")
    if hook == "usable_now" and _region_locked(availability) and not _VIETNAM.search(text):
        gates.append("chỉ có ở nước ngoài")

    total = hook_points + vn_points + momentum + visual
    coverage_urls = [_str(c.get("url")) for c in story.get("coverage") or [] if isinstance(c, dict)]
    sid = story.get("id")
    return {
        "id": sid, "kind": "story", "lane": lane, "score": total,
        "breakdown": {
            "hook": {"points": hook_points, "max": 40, "hook": hook, "why": HOOK_NAMES[hook],
                     "labels": "editor" if labels else "keyword"},
            "vietnam": {"points": vn_points, "max": 15, "why": vn_why},
            "momentum": {"points": momentum, "max": 25, **signals},
            "visual": {"points": visual, "max": 20, "why": visual_why},
        },
        "gates": gates,
        "title": _str(story.get("title")),
        "headline_vi": _str((row or {}).get("editorial_headline_vi")) or _str(story.get("editorial_headline_vi"))
        or _str(story.get("title_vi")),
        "published_at": _str(story.get("published_at")),
        "hco_url": f"{SITE_BASE_URL.rstrip('/')}/tin/{sid}/" if sid else None,
        "source_urls": list(dict.fromkeys(u for u in [_str(story.get("url"))] + coverage_urls if u)),
        "visual_links": visual_links,
        "chain": {
            "person_drama": person_drama,
            "people": sorted(_people(story, row, labels)),
            # Company names chain only personal drama (a CEO's scandal and his resignation), never two unrelated
            # lawsuits or outages of one company.
            "orgs": sorted({m.group(0).casefold() for m in _ORG.finditer(title)}) if person_drama else [],
            "subject": _subject_key((row or {}).get("subject")),
        },
        "hot_score": story.get("hot_score") if isinstance(story.get("hot_score"), (int, float)) else 0,
    }


def _subject_key(subject) -> str | None:
    """The editor's subject, when specific enough to name a chain: a bare "DeepSeek" covers a financing story and a
    model launch alike, so a subject needs at least two words."""
    key = " ".join(_str(subject).casefold().split())
    return key if len(key.split()) >= 2 else None


def score_repo(repo: dict) -> dict:
    """Score one entry of the snapshot's `repos` section for the "Dùng được ngay" lane."""
    signals = repo.get("signals") if isinstance(repo.get("signals"), dict) else {}
    week = (repo.get("stars_gained") or {}).get("week") if isinstance(repo.get("stars_gained"), dict) else None
    week = week if isinstance(week, int) else repo.get("stars_gained_7d") if isinstance(repo.get("stars_gained_7d"), int) else 0
    install = _str(signals.get("install_command")).strip()
    desc = " ".join([_str(repo.get("description")), _str(repo.get("description_vi"))])
    hook_points = HOOK_POINTS["usable_now"] + (5 if _REPLACEABLE_TOOL.search(desc) else 0)
    momentum = 20 if week >= 10000 else 15 if week >= 5000 else 0
    url = _str(repo.get("url"))
    if signals.get("has_demo") or install:
        visual, visual_why = 20, "có demo" if signals.get("has_demo") else "tự quay màn hình được: có lệnh cài"
    elif signals.get("has_product_page") or signals.get("readme_measured"):
        visual, visual_why = 12, "trang repo có README minh hoạ"
    else:
        visual, visual_why = 0, "không quay được"
    gates = []
    if repo.get("label") != "dung-ngay":
        gates.append("không phải công cụ dùng ngay")
    if week < MIN_REPO_WEEK_STARS:
        gates.append("repo dưới 3.000 sao/tuần")
    if not install and not signals.get("has_demo"):
        gates.append("không có lệnh cài hay demo để quay")
    if visual == 0:
        gates.append("không có hình thật")
    rid = _str(repo.get("id")) or _str(repo.get("full_name"))
    return {
        "id": rid, "kind": "repo", "lane": LANE_USABLE, "score": hook_points + 15 + momentum + visual,
        "breakdown": {
            "hook": {"points": hook_points, "max": 40, "hook": "usable_now", "why": HOOK_NAMES["usable_now"],
                     "labels": "repos"},
            "vietnam": {"points": 15, "max": 15, "why": "repo mở, cài được ở Việt Nam"},
            "momentum": {"points": momentum, "max": 25, "stars_week": week, "stars": repo.get("stars")},
            "visual": {"points": visual, "max": 20, "why": visual_why},
        },
        "gates": gates,
        "title": rid,
        "headline_vi": _str(repo.get("description_vi")) or _str(repo.get("description")),
        "published_at": None,
        "hco_url": None,  # repos have no article page on hco.news
        "source_urls": [url] if url else [],
        "visual_links": [url] if url else [],
        "install_command": install or None,
        "chain": _repo_chain(rid), "hot_score": week,
    }


def _repo_chain(rid) -> dict:
    return {"person_drama": False, "people": [], "orgs": [], "subject": f"repo:{_str(rid).casefold()}"}


def major_turn(candidate: dict) -> str | None:
    """The kind of major development a story reports (resignation, return, verdict, arrest), or None."""
    text = " ".join([candidate.get("title") or "", candidate.get("headline_vi") or ""])
    return next((kind for kind, pattern in _MAJOR_TURNS if pattern.search(text)), None)


def _chain(c: dict) -> dict:
    chain = c.get("chain")
    return chain if isinstance(chain, dict) else {}


def _names(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def same_chain(a: dict, b: dict) -> bool:
    """Two candidates belong to one story chain when, with at least one of them personal drama, they share a named
    person or a company; or they share a specific editor subject; or they report the same event by title. The
    back-test grouped by title only and let one chain fill 7 of the top 10. A person merely quoted in a launch does
    not tie it to that person's later scandal, and two unrelated lawsuits against one company are two chains."""
    ca, cb = _chain(a), _chain(b)
    if LANE_GUIDE in (a.get("lane"), b.get("lane")):
        return False   # a guide is evergreen: it neither blocks nor is blocked by the news chains
    if ca.get("person_drama") is True or cb.get("person_drama") is True:
        if any(_same_person(x, y) for x in _names(ca.get("people")) for y in _names(cb.get("people"))):
            return True
        if set(_names(ca.get("orgs"))) & set(_names(cb.get("orgs"))):
            return True
    if ca.get("subject") and ca.get("subject") == cb.get("subject"):
        return True
    return a.get("kind") == b.get("kind") == "story" and same_event(a, b)


def _at(candidate: dict) -> datetime | None:
    return instant(candidate.get("picked_at") or candidate.get("published_at"))


def _vn_date(moment: datetime):
    return moment.astimezone(VIETNAM).date()


def chain_block(candidate: dict, kept: list[dict], now: datetime) -> str | None:
    """Why the chain rule refuses this candidate, or None (then it may set candidate["chain_note"]). A chain shown
    on one of the last CHAIN_DAYS Vietnam calendar days (today included) takes a follow-up only when it scores
    MAJOR_THRESHOLD and reports a kind of major development the chain has not had."""
    today = _vn_date(now)
    recent = [k for k in kept if same_chain(candidate, k)
              and (_at(k) is None or 0 <= (today - _vn_date(_at(k))).days < CHAIN_DAYS)]
    if not recent:
        return None
    turn = major_turn(candidate)
    seen = {major_turn(k) for k in recent}
    if candidate["score"] >= MAJOR_THRESHOLD and turn and turn not in seen:
        candidate["chain_note"] = f"diễn biến mới lớn ({turn}) của chuỗi tin đã làm"
        return None
    return "cùng chuỗi tin đã làm trong 3 ngày"


def _rank(c: dict):
    return (-c["score"], -(c.get("hot_score") or 0), c.get("id") or "")


def _reason(c: dict) -> str:
    b = c["breakdown"]
    parts = [f"{LANE_NAMES[c['lane']]} {c['score']}/100", b["hook"]["why"]]
    if c["lane"] == LANE_GUIDE:
        return "; ".join(parts + [b["visual"]["why"]])
    if c["kind"] == "repo":
        parts.append(f"+{b['momentum']['stars_week']:,} sao/tuần".replace(",", "."))
        if c.get("install_command"):
            parts.append(f"cài: {c['install_command']}")
    else:
        parts.append(f"{b['momentum']['sources']} nguồn độc lập")
        if b["momentum"]["hn_points"]:
            parts.append(f"HN {b['momentum']['hn_points']} điểm")
    parts.append(b["visual"]["why"])
    if b["vietnam"]["points"]:
        parts.append(b["vietnam"]["why"])
    if c.get("chain_note"):
        parts.append(c["chain_note"])
    return "; ".join(parts)


def pick_day(candidates: list[dict], kept: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """Choose one day's picks: at most MAX_HOT_PER_DAY "Tin nóng" and MAX_USABLE_PER_DAY "Dùng được ngay", each at
    or above CANDIDATE_THRESHOLD and past every gate. A day without a hot pick keeps its usable picks (owner decision
    3) but still at most MAX_USABLE_PER_DAY (spec §4.2: "tối đa 1 tin làn A và 1–2 tin làn B").
    Returns (picks, refused) where refused lists strong candidates and why they were not taken."""
    picks, refused = [], []
    eligible = sorted((c for c in candidates if not c["gates"] and c["score"] >= CANDIDATE_THRESHOLD), key=_rank)
    # The guide lane comes before the usable lane, so a guide takes a slot the usable lane would have had.
    for lane, limit in ((LANE_HOT, MAX_HOT_PER_DAY), (LANE_GUIDE, MAX_GUIDE_PER_DAY), (LANE_USABLE, MAX_USABLE_PER_DAY)):
        taken = 0
        lane_candidates = [c for c in eligible if c["lane"] == lane]
        if lane == LANE_GUIDE:   # oldest approved guide first, so none waits behind a newer one
            lane_candidates.sort(key=lambda c: (c.get("published_at") or "", c.get("id") or ""))
        for c in lane_candidates:
            if taken >= limit or len(picks) >= MAX_PER_DAY:
                refused.append({**c, "refused": "đã đủ chỗ trong ngày"})
                continue
            c = dict(c)
            blocked = chain_block(c, kept + picks, now)
            if blocked:
                refused.append({**c, "refused": blocked})
                continue
            picks.append({**c, "picked_at": now.isoformat()})
            taken += 1
    for p in picks:
        p["reason"] = _reason(p)
    return picks, refused


def _public(c: dict) -> dict:
    keys = ("id", "kind", "lane", "score", "breakdown", "reason", "title", "headline_vi", "published_at",
            "hco_url", "source_urls", "visual_links", "install_command", "gates", "refused")
    out = {k: c[k] for k in keys if k in c and c[k] is not None}
    out["lane_name"] = LANE_NAMES[c["lane"]]
    return out


def _history(previous: dict | None, today) -> list[dict]:
    """The stored days of the last published file that are before today (Vietnam date), newest first, verbatim.

    These are the picks that were actually offered; they are never re-scored. A day dated today is dropped, so a
    rerun recomputes today from scratch and today's earlier run never blocks it.
    """
    days = previous.get("days") if isinstance(previous, dict) else None
    out = {}
    for day in days if isinstance(days, list) else []:
        if not isinstance(day, dict) or not isinstance(day.get("picks"), list):
            continue
        try:
            date = datetime.strptime(_str(day.get("date")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if date < today and 0 < (today - date).days <= HISTORY_DAYS and date not in out:
            out[date] = {**day, "picks": [p for p in day["picks"] if isinstance(p, dict) and isinstance(p.get("id"), str)
                                          and p.get("lane") in LANE_NAMES]}
    return [out[d] for d in sorted(out, reverse=True)]


def _stored_pick(pick: dict, day: dict) -> dict:
    """A stored pick as the chain rule reads it: its chain keys and the moment it was offered."""
    chain = pick.get("chain") if isinstance(pick.get("chain"), dict) else (
        _repo_chain(pick.get("id")) if pick.get("kind") == "repo" else {})
    return {**pick, "chain": chain, "picked_at": pick.get("picked_at") or day.get("picked_at") or f"{day['date']}T12:00:00+07:00"}


def video_candidates(stories: list[dict], decision_rows: dict | None = None, repos: list[dict] | None = None,
                     now: datetime | None = None, previous: dict | None = None) -> dict:
    """Today's video candidates (Vietnam date of `now`) plus the stored picks of earlier days, newest day first.

    `previous` is the last published file (update.yml fetches it from hco.news). Its earlier days are the picker's
    memory: kept verbatim, never re-scored with today's momentum, and their picks feed the 3-day chain rule. Only
    today is computed, from stories published in the FRESH_HOURS before `now` that no stored day already picked,
    and from the snapshot's repos. Without a previous file (first run, failed fetch) today is picked without
    memory; earlier days are not replayed, because a replay files a story that heated up overnight under a day
    already gone and would then be stored as a pick that was never offered.
    """
    now = now or datetime.now(timezone.utc)
    today = _vn_date(now)
    rows = decision_rows or {}
    history = _history(previous, today)
    kept = [_stored_pick(p, day) for day in history for p in day["picks"]]
    stored_ids = {p["id"] for p in kept}
    # A guide is offered once ever: stored days only reach back HISTORY_DAYS, so the ids of offered guides are also
    # kept, with the date offered, under `guide_log`. A date of today is ignored so a rerun recomputes today.
    guide_log = {gid: day for gid, day in (previous.get("guide_log") if isinstance(previous, dict)
                                           and isinstance(previous.get("guide_log"), dict) else {}).items()
                 if isinstance(gid, str) and isinstance(day, str) and day < today.isoformat()}
    stored_ids |= set(guide_log)
    scored = [score_story(s, rows.get(s.get("id"))) for s in stories if isinstance(s, dict) and s.get("id")]
    pool = [c for c in scored if c["id"] not in stored_ids
            and (c["lane"] == LANE_GUIDE or (_at(c) and timedelta(0) <= now - _at(c) <= timedelta(hours=FRESH_HOURS)))]
    pool += [score_repo(r) for r in repos or [] if isinstance(r, dict)]
    picks, refused = pick_day(pool, kept, now)
    excluded = sorted([c for c in pool if c["gates"]], key=_rank)[:5]
    today_out = {
        "date": today.isoformat(), "picked_at": now.isoformat(),
        "picks": [_public(p) | {"picked_at": p["picked_at"], "chain": _chain(p)} for p in picks],
        "no_video": not picks,
        "refused": [_public(c) for c in refused[:5]],
        "excluded": [_public(c) for c in excluded],
    }
    result = {
        "schema_version": 2, "version": CANDIDATES_VERSION, "generated_at": now.isoformat(),
        "memory": "stored" if previous is not None and isinstance(previous, dict) else "cold-start",
        "rubric": {"threshold": CANDIDATE_THRESHOLD, "major_followup_threshold": MAJOR_THRESHOLD,
                   "chain_days": CHAIN_DAYS, "fresh_hours": FRESH_HOURS, "max_per_day": MAX_PER_DAY,
                   "max_hot_per_day": MAX_HOT_PER_DAY, "max_usable_per_day": MAX_USABLE_PER_DAY,
                   "max_guide_per_day": MAX_GUIDE_PER_DAY,
                   "min_hot_sources": MIN_HOT_SOURCES, "hook_points": HOOK_POINTS},
        "days": [today_out] + history,
    }
    offered = {**guide_log, **{p["id"]: today.isoformat() for p in picks if p["lane"] == LANE_GUIDE}}
    if offered:
        result["guide_log"] = dict(sorted(offered.items()))
    return result


def write_video_candidates(input_path: str | Path, output_path: str | Path, decisions_path: str | Path | None = None,
                           now: datetime | None = None) -> dict:
    """Read the snapshot and newsroom decisions, write the candidates file atomically, return its payload."""
    from radar.newsroom_decisions import load_decisions, story_decisions
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    stories = [s for s in payload.get("stories") or [] if isinstance(s, dict)]
    decisions = load_decisions(decisions_path, now=now) if decisions_path is not None else load_decisions(now=now)
    rows = story_decisions(stories, decisions) if decisions is not None else {}
    previous = None
    output_path = Path(output_path)
    if output_path.is_file():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
    result = video_candidates(stories, rows, payload.get("repos") or [], now=now, previous=previous)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(result, output_path)
    return result


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
                          ref: str | None = None,
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

    if ref is None:
        ref = os.environ.get("GITHUB_REF") or os.environ.get("GITHUB_REF_NAME") or ""

    # 1. Check daily schedule window [05:00, 06:00) VN time.
    # Non-main refs (branches) ignore the time window for on-demand testing,
    # while strictly preserving daily idempotency and shared ledger quota.
    on_branch = is_non_main_ref(ref)
    in_window = is_scheduled_window(now_vn)
    if not force and not on_branch and not in_window:
        return {
            "status": "outside_window",
            "date": today_vn,
            "tokens": 0,
            "script_written": False,
            "ledger_written": False,
            "detail": f"hour {now_vn.hour} is outside {SCHEDULED_START_HOUR}:00-{SCHEDULED_END_HOUR}:00 VN time"
        }

    # 2. Read input stories
    # Daily identity belongs to the published script, not today's changing picks.
    if not force and summary_budget.is_script_written_today(
            script_path=output_path, ledger_path=ledger_path, today_vn=today_vn):
        return {"status": "already_generated", "date": today_vn, "tokens": 0,
                "script_written": False, "ledger_written": False}

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
            "detail": f"found only {len(selected)} eligible translated stories with >= 2 news sources"
        }

    stories_map = {s["id"]: s for s in selected}

    # 5. Check API credentials & free-tier confirmation
    api_key = os.environ.get("GEMINI_API_KEY", "")
    paid = gemini_paid_budget.enabled()
    confirmed = paid or os.environ.get("RADAR_GEMINI_FREE_TIER_CONFIRMED") == "1"
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
    cap_err = None if paid else summary_budget.capacity_error(ledger_path, now=now.timestamp())
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
    req_body = build_gemini_request(selected)
    if paid:
        estimated_tokens = len(json.dumps(req_body).encode("utf-8")) + req_body["generationConfig"]["maxOutputTokens"]
    paid_reservation = None
    if paid:
        reserve_err, paid_reservation = gemini_paid_budget.reserve(
            gemini_paid_budget.ledger_path(), estimated_tokens, now=reserve_now,
            consumer="video", idempotency_key=today_vn)
    else:
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
    if paid:
        gemini_paid_budget.settle(gemini_paid_budget.ledger_path(), paid_reservation,
                                 actual_tokens, now=reserve_now)
    elif actual_tokens > 0:
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
    summary_budget.mark_script_completed(ledger_path, today_vn)

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
    parser.add_argument("--ref", default=None,
                        help="Git ref or branch name (non-main refs bypass schedule window)")
    parser.add_argument("--now", help="Explicit ISO timestamp for offline testing")
    parser.add_argument("--candidates-output", default=None,
                        help="Video candidates output path (defaults to video-candidates.json beside --output, "
                             "i.e. site/data/video-candidates.json); empty string skips it")
    parser.add_argument("--decisions", default=None,
                        help="Newsroom decisions path (defaults to RADAR_NEWSROOM_DECISIONS or phong-bao/decisions.json)")
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

    # Candidates are pure code (no model call), so they are refreshed on every run, outside the script window too.
    candidates_path = (Path(args.output).with_name("video-candidates.json") if args.candidates_output is None
                       else args.candidates_output)
    if candidates_path and input_path.is_file():
        try:
            result = write_video_candidates(input_path, candidates_path, args.decisions, now=now_val)
            today = result["days"][0] if result["days"] else {}
            print(f"Video candidates written: date={today.get('date')}, picks={len(today.get('picks') or [])}")
        except Exception as error:  # the daily script must not depend on the candidates file
            print(f"Video candidates failed: {error}")

    res = generate_video_script(
        input_path=input_path,
        output_path=args.output,
        ledger_path=args.ledger,
        editor_picks_path=args.editor_picks,
        force=args.force or (os.environ.get("RADAR_VIDEO_SCRIPT_FORCE") == "1"),
        ref=args.ref,
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
