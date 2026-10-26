"""Build the hand-reviewed labels from the fixed live sample and public evidence."""

import json
import gzip
import random
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).parent
snapshot = json.loads(gzip.decompress((ROOT / "snapshot-261026.json.gz").read_bytes()))
evidence = json.loads((ROOT / "evidence-261026.json").read_bytes())
alternatives = json.loads((ROOT / "alternatives-261026.json").read_bytes())
ranked = sorted(snapshot["stories"],
                key=lambda row: (-(row.get("importance_weight") or 0), row["id"]))
sample = ranked[:40] + random.Random(261026).sample(ranked[40:], 110)

# Exclusive editorial decision for each junk story; source-body evidence was
# reviewed wherever it was available. Unverified blocked pages stay non-junk.
JUNK = {
    19: ("customer_case_study", "Bài AWS kể quy trình Octave dùng Bedrock để triển khai cho khách hàng."),
    23: ("incidental_ai", "Tin niêm yết nhà sản xuất PCB; AI chỉ là bối cảnh cầu thị trường trong teaser."),
    40: ("non_news_page", "Bài đăng Bluesky là ý kiến về mức chi token, không có sự kiện mới."),
    53: ("non_news_page", "Trang bộ dữ liệu Hugging Face không nêu lần phát hành hay sự kiện tin tức."),
    56: ("incidental_ai", "Thân bài chỉ hướng dẫn vẽ GeoJSON bằng Amazon Quick Sight, không có ứng dụng AI."),
    57: ("customer_case_study", "Bài AWS kể cách khách hàng Eon cấu hình MCP Gateway trên Bedrock AgentCore."),
    63: ("customer_case_study", "Bài Sakana mô tả một khách hàng đưa Sakana Namazu vào Evidence Finder."),
    68: ("non_news_page", "README Supabase là trang giới thiệu nền tảng lâu dài, không có tin phát hành cụ thể."),
    70: ("non_news_page", "Model card chỉ có danh mục liên kết, không có thân bài về lần phát hành."),
    73: ("non_news_page", "Dataset card chỉ có mô tả bộ persona và liên kết, không có tin mới."),
    74: ("vendor_sales", "Trang Spinoza Labs trưng các demo và lời chào sản phẩm Vortex Code."),
    77: ("incidental_ai", "Phần chính của bài Nextgov là bảng lương OPM; AI chỉ là một nhánh trong kế hoạch CIO."),
    78: ("tutorial", "Bài NVIDIA hướng dẫn nạp dữ liệu vào GPU bằng GPUDirect Storage, không phải sự kiện mới."),
    85: ("non_news_page", "Bài đăng Bluesky nói về dấu vết suy luận của phép tính, không có sự kiện mới."),
    90: ("vendor_sales", "Thông báo nhận giải của chính Sakana chủ yếu quảng bá thành tích và tuyển dụng."),
    91: ("non_news_page", "Bài đăng Bluesky suy đoán chi phí Uber dựa trên giả định số kỹ sư."),
    93: ("non_news_page", "Bài đăng Bluesky khoe một demo city builder, không có sự kiện tin tức."),
    112: ("non_news_page", "Bài đăng Bluesky là lời nhắc ý kiến kèm liên kết, không phải bài nguồn."),
    114: ("non_news_page", "Model card chỉ hiện 'Refreshing', không nêu nội dung phát hành."),
    115: ("non_news_page", "README một bản fork AnythingLLM Desktop chỉ quảng bá bản đóng gói."),
    116: ("non_news_page", "README Runic giới thiệu ứng dụng theo dõi token, không có sự kiện phát hành được định ngày."),
    118: ("vendor_sales", "Thân bài ghi 'Sponsored Presented by Vanguard' và giới thiệu buổi hội thảo."),
    121: ("non_news_page", "Trang Google giới thiệu video đối thoại phi hành gia, không có tin AI cụ thể."),
    127: ("tutorial", "Bài NVIDIA hướng dẫn dùng VSS Blueprint 3.3, chủ yếu là nội dung triển khai kỹ thuật."),
    130: ("non_news_page", "Bài đăng Bluesky kể một lần chạy phép cộng trên Qwen, không có sự kiện mới."),
    132: ("non_news_page", "README cindy là trang giới thiệu ứng dụng, không có tin phát hành cụ thể."),
    137: ("non_news_page", "Trang GitHub gom lịch sử nhiều bản TradingAgents; card không gắn với một sự kiện phát hành."),
    146: ("vendor_sales", "README huashu-design có lời quảng cáo sản phẩm, lệnh cài và nhiều mẫu demo."),
    148: ("non_news_page", "Ghi chú web-edit 0.1a1 là release note nhỏ, không có bài tin đủ ngữ cảnh."),
}

