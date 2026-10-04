"""Explainable worth score and why-line for stories.

THE WEIGHTS ARE A FIRST GUESS (04/10). They will be calibrated on a week of real snapshots:
what readers open, what the daily edition keeps, what an editor would have chosen
(plans/reports/feed-dang-doc-report.md).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import math
import re

from radar.items import instant

# THE WEIGHTS ARE A FIRST GUESS (04/10). They will be calibrated on a week of real snapshots:
# what readers open, what the daily edition keeps, what an editor would have chosen.
WORTH = {
    "attention": 35.0,
    "attentionFull": 60.0,   # points; full at hot_score 60 (the window's top on 04/10 ran from 57 to 69)
    "breadth": 35.0,
    "breadthFull": 4.0,     # points; 0 for one publisher, full at 4 independent publishers
    "freshness": 15.0,
    "halfLifeH": 24.0,      # points at publication (unmeasured stories); half after 24 h, a quarter after 48 h
    "firstHand": 1.3,       # multiplier for a first-hand story
    "hotLabel": 20.0,       # hot_score from which a card says "Đang bàn nhiều" or "Đang được chú ý"
    "picksMax": 5,          # "Đáng đọc hôm nay" shows up to 5; fewer only when fewer stories have evidence
    "sameEvent": 0.34,      # title-word overlap from which two stories count as one event in the block
}

NOT_FIRST_HAND = {"hf-trending"}

LAB_NAME = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta",
    "microsoft": "Microsoft",
    "nvidia": "NVIDIA",
    "amazon": "Amazon",
    "mistral": "Mistral",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "huggingface": "Hugging Face",
}

METRIC_WORDS = {
    "points": "điểm",
    "comments": "bình luận",
    "score": "điểm",
    "upvotes": "lượt bình chọn",
    "likes": "lượt thích",
    "downloads": "lượt tải",
    "trendingScore": "điểm thịnh hành",
    "trending_score": "điểm thịnh hành",
    "stars_today": "sao hôm nay",
    "stargazers_count": "sao",
    "stars": "sao",
    "forks": "lượt phân nhánh",
}

PREFER_METRICS = [
    "points", "score", "stars", "upvotes", "likes", "trending_score", "downloads", "comments"
]

TZ_VN = timezone(timedelta(hours=7))


def src_name(source_id, sources_map=None):
    """Normalize a source name by removing parenthesized notes, matching feed.js."""
    if sources_map and source_id in sources_map:
        info = sources_map[source_id]
        name = info.get("name") if isinstance(info, dict) else getattr(info, "name", None)
        if name:
            return re.sub(r"\s*\(.*?\)\s*", " ", str(name)).strip()
    return re.sub(r"\s*\(.*?\)\s*", " ", str(source_id or "")).strip()


def lab_of(cov, sources_map=None):
    """Return the publishing lab identifier for a coverage item."""
    if not cov:
        return ""
    lab = cov.get("lab")
    if lab:
        return lab
    src = cov.get("source")
    if sources_map and src in sources_map:
        info = sources_map[src]
        if isinstance(info, dict) and info.get("lab"):
            return info["lab"]
    return ""


def first_hand_of(story, sources_map=None):
    """Detect if a story is published first-hand by a lab or original researchers."""
    coverage = story.get("coverage") or []
    own_candidates = []
    for c in coverage:
        lab = lab_of(c, sources_map)
        src = c.get("source")
        if lab and src not in NOT_FIRST_HAND:
            dt = instant(c.get("published_at"))
            ts = dt.timestamp() if dt else 0.0
            own_candidates.append((ts, lab, c))
    if own_candidates:
        own_candidates.sort(key=lambda x: x[0])
        earliest_lab = own_candidates[0][1]
        name = LAB_NAME.get(earliest_lab, earliest_lab)
        return {"label": f"{name} công bố", "why": f"{name} công bố trực tiếp"}
    if story.get("kind") == "paper":
        return {"label": "Bài báo gốc", "why": "bài báo gốc của nhóm nghiên cứu"}
    return None


def uniq_coverage(coverage, sources_map=None):
    """One entry per publisher: highest metric count wins, preserving first occurrence order."""
    best = {}
    for i, c in enumerate(coverage or []):
        if not c:
            continue
        pub = src_name(c.get("source"), sources_map) or c.get("source") or str(i)
        key = str(c.get("publisher") or pub).lower()
        metrics = c.get("metrics") or {}
        score = sum(1 for v in metrics.values() if isinstance(v, (int, float)) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))
        if key not in best or score > best[key]["score"]:
            best[key] = {"c": c, "i": best[key]["i"] if key in best else i, "score": score}
    sorted_items = sorted(best.values(), key=lambda x: x["i"])
    return [x["c"] for x in sorted_items]


def measure_of(story, sources_map=None):
    """Extract the primary measured signal for display in the why-line."""
    hot_signals = story.get("hot_signals") or {}
    m = hot_signals.get("measurement")
    if m and isinstance(m.get("value"), (int, float)) and not (isinstance(m["value"], float) and (math.isnan(m["value"]) or math.isinf(m["value"]))):
        metric = m.get("metric", "")
        speed = m.get("velocity_per_hour")
        valid_speed = speed if (isinstance(speed, (int, float)) and speed > 0 and not (isinstance(speed, float) and (math.isnan(speed) or math.isinf(speed)))) else None
        return {
            "value": m["value"],
            "word": METRIC_WORDS.get(metric, metric),
            "where": src_name(m.get("source"), sources_map),
            "speed": valid_speed,
        }
    coverage = story.get("coverage") or []
    for key in PREFER_METRICS:
        for c in coverage:
            metrics = c.get("metrics") or {}
            v = metrics.get(key)
            if isinstance(v, (int, float)) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                return {
                    "value": v,
                    "word": METRIC_WORDS.get(key, key),
                    "where": src_name(c.get("source"), sources_map),
                    "speed": None,
                }
    return None


def fmt_vi(v):
    """Format integers with Vietnamese dot grouping (1.234), matching faces.js fmt."""
    return f"{int(round(v)):,}".replace(",", ".")


def fmt_speed_vi(v):
    """Format velocity with up to 1 decimal place using Vietnamese comma, matching feed.js nf1."""
    val = round(float(v), 1)
    if val.is_integer():
        return str(int(val))
    return f"{val:.1f}".replace(".", ",")


def ago_vi(iso_str, now_dt):
    """Format publication age relative to snapshot generation time in Vietnamese."""
    pub_dt = instant(iso_str)
    if not pub_dt or not now_dt:
        return "không rõ thời gian"
    diff_s = (now_dt - pub_dt).total_seconds()
    h = diff_s / 3600.0
    if h < 0:
        return "sắp tới"
    if h < 1:
        minutes = max(1, round(h * 60))
        return f"{minutes} phút trước"
    if h < 24:
        hours = round(h)
        return f"{hours} giờ trước"

    now_vn = now_dt.astimezone(TZ_VN)
    pub_vn = pub_dt.astimezone(TZ_VN)
    days = (now_vn.date() - pub_vn.date()).days
    if days <= 1:
        return f"hôm qua, {pub_vn.strftime('%H:%M')}"
    if days < 7:
        return f"{days} ngày trước"
    return f"{pub_vn.day}/{pub_vn.month}/{pub_vn.year}"


def worth_why_line(story, worth_data, sources_map=None, now_dt=None):
    """Build the Vietnamese 'Vì sao nên đọc' line from real measured numbers only."""
    fh = worth_data.get("fh")
    n = worth_data.get("n", 1)
    m = measure_of(story, sources_map)
    parts = []
    if fh:
        parts.append(escape(fh["why"]))
    if n >= 2:
        parts.append(f'<b class="num">{n}</b> nguồn cùng đưa tin')
    if m:
        where_str = f" trên {escape(m['where'])}" if m.get("where") else ""
        parts.append(f'<b class="num">{fmt_vi(m["value"])}</b> {escape(m["word"])}{where_str}')
    if m and m.get("speed") and len(parts) < 3:
        parts.append(f'tăng <b class="num">{fmt_speed_vi(m["speed"])}</b> {escape(m["word"])} mỗi giờ')
    pub_at = story.get("published_at")
    ago_str = ago_vi(pub_at, now_dt)
    parts.append(f"đăng {escape(ago_str)}")
    return " · ".join(parts)


def calculate_worth(story, now_dt, sources_map=None):
    """Calculate the 'Đáng đọc' worth score, measured components, and why-line.

    No invented data: components without real measurements are absent from parts.
    """
    meas = (story.get("hot_signals") or {}).get("measurement")
    hot_score = story.get("hot_score")
    has_hot = meas and isinstance(hot_score, (int, float)) and not (isinstance(hot_score, float) and (math.isnan(hot_score) or math.isinf(hot_score)))
    hot = max(0.0, float(hot_score)) if has_hot else 0.0

    covs = uniq_coverage(story.get("coverage"), sources_map)
    n = len(covs)

    pub_dt = instant(story.get("published_at"))
    if now_dt and pub_dt:
        age_h = max(0.0, (now_dt - pub_dt).total_seconds() / 3600.0)
        fresh_score = WORTH["freshness"] * (0.5 ** (age_h / WORTH["halfLifeH"]))
    else:
        age_h = None
        fresh_score = 0.0

    fh = first_hand_of(story, sources_map)

    att_score = WORTH["attention"] * min(1.0, hot / WORTH["attentionFull"])
    brd_score = WORTH["breadth"] * min(1.0, max(0.0, float(n - 1)) / (WORTH["breadthFull"] - 1.0))

    mult = WORTH["firstHand"] if fh else 1.0
    total_score = (att_score + brd_score + fresh_score) * mult

    # Boundary: No invented data. Only include measured parts in parts dictionary.
    parts = {}
    if meas and hot > 0:
        parts["attention"] = round(att_score, 2)
    if n >= 2:
        parts["breadth"] = round(brd_score, 2)
    if pub_dt:
        parts["freshness"] = round(fresh_score, 2)

    worth_data = {
        "score": round(total_score, 2),
        "parts": parts,
        "hot": hot,
        "n": n,
        "fh": fh,
        "metric": meas.get("metric") if (meas and isinstance(meas, dict)) else None,
        "evidence": bool(fh or n >= 2 or hot > 0)
    }

    worth_data["why"] = worth_why_line(story, worth_data, sources_map, now_dt)
    return worth_data


def annotate_story_worth(story, now_dt, sources_map=None):
    """Annotate a story dictionary in place with worth_score, worth_parts, and worth_why."""
    w = calculate_worth(story, now_dt, sources_map)
    story["worth_score"] = w["score"]
    story["worth_parts"] = w["parts"]
    story["worth_why"] = w["why"]
    return w
