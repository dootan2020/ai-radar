"""Validation of the optional official product-change projection."""

from datetime import date

from radar.common import web_url
from radar.items import instant
from radar.tool_sources import SOURCES


def _official_url(url, source, version=None):
    if not web_url(url):
        return False
    if source["parser"] == "markdown":
        if not isinstance(version, str):
            return False
        return url in {source["entry_prefix"] + prefix + version.lower().replace(".", "")
                       for prefix in ("", "v")}
    prefixes = [source[key] for key in ("release_prefix", "entry_prefix") if source.get(key)]
    if source.get("entry_base"):
        prefixes.extend((source["entry_base"] + "#", source["url"] + "#",
                         "https://github.com/openai/codex/releases/tag/"))
    return any(url.startswith(prefix) and len(url) > len(prefix) for prefix in prefixes)


def inspect_tool_update(row):
    known = {source["id"]: source for source in SOURCES}
    for key in ("id", "product", "product_name", "title"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError("invalid tool update " + key)
    if row.get("version") is not None and (not isinstance(row["version"], str) or not row["version"].strip()):
        raise ValueError("invalid tool version")
    sources = row.get("sources")
    if not isinstance(sources, list) or not sources or any(not isinstance(id_, str) or id_ not in known for id_ in sources):
        raise ValueError("invalid tool update source")
    if len(set(sources)) != len(sources):
        raise ValueError("duplicate tool update sources")
    if not all(row["product"] in known[id_].get("products", {known[id_]["product"]: known[id_]["product_name"]}) for id_ in sources):
        raise ValueError("tool product does not match its sources")
    if not any(_official_url(row.get("url"), known[id_], row.get("version")) for id_ in sources):
        raise ValueError("tool URL is not an official entry")
    if row.get("channel") != "stable":
        raise ValueError("invalid tool release channel")
    for key in ("published_at", "updated_at"):
        if row.get(key) is not None and instant(row[key]) is None:
            raise ValueError("invalid tool " + key)
    day = row.get("published_date")
    if day is not None:
        if not isinstance(day, str) or len(day) != 10 or date.fromisoformat(day).isoformat() != day:
            raise ValueError("invalid tool published date")
    precision, basis = row.get("time_precision"), row.get("time_basis")
    if precision == "exact":
        if basis == "published":
            if instant(row.get("published_at")) is None or day != row["published_at"][:10]:
                raise ValueError("invalid tool publication evidence")
        else:
            raise ValueError("invalid tool time basis")
    elif precision != "date" or basis != "published" or day is None or row.get("published_at") is not None:
        raise ValueError("invalid tool time precision")
    quotes = row.get("highlights")
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 3:
        raise ValueError("invalid tool highlights")
    for quote in quotes:
        if (not isinstance(quote, dict) or not isinstance(quote.get("text"), str)
                or not quote["text"].strip() or len(quote["text"]) > 240
                or not isinstance(quote.get("source"), str) or quote["source"] not in sources
                or not isinstance(quote.get("source_name"), str) or not quote["source_name"].strip()
                or quote["source_name"] != known[quote["source"]]["name"]
                or not _official_url(quote.get("url"), known[quote["source"]], row.get("version"))):
            raise ValueError("invalid attributed tool quote")


def inspect_tool_meta(meta):
    if (not isinstance(meta, dict) or type(meta.get("window_days")) is not int
            or meta["window_days"] != 7 or instant(meta.get("window_start")) is None
            or instant(meta.get("window_end")) is None
            or instant(meta["window_start"]) >= instant(meta["window_end"])
            or not isinstance(meta.get("products"), list)
            or not isinstance(meta.get("excluded"), dict)):
        raise ValueError("invalid tool update metadata")
    if "ok" in meta and (type(meta["ok"]) is not bool or
                         (meta["ok"] is False and not isinstance(meta.get("error"), str))):
        raise ValueError("invalid tool processing status")
    dropped = meta.get("dropped_entries", {})
    if not isinstance(dropped, dict) or any(not isinstance(key, str) or type(value) is not int or value < 0
                                            for key, value in dropped.items()):
        raise ValueError("invalid tool parser drop counts")
    for value in meta["excluded"].values():
        if type(value) is not int or value < 0:
            raise ValueError("invalid tool exclusion count")
    for product in meta["products"]:
        if (not isinstance(product, dict) or not isinstance(product.get("product"), str)
                or not isinstance(product.get("product_name"), str)
                or type(product.get("count")) is not int or product["count"] < 0):
            raise ValueError("invalid tool product metadata")
        for key in ("sources", "successful_sources", "failed_sources"):
            if not isinstance(product.get(key), list) or any(not isinstance(id_, str) for id_ in product[key]):
                raise ValueError("invalid tool source metadata")
