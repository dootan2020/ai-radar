"""Collector and parser for official DeepSeek updates and model releases.

Extracts dated model announcements, API updates, and technical changes from
https://api-docs.deepseek.com/updates and related news pages.
"""

import re
from urllib.parse import urljoin

from radar.classification import classify
from radar.common import clean_text, stable_id, web_url
from radar.items import observation

DEFAULT_SOURCE = {
    "id": "deepseek-news",
    "name": "DeepSeek News",
    "lab": "deepseek",
    "group": "lab",
    "url": "https://api-docs.deepseek.com/updates",
}


def parse_deepseek(text, source=None, observed_at=None):
    """Parse DeepSeek updates from https://api-docs.deepseek.com/updates."""
    if source is None:
        source = DEFAULT_SOURCE

    base_url = "https://api-docs.deepseek.com/updates"
    items, seen = [], set()

    # Split into sections by <h2 ...>Date: YYYY-MM-DD ...</h2>
    date_blocks = re.findall(
        r'<h2[^>]*>\s*Date:\s*(\d{4}-\d{2}-\d{2})\s*.*?</h2>(.*?)(?=<h2|\Z)',
        text,
        re.DOTALL
    )

    for date_str, block_body in date_blocks:
        published_at = f"{date_str}T00:00:00Z"
        
        # Each date block can contain one or more releases in <h3 ...>Title</h3>
        h3_entries = re.findall(r'<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|\Z)', block_body, re.DOTALL)
        
        # If no h3 found, use the block body directly
        if not h3_entries:
            first_p = re.search(r'<p[^>]*>(.*?)</p>', block_body, re.DOTALL)
            desc = re.sub(r'<[^>]+>', ' ', first_p.group(1)).strip() if first_p else ""
            title = f"DeepSeek Update {date_str}"
            h3_entries = [(title, block_body)]

        for raw_title, raw_body in h3_entries:
            title = re.sub(r'<[^>]+>', ' ', raw_title).strip().rstrip('\u200b# ').strip()
            title = clean_text(' '.join(title.split()), 500)
            if not title:
                continue

            desc = re.sub(r'<[^>]+>', ' ', raw_body).strip()
            summary = clean_text(' '.join(desc.split()))
            if not summary:
                summary = title

            # Check if this release links to a specific /news/ page
            news_links = re.findall(r'href=["\'](/news/[^"\']+)["\']', raw_body)
            if news_links:
                item_url = urljoin(base_url, news_links[-1])
            else:
                slug = re.sub(r'[^a-zA-Z0-9]+', '-', title.lower()).strip('-')
                item_url = f"{base_url}#{slug}"

            if item_url in seen:
                continue
            seen.add(item_url)

            kind = classify(title, summary)
            if observed_at is not None:
                obs = observation(source, title, item_url, published_at, observed_at, kind=kind, summary=summary)
                if obs:
                    items.append(obs)
            else:
                items.append(dict(
                    id=stable_id(item_url),
                    lab=source.get("lab", "deepseek"),
                    source=source["id"],
                    title=title,
                    url=item_url,
                    published_at=published_at,
                    summary=summary,
                    kind=kind,
                ))

    return sorted(items, key=lambda it: it["published_at"] or "", reverse=True)[:30]
