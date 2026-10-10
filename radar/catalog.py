"""First-wave endpoint inventory, publisher identity and relevance boundaries."""

from datetime import timedelta
from urllib.parse import urlencode

RSS = [
    ("simon-willison", "Simon Willison", "research", "simon-willison", "https://simonwillison.net/atom/everything/", True),
    ("interconnects", "Interconnects", "research", "interconnects", "https://www.interconnects.ai/feed", False),
    ("import-ai", "Import AI", "newsletter", "import-ai", "https://jack-clark.net/feed/", False),
    ("ai-news", "AI News", "newsletter", "smol-ai", "https://news.smol.ai/rss.xml", False),
    ("dwarkesh-podcast", "Dwarkesh Podcast", "podcast", "dwarkesh", "https://www.dwarkeshpatel.com/feed", True),
    ("latent-space", "Latent Space", "podcast", "latent-space", "https://api.substack.com/feed/podcast/1084089.rss", False),
    ("no-priors", "No Priors", "podcast", "no-priors", "https://feeds.megaphone.fm/nopriors", False),
    ("techcrunch-ai", "TechCrunch AI", "press", "techcrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", False),
    ("verge-ai", "The Verge AI", "press", "the-verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", False),
    ("ars-ai", "Ars Technica AI", "press", "ars-technica", "https://arstechnica.com/ai/feed/", False),
    ("mit-tech-review", "MIT Technology Review AI", "press", "mit-tech-review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", False),
    ("microsoft-research", "Microsoft Research", "lab", "microsoft", "https://www.microsoft.com/en-us/research/feed/", False),
    ("nvidia-blog", "NVIDIA Technical Blog", "lab", "nvidia", "https://developer.nvidia.com/blog/feed", True),
    ("dwarkesh-video", "Video Dwarkesh", "podcast", "dwarkesh", "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId=UUXl4i9dYBrFOabk0xGmbkRA&maxResults=50", True),
    ("vnexpress-tech", "VnExpress International Tech", "press", "vnexpress", "https://e.vnexpress.net/rss/tech.rss", True),
    ("genk-ai", "GenK AI", "press", "genk", "https://genk.vn/rss/ai.rss", False),
    ("tuoitre-so", "Tuổi Trẻ Nhịp sống số", "press", "tuoi-tre", "https://tuoitre.vn/rss/nhip-song-so.rss", True, {"default_tz": "+07:00"}),
    ("thanhnien-cong-nghe", "Thanh Niên Công nghệ", "press", "thanh-nien", "https://thanhnien.vn/rss/cong-nghe.rss", True),
    ("theregister-ai", "The Register AI/ML", "press", "the-register", "https://www.theregister.com/software/ai_ml/headlines.atom", False),
    ("wired-ai", "Wired AI", "press", "wired", "https://www.wired.com/feed/tag/ai/latest/rss", False),
    ("404media", "404 Media", "press", "404-media", "https://www.404media.co/rss/", True),
    ("semafor", "Semafor", "press", "semafor", "https://www.semafor.com/rss.xml", True),
    ("cnbc-tech", "CNBC Tech", "press", "cnbc", "https://www.cnbc.com/id/19854910/device/rss/rss.html", True),
    ("bloomberg-tech", "Bloomberg Technology", "press", "bloomberg", "https://feeds.bloomberg.com/technology/news.rss", True),
    ("fedscoop", "FedScoop", "press", "fedscoop", "https://fedscoop.com/feed/", True),
    ("nextgov-ai", "Nextgov AI", "press", "nextgov", "https://www.nextgov.com/rss/artificial-intelligence/", False),
    ("technode", "TechNode", "press", "technode", "https://technode.com/feed/", True),
    ("pandaily", "Pandaily", "press", "pandaily", "https://pandaily.com/feed/", True),
    ("scmp-tech", "SCMP Tech", "press", "scmp", "https://www.scmp.com/rss/36/feed", True),
    ("restofworld", "Rest of World", "press", "rest-of-world", "https://restofworld.org/feed/latest/", True),
    ("meta-newsroom", "Meta Newsroom", "lab", "meta", "https://about.fb.com/news/feed/", True),
    ("microsoft-blog", "Official Microsoft Blog", "lab", "microsoft", "https://blogs.microsoft.com/feed/", True),
    ("aws-ml-blog", "AWS Machine Learning Blog", "lab", "amazon", "https://aws.amazon.com/blogs/machine-learning/feed/", False),
    ("nvidia-newsroom", "NVIDIA Newsroom", "lab", "nvidia", "https://nvidianews.nvidia.com/releases.xml", True),
    ("qwen-blog", "Qwen Blog", "lab", "qwen", "https://qwenlm.github.io/blog/index.xml", False),
]
NVIDIA_CHANNEL = ("nvidia-youtube", "nvidia", "NVIDIA", "NVIDIA", "UCHuiy8bXnmK5nisYHUd1J5g")