ALTERNATIVE_URL = {
    22: "https://artificialwatch.com/wire/metr-redwood-red-team-openai-internal-agent-monitoring",
    27: "https://technode.com/2026/10/19/deepseek-releases-v4-1-flash-1017-with-stronger-coding-and-agent-capabilities/",
    37: "https://www.datacenterknowledge.com/ai-data-centers/nvidia-unveils-dsx-pod-for-faster-ai-data-center-builds",
    38: "https://decrypt.co/381570/fill",
    49: "https://www.theguardian.com/technology/2026/oct/16/meta-releases-muse-spark-open-a-new-open-weight-ai-model",
    58: "https://www.channelnewsasia.com/singapore/govtech-google-deepmind-ai-scam-quantum-sicw-6455621",
    80: "https://decrypt.co/381763/sweden-government-offices-block-chatgpt-claude",
}
FOUND_IN = {27: "snapshot.stories"}
ALT_ROWS = {(row["index"], row["url"]): row for row in alternatives}
CLUSTER_ISSUE = {
    10: "Một trang changelog gộp 30 mục khác sự kiện vào cùng story.",
    22: "Coverage ghép bài Semafor về sự cố agent tắt monitor với báo cáo red-team METR/Redwood.",
    24: "Coverage ghép nhầm bài China Telecom về mô hình Xing4.0 vào tin NVIDIA/Nokia.",
    25: "Coverage ghép nhầm bài SCMP về Discovery Loop vào tin NVIDIA y sinh.",
    97: "Một trang changelog gộp 12 mục Gemini khác sự kiện vào cùng story.",
}


def one_line(text):
    return re.sub(r"\s+", " ", text).strip()


def article_status(row):
    if row["access"] == "robots_blocked":
        return "robots_blocked"
    if row["access"] == "http_blocked":
        return "http_blocked"
    if row["access"] == "parse_error":
        return "parse_error"
    visible_text = row.get("article_excerpt", "") + " " + row.get("article_tail", "")
    if re.search(r"\b(?:subscribe to (?:read|continue)|sign in to (?:read|continue)|"
                 r"subscriber[- ]only|members[- ]only|unlock the full article|please subscribe)\b",
                 visible_text, re.I):
        return "paywalled"
    if row["access"] == "parsed" and row.get("article_chars", 0) >= 300 and row["index"] != 58:
        return "readable"
    return "too_short"


def main():
    generated = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
    rows = []
    for index, story in enumerate(sample):
        page = evidence["stories"][index]
        assert page["id"] == story["id"] and page["index"] == index
        status = article_status(page)
        published = story.get("published_at")
        age_days = ((generated - datetime.fromisoformat(published.replace("Z", "+00:00")))
                    .total_seconds() / 86400) if published else None
        old = age_days is not None and age_days > 30
        kind, explanation = JUNK.get(index, (None, ""))
        if kind is None and old:
            kind = "stale_content"
            explanation = f"Bài gốc ngày {published[:10]} đã {age_days:.0f} ngày tuổi khi lên snapshot."
        if not explanation:
            if status == "readable":
                explanation = (f"Thân bài công khai có {page['article_chars']} ký tự; "
                               f"nội dung kiểm được: {one_line(page.get('article_excerpt', ''))[:115]}")
            else:
                detail = f"HTTP {page.get('http_status')}" if status == "http_blocked" else status
                explanation = f"Chưa đọc được thân bài ({detail}); chưa đủ căn cứ gắn nhãn rác nội dung."
        if old and kind != "stale_content":
            explanation += f" Trang nguồn cũ {age_days:.0f} ngày."
        if index in CLUSTER_ISSUE:
            explanation += " " + CLUSTER_ISSUE[index]
        alternative = None
        if status != "readable" and index in ALTERNATIVE_URL:
            url = ALTERNATIVE_URL[index]
            candidate = ALT_ROWS[(index, url)]
            assert candidate["access"] == "parsed" and candidate.get("article_chars", 0) >= 300
            alternative = {"url": url, "found_in": FOUND_IN.get(index, "public_search"),
                           "article_chars": candidate["article_chars"]}
        record = {
            "id": story["id"], "url": story["url"], "title": story["title"],
            "sample_group": "top_40" if index < 40 else "random_110",
            "importance_weight": story.get("importance_weight"),
            "importance_tier": story.get("importance_tier"),
            "published_at": published,
            "labels": {"junk": kind is not None, "junk_kind": kind,
                       "old_content_reposted": old, "duplicate_of": None,
                       "article_status": status,
                       "readable_alternative": alternative is not None},
            "reason": one_line(explanation),
            "alternative_source": alternative,
            "article_evidence": one_line(page.get("article_excerpt", ""))[:240] or None,
            "cluster_issue": CLUSTER_ISSUE.get(index),
        }
        rows.append(record)
    output = {"snapshot_url": "https://radar-ai-vn.pages.dev/data/radar-ui.json",
              "generated_at": snapshot["generated_at"], "sample_seed": 261026,
              "sampling": "importance_weight descending, id ascending; top 40 + Random(seed).sample(rest, 110)",
              "stories": rows}
    (ROOT / "nhan-tin-261026.json").write_bytes(
        (json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print("total", len(rows), "junk", sum(r["labels"]["junk"] for r in rows),
          "top40_junk", sum(r["labels"]["junk"] for r in rows[:40]))
    print("kinds", dict(Counter(r["labels"]["junk_kind"] for r in rows if r["labels"]["junk"])))
    print("access", dict(Counter(r["labels"]["article_status"] for r in rows)))
    print("alternatives", [i for i, r in enumerate(rows) if r["labels"]["readable_alternative"]])
    print("old", sum(r["labels"]["old_content_reposted"] for r in rows))


if __name__ == "__main__":
    main()
