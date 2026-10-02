"""First-wave endpoint inventory, publisher identity and relevance boundaries."""

from datetime import timedelta
from urllib.parse import urlencode

RSS = [
    ("simon-willison", "Simon Willison", "research", "simon-willison", "https://simonwillison.net/atom/everything/", True),
    ("interconnects", "Interconnects", "research", "interconnects", "https://www.interconnects.ai/feed", False),
    ("import-ai", "Import AI", "newsletter", "import-ai", "https://importai.substack.com/feed", False),
    ("ai-news", "AI News", "newsletter", "smol-ai", "https://buttondown.com/ainews/rss", False),
    ("dwarkesh-podcast", "Dwarkesh Podcast", "podcast", "dwarkesh", "https://api.substack.com/feed/podcast/69345.rss", True),
    ("latent-space", "Latent Space", "podcast", "latent-space", "https://api.substack.com/feed/podcast/1084089.rss", False),
    ("no-priors", "No Priors", "podcast", "no-priors", "https://feeds.megaphone.fm/nopriors", False),
    ("techcrunch-ai", "TechCrunch AI", "press", "techcrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", False),
    ("verge-ai", "The Verge AI", "press", "the-verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", False),
    ("ars-ai", "Ars Technica AI", "press", "ars-technica", "https://arstechnica.com/ai/feed/", False),
    ("mit-tech-review", "MIT Technology Review AI", "press", "mit-tech-review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", False),
    ("microsoft-research", "Microsoft Research", "lab", "microsoft", "https://www.microsoft.com/en-us/research/feed/", False),
    ("nvidia-blog", "NVIDIA Technical Blog", "lab", "nvidia", "https://developer.nvidia.com/blog/feed", True),
    ("vnexpress-tech", "VnExpress Số Hóa AI", "vietnam", "vnexpress", "https://vnexpress.net/rss/so-hoa.rss", True),
    ("dwarkesh-video", "Dwarkesh video", "podcast", "dwarkesh", "https://www.youtube.com/feeds/videos.xml?channel_id=UCXl4i9dYBrFOabk0xGmbkRA", True),
]
NVIDIA_CHANNEL = ("nvidia-youtube", "nvidia", "NVIDIA", "NVIDIA", "UCHuiy8bXnmK5nisYHUd1J5g")

# Keep unavailable endpoints in the inventory and exported source health records.
DISABLED = {
    "import-ai": "Substack feed returned HTTP 403 on the hosted runner; an alternate author-site feed has not yet been verified.",
    "dwarkesh-podcast": "Substack podcast feed returned HTTP 403 on the hosted runner; Dwarkesh video remains a separate source.",
    "latent-space": "Substack podcast feed returned HTTP 403 on the hosted runner; no alternate feed has been verified.",
}


def source(id_, name, url, parser, group, publisher, **extra):
    return dict(id=id_, name=name, url=url, parser=parser, kind="rss" if parser == "feed" else "json",
                group=group, publisher=publisher, lab=publisher if group == "lab" else "",
                first_wave=True, **extra)


def sources(now):
    result = [source(id_, name, url, "feed", group, publisher, filter_ai=filter_ai)
              for id_, name, group, publisher, url, filter_ai in RSS]
    for row in result:
        if row["id"] in DISABLED:
            row.update(disabled=True, disabled_reason=DISABLED[row["id"]])
    after = int((now - timedelta(days=7)).timestamp())
    for id_, tags, query in (("hn-front", "front_page", ""), ("hn-ai", "story", "AI")):
        params = {"tags": tags, "hitsPerPage": 100, "numericFilters": "created_at_i>=" + str(after)}
        if query:
            params["query"] = query
        result.append(source(id_, "Hacker News", "https://hn.algolia.com/api/v1/search?" + urlencode(params), "hn", "forum", "hacker-news"))
    result.extend([
        source("lobsters-ai", "Lobsters AI", "https://lobste.rs/hottest.json", "lobsters", "forum", "lobsters"),
        source("hf-papers", "Hugging Face Daily Papers", "https://huggingface.co/api/daily_papers?limit=50", "papers", "paper", "huggingface"),
        source("hf-models-ranked", "HF trending models", "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=20", "hf_trending", "repository", "huggingface", repo_type="model"),
        source("hf-spaces-ranked", "HF trending spaces", "https://huggingface.co/api/spaces?sort=trendingScore&direction=-1&limit=20", "hf_trending", "repository", "huggingface", repo_type="space"),
        source("github-ai", "GitHub AI repositories", "https://api.github.com/search/repositories?" + urlencode({"q": "topic:llm created:>=" + (now - timedelta(days=7)).date().isoformat(), "sort": "stars", "order": "desc", "per_page": 20}), "github", "repository", "github"),
    ])
    return result