# Editorial retirements stay in the inventory as disabled sources, so observations
# still held by 7-day retention resolve to a source record during publication.
# Their coverage is withdrawn from every reader-facing output (see is_retired).
_VN_PRESS_REASON = ("Đã gỡ theo quyết định biên tập: báo Việt Nam đa số đăng lại tin của nơi khác; "
                    "radar lấy tin trực tiếp từ nguồn gốc.")
RETIRED = dict.fromkeys(("vnexpress-tech", "genk-ai", "tuoitre-so", "thanhnien-cong-nghe"), _VN_PRESS_REASON)

# Keep unavailable endpoints in the inventory and exported source health records.
DISABLED = {
    **RETIRED,
    "latent-space": "Nguồn podcast trên Substack trả mã HTTP 403 trên máy dựng của GitHub; chưa kiểm được nguồn thay thế.",
    "cnbc-tech": "Nguồn CNBC trả mã HTTP 403 trên máy dựng của GitHub; chưa kiểm được nguồn thay thế.",
    "ai-news": "Nguồn smol.ai được đo ngày 2026-10-09 nhưng mục mới nhất là 2026-09-09; hiện không còn đăng đều.",
    "theregister-ai": "Nguồn này không cho phép radar thu thập nội dung.",
    "lobsters-ai": "Nguồn này không cho phép radar thu thập nội dung.",
}


def is_retired(item):
    """True for an observation whose source was editorially retired."""
    return isinstance(item, dict) and item.get("source") in RETIRED


def source(id_, name, url, parser, group, publisher, **extra):
    data = dict(id=id_, name=name, url=url, parser=parser, kind="rss" if parser == "feed" else "json",
                group=group, publisher=publisher, entity=publisher, lab=publisher if group == "lab" else "",
                first_wave=True)
    data.update(extra)
    tz_val = extra.get("default_tz") or extra.get("timezone") or extra.get("tz")
    if tz_val:
        data["default_tz"] = tz_val
        data["timezone"] = tz_val
        data["tz"] = tz_val
    return data


def sources(now):
    result = []
    for row in RSS:
        id_, name, group, publisher, url, filter_ai = row[:6]
        extra = row[6] if len(row) > 6 else {}
        if isinstance(extra, str):
            extra = {"default_tz": extra}
        result.append(source(id_, name, url, "feed", group, publisher, filter_ai=filter_ai, **extra))
    after = int((now - timedelta(days=7)).timestamp())
    for id_, tags, query in (("hn-front", "front_page", ""), ("hn-ai", "story", "AI")):
        params = {"tags": tags, "hitsPerPage": 100, "numericFilters": "created_at_i>=" + str(after)}
        if query:
            params["query"] = query
        result.append(source(id_, "Hacker News", "https://hn.algolia.com/api/v1/search?" + urlencode(params), "hn", "forum", "hacker-news"))
    result.extend([
        source("lobsters-ai", "Lobsters AI", "https://lobste.rs/hottest.json", "lobsters", "forum", "lobsters"),
        source("hf-papers", "Hugging Face Daily Papers", "https://huggingface.co/api/daily_papers?limit=50", "papers", "paper", "huggingface"),
        source("hf-models-ranked", "Mô hình thịnh hành trên Hugging Face", "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=20", "hf_trending", "repository", "huggingface", repo_type="model"),
        source("hf-spaces-ranked", "Space thịnh hành trên Hugging Face", "https://huggingface.co/api/spaces?sort=trendingScore&direction=-1&limit=20", "hf_trending", "repository", "huggingface", repo_type="space"),
        source("github-ai", "Kho mã AI mới trên GitHub", "https://api.github.com/search/repositories?" + urlencode({"q": "topic:llm created:>=" + (now - timedelta(days=7)).date().isoformat(), "sort": "stars", "order": "desc", "per_page": 20}), "github", "repository", "github"),
    ])
    for row in result:
        if row["id"] in DISABLED:
            row.update(disabled=True, disabled_reason=DISABLED[row["id"]])
    for handle in ("simonwillison.net", "emollick.bsky.social"):
        url = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?" + urlencode(
            {"actor": handle, "filter": "posts_with_replies", "limit": 100})
        person = "Simon Willison" if handle.startswith("simon") else "Ethan Mollick"
        entity = "simon-willison" if handle.startswith("simon") else "ethan-mollick"
        result.append(source("bluesky-" + handle.split(".")[0], "Bài đăng của " + person + " trên Bluesky", url,
                             "bluesky", "forum", "bluesky", entity=entity, handle=handle, filter_ai=True))
    return result
