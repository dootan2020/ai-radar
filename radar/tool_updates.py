"""Group official product changes while keeping evidence and date uncertainty."""

import copy
from datetime import date, timedelta

from radar.common import iso_date
from radar.items import instant
from radar.tool_parsers import parse_atom, parse_markdown
from radar.tool_sources import SOURCES

WINDOW_DAYS = 7


def parse_source(text, source, now=None):
    """Return source observations, including excluded channels and unknown dates."""
    if source["parser"] == "atom":
        return parse_atom(text, source)
    if source["parser"] == "markdown":
        return parse_markdown(text, source)
    if source["parser"] == "codex_html":
        from radar.tool_changelog import parse_codex_html
        return parse_codex_html(text, source)
    raise ValueError("Unsupported official changelog parser")


def _date_rank(row):
    return (3 if row.get("published_at") else 2 if row.get("published_date")
            else 1 if row.get("updated_at") else 0)


def _window_reason(row, now):
    cutoff = now - timedelta(days=WINDOW_DAYS)
    # A release's publication never becomes fresh because its notes were edited.
    stamp = instant(row.get("published_at"))
    if stamp is not None:
        return None if cutoff <= stamp <= now else "outside_window"
    value = row.get("published_date")
    if value:
        try:
            day = date.fromisoformat(value)
        except (TypeError, ValueError):
            return "unknown_date"
        # Whole date buckets only: the partial lower-bound day cannot be proven fresh.
        return None if cutoff.date() < day <= now.date() else "outside_window"
    return "unknown_date"


def _priority(quote):
    text = quote["text"].lower()
    if any(term in text for term in ("security", "breaking", "deprecat", "vulnerability")):
        return 0
    if any(term in text for term in ("added", "introduc", "support", "new ", "now ")):
        return 1
    return 2


def finish(rows, source_records, now):
    """Merge matching versions, then select the last seven days deterministically.

    No previous snapshot is consulted. Counts refer to this collection only.
    """
    grouped = {}
    for row in sorted(rows, key=lambda row: (row["product"], row.get("version") or row["url"],
                                              -_date_rank(row), row["sources"][0])):
        key = (row["product"], row.get("version") or row["url"])
        if key not in grouped:
            grouped[key] = copy.deepcopy(row)
            continue
        current = grouped[key]
        if row["channel"] != "stable":
            current["channel"] = "prerelease"
        current["sources"] = sorted(set(current["sources"] + row["sources"]))
        current["highlights"].extend(copy.deepcopy(row["highlights"]))
    selected = []
    excluded = dict(prerelease=0, unknown_date=0, outside_window=0, no_highlights=0)
    for row in grouped.values():
        if row["channel"] != "stable":
            excluded["prerelease"] += 1
            continue
        reason = _window_reason(row, now)
        if reason:
            excluded[reason] += 1
            continue
        seen, chosen = set(), []
        for quote in sorted(row["highlights"], key=_priority):
            # Feed bullets and Markdown code delimiters must not repeat one change.
            # This key affects equality only; the retained excerpt remains untouched.
            identity = quote["text"].lstrip("•-* ").replace("`", "")
            if identity not in seen:
                chosen.append(quote)
                seen.add(identity)
        if not chosen:
            excluded["no_highlights"] += 1
            continue
        row["highlights"] = chosen[:3]
        selected.append(row)
    selected.sort(key=lambda row: (row.get("published_at") or row.get("published_date") or
                                    row.get("updated_at") or "", row["product"], row["id"]), reverse=True)
    return selected, metadata(selected, source_records, now, excluded)


def metadata(selected, source_records, now, excluded=None, error=None):
    """Describe collection health even when grouping cannot produce any rows."""
    records = {row["id"]: row for row in source_records}
    products = []
    names = {}
    for source in SOURCES:
        names.update(source.get("products", {source["product"]: source["product_name"]}))
    for product, name in names.items():
        sources = [source for source in SOURCES if product in source.get("products", {source["product"]: source["product_name"]})]
        ids = [source["id"] for source in sources]
        successful = [id_ for id_ in ids if records.get(id_, {}).get("ok") is True]
        products.append(dict(product=product, product_name=name, sources=ids,
                             successful_sources=successful, failed_sources=[id_ for id_ in ids if id_ not in successful],
                             count=sum(row["product"] == product for row in selected)))
    meta = dict(window_days=WINDOW_DAYS, window_start=iso_date(now - timedelta(days=WINDOW_DAYS)),
                window_end=iso_date(now), selection="official-stable-seven-days-v1",
                selection_description="Bản ổn định trong 7 ngày; ưu tiên bảo mật, thay đổi lớn và tính năng mới; tối đa 3 trích dẫn mỗi bản.",
                date_policy="Chỉ ngày đăng gốc xác lập độ mới; ngày sửa không chứng minh ngày phát hành.",
                products=products, excluded=excluded or {}, ok=error is None, error=error,
                dropped_entries={id_: record["dropped_entries"] for id_, record in records.items()
                                 if record.get("group") == "tool" and record.get("dropped_entries", 0)})
    return meta
