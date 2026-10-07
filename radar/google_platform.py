"""Collector and parser for official Google AI Studio and Gemini API changelog.

Extracts dated Gemini model releases, API features, and SDK updates from
https://ai.google.dev/gemini-api/docs/changelog.
"""

import re
from urllib.parse import urljoin

from radar.classification import classify
from radar.common import clean_text, stable_id
from radar.items import observation

MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "january": "01", "february": "02", "march": "03", "april": "04",
    "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}

DEFAULT_SOURCE = {
    "id": "google-ai-studio",
    "name": "Google AI Studio",
    "lab": "google",
    "group": "lab",
    "url": "https://ai.google.dev/gemini-api/docs/changelog",
}


def parse_google_ai_studio(html_text, source=None, observed_at=None):
    """Parse Google AI Studio / Gemini API changelog from https://ai.google.dev/gemini-api/docs/changelog."""
    if source is None:
        source = DEFAULT_SOURCE

    base_url = "https://ai.google.dev/gemini-api/docs/changelog"
    sections = re.findall(
        r'<h2[^>]*>(?:<a[^>]*>)?\s*([A-Za-z]+\s+\d{1,2},\s+202[4-6])\s*(?:</a>)?</h2>(.*?)(?=<h2|\Z)',
        html_text,
        re.DOTALL
    )

    items, seen = [], set()

    for date_str, body in sections:
        parts = date_str.replace(",", "").split()
        if len(parts) == 3:
            m_name, day, year = parts[0].lower(), int(parts[1]), parts[2]
            month = MONTHS.get(m_name, "01")
            published_at = f"{year}-{month}-{day:02d}T00:00:00Z"
        else:
            continue

        bullets = re.findall(r'<li>\s*<p>\s*<strong>(.*?)</strong>\s*:(.*?)</p>', body, re.DOTALL)
        if not bullets:
            bullets = re.findall(r'<li>\s*<strong>(.*?)</strong>\s*:(.*?)</li>', body, re.DOTALL)

        day_slug = published_at[:10].replace("-", "")

        for idx, (raw_title, raw_desc) in enumerate(bullets):
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            title = clean_text(' '.join(title.split()), 500)
            desc = re.sub(r'<[^>]+>', ' ', raw_desc).strip()
            desc = ' '.join(desc.split())
            if not title:
                continue

            link_m = re.search(r'href="([^"]+)"', raw_title + raw_desc)
            if link_m and not link_m.group(1).startswith("#"):
                item_url = urljoin(base_url, link_m.group(1))
            else:
                item_url = f"{base_url}#{day_slug}-{idx}"

            if item_url in seen:
                continue
            seen.add(item_url)

            summary = clean_text(desc if desc else title)
            kind = classify(title, summary)
            if observed_at is not None:
                obs = observation(source, title, item_url, published_at, observed_at, kind=kind, summary=summary)
                if obs:
                    items.append(obs)
            else:
                items.append(dict(
                    id=stable_id(item_url),
                    lab=source.get("lab", "google"),
                    source=source["id"],
                    title=title,
                    url=item_url,
                    published_at=published_at,
                    summary=summary,
                    kind=kind,
                ))

    return sorted(items, key=lambda it: it["published_at"] or "", reverse=True)[:30]
