"""Collector and parser for official OpenAI Platform and API changelog.

Parses markdown release notes from https://platform.openai.com/docs/changelog.md,
extracting dated model releases, Decisions API, Agents API, and platform updates.
"""

import re

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
    "id": "openai-platform",
    "name": "OpenAI Platform",
    "lab": "openai",
    "group": "lab",
    "url": "https://platform.openai.com/docs/changelog.md",
}


def parse_openai_changelog(md_text, source=None, observed_at=None):
    """Parse OpenAI changelog markdown from platform.openai.com/docs/changelog.md."""
    if source is None:
        source = DEFAULT_SOURCE

    lines = md_text.splitlines()
    current_year = None
    current_month = None

    entries = []
    current_entry = None

    for line in lines:
        line_s = line.strip()
        # ## October, 2026
        m_my = re.match(r'^##\s+([A-Za-z]+),\s+(\d{4})', line_s)
        if m_my:
            m_name = m_my.group(1).lower()
            current_month = MONTHS.get(m_name, "01")
            current_year = m_my.group(2)
            continue

        # ### Oct 6
        m_day = re.match(r'^###\s+([A-Za-z]+)\s+(\d{1,2})', line_s)
        if m_day:
            day_m_name = m_day.group(1).lower()
            month = MONTHS.get(day_m_name, current_month or "01")
            day = int(m_day.group(2))
            year = current_year or "2026"
            current_date_str = f"{year}-{month}-{day:02d}T00:00:00Z"
            if current_entry:
                entries.append(current_entry)
            current_entry = {
                "date": current_date_str,
                "lines": []
            }
            continue

        if current_entry:
            if line_s.startswith("### ") or line_s.startswith("## "):
                continue
            if line_s:
                current_entry["lines"].append(line_s)

    if current_entry and current_entry["lines"]:
        entries.append(current_entry)

    items, seen = [], set()
    base_url = "https://platform.openai.com/docs/changelog"

    for idx, e in enumerate(entries):
        lines = [l for l in e["lines"] if l]
        if not lines:
            continue

        first_line = lines[0]
        # Check if first line contains structured tags like "Feature · Model: ... · API: ..."
        if any(first_line.startswith(tag) for tag in ("Feature", "Update", "Fix", "Deprecation")):
            tag_prefix = first_line.split("·")[0].strip()
            if len(lines) > 1:
                clean_title = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', lines[1])
                first_sentence = clean_title.split(". ")[0].strip(" .")
                if len(first_sentence) > 150:
                    first_sentence = first_sentence[:147] + "..."
                title = clean_text(f"{tag_prefix}: {first_sentence}", 500)
                summary = clean_text(" ".join(re.sub(r'\[(.*?)\]\(.*?\)', r'\1', l) for l in lines[1:]))
            else:
                title = clean_text(first_line, 500)
                summary = title
        else:
            clean_title = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', first_line)
            first_sentence = clean_title.split(". ")[0].strip(" .")
            title = clean_text(first_sentence, 500)
            summary = clean_text(" ".join(re.sub(r'\[(.*?)\]\(.*?\)', r'\1', l) for l in lines))

        day_tag = e["date"][:10].replace("-", "")
        item_url = f"{base_url}#{day_tag}-{idx}"
        if item_url in seen:
            continue
        seen.add(item_url)

        published_at = e["date"]
        kind = classify(title, summary)
        if observed_at is not None:
            obs = observation(source, title, item_url, published_at, observed_at, kind=kind, summary=summary)
            if obs:
                items.append(obs)
        else:
            items.append(dict(
                id=stable_id(item_url),
                lab=source.get("lab", "openai"),
                source=source["id"],
                title=title,
                url=item_url,
                published_at=published_at,
                summary=summary,
                kind=kind,
            ))

    return sorted(items, key=lambda it: it["published_at"] or "", reverse=True)[:30]
